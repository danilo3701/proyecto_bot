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
import sqlite3
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
_ADMIN_MENU_USERS: set[int] = set()  # 💬 пользователи, открывшие секретное админ-меню
_ADMIN_MENU_WAIT: dict[int, dict] = {}  # 💬 admin_id -> {"action": "pay|rollback", "referrer_id": str}
_REF_MENU_USERS: set[int] = set()  # 💬 пользователи, открывшие /ref меню
PAYOUTS_DB_PATH = os.getenv("REFERRAL_PAYOUTS_DB_PATH", "/data/referral_payouts.sqlite3")
MIN_PAYOUT_CENTS = 2000



# 💬 кэш username бота, чтобы не дергать getMe постоянно
_BOT_USERNAME_CACHE: str | None = None

# 💬 простой lock, чтобы не было гонок (webhook + UI)
_REF_LOCK = asyncio.Lock()
_NOW_OVERRIDE: Optional[int] = None


# -----------------------------------------------------------------------------
# Storage helpers
# -----------------------------------------------------------------------------
def _now() -> int:
    if _NOW_OVERRIDE is not None:
        return int(_NOW_OVERRIDE)
    return int(time.time())


def set_now_override(now_ts: Optional[int]) -> None:
    """QA helper: фиксируем текущее время для детерминированных тестов."""
    global _NOW_OVERRIDE
    _NOW_OVERRIDE = None if now_ts is None else int(now_ts)


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


def _init_payouts_table() -> None:
    conn = sqlite3.connect(PAYOUTS_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                note TEXT DEFAULT '',
                admin_id INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def add_payout(referrer_id: str, amount_cents: int, admin_id: int, note: str = "") -> None:
    _init_payouts_table()
    conn = sqlite3.connect(PAYOUTS_DB_PATH)
    try:
        conn.execute(
            "INSERT INTO referral_payouts(referrer_id, amount_cents, created_at, note, admin_id) VALUES(?,?,?,?,?)",
            (str(referrer_id), int(amount_cents), _now(), str(note or ""), int(admin_id or 0)),
        )
        conn.commit()
    finally:
        conn.close()


def get_payouts(referrer_id: str, limit: int = 10) -> list[dict]:
    _init_payouts_table()
    lim = max(1, min(100, _safe_int(limit, 10)))
    conn = sqlite3.connect(PAYOUTS_DB_PATH)
    try:
        cur = conn.execute(
            "SELECT id, amount_cents, created_at, note, admin_id FROM referral_payouts WHERE referrer_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (str(referrer_id), lim),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(r[0]),
            "amount_cents": int(r[1]),
            "created_at": int(r[2]),
            "note": r[3] or "",
            "admin_id": int(r[4]),
        }
        for r in rows
    ]


def get_payouts_summary(month: str) -> dict:
    _init_payouts_table()
    month = (month or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", month)
    if not m:
        return {"month": month, "total_cents": 0, "count": 0}

    year = int(m.group(1))
    mon = int(m.group(2))
    if mon < 1 or mon > 12:
        return {"month": month, "total_cents": 0, "count": 0}

    start_dt = datetime(year, mon, 1)
    next_dt = datetime(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
    start_ts = int(start_dt.timestamp())
    end_ts = int(next_dt.timestamp())

    conn = sqlite3.connect(PAYOUTS_DB_PATH)
    try:
        cur = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0), COUNT(*) FROM referral_payouts WHERE created_at >= ? AND created_at < ?",
            (start_ts, end_ts),
        )
        total_cents, count = cur.fetchone()
    finally:
        conn.close()
    return {"month": month, "total_cents": int(total_cents or 0), "count": int(count or 0)}


def get_user_partner_id(tg_user_id: int) -> Optional[str]:
    """
    Возвращает partner_id (referrer_id) для пользователя, если есть реферальная связка.
    Приоритет:
    1) user_to_referrer[uid]
    2) fallback-поиск в referrers[*].referred[uid] со статусом pending/paid/confirmed
    """
    uid = str(_safe_int(tg_user_id, 0))
    if not uid or uid == "0":
        return None

    d = _load_ref_data_sync()

    direct = d.get("user_to_referrer", {}).get(uid)
    if direct:
        return str(direct)

    allowed_statuses = {"pending", "paid", "confirmed"}
    referrers = d.get("referrers", {}) or {}
    for referrer_id, ref_data in referrers.items():
        referred = (ref_data or {}).get("referred", {}) or {}
        user_entry = referred.get(uid)
        if not isinstance(user_entry, dict):
            continue
        status = str(user_entry.get("status", "")).strip().lower()
        if status in allowed_statuses:
            return str(referrer_id)

    return None


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


