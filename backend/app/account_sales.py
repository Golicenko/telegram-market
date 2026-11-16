"""Account subtype: encrypted delivery over the existing Listing/Deal/Wallet."""

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .account_crypto import keyring, seal, unseal
from .auth import get_current_user
from .config import get_settings
from .database import AsyncSession, SessionLocal, get_session
from .models import (
    AccountGrant,
    AccountSecret,
    AccountVideo,
    ConversationMessage,
    Deal,
    Listing,
    ListingImage,
    User,
    Wallet,
)


class RedactedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def protected(request):
            try:
                return await original(request)
            except RequestValidationError as error:
                # Never echo password/login through Pydantic's input or body.
                raise HTTPException(
                    422,
                    [
                        {"loc": e["loc"], "msg": "Проверьте поле", "type": e["type"]}
                        for e in error.errors()
                    ],
                ) from None
            except SQLAlchemyError:
                raise HTTPException(
                    503, "Операция не подтверждена. Проверьте результат перед повтором"
                ) from None

        return protected


router = APIRouter(prefix="/api", tags=["account-sales"], route_class=RedactedRoute)
FORBIDDEN = re.compile(
    r"https?://|www\.|t\.me/|@[a-z0-9_]{3,}|game\s*guardian|гейм\s*гардиан|оплат[аиуы].{0,12}(вне|напрямую|в лич|лс)",
    re.I,
)


class AccountCreate(BaseModel):
    client_request_id: uuid.UUID
    game_version: str = Field(pattern="^car_parking_[12]$")
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=5, max_length=5000)
    image_url: str = Field(min_length=1, max_length=2000)
    video_asset_id: uuid.UUID
    login: SecretStr = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=256)
    price_af_coins: Decimal = Field(ge=1, decimal_places=2, max_digits=18)
    owns_account: bool
    # Older clients send this declaration. The current form no longer asks for
    # it and must not fabricate a checked consent on the seller's behalf.
    no_personal_mail_required: bool | None = Field(default=None, deprecated=True)
    publication_fee_confirmed: bool = False


def ready():
    if not get_settings().account_sales_enabled:
        raise HTTPException(503, "Продажа аккаунтов ещё не включена администратором")
    keyring()


def validate_public(payload):
    login, password = (
        payload.login.get_secret_value().strip(),
        payload.password.get_secret_value(),
    )
    public = payload.title + "\n" + payload.description
    if len(payload.title.strip()) < 2 or len(payload.description.strip()) < 5:
        raise HTTPException(422, "Заполните название и описание без пустых пробелов")
    if not payload.owns_account or payload.no_personal_mail_required is False:
        raise HTTPException(
            422,
            "Нужны собственный игровой аккаунт и передача без доступа к личному почтовому ящику",
        )
    if FORBIDDEN.search(public):
        raise HTTPException(
            422,
            "Уберите рекламу, контакты, стороннюю оплату и запрещённые услуги из объявления",
        )
    if login in public or (len(password) >= 3 and password in public):
        raise HTTPException(
            422, "Данные входа нельзя помещать в публичное название или описание"
        )
    return {"login": login, "password": password}


async def account_count(session, seller_id):
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Listing)
            .where(
                Listing.seller_id == seller_id,
                Listing.product_kind == "account",
                Listing.deleted_at.is_(None),
                Listing.status == "active",
            )
        )
        or 0
    )


