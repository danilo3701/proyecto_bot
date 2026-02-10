# referral_feature.py
# =============================================================================
# 🤝 Реферальная программа (подписка) — отдельная фича
# - привязка реферала только при первом /start по ссылке
# - комиссия начисляется за КАЖДОЕ продление (invoice.paid), пока подписка активна
# - процент динамический и может снижаться (зависит от текущего числа активных платящих)
# - хранение в Railway Volume: /data/referrals_data.json
# =============================================================================

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Optional

from aiogram.filters import Command
from aiogram.types import Message


from urllib.parse import quote

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router = Router()

REFERRALS_DATA_PATH = os.getenv("REFERRALS_DATA_PATH", "/data/referrals_data.json")
REFERRALS_BACKUP_PATH = os.getenv("REFERRALS_BACKUP_PATH", "/data/referrals_data.backup.json")

# 💬 payload для deep-link: /start refpay_<referrer_id>
REF_PAYLOAD_PREFIX = "refpay_"

# 💬 жесткая проверка владельца (нельзя использовать _safe_int, он объявлен ниже)
try:
    OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0"))
except Exception:
    OWNER_USER_ID = 0

_PAYOUT_WAIT: dict[int, bool] = {}  # 💬 owner_id -> ждём ввод "user_id amount"



# 💬 кэш username бота, чтобы не дергать getMe постоянно
_BOT_USERNAME_CACHE: str | None = None

# 💬 простой lock, чтобы не было гонок (webhook + UI)
_REF_LOCK = asyncio.Lock()


# -----------------------------------------------------------------------------
# Storage helpers
# -----------------------------------------------------------------------------
def _now() -> int:
    return int(time.time())


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _ensure_shape(d: dict) -> dict:
    d = d or {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("referrers", {})  # referrer_id -> data
    d.setdefault("user_to_referrer", {})  # user_id -> referrer_id
    d.setdefault("__processed_invoices", {})  # invoice_id -> ts (анти-дубль комиссий)
    return d


def _load_ref_data_sync() -> dict:
    try:
        if os.path.exists(REFERRALS_DATA_PATH):
            with open(REFERRALS_DATA_PATH, "r", encoding="utf-8") as f:
                return _ensure_shape(json.load(f))
    except Exception:
        logging.exception("referrals_data.json read failed")
    return _ensure_shape({})


def _save_ref_data_sync(d: dict) -> None:
    d = _ensure_shape(d)

    # 💬 backup (best effort)
    try:
        if os.path.exists(REFERRALS_DATA_PATH):
            try:
                with open(REFERRALS_DATA_PATH, "r", encoding="utf-8") as f:
                    prev = f.read()
                with open(REFERRALS_BACKUP_PATH, "w", encoding="utf-8") as b:
                    b.write(prev)
            except Exception:
                pass
    except Exception:
        pass

    tmp_path = REFERRALS_DATA_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, REFERRALS_DATA_PATH)


def _get_or_create_referrer(d: dict, referrer_id: str) -> dict:
    referrers = d.setdefault("referrers", {})
    r = referrers.setdefault(referrer_id, {})
    r.setdefault("enabled", False)  # 💬 включается админом (ручной флаг)
    r.setdefault("created_at", _now())
    # 💬 Новая финансовая модель (backward-compatible)
    r.setdefault("accrued_total_cents", _safe_int(r.get("earned_cents"), 0))
    r.setdefault("paid_total_cents", _safe_int(r.get("paid_out_cents"), 0))

    r.setdefault("referred", {})      # user_id -> data
    r.setdefault("events", [])        # 💬 журнал начислений
    return r


def _is_referrer_enabled(d: dict, referrer_id: str) -> bool:
    r = d.get("referrers", {}).get(referrer_id, {})
    return bool(r.get("enabled"))