def _get_referrer_if_exists(d: dict, referrer_id: str) -> Optional[dict]:
    referrers = d.get("referrers", {}) or {}
    r = referrers.get(str(referrer_id))
    if isinstance(r, dict):
        return r
    return None


def _referrals_count(referrer: dict) -> int:
    explicit = _safe_int(referrer.get("referrals_count"), -1)
    inferred = len((referrer.get("referred") or {}))
    if explicit >= 0:
        return max(explicit, inferred)
    return inferred


def _is_partner_allowed(referrer: dict) -> bool:
    return True


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
    - реферер может быть любым валидным user_id
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
    payment_provider: str = "stripe",
) -> None:
    """
    💬 Начисление комиссии по invoice.paid / invoice.payment_succeeded.
    - комиссия = gross * текущий процент (по текущему активному числу)
    - анти-дубль по invoice_id
    """
    invoice_id = str(invoice_obj.get("id") or "").strip()
    provider = str(payment_provider or "stripe").strip().lower()
    provider = provider or "stripe"
    dedupe_key = f"{provider}:{invoice_id}" if invoice_id else ""
    if not dedupe_key:
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
        already_processed = dedupe_key in processed
        if not already_processed:
            processed[dedupe_key] = now_ts  # 💬 помечаем, что начисление сделано

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
            "provider": provider,
            "invoice_id": invoice_id,
            "dedupe_key": dedupe_key,
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
    if s not in ("pending", "paid", "unpaid", "canceled"):
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

        u["status"] = s
        u["active_until"] = int(active_until or 0)

        _save_ref_data_sync(d)


