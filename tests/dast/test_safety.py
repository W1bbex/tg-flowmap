"""Тесты контекстного фильтра опасных кнопок."""

from tg_flowmap.dast.config import Config
from tg_flowmap.dast.safety import SafetyFilter, is_emoji_only


def make_safety(**overrides) -> SafetyFilter:
    cfg = Config(root=None if False else __import__("pathlib").Path("."))  # не используется
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return SafetyFilter(cfg)


def test_danger_word_en():
    s = make_safety()
    ok, reason = s.button_verdict("Buy now", "callback", "Main menu")
    assert not ok and reason and reason.startswith("danger_word:buy")


def test_danger_word_ru():
    s = make_safety()
    ok, reason = s.button_verdict("Купить", "callback", "Каталог")
    assert not ok and reason and "купить" in reason


def test_price_with_action_word():
    s = make_safety()
    ok, reason = s.button_verdict("Pay $50", "callback", "Checkout? no")
    assert not ok and reason.startswith("price_with_action_word")


def test_checkout_screen_blocks_all():
    s = make_safety()
    ok, reason = s.button_verdict("Continue", "callback", "Оплата заказа. К оплате: 100$")
    assert not ok and reason == "checkout_screen"


def test_wallet_address_blocks():
    s = make_safety()
    text = "Переведите USDT на TRC20 кошелёк TQn9Y2khDD95J42FQtQTdwVVRvBoo4Vb7x"
    ok, reason = s.button_verdict("Далее", "callback", text)
    assert not ok and reason == "payment_screen"


def test_password_required_blocks():
    s = make_safety()
    ok, reason = s.button_verdict("Войти", "callback", "Введите пароль для входа")
    assert not ok and reason == "password_required"


def test_url_button_never_activated():
    s = make_safety()
    ok, reason = s.button_verdict("Наш канал", "url", "Main menu")
    assert not ok and reason == "button_type:url_not_activated"


def test_quantity_total_unknown_action():
    s = make_safety()
    text = "Количество: 2 Итого: $50. Подтвердите состав заказа"
    ok, reason = s.button_verdict("Дальше", "callback", text)
    assert not ok and reason == "quantity_total_unknown_action"
    # навигационная кнопка известного назначения — можно
    ok2, _ = s.button_verdict("Назад", "callback", text)
    assert ok2


def test_emoji_only_on_sensitive_screen():
    s = make_safety()
    ok, reason = s.button_verdict("✅", "callback", "Оплата заказа: 10$")
    assert not ok and reason == "emoji_only_on_sensitive_screen"
    # на нейтральном экране emoji-кнопка разрешена
    ok2, _ = s.button_verdict("✅", "callback", "Каталог товаров")
    assert ok2


def test_allowed_labels_override():
    s = make_safety(allowed_button_labels=["Купить 1 аккаунт"])
    ok, _ = s.button_verdict("Купить 1 аккаунт", "callback", "Каталог")
    assert ok


def test_is_emoji_only():
    assert is_emoji_only("✅🔥")
    assert is_emoji_only("⬅")
    assert not is_emoji_only("Каталог")
    assert not is_emoji_only("Xbox $100")


def test_back_detection():
    s = make_safety()
    assert s.is_back("⬅ Назад")
    assert s.is_back("Back")
    assert not s.is_back("Catalog")


def test_requires_input_hint():
    s = make_safety()
    assert s.requires_input_hint("Введите email:", has_force_reply=False)
    assert s.requires_input_hint("текст", has_force_reply=True)
    assert not s.requires_input_hint("Главное меню", has_force_reply=False)


def test_manual_answers_exact_and_regex():
    answers = {
        "@bot": {"screens": [
            {"match": "Введите email:", "match_type": "exact", "answer": "a@b.c"},
            {"match": "(?i)укажите количество", "match_type": "regex", "answer": "1"},
        ]}
    }
    assert SafetyFilter.manual_answer(answers, "@bot", "Введите email:") == "a@b.c"
    assert SafetyFilter.manual_answer(answers, "@bot", "Укажите количество товара") == "1"
    assert SafetyFilter.manual_answer(answers, "@bot", "Другой текст") is None
    assert SafetyFilter.manual_answer(answers, "@other", "Введите email:") is None