def _extract_referrer_id_from_payload(payload: Optional[str]) -> Optional[str]:
    if not payload:
        return None
    s = str(payload).strip()
    # 💬 строго refpay_<digits>
    m = re.fullmatch(rf"{re.escape(REF_PAYLOAD_PREFIX)}(\d+)", s)
    return m.group(1) if m else None


def _format_money(cents: int) -> str:
    # 💬 показываем как 12.34 (EUR по умолчанию)
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def _status_ru(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "paid":
        return "Оплачено"
    if s == "unpaid":
        return "Не оплачено"
    if s == "canceled":
        return "Отменено"
    if s == "pending":
        return "В ожидании"
    return "—"


def _is_active_paying(entry: dict, now_ts: int) -> bool:
    # 💬 активный = оплачено и период ещё не истёк
    return (entry.get("status") == "paid") and (_safe_int(entry.get("active_until")) > now_ts)


def _active_paying_count(referrer: dict, now_ts: int) -> int:
    referred = referrer.get("referred", {}) or {}
    c = 0
    for _, u in referred.items():
        if isinstance(u, dict) and _is_active_paying(u, now_ts):
            c += 1
    return c


def _tier_percent(active_count: int) -> float:
    # 💬 до 10 включительно = 30%; с 11 = 40%; с 26 = 50%
    if active_count <= 10:
        return 0.30
    if active_count <= 25:
        return 0.40
    return 0.50


def _extract_invoice_gross_cents(invoice_obj: dict) -> int:
    # 💬 Stripe invoice: amount_paid / amount_due / total (в центах)
    for k in ("amount_paid", "amount_due", "amount_total", "total"):
        v = invoice_obj.get(k)
        if v is not None:
            return _safe_int(v, 0)
    return 0


# -----------------------------------------------------------------------------
# Public hooks (called from Core 8.1)
# -----------------------------------------------------------------------------
async def referrals_try_bind_on_start(
    *,
    new_user_id: int,
    raw_payload: Optional[str],
    is_first_start: bool,
    tg_username: str,
    full_name: str,
) -> None:
    """
    💬 Привязка реферала:
    - только если это первый /start пользователя
    - payload вида refpay_<referrer_id>
    - referrer должен быть enabled=True
    - anti-duble по user_id
    """
    if not is_first_start:
        return

    referrer_id = _extract_referrer_id_from_payload(raw_payload)
    if not referrer_id:
        return
    if referrer_id == str(new_user_id):
        return

    async with _REF_LOCK:
        d = _load_ref_data_sync()

        # 💬 не дублируем приведённого
        user_to_ref = d.setdefault("user_to_referrer", {})
        if str(new_user_id) in user_to_ref:
            return

        r = _get_or_create_referrer(d, referrer_id)
        referred = r.setdefault("referred", {})

        referred[str(new_user_id)] = {
            "user_id": int(new_user_id),
            "username": tg_username or "",
            "full_name": full_name or "",
            "status": "pending",      # 💬 в ожидании оплаты
            "first_start_ts": _now(),
            "active_until": 0,
            "last_payment_ts": 0,
            "earned_cents": 0,
        }
        user_to_ref[str(new_user_id)] = str(referrer_id)

        _save_ref_data_sync(d)


async def referrals_apply_invoice_paid(
    *,
    tg_user_id: int,
    invoice_obj: dict,
    active_until: int,
) -> None:
    """
    💬 Начисление комиссии по invoice.paid / invoice.payment_succeeded.
    - комиссия = gross * текущий процент (по текущему активному числу)
    - анти-дубль по invoice_id
    """
    invoice_id = str(invoice_obj.get("id") or "").strip()
    if not invoice_id:
        return

    now_ts = _now()
    gross_cents = _extract_invoice_gross_cents(invoice_obj)

    async with _REF_LOCK:
        d = _load_ref_data_sync()

        referrer_id = d.get("user_to_referrer", {}).get(str(tg_user_id))
        if not referrer_id:
            return

        r = _get_or_create_referrer(d, str(referrer_id))
        referred = r.setdefault("referred", {})
        u = referred.setdefault(str(tg_user_id), {
            "user_id": int(tg_user_id),
            "username": "",
            "full_name": "",
            "status": "pending",
            "first_start_ts": now_ts,
            "active_until": 0,
            "last_payment_ts": 0,
            "earned_cents": 0,
        })

        # 💬 всегда синкаем статус и срок
        u["status"] = "paid"
        u["active_until"] = int(active_until or 0)
        u["last_payment_ts"] = now_ts

        processed = d.setdefault("__processed_invoices", {})
        already_processed = invoice_id in processed
        if not already_processed:
            processed[invoice_id] = now_ts  # 💬 помечаем, что начисление сделано

        # 💬 если invoice уже обрабатывали = не начисляем повторно
        if already_processed or gross_cents <= 0:
            _save_ref_data_sync(d)
            return

        active_cnt = _active_paying_count(r, now_ts)
        pct = _tier_percent(active_cnt)
        commission_cents = int(round(gross_cents * pct))

        # 💬 Новая модель: accrued_total растёт сразу после успешной оплаты
        r["accrued_total_cents"] = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0)) + commission_cents

        # 💬 backward-compatible поля (не ломаем старые данные/экраны)
        r["earned_cents"] = _safe_int(r.get("earned_cents")) + commission_cents

        u["earned_cents"] = _safe_int(u.get("earned_cents")) + commission_cents


        ev = {
            "ts": now_ts,
            "invoice_id": invoice_id,
            "gross_cents": gross_cents,
            "pct": pct,
            "commission_cents": commission_cents,
            "active_cnt": active_cnt,
        }
        events = r.setdefault("events", [])
        events.append(ev)
        if len(events) > 2000:
            del events[:200]  # 💬 срезаем старые хвосты

        _save_ref_data_sync(d)