async def referrals_recompute_expired(now_ts: Optional[int] = None) -> None:
    """
    Сервисный пересчёт: paid + истёкший active_until -> unpaid.
    Нужен для QA/cron и синка кабинета реферера без внешних вебхуков.
    """
    now_ts = int(now_ts) if now_ts is not None else _now()

    async with _REF_LOCK:
        d = _load_ref_data_sync()
        changed = False

        referrers = d.get("referrers", {}) or {}
        for _, ref_data in referrers.items():
            if not isinstance(ref_data, dict):
                continue
            referred = ref_data.get("referred", {}) or {}
            for _, entry in referred.items():
                if not isinstance(entry, dict):
                    continue
                status = str(entry.get("status") or "").strip().lower()
                until = _safe_int(entry.get("active_until"), 0)
                if status == "paid" and until > 0 and until <= now_ts:
                    entry["status"] = "unpaid"
                    changed = True

        if changed:
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
        [InlineKeyboardButton(text="📋 Мои рефералы", callback_data="ref:my:0")],
        [InlineKeyboardButton(text="🔗 Моя ссылка", callback_data="ref:link")],
        [InlineKeyboardButton(text="📜 Правила партнёрки", callback_data="ref:rules:0")],
        [InlineKeyboardButton(text="💸 История выплат", callback_data="ref:payout_history:0")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings:open")],
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


def _kb_admin_ref_list(prefix: str, page: int, total_pages: int, back_cb: str) -> InlineKeyboardMarkup:
    last_page = max(0, int(total_pages) - 1)

    if page <= 0:
        left_cb = "refadm:edge:first"
    else:
        left_cb = f"{prefix}:{page - 1}"

    if page >= last_page:
        right_cb = "refadm:edge:last"
    else:
        right_cb = f"{prefix}:{page + 1}"

    row1 = [
        InlineKeyboardButton(text="⬅️", callback_data=left_cb),
        InlineKeyboardButton(text=f"{page+1} из {total_pages}", callback_data="refadm:noop"),
        InlineKeyboardButton(text="➡️", callback_data=right_cb),
    ]
    row2 = [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def _kb_admin_ref_card(referrer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Выплата", callback_data=f"refadm:pay:{referrer_id}"),
            InlineKeyboardButton(text="➖ Откат", callback_data=f"refadm:rollback:{referrer_id}"),
        ],
        [InlineKeyboardButton(text="🧾 История выплат", callback_data=f"refadm:history:{referrer_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="refadm:list:0")],
    ])


def _admin_ref_list_data() -> list[dict]:
    d = _load_ref_data_sync()
    referrers = d.get("referrers", {}) or {}
    items: list[dict] = []
    now_ts = _now()

    for ref_id, ref_data in referrers.items():
        if not isinstance(ref_data, dict):
            continue
        accrued_total = _safe_int(ref_data.get("accrued_total_cents"), _safe_int(ref_data.get("earned_cents"), 0))
        paid_total = _safe_int(ref_data.get("paid_total_cents"), _safe_int(ref_data.get("paid_out_cents"), 0))
        balance_due = max(0, accrued_total - paid_total)
        active_cnt = _active_paying_count(ref_data, now_ts)
        items.append({
            "referrer_id": str(ref_id),
            "accrued_total": accrued_total,
            "paid_total": paid_total,
            "balance_due": balance_due,
            "active_cnt": active_cnt,
        })

    items.sort(key=lambda x: (-(x.get("balance_due", 0)), -(x.get("active_cnt", 0)), x.get("referrer_id", "")))
    return items


def _admin_ref_card_text(referrer_id: str) -> str:
    d = _load_ref_data_sync()
    r = d.get("referrers", {}).get(str(referrer_id), {}) or {}
    accrued_total = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0))
    paid_total = _safe_int(r.get("paid_total_cents"), _safe_int(r.get("paid_out_cents"), 0))
    balance_due = max(0, accrued_total - paid_total)
    active_cnt = _active_paying_count(r, _now())

    return (
        f"👤 <b>Referrer {referrer_id}</b>\n\n"
        f"Начислено всего: <b>{_format_money(accrued_total)} €</b>\n"
        f"Выплачено всего: <b>{_format_money(paid_total)} €</b>\n"
        f"К выплате: <b>{_format_money(balance_due)} €</b>\n"
        f"Активных платящих: <b>{active_cnt}</b>"
    )


_RULE_PAGES: list[str] = [
    "📜 <b>Правила партнёрской программы</b>\n\n"
    "Процент зависит от числа <b>активных платящих</b> рефералов и может как расти, так и снижаться.",
    "📈 <b>Текущие уровни</b>\n\n"
    "• до 10 активных — <b>30%</b>\n"
    "• 11–25 активных — <b>40%</b>\n"
    "• 26+ активных — <b>50%</b>",
    "✅ <b>Кто считается активным платящим</b>\n\n"
    "Только реферал со статусом <b>paid</b> и датой <b>active_until &gt; now</b>.\n"
    "Статусы canceled, unpaid и pending в активные не входят.",
    "💶 <b>Пример с подпиской €6.99</b>\n\n"
    "• 30% → €2.10\n"
    "• 40% → €2.80\n"
    "• 50% → €3.50",
    "💸 <b>Выплаты</b>\n\n"
    "Минимальная сумма выплаты — <b>20€</b>.\n"
    "Выплаты выполняются вручную: раз в месяц владелец переводит деньги вне Telegram.",
    "🔒 <b>Привязка реферала</b>\n\n"
    "Реферал засчитывается только если пользователь впервые запускает бота по вашей ссылке /start refpay_...",
]


def _build_ref_cabinet_text(referrer: dict, deeplink: str) -> str:
    now_ts = _now()
    active_cnt = _active_paying_count(referrer, now_ts)
    total_refs = _referrals_count(referrer)
    pct = _tier_percent(active_cnt)

    accrued_total = _safe_int(referrer.get("accrued_total_cents"), _safe_int(referrer.get("earned_cents"), 0))
    paid_total = _safe_int(referrer.get("paid_total_cents"), _safe_int(referrer.get("paid_out_cents"), 0))
    balance_due = max(0, accrued_total - paid_total)

    return (
        "🤝 <b>Партнёрский кабинет</b>\n\n"
        f"🔗 Ваша ссылка:\n{deeplink}\n\n"
        f"✅ Активных платящих: <b>{active_cnt}</b>\n"
        f"👥 Всего рефералов: <b>{total_refs}</b>\n"
        f"📈 Текущий уровень: <b>{int(pct * 100)}%</b>\n\n"
        f"💰 Начислено всего: <b>{_format_money(accrued_total)} €</b>\n"
        f"💸 Выплачено всего: <b>{_format_money(paid_total)} €</b>\n"
        f"💳 Баланс к выплате: <b>{_format_money(balance_due)} €</b>\n"
        f"📌 Минимум для выплаты: <b>{_format_money(MIN_PAYOUT_CENTS)} €</b>"
    )