@router.get("/account-publication-rules")
async def publication_rules(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    count = await account_count(session, user.id)
    return {
        "enabled": get_settings().account_sales_enabled,
        "free_limit": 3,
        "active_count": count,
        "price_af": 15,
        "payment_required": count >= 3,
        "vip_stars": 5,
        "vip_hours": 24,
        "secret_retention_days": get_settings().account_secret_retention_days,
        "video_max_bytes": get_settings().account_video_max_bytes,
    }


async def publish(session, user, payload):
    from .services import debit_spendable, wallet_snapshot, wallet_transaction
    from .listing_media import validate_listing_media

    ready()
    values = validate_public(payload)
    async with session.begin():
        await session.scalar(
            select(User).where(User.id == user.id).with_for_update(key_share=True)
        )
        existing = await session.scalar(
            select(Listing).where(
                Listing.seller_id == user.id,
                Listing.client_request_id == payload.client_request_id,
            )
        )
        if existing:
            if (
                existing.product_kind != "account"
                or existing.brand != payload.title.strip()
                or existing.description != payload.description.strip()
                or existing.price_af_coins != payload.price_af_coins
                or existing.game_version != payload.game_version
                or existing.video_asset_id != payload.video_asset_id
            ):
                raise HTTPException(
                    409, "Идентификатор уже связан с другим объявлением"
                )
            image = await session.scalar(
                select(ListingImage.url).where(
                    ListingImage.listing_id == existing.id, ListingImage.position == 0
                )
            )
            secret = await session.get(AccountSecret, existing.id)
            if image != payload.image_url or (
                secret
                and secret.ciphertext
                and unseal(f"listing:{existing.id}", secret.key_id, secret.ciphertext)
                != values
            ):
                raise HTTPException(
                    409, "Идентификатор уже связан с другими данными объявления"
                )
            return existing
        await validate_listing_media(session, [payload.image_url], user.id)
        if not re.fullmatch(r"/api/media/[a-fA-F0-9-]{36}", payload.image_url):
            raise HTTPException(
                422, "Загрузите главную фотографию через форму аккаунта"
            )
        video = await session.scalar(
            select(AccountVideo)
            .where(AccountVideo.id == payload.video_asset_id)
            .with_for_update()
        )
        if not video or video.owner_id != user.id or not video.ready:
            raise HTTPException(422, "Загрузите и дождитесь проверки видео аккаунта")
        paid = await account_count(session, user.id) >= 3
        if paid and not payload.publication_fee_confirmed:
            raise HTTPException(
                402,
                {
                    "code": "account_publication_confirmation",
                    "price_af": "15",
                    "message": "Вы используете 3 бесплатных места. Подтвердите публикацию дополнительного аккаунта за 15 AF.",
                },
            )
        item = Listing(
            id=uuid.uuid4(),
            seller_id=user.id,
            client_request_id=payload.client_request_id,
            product_kind="account",
            listing_type="regular",
            game_version=payload.game_version,
            brand=payload.title.strip(),
            model="",
            power_hp=None,
            max_speed_kph=None,
            description=payload.description.strip(),
            price_af_coins=payload.price_af_coins,
            video_asset_id=video.id,
            status="active",
        )
        if paid:
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == user.id).with_for_update()
            )
            if not wallet or wallet.available_balance < 15:
                raise HTTPException(
                    402,
                    {
                        "code": "insufficient_af_coins",
                        "message": "Для публикации нужно 15 AF. Пополните баланс.",
                    },
                )
            before = wallet_snapshot(wallet)
            funding = debit_spendable(wallet, Decimal(15))
            wallet.version += 1
            session.add(
                wallet_transaction(
                    wallet,
                    "account_publication",
                    Decimal(-15),
                    *before,
                    "Публикация дополнительного аккаунта",
                    external_reference=f"account-publication:{item.id}",
                    funding=funding,
                )
            )
        session.add(item)
        await session.flush()
        key, ciphertext = seal(f"listing:{item.id}", values)
        session.add(
            AccountSecret(listing_id=item.id, key_id=key, ciphertext=ciphertext)
        )
        session.add(ListingImage(listing_id=item.id, url=payload.image_url, position=0))
    return item


