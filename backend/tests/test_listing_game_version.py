"""HTTP/service persistence and DB constraints; SQLite is not PostgreSQL locking."""
import importlib.util
import io
import uuid
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.auth import get_current_user, require_admin
from app.database import get_session
from app.models import User, Listing, ListingImage, ListingLike, Conversation, AdminAction
from app.routes import router
from app.schemas import ListingCreate, ListingUpdate, UniqueListingCreate
from test_chat_lifecycle_db import DB


def payload(**overrides):
    return dict(game_version="car_parking_1", brand="My car", power_hp=1000000,
                max_speed_kph=1000000, description="Original game screenshot", price_af_coins=10,
                image_urls=["/api/media/test-photo"], **overrides)


@pytest.mark.parametrize("game", [None, "", "car_parking_3", "Car Parking 2", 1, {}])
def test_create_and_update_reject_invalid_game(game):
    for schema in (ListingCreate, UniqueListingCreate):
        with pytest.raises(ValidationError):
            schema(**{**payload(), "game_version": game})
    with pytest.raises(ValidationError):
        ListingUpdate(game_version=game)


def test_new_listing_requires_explicit_game_but_patch_can_omit_it():
    values = payload()
    del values["game_version"]
    for schema in (ListingCreate, UniqueListingCreate):
        with pytest.raises(ValidationError):
            schema(**values)
    assert "game_version" not in ListingUpdate(description="Changed").model_dump(exclude_unset=True)
    for game in ("car_parking_1", "car_parking_2"):
        assert ListingCreate(**{**values, "game_version": game}).game_version == game


class ListingDB(DB):
    async def refresh(self, value):
        self.session.refresh(value)

    async def rollback(self):
        self.session.rollback()

    async def commit(self):
        self.session.commit()


@pytest.mark.asyncio
async def test_http_create_edit_get_and_database_reopen(tmp_path):
    database_url = "sqlite:///" + (tmp_path / "listings.sqlite").as_posix()
    engine = sa.create_engine(database_url)
    # Unique listing creation uses PostgreSQL's publication sequence. The test
    # emulates only nextval; the production sequence/service remains unchanged.
    @sa.event.listens_for(engine, "connect")
    def sequence_fixture(connection, _record):
        connection.create_function("nextval", 1, lambda _name: 1)
    with engine.begin() as connection:
        for model in (User, Listing, ListingImage, ListingLike, Conversation, AdminAction):
            connection.execute(CreateTable(model.__table__))
    user = User(id=uuid.uuid4(), telegram_id=77, first_name="Seller", role="admin")
    with Session(engine) as session, session.begin():
        session.add(user)
        session.flush()
        user_id = user.id
    bridge = ListingDB(Session(engine, expire_on_commit=False))
    # Auth returns an actor independent of the request's DB transaction.
    user = User(id=user_id, telegram_id=77, first_name="Seller", role="admin")
    app = FastAPI()
    app.include_router(router)
    async def session_dependency():
        try:
            yield bridge
        finally:
            bridge.session.rollback()
    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for url in ("/api/listings", "/api/admin/listings/unique"):
                for values in ({k: v for k, v in payload().items() if k != "game_version"}, {**payload(), "game_version": "fake"}, {**payload(), "game_version": None}):
                    assert (await client.post(url, json=values)).status_code == 422
            assert bridge.session.scalar(sa.select(sa.func.count()).select_from(Listing)) == 0
            bridge.session.rollback()
            created = []
            for game in ("car_parking_1", "car_parking_2"):
                response = await client.post("/api/listings", json={**payload(), "game_version": game})
                assert response.status_code == 201, response.text
                assert response.json()["game_version"] == game
                assert response.json()["images"] == payload()["image_urls"]
                created.append(response.json())
            unique = await client.post("/api/admin/listings/unique", json={**payload(), "game_version": "car_parking_2"})
            assert unique.status_code == 201, unique.text
            assert unique.json()["game_version"] == "car_parking_2"
            listing_id = created[1]["id"]
            for value in (None, "invalid"):
                assert (await client.patch(f"/api/listings/{listing_id}", json={"game_version": value})).status_code == 422
            edited = await client.patch(f"/api/listings/{listing_id}", json={"description": "Edited"})
            assert edited.status_code == 200, edited.text
            assert edited.json()["game_version"] == "car_parking_2"
            changed = await client.patch(f"/api/listings/{created[0]['id']}", json={"game_version": "car_parking_2"})
            assert changed.status_code == 200
            assert changed.json()["game_version"] == "car_parking_2"
            # Closing the engine/session discards every in-memory object/cache.
            bridge.session.close()
            engine.dispose()
            engine = sa.create_engine(database_url)
            bridge.session = Session(engine, expire_on_commit=False)
            reopened = await client.get(f"/api/listings/{listing_id}")
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["game_version"] == "car_parking_2"
            assert reopened.json()["description"] == "Edited"
            listed = await client.get("/api/listings?type=regular")
            assert listed.status_code == 200, listed.text
            assert all(row["game_version"] == "car_parking_2" for row in listed.json())
    finally:
        bridge.session.close()
        engine.dispose()


@pytest.mark.parametrize("game", [None, "unknown"])
def test_database_itself_rejects_missing_or_invalid_game(game):
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(CreateTable(Listing.__table__))
        with Session(engine) as session, pytest.raises(sa.exc.IntegrityError):
            session.add(Listing(seller_id=uuid.uuid4(), game_version=game, listing_type="regular",
                                brand="Car", model="", power_hp=1, max_speed_kph=1, price_af_coins=10))
            session.commit()
        assert Listing.__table__.c.game_version.default is None
        assert Listing.__table__.c.game_version.server_default is None
    finally:
        engine.dispose()


def test_migration_backfills_every_legacy_status_then_removes_default():
    filename = Path(__file__).parents[1] / "migrations/versions/0040_listing_game_version.py"
    spec = importlib.util.spec_from_file_location("game_migration", filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "DEFAULT 'car_parking_1' NOT NULL" in sql
    assert "CHECK (game_version IN ('car_parking_1','car_parking_2'))" in sql
    assert "ALTER TABLE listings ALTER COLUMN game_version DROP DEFAULT" in sql
    assert "DELETE FROM" not in sql and "DROP TABLE" not in sql
    # Execute the actual ADD COLUMN statement over pre-existing legacy rows.
    # SQLite accepts this statement; PG-only ALTER CONSTRAINT/default SQL is
    # compiled/checked above, not represented as a live PostgreSQL migration.
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE listings (id INTEGER PRIMARY KEY, status TEXT)"))
        statuses = ["active", "paused", "reserved", "sold", "deleted"]
        for index, status in enumerate(statuses):
            connection.execute(sa.text("INSERT INTO listings (id,status) VALUES (:id,:status)"), {"id": index, "status": status})
        connection.execute(sa.text(sql.split(";")[0]))
        rows = connection.execute(sa.text("SELECT id,status,game_version FROM listings ORDER BY id")).all()
        assert rows == [(index, status, "car_parking_1") for index, status in enumerate(statuses)]
    engine.dispose()
