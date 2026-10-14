"""One presentation dictionary for Mini App, staff and Telegram; stored keys stay stable."""
from .withdrawal_support import validated_username

CATEGORIES = (
    ("payment", "💳", "Оплата и баланс", False),
    ("purchase", "🚗", "Покупка автомобиля", True),
    ("deal", "🤝", "Проблема со сделкой", True),
    ("listing", "📢", "Объявления", False),
    ("withdrawal", "⭐", "Вывод средств", False),
    ("deal_details", "🔄", "Изменение данных сделки", True),
    ("transfer", "🎮", "Передача автомобиля", True),
    ("training", "🎓", "Обучение", False),
    ("referral", "🎁", "Реферальная программа", False),
    ("technical", "⚙️", "Техническая проблема", False),
    ("other", "💬", "Другое", False),
)
ALIASES = {"payment_issue": "payment", "transaction_problem": "deal", "Проблема по сделке": "deal"}
LABELS = {key: label for key, _, label, _ in CATEGORIES}


def category_key(value):
    value = value.strip()
    return ALIASES.get(value, ALIASES.get(value.lower(), value.lower()))


def topic_label(value):
    # Legacy tickets sometimes stored a Russian sentence (including withdrawal number).
    return LABELS.get(category_key(value), value if any("А" <= c <= "я" for c in value) else "Другое")


def ticket_number(ticket):
    return str(ticket.id).split("-")[0].upper()


def ticket_notice(ticket, author, message):
    username = validated_username(author.username)
    identity = f"@{username}" if username else "Username отсутствует"
    name = " ".join(filter(None, (author.first_name, author.last_name)))[:120]
    return (f"🆘 Новое обращение в поддержку\n🎫 Обращение №{ticket_number(ticket)}\n"
            f"👤 Пользователь: {identity}\n" + (f"Имя: {name}\n" if not username and name else "") +
            f"📂 Тема: {topic_label(ticket.topic)}\n" +
            (f"Заказ №{str(ticket.deal_id)[:8]}\n" if ticket.deal_id else "") +
            f"\n💬 Сообщение:\n{message.strip()[:800]}")