async def referrals_apply_subscription_status(
    *,
    tg_user_id: int,
    status: str,
    active_until: int,
) -> None:
    """
    💬 Синкаем статус подписки по событиям subscription.updated/deleted.
    - unpaid = сразу неактивный
    - canceled = неактивный
    """
    s = (status or "").strip().lower()
    if s not in ("unpaid", "canceled"):
        return

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        referrer_id = d.get("user_to_referrer", {}).get(str(tg_user_id))
        if not referrer_id:
            return

        r = _get_or_create_referrer(d, str(referrer_id))
        referred = r.setdefault("referred", {})
        u = referred.get(str(tg_user_id))
        if not isinstance(u, dict):
            return

        u["status"] = "unpaid" if s == "unpaid" else "canceled"
        u["active_until"] = int(active_until or 0)

        _save_ref_data_sync(d)


# -----------------------------------------------------------------------------
# UI builders
# -----------------------------------------------------------------------------
async def _get_bot_username(bot) -> str:
    global _BOT_USERNAME_CACHE
    if _BOT_USERNAME_CACHE:
        return _BOT_USERNAME_CACHE
    try:
        me = await bot.get_me()
        _BOT_USERNAME_CACHE = (me.username or "").strip()
    except Exception:
        _BOT_USERNAME_CACHE = ""
    return _BOT_USERNAME_CACHE or ""


async def _make_ref_deeplink(bot, referrer_id: str) -> str:
    username = await _get_bot_username(bot)
    if not username:
        return ""
    return f"https://t.me/{username}?start={REF_PAYLOAD_PREFIX}{referrer_id}"


def _kb_ref_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Мои рефералы", callback_data="ref:my:0")],
        [InlineKeyboardButton(text="🔗 Моя ссылка", callback_data="ref:link")],
        [InlineKeyboardButton(text="💸 Запросить выплату", callback_data="ref:payout_request")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="ref:rules:0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:open")],
    ])