async def render_ref_cabinet(message_or_event, user_id: int, prefer_edit: bool = False) -> None:
    referrer_id = str(user_id)
    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_referrer_if_exists(d, referrer_id)

    if not r:
        txt = "Нет партнёрского доступа. Напишите администратору."
        if isinstance(message_or_event, CallbackQuery):
            await message_or_event.message.answer(txt)
        else:
            await message_or_event.answer(txt)
        return

    event_bot = getattr(message_or_event, "bot", None)
    if event_bot is None and isinstance(message_or_event, CallbackQuery):
        event_bot = message_or_event.message.bot

    deeplink = await _make_ref_deeplink(event_bot, referrer_id) if event_bot else ""
    txt = _build_ref_cabinet_text(r, deeplink)
    if isinstance(message_or_event, CallbackQuery) and prefer_edit:
        try:
            await message_or_event.message.edit_text(txt, reply_markup=_kb_ref_home(), parse_mode="HTML", disable_web_page_preview=True)
            return
        except TelegramBadRequest:
            pass
    if isinstance(message_or_event, CallbackQuery):
        await message_or_event.message.answer(txt, reply_markup=_kb_ref_home(), parse_mode="HTML", disable_web_page_preview=True)
    else:
        await message_or_event.answer(txt, reply_markup=_kb_ref_home(), parse_mode="HTML", disable_web_page_preview=True)


# -----------------------------------------------------------------------------
# UI handlers
# -----------------------------------------------------------------------------
@router.callback_query(F.data == "settings:referrals")
async def referrals_open_cb(callback: CallbackQuery):
    await callback.answer()
    _REF_MENU_USERS.add(callback.from_user.id)
    await render_ref_cabinet(callback, callback.from_user.id, prefer_edit=True)

# -----------------------------------------------------------------------------
# UI handlers
# -----------------------------------------------------------------------------
@router.callback_query(F.data == "settings:referrals")
async def referrals_open_cb(callback: CallbackQuery):
    await callback.answer()
    await render_ref_cabinet(callback, callback.from_user.id, prefer_edit=True)

@router.message(Command("ref"))
async def cmd_ref(message: Message):
    if getattr(message, "_ref_proxy_handled", False):
        return
    _REF_MENU_USERS.add(message.from_user.id)
    await render_ref_cabinet(message, message.from_user.id, prefer_edit=False)

async def _render_admin_ref_list(message_or_event, page: int = 0, prefer_edit: bool = False) -> None:
    items = _admin_ref_list_data()
    per_page = 12
    total_items = len(items)
    lines = ["📋 <b>Рефералы (админ)</b>\n"]

    if total_items == 0:
        lines.append("Рефералов пока нет. Когда появятся — список появится здесь.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="refadm:list:0")],
            [InlineKeyboardButton(text="⬅️ Закрыть", callback_data="refadm:close")],
        ])
        text = "\n".join(lines)
    else:
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        page = max(0, min(total_pages - 1, page))
        start = page * per_page
        slice_items = items[start:start + per_page]

        for i, it in enumerate(slice_items, start=1 + start):
            rid = it["referrer_id"]
            bal = _format_money(it["balance_due"])
            active = it["active_cnt"]
            lines.append(f"{i}) <b>{rid}</b> | к выплате: <b>{bal} €</b> | активных: {active}")

        kb_rows = []
        for it in slice_items:
            rid = it["referrer_id"]
            kb_rows.append([InlineKeyboardButton(text=f"Открыть {rid}", callback_data=f"refadm:open:{rid}")])
        kb = _kb_admin_ref_list(prefix="refadm:list", page=page, total_pages=total_pages, back_cb="refadm:close")
        kb.inline_keyboard = kb_rows + kb.inline_keyboard
        text = "\n".join(lines)
    if isinstance(message_or_event, CallbackQuery) and prefer_edit:
        try:
            await message_or_event.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
            return
        except TelegramBadRequest:
            pass
    if isinstance(message_or_event, CallbackQuery):
        await message_or_event.message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await message_or_event.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("refadm:list:"))
