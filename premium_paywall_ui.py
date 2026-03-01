from __future__ import annotations

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramBadRequest
import logging

ENTRY_TEXT = (
    "🔒 <b>Premium доступ</b>\n\n"
    "Оформи Monthly Premium (30 days), чтобы снять ограничения во всех разделах."
)


def CHECKOUT_TEXT_TEMPLATE(user_id: int) -> str:
    return (
        "🔒 <b>Checkout: Monthly Premium (30 days)</b>\n\n"
        "📋 <b>Твой Telegram ID для оплаты:</b>\n"
        f"<pre><code>{user_id}</code></pre>\n"
        "➡️ Укажи этот ID в Stripe Payment Link.\n"
        "➡️ После оплаты нажми «Check Premium»."
    )


def build_entry_kb(
    back_cb: str,
    check_cb: str,
    buy_card_cb: str = "premium:buy_card",
    stars_cb: str = "premium:stars_month",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Buy by card", callback_data=buy_card_cb)],
            [InlineKeyboardButton(text="⭐ Buy by Stars", callback_data=stars_cb)],
            [InlineKeyboardButton(text="✅ Check Premium", callback_data=check_cb)],
            [InlineKeyboardButton(text="⬅️ Back", callback_data=back_cb)],
        ]
    )


def build_checkout_kb(
    stripe_url: str,
    back_cb: str,
    check_cb: str,
    stars_cb: str = "premium:stars_month",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay by card (Stripe)", url=stripe_url)],
            [InlineKeyboardButton(text="⭐ Pay by Stars", callback_data=stars_cb)],
            [InlineKeyboardButton(text="✅ Check Premium", callback_data=check_cb)],
            [InlineKeyboardButton(text="⬅️ Back", callback_data=back_cb)],
        ]
    )


def _resolve_message(target):
    return getattr(target, "message", target)


def _can_edit_target(target, message) -> bool:
    if isinstance(target, CallbackQuery):
        return isinstance(message, Message)
    return isinstance(message, Message)


async def show_entry(
    target,
    user_id: int,
    back_cb: str,
    check_cb: str,
    parse_mode: str = "HTML",
    buy_card_cb: str = "premium:buy_card",
    stars_cb: str = "premium:stars_month",
):
    message = _resolve_message(target)
    text = ENTRY_TEXT
    kb = build_entry_kb(back_cb=back_cb, check_cb=check_cb, buy_card_cb=buy_card_cb, stars_cb=stars_cb)
    if _can_edit_target(target, message):
        try:
            return await message.edit_text(text, reply_markup=kb, parse_mode=parse_mode, disable_web_page_preview=True)
        except TelegramBadRequest as e:
            err = str(e) or ""
            if "message is not modified" in err.lower() or "message is not modified" in getattr(e, 'message', ""):
                return message
            logging.exception("show_entry: TelegramBadRequest while editing message for user %s: %s", user_id, err)
            return None
        except Exception:
            logging.exception("show_entry: unexpected error while editing message for user %s", user_id)
            return None
    # If we can't edit the message, do not send a new message to avoid duplicates.
    return None


async def show_checkout(
    target,
    user_id: int,
    back_cb: str,
    check_cb: str,
    stripe_url: str,
    parse_mode: str = "HTML",
):
    message = _resolve_message(target)
    text = CHECKOUT_TEXT_TEMPLATE(user_id)
    kb = build_checkout_kb(stripe_url=stripe_url, back_cb=back_cb, check_cb=check_cb)
    if _can_edit_target(target, message):
        try:
            return await message.edit_text(text, reply_markup=kb, parse_mode=parse_mode, disable_web_page_preview=True)
        except TelegramBadRequest as e:
            err = str(e) or ""
            if "message is not modified" in err.lower() or "message is not modified" in getattr(e, 'message', ""):
                return message
            logging.exception("show_checkout: TelegramBadRequest while editing message for user %s: %s", user_id, err)
            return None
        except Exception:
            logging.exception("show_checkout: unexpected error while editing message for user %s", user_id)
            return None
    # If we can't edit the message, do not send a new message to avoid duplicates.
    return None