def _kb_ref_pager(prefix: str, page: int, total_pages: int, back_cb: str) -> InlineKeyboardMarkup:
    # 💬 На границах не листаем дальше:
    # - если первая страница и жмём ← = показываем toast
    # - если последняя страница и жмём → = показываем toast
    last_page = max(0, int(total_pages) - 1)

    if page <= 0:
        left_cb = "ref:edge:first"
    else:
        left_cb = f"{prefix}:{page - 1}"

    if page >= last_page:
        right_cb = "ref:edge:last"
    else:
        right_cb = f"{prefix}:{page + 1}"

    row1 = [
        InlineKeyboardButton(text="⬅️", callback_data=left_cb),
        InlineKeyboardButton(text=f"{page+1} из {total_pages}", callback_data="ref:noop"),
        InlineKeyboardButton(text="➡️", callback_data=right_cb),
    ]
    row2 = [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


_RULE_PAGES: list[str] = [
    "📜 <b>Правила реферальной программы</b>\n\n"
    "Комиссия начисляется за <b>каждое продление</b> подписки приведённого пользователя, пока подписка активна и оплачена.",

    "✅ <b>Кто считается активным</b>\n\n"
    "Активный = статус <b>Оплачено</b> и нет задержки.\n"
    "Статус <b>Не оплачено</b> = сразу неактивный и не считается.",

    "📈 <b>Процент (динамический)</b>\n\n"
    "Процент зависит от текущего числа <b>активных платящих</b>:\n"
    "• до 10 = 30%\n"
    "• с 11 = 40%\n"
    "• с 26 = 50%\n\n"
    "Если активных стало меньше = процент снижается обратно.",

    "🧾 <b>База комиссии</b>\n\n"
    "Комиссия считается от <b>полной суммы платежа</b> (gross).",

    "🚫 <b>Когда комиссия не начисляется</b>\n\n"
    "• статус Не оплачено\n"
    "• статус Отменено\n"
    "• подписка не активна\n"
    "• платёж отменён или не прошёл",

    "🔒 <b>Важно про реферальную ссылку</b>\n\n"
    "<b>Реферал засчитывается только если человек впервые запускает бота по вашей ссылке.</b>\n"
    "Если он уже запускал бота раньше = привязка не создаётся.",
]


# -----------------------------------------------------------------------------
# UI handlers
# -----------------------------------------------------------------------------
@router.callback_query(F.data == "settings:referrals")
async def referrals_open_cb(callback: CallbackQuery):
    await callback.answer()

    referrer_id = str(callback.from_user.id)

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)
        _save_ref_data_sync(d)

    now_ts = _now()
    active_cnt = _active_paying_count(r, now_ts)
    pct = _tier_percent(active_cnt)

    # 💬 Новая фин-модель (backward-compatible)
    accrued_total = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0))
    paid_total = _safe_int(r.get("paid_total_cents"), _safe_int(r.get("paid_out_cents"), 0))
    balance_due = max(0, accrued_total - paid_total)

    txt = (
        "🤝 <b>Рефералы</b>\n\n"
        f"📈 Текущий процент = <b>{int(pct*100)}%</b>\n"
        f"✅ Активных платящих = <b>{active_cnt}</b>\n\n"
        f"💳 Баланс к выплате = <b>{_format_money(balance_due)}</b> €\n"
        "📌 Выплата доступна от <b>30</b> €\n\n"
        f"💰 Начислено всего = <b>{_format_money(accrued_total)}</b> €\n"
        f"💸 Выплачено всего = <b>{_format_money(paid_total)}</b> €\n\n"
        "Выбери раздел:"
    )



    try:
        await callback.message.edit_text(txt, reply_markup=_kb_ref_home(), parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer(txt, reply_markup=_kb_ref_home(), parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data == "ref:home")
async def ref_home_cb(callback: CallbackQuery):
    await callback.answer()
    return await referrals_open_cb(callback)


@router.callback_query(F.data == "ref:payout_request")
async def ref_payout_request_cb(callback: CallbackQuery):
    # 💬 Только alert/toast, без сообщений
    referrer_id = str(callback.from_user.id)

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)

        accrued_total = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0))
        paid_total = _safe_int(r.get("paid_total_cents"), _safe_int(r.get("paid_out_cents"), 0))
        balance_due = max(0, accrued_total - paid_total)

    if balance_due < 3000:
        await callback.answer("Выплата доступна только от 30 €", show_alert=True)
        return

    await callback.answer("Запрос получен. Я свяжусь с тобой для выплаты.", show_alert=True)


