import html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

ENTRY_TEXT = (
    "👑 <b>Premium — полный доступ на 1 месяц</b>\n"
    "Оформи Premium, чтобы снять замки во всех разделах."
)


def CHECKOUT_TEXT_TEMPLATE(user_id: int) -> str:
    safe_user_id = html.escape(str(int(user_id)))
    return (
        "👑 <b>Premium — полный доступ на 1 месяц</b>\n"
        "Цена: €6.99 (карта) или ⭐ 400 Stars (в Telegram).\n\n"
        "📋 <b>Твой Telegram ID:</b>\n"
        f"<pre><code>{safe_user_id}</code></pre>\n"
        "➡️ Укажи этот ID при оплате картой\n"
        "➡️ После оплаты нажми «✅ Проверить Premium»\n"
        "🔓 Доступ откроется автоматически"
    )


def build_entry_kb(
    back_cb: str,
    check_cb: str,
    buy_card_cb: str = "premium:buy_card",
    stars_cb: str = "premium:stars_month",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить Premium (карта)", callback_data=buy_card_cb)],
            [InlineKeyboardButton(text="⭐ Купить Premium за Stars", callback_data=stars_cb)],
            [InlineKeyboardButton(text="✅ Проверить Premium", callback_data=check_cb)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)],
        ]
    )


def build_checkout_kb(
    stripe_url: str,
    back_cb: str,
    check_cb: str,
    stars_cb: str = "premium:stars_month",
) -> InlineKeyboardMarkup:
    rows = []
    if stripe_url:
        rows.append([InlineKeyboardButton(text="💳 Оплатить картой (Stripe)", url=stripe_url)])
    rows.append([InlineKeyboardButton(text="⭐ Оплатить Stars", callback_data=stars_cb)])
    rows.append([InlineKeyboardButton(text="✅ Проверить Premium", callback_data=check_cb)])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render(target: Message, text: str, reply_markup: InlineKeyboardMarkup, parse_mode: str = "HTML") -> Message:
    try:
        await target.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)
        return target
    except Exception:
        return await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)


async def show_entry(
    target: Message,
    user_id: int,
    back_cb: str,
    check_cb: str,
    parse_mode: str = "HTML",
    buy_card_cb: str = "premium:buy_card",
    stars_cb: str = "premium:stars_month",
) -> Message:
    return await _render(
        target,
        ENTRY_TEXT,
        build_entry_kb(back_cb=back_cb, check_cb=check_cb, buy_card_cb=buy_card_cb, stars_cb=stars_cb),
        parse_mode=parse_mode,
    )


async def show_checkout(
    target: Message,
    user_id: int,
    back_cb: str,
    check_cb: str,
    stripe_url: str,
    parse_mode: str = "HTML",
    stars_cb: str = "premium:stars_month",
) -> Message:
    return await _render(
        target,
        CHECKOUT_TEXT_TEMPLATE(user_id),
        build_checkout_kb(stripe_url=stripe_url, back_cb=back_cb, check_cb=check_cb, stars_cb=stars_cb),
        parse_mode=parse_mode,
    )