async def admin_ref_list_cb(callback: CallbackQuery):
    if callback.from_user.id not in _ADMIN_MENU_USERS:
        await callback.answer("Команда недоступна.", show_alert=True)
        return
    await callback.answer()
    try:
        page = int(callback.data.split(":")[-1])
    except Exception:
        page = 0
    await _render_admin_ref_list(callback, page=page, prefer_edit=True)


@router.callback_query(F.data == "refadm:close")
async def admin_ref_close_cb(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "refadm:noop")
async def admin_ref_noop_cb(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "refadm:edge:first")
async def admin_ref_edge_first_cb(callback: CallbackQuery):
    await callback.answer("Это первая страница", show_alert=False)


@router.callback_query(F.data == "refadm:edge:last")
async def admin_ref_edge_last_cb(callback: CallbackQuery):
    await callback.answer("Это последняя страница", show_alert=False)


@router.callback_query(F.data.startswith("refadm:open:"))
async def admin_ref_open_cb(callback: CallbackQuery):
    if callback.from_user.id not in _ADMIN_MENU_USERS:
        await callback.answer("Команда недоступна.", show_alert=True)
        return
    await callback.answer()
    referrer_id = callback.data.split(":")[-1]
    txt = _admin_ref_card_text(referrer_id)
    kb = _kb_admin_ref_card(referrer_id)
    try:
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer(txt, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("refadm:history:"))
async def admin_ref_history_cb(callback: CallbackQuery):
    if callback.from_user.id not in _ADMIN_MENU_USERS:
        await callback.answer("Команда недоступна.", show_alert=True)
        return
    await callback.answer()
    referrer_id = callback.data.split(":")[-1]
    payouts = get_payouts(referrer_id=referrer_id, limit=10)
    lines = [f"💸 <b>История выплат: {referrer_id}</b>\n"]
    if not payouts:
        lines.append("— выплат пока не было —")
    else:
        for p in payouts:
            dt = time.strftime("%Y-%m-%d", time.gmtime(int(p["created_at"])))
            note = f" — {p['note']}" if p.get("note") else ""
            lines.append(f"• {dt}: <b>{_format_money(p['amount_cents'])} €</b>{note}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"refadm:open:{referrer_id}")]])
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("refadm:pay:"))
async def admin_ref_pay_cb(callback: CallbackQuery):
    if callback.from_user.id not in _ADMIN_MENU_USERS:
        await callback.answer("Команда недоступна.", show_alert=True)
        return
    await callback.answer()
    referrer_id = callback.data.split(":")[-1]
    _ADMIN_MENU_WAIT[callback.from_user.id] = {"action": "pay", "referrer_id": referrer_id}
    await callback.message.answer("Введи сумму выплаты: например 12.50 или cents:1234")


@router.callback_query(F.data.startswith("refadm:rollback:"))
async def admin_ref_rollback_cb(callback: CallbackQuery):
    if callback.from_user.id not in _ADMIN_MENU_USERS:
        await callback.answer("Команда недоступна.", show_alert=True)
        return
    await callback.answer()
    referrer_id = callback.data.split(":")[-1]
    _ADMIN_MENU_WAIT[callback.from_user.id] = {"action": "rollback", "referrer_id": referrer_id}
    await callback.message.answer("Введи сумму отката выплаты: например 12.50 или cents:1234")


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

    if balance_due < MIN_PAYOUT_CENTS:
        await callback.answer(f"Выплата доступна только от {_format_money(MIN_PAYOUT_CENTS)} €", show_alert=True)
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

    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=3)
    if len(parts) < 3:
        _PAYOUT_WAIT[message.from_user.id] = True
        await message.answer("Формат: /payout <referrer_user_id> <amount> [note].\nИли отправь в следующем сообщении: user_id сумма [note]")
        return

    ref_uid_raw = parts[1].strip()
    amount_raw = parts[2].strip()
    note = parts[3].strip() if len(parts) >= 4 else ""
    if not ref_uid_raw.isdigit():
        await message.answer("referrer_user_id должен быть числом.")
        return

    amount_cents = _parse_amount_to_cents(amount_raw)
    if amount_cents <= 0:
        await message.answer("Некорректная сумма. Используйте 12.34 (EUR) или cents:1234")
        return

    await _apply_owner_payout(message, referrer_id=str(int(ref_uid_raw)), amount_cents=amount_cents, note=note)