@router.post("/account-products", status_code=201)
async def create(
    payload: AccountCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from .routes import listing_out

    return await listing_out(session, await publish(session, user, payload), user.id)


@router.patch("/account-products/{listing_id}")
async def edit(
    listing_id: uuid.UUID,
    payload: AccountCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from .listing_media import validate_listing_media
    from .routes import listing_out

    ready()
    values = validate_public(payload)
    async with session.begin():
        item = await session.scalar(
            select(Listing).where(Listing.id == listing_id).with_for_update()
        )
        if not item or item.product_kind != "account" or item.seller_id != user.id:
            raise HTTPException(404, "Аккаунт не найден")
        if item.status not in {"active", "paused"} or item.deleted_at:
            raise HTTPException(
                409, "Нельзя изменять проданный или зарезервированный аккаунт"
            )
        await validate_listing_media(session, [payload.image_url], user.id)
        video = await session.scalar(
            select(AccountVideo)
            .where(AccountVideo.id == payload.video_asset_id)
            .with_for_update()
        )
        if not video or video.owner_id != user.id or not video.ready:
            raise HTTPException(422, "Видео не готово")
        item.brand, item.description, item.game_version = (
            payload.title.strip(),
            payload.description.strip(),
            payload.game_version,
        )
        item.price_af_coins, item.video_asset_id = payload.price_af_coins, video.id
        image = await session.scalar(
            select(ListingImage).where(
                ListingImage.listing_id == item.id, ListingImage.position == 0
            )
        )
        secret = await session.get(AccountSecret, item.id)
        if not image or not secret:
            raise HTTPException(
                409, "Данные объявления неполны; обратитесь в поддержку"
            )
        if await session.scalar(
            select(Deal.id).where(Deal.listing_id == item.id).limit(1)
        ):
            raise HTTPException(409, "Нельзя повторно публиковать уже выданный аккаунт")
        image.url = payload.image_url
        secret.key_id, secret.ciphertext = seal(f"listing:{item.id}", values)
    return await listing_out(session, item, user.id)


async def prepare_purchase(session, listing):
    ready()
    secret = await session.get(AccountSecret, listing.id)
    if not secret or not secret.ciphertext:
        raise HTTPException(409, "Данные выдачи отсутствуют; покупка остановлена")
    return unseal(f"listing:{listing.id}", secret.key_id, secret.ciphertext)


async def deliver_locked(session, deal, values):
    from .deal_lifecycle import audit_deal

    now = datetime.now(UTC)
    key, ciphertext = seal(f"deal:{deal.id}", values)
    session.add(AccountGrant(deal_id=deal.id, key_id=key, ciphertext=ciphertext))
    await session.flush()
    deal.product_kind, deal.status = "account", "transfer_in_progress"
    deal.transfer_started_at = now
    deal.seller_delivery_deadline = deal.seller_response_deadline = None
    deal.seller_responded_at = deal.seller_accepted_at = now
    deal.buyer_transfer_reminder_status = "skipped"
    session.add(
        ConversationMessage(
            conversation_id=deal.conversation_id,
            deal_id=deal.id,
            sender_id=deal.buyer_id,
            message_type="system",
            account_card_id=deal.id,
            body="⚡ Ваш аккаунт готов! Данные доступны в защищённой карточке. Проверьте доступ до подтверждения получения.",
        )
    )
    audit_deal(session, deal, "account_delivery_available", deal.buyer_id)


def accessible(deal, now=None):
    now = now or datetime.now(UTC)
    if deal.product_kind != "account":
        return False
    if deal.status in {"transfer_in_progress", "disputed"}:
        return True
    stamp = deal.completed_at or deal.cancelled_at
    if stamp and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return bool(
        deal.status == "completed"
        and stamp
        and stamp + timedelta(days=get_settings().account_secret_retention_days) > now
    )


@router.post("/account-deals/{deal_id}/credentials")
async def reveal(
    deal_id: uuid.UUID,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from .deal_lifecycle import audit_deal

    # POST is intentional: no browser/proxy prefetch, cache or automatic GET retry.
    async with session.begin():
        deal = await session.scalar(
            select(Deal).where(Deal.id == deal_id).with_for_update()
        )
        if not deal or deal.buyer_id != user.id or deal.product_kind != "account":
            raise HTTPException(404, "Карточка не найдена")
        if not accessible(deal):
            raise HTTPException(410, "Срок доступа завершён или сделка отменена")
        grant = await session.get(AccountGrant, deal.id)
        listing = await session.get(Listing, deal.listing_id)
        wallet = await session.scalar(
            select(Wallet).where(Wallet.user_id == deal.buyer_id)
        )
        if deal.status != "completed":
            from .services import validate_deal_hold

            validate_deal_hold(deal, listing, wallet)
        if not grant or not grant.ciphertext or grant.deleted_at:
            raise HTTPException(410, "Данные удалены по сроку хранения")
        now = datetime.now(UTC)
        last = grant.last_opened_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last and (now - last).total_seconds() < 1:
            raise HTTPException(429, "Повторите через секунду")
        values = unseal(f"deal:{deal.id}", grant.key_id, grant.ciphertext)
        grant.first_opened_at = grant.first_opened_at or now
        grant.last_opened_at = now
        grant.open_count += 1
        audit_deal(session, deal, "account_credentials_opened", user.id)
    response.headers.update(
        {
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "Vary": "X-Telegram-Init-Data",
        }
    )
    return values


class Receipt(BaseModel):
    checked_access: bool


@router.post("/account-deals/{deal_id}/confirm")
async def confirm(
    deal_id: uuid.UUID,
    payload: Receipt,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from .services import complete_deal

    if not payload.checked_access:
        raise HTTPException(422, "Подтвердите проверку доступа")
    # The shared command repeats all financial checks under its existing lock.
    return await complete_deal(session, user, deal_id, account_confirmation=True)


async def purge_once():
    """Bounded cleanup. Never erase a secret while its dispute is unresolved."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=get_settings().account_secret_retention_days)
    async with SessionLocal() as session, session.begin():
        rows = (
            await session.scalars(
                select(Deal)
                .join(AccountGrant, AccountGrant.deal_id == Deal.id)
                .where(
                    Deal.product_kind == "account",
                    Deal.status.in_(("completed", "cancelled")),
                    func.coalesce(Deal.completed_at, Deal.cancelled_at) <= cutoff,
                    AccountGrant.deleted_at.is_(None),
                )
                .order_by(Deal.id)
                .limit(100)
                .with_for_update(of=Deal, skip_locked=True)
            )
        ).all()
        for deal in rows:
            grant = await session.get(AccountGrant, deal.id)
            grant.ciphertext, grant.deleted_at = None, now
            secret = await session.get(AccountSecret, deal.listing_id)
            if secret:
                secret.ciphertext = None


async def run_cleanup():
    while True:
        try:
            await purge_once()
            from .account_pins import refund_once

            async with SessionLocal() as session:
                await refund_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never log SQL parameters containing encrypted or plaintext secrets.
            import logging

            logging.getLogger(__name__).warning("account_cleanup_unavailable")
        await asyncio.sleep(60)