@router.callback_query(F.data.startswith("ref:rules:"))
async def ref_rules_cb(callback: CallbackQuery):
    await callback.answer()

    try:
        page = int(callback.data.split(":")[-1])
    except Exception:
        page = 0

    pages = _RULE_PAGES
    total = max(1, len(pages))
    page = max(0, min(total - 1, page))

    txt = pages[page]
    kb = _kb_ref_pager(prefix="ref:rules", page=page, total_pages=total, back_cb="ref:home")

    try:
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data == "ref:link")
async def ref_link_cb(callback: CallbackQuery):
    await callback.answer()

    referrer_id = str(callback.from_user.id)

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)
        _save_ref_data_sync(d)

    deeplink = await _make_ref_deeplink(callback.bot, referrer_id)

    share_text = "Открой бота по ссылке и нажми Start, чтобы тебя засчитали рефералом"
    share_url = f"https://t.me/share/url?url={quote(deeplink)}&text={quote(share_text)}"

    txt = (
        "🔗 <b>Моя ссылка</b>\n\n"
        f"{deeplink}\n\n"
        "Инструкция:\n"
        "1) Отправь ссылку другу\n"
        "2) Друг должен впервые открыть бота по ссылке и нажать Start\n"
        "3) Если он уже запускал бота раньше, привязка не создаётся"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=share_url)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ref:home")],
    ])

    try:
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("ref:my:"))
async def ref_my_cb(callback: CallbackQuery):
    await callback.answer()

    referrer_id = str(callback.from_user.id)
    try:
        page = int(callback.data.split(":")[-1])
    except Exception:
        page = 0

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)
        _save_ref_data_sync(d)

    referred = r.get("referred", {}) or {}

    # 💬 сортировка: оплачено сверху, потом ожидание, потом неоплачено, потом отменено
    order = {"paid": 0, "pending": 1, "unpaid": 2, "canceled": 3}

    items = []
    for uid, info in referred.items():
        if not isinstance(info, dict):
            continue
        st = info.get("status") or "pending"
        items.append((order.get(st, 9), -_safe_int(info.get("first_start_ts")), uid, info))

    items.sort()

    per_page = 12
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(0, min(total_pages - 1, page))

    start = page * per_page
    chunk = items[start:start + per_page]

    now_ts = _now()

    cnt_paid = 0
    cnt_pending = 0
    cnt_unpaid = 0
    cnt_canceled = 0

    for _, _, _, info in items:
        st = (info.get("status") or "pending")
        if st == "paid" and _safe_int(info.get("active_until")) > now_ts:
            cnt_paid += 1
        elif st == "pending":
            cnt_pending += 1
        elif st == "unpaid":
            cnt_unpaid += 1
        elif st == "canceled":
            cnt_canceled += 1

    lines = ["👥 <b>Мои рефералы</b>\n"]

    if not chunk:
        lines.append("Пока нет приглашённых.")
    else:
        for _, _, uid, info in chunk:
            username = (info.get("username") or "").strip()
            if not username:
                username = "—"
            status = _status_ru(info.get("status") or "pending")
            until = _safe_int(info.get("active_until"))
            until_line = ""
            if (info.get("status") == "paid") and until > 0:
                until_line = f" до {time.strftime('%Y-%m-%d', time.gmtime(until))}"
            lines.append(f"{username} | id {uid} = <b>{status}</b>{until_line}")

    lines.append("\nИтоги:")
    lines.append(f"✅ Активных (оплачено) = <b>{cnt_paid}</b>")
    lines.append(f"⏳ В ожидании = <b>{cnt_pending}</b>")
    lines.append(f"⚠️ Не оплачено = <b>{cnt_unpaid}</b>")
    lines.append(f"🛑 Отменено = <b>{cnt_canceled}</b>")

    txt = "\n".join(lines)
    kb = _kb_ref_pager(prefix="ref:my", page=page, total_pages=total_pages, back_cb="ref:home")

    try:
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data == "ref:noop")
async def ref_noop_cb(callback: CallbackQuery):
    # 💬 кнопка-индикатор страниц
    await callback.answer()