def _parse_amount_to_cents(raw_amount: str) -> int:
    raw = str(raw_amount or "").strip().replace(",", ".")
    if not raw:
        return 0
    if raw.lower().startswith("cents:"):
        v = raw.split(":", 1)[1].strip()
        return _safe_int(v, 0)
    if raw.isdigit() and len(raw) >= 4:
        return _safe_int(raw, 0)
    try:
        dec = Decimal(raw)
    except (InvalidOperation, ValueError):
        return 0
    if dec <= 0:
        return 0
    return int((dec * 100).quantize(Decimal("1")))


async def _apply_owner_payout(message: Message, referrer_id: str, amount_cents: int, note: str = "") -> None:
    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)
        accrued_total = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0))
        paid_total = _safe_int(r.get("paid_total_cents"), _safe_int(r.get("paid_out_cents"), 0))
        balance_due = max(0, accrued_total - paid_total)
        if amount_cents > balance_due:
            await message.answer(f"Ошибка. Сумма больше баланса. Баланс = {_format_money(balance_due)} €")
            return

        r["paid_total_cents"] = paid_total + amount_cents
        r["paid_out_cents"] = _safe_int(r.get("paid_out_cents")) + amount_cents
        _save_ref_data_sync(d)

    add_payout(referrer_id=referrer_id, amount_cents=amount_cents, admin_id=message.from_user.id, note=note)

    new_paid_total = paid_total + amount_cents
    new_balance_due = max(0, accrued_total - new_paid_total)
    await message.answer(
        "✅ Выплата зафиксирована.\n"
        f"Начислено: {_format_money(accrued_total)} €\n"
        f"Выплачено: {_format_money(new_paid_total)} €\n"
        f"К выплате: {_format_money(new_balance_due)} €"
    )


async def _apply_owner_payout_rollback(message: Message, referrer_id: str, amount_cents: int, note: str = "") -> None:
    async with _REF_LOCK:
        d = _load_ref_data_sync()
        r = _get_or_create_referrer(d, referrer_id)
        accrued_total = _safe_int(r.get("accrued_total_cents"), _safe_int(r.get("earned_cents"), 0))
        paid_total = _safe_int(r.get("paid_total_cents"), _safe_int(r.get("paid_out_cents"), 0))
        if amount_cents > paid_total:
            await message.answer(f"Ошибка. Сумма больше выплачено. Выплачено = {_format_money(paid_total)} €")
            return

        r["paid_total_cents"] = max(0, paid_total - amount_cents)
        r["paid_out_cents"] = max(0, _safe_int(r.get("paid_out_cents")) - amount_cents)
        _save_ref_data_sync(d)

    add_payout(referrer_id=referrer_id, amount_cents=-int(amount_cents), admin_id=message.from_user.id, note=note)

    new_paid_total = max(0, paid_total - amount_cents)
    new_balance_due = max(0, accrued_total - new_paid_total)
    await message.answer(
        "✅ Откат выплаты зафиксирован.\n"
        f"Начислено: {_format_money(accrued_total)} €\n"
        f"Выплачено: {_format_money(new_paid_total)} €\n"
        f"К выплате: {_format_money(new_balance_due)} €"
    )


@router.message(F.text)
async def cmd_payout_input(message: Message):
    # 💬 админ-меню ожидание суммы (секретная команда)
    if _ADMIN_MENU_WAIT.get(message.from_user.id):
        payload = _ADMIN_MENU_WAIT.pop(message.from_user.id, None) or {}
        raw = (message.text or "").strip()
        amount_cents = _parse_amount_to_cents(raw)
        if amount_cents <= 0:
            await message.answer("Сумма должна быть > 0. Используйте 12.50 или cents:1234")
            return
        action = payload.get("action")
        referrer_id = str(payload.get("referrer_id") or "")
        if not referrer_id.isdigit():
            await message.answer("Ошибка. referrer_id неверный.")
            return
        try:
            await message.delete()
        except Exception:
            pass
        if action == "pay":
            await _apply_owner_payout(message, referrer_id=referrer_id, amount_cents=amount_cents)
        elif action == "rollback":
            await _apply_owner_payout_rollback(message, referrer_id=referrer_id, amount_cents=amount_cents)
        return

    # 💬 Ловим только если владелец в режиме ожидания ввода
    if OWNER_USER_ID <= 0 or message.from_user.id != OWNER_USER_ID:
        return
    if not _PAYOUT_WAIT.get(message.from_user.id):
        return

    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Неверный формат. Нужно: user_id сумма [note]")
        return

    ref_uid_raw = parts[0]
    amount_raw = parts[1]
    note = parts[2] if len(parts) >= 3 else ""
    if not ref_uid_raw.isdigit():
        await message.answer("user_id должен быть числом.")
        return

    amount_cents = _parse_amount_to_cents(amount_raw)
    if amount_cents <= 0:
        await message.answer("Сумма должна быть > 0. Используйте 12.34 или cents:1234")
        return
    referrer_id = str(int(ref_uid_raw))

    # 💬 выходим из режима ожидания
    _PAYOUT_WAIT.pop(message.from_user.id, None)

    # 💬 clean chat: удаляем сообщение ввода владельца (best effort)
    try:
        await message.delete()
    except Exception:
        pass

    await _apply_owner_payout(message, referrer_id=referrer_id, amount_cents=amount_cents, note=note)


@router.message(Command("payouts"))
async def cmd_payouts(message: Message):
    raw = (message.text or "").strip()
    parts = raw.split()

    # Секретная команда без параметров: открываем админ-меню
    if len(parts) == 1:
        _ADMIN_MENU_USERS.add(message.from_user.id)
        await _render_admin_ref_list(message, page=0, prefer_edit=False)
        return

    referrer_id = parts[1] if len(parts) >= 2 else ""
    if not str(referrer_id).isdigit():
        await message.answer("Формат: /payouts <referrer_user_id> [limit]")
        return
    limit = _safe_int(parts[2], 10) if len(parts) >= 3 else 10
    payouts = get_payouts(referrer_id=str(int(referrer_id)), limit=limit)
    lines = [f"💸 Выплаты referrer {referrer_id}:"]
    if not payouts:
        lines.append("— нет записей")
    else:
        for p in payouts:
            dt = time.strftime("%Y-%m-%d %H:%M", time.gmtime(p["created_at"]))
            lines.append(f"• {dt} | {_format_money(p['amount_cents'])} €")
    await message.answer("\n".join(lines))


@router.message(Command("payouts_summary"))
async def cmd_payouts_summary(message: Message):
    if OWNER_USER_ID <= 0 or message.from_user.id != OWNER_USER_ID:
        await message.answer("Команда недоступна.")
        return
    parts = (message.text or "").strip().split()
    month = parts[1] if len(parts) >= 2 else datetime.utcnow().strftime("%Y-%m")
    summary = get_payouts_summary(month)
    await message.answer(
        f"📊 Выплаты за {summary['month']}:\n"
        f"Сумма: {_format_money(summary['total_cents'])} €\n"
        f"Количество выплат: {summary['count']}"
    )
@router.callback_query(F.data.startswith("ref:payout_history:"))
async def ref_payout_history_cb(callback: CallbackQuery):
    await callback.answer()
    referrer_id = str(callback.from_user.id)
    payouts = get_payouts(referrer_id=referrer_id, limit=10)
    lines = ["💸 <b>История выплат</b>\n"]
    if not payouts:
        lines.append("Выплат пока не было.")
    else:
        for p in payouts:
            dt = time.strftime("%Y-%m-%d", time.gmtime(int(p["created_at"])))
            note = f" — {p['note']}" if p.get("note") else ""
            lines.append(f"• {dt}: <b>{_format_money(p['amount_cents'])} €</b>{note}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="ref:home")]])
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        await callback.message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