@router.callback_query(F.data == "ref:edge:first")
async def ref_edge_first_cb(callback: CallbackQuery):
    # 💬 Первая страница, дальше влево нельзя
    await callback.answer("Это первая страница", show_alert=False)

@router.callback_query(F.data == "ref:edge:last")
async def ref_edge_last_cb(callback: CallbackQuery):
    # 💬 Последняя страница, дальше вправо нельзя
    await callback.answer("Это последняя страница", show_alert=False)

@router.message(Command("payout"))
async def cmd_payout(message: Message):
    # 💬 Доступ только владельцу
    if OWNER_USER_ID <= 0 or message.from_user.id != OWNER_USER_ID:
        await message.answer("Команда недоступна.")
        return

    _PAYOUT_WAIT[message.from_user.id] = True
    await message.answer("Ок. Отправь: user_id сумма\nНапример: 123456789 30")


@router.message(F.text)
async def cmd_payout_input(message: Message):
    # 💬 Ловим только если владелец в режиме ожидания ввода
    if OWNER_USER_ID <= 0 or message.from_user.id != OWNER_USER_ID:
        return
    if not _PAYOUT_WAIT.get(message.from_user.id):
        return

    raw = (message.text or "").strip()
    parts = raw.split()
    if len(parts) != 2:
        await message.answer("Неверный формат. Нужно: user_id сумма\nНапример: 123456789 30")
        return

    ref_uid_raw, amount_raw = parts[0], parts[1].replace(",", ".")
    if not ref_uid_raw.isdigit():
        await message.answer("user_id должен быть числом.")
        return

    try:
        amount_eur = float(amount_raw)
    except Exception:
        await message.answer("Сумма должна быть числом. Например: 30 или 30.50")
        return

    if amount_eur <= 0:
        await message.answer("Сумма должна быть > 0")
        return

    amount_cents = int(round(amount_eur * 100))
    referrer_id = str(int(ref_uid_raw))

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)

        accrued_total = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0))
        paid_total = _safe_int(r.get("paid_total_cents"), _safe_int(r.get("paid_out_cents"), 0))
        balance_due = max(0, accrued_total - paid_total)

        if amount_cents > balance_due:
            await message.answer(f"Ошибка. Сумма больше баланса.\nБаланс = {_format_money(balance_due)} €")
            return

        # 💬 применяем выплату
        r["paid_total_cents"] = paid_total + amount_cents
        r["paid_out_cents"] = _safe_int(r.get("paid_out_cents")) + amount_cents  # backward-compatible

        new_paid_total = _safe_int(r.get("paid_total_cents"))
        new_balance_due = max(0, accrued_total - new_paid_total)

        _save_ref_data_sync(d)

    # 💬 выходим из режима ожидания
    _PAYOUT_WAIT.pop(message.from_user.id, None)

    # 💬 clean chat: удаляем сообщение ввода владельца (best effort)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        "ОК. Выплачено +{amt}€.\nТеперь: paid_total={paid}€, balance_due={bal}€".format(
            amt=_format_money(amount_cents),
            paid=_format_money(new_paid_total),
            bal=_format_money(new_balance_due),
        )
    )

