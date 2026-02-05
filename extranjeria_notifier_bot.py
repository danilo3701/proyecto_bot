import os
import json
import asyncio
import random
import datetime as dt
from zoneinfo import ZoneInfo
from typing import Any
from html import escape as _h  # 💬 HTML-екранирование для значений в тексте

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest


# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATA_PATH = os.getenv("DATA_PATH", "/data/notifier_users.json").strip()

# 💬 Канал, на який треба підписатися, щоб увімкнути сповіщення
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@espanolingooo").strip()

# 💬 Куди веде кнопка в сповіщенні (поки можна залишити так, потім заміниш)
BOOKING_URL = os.getenv("BOOKING_URL", "https://sede.administracionespublicas.gob.es/icpplus/index.html").strip()

# 💬 Вікно сповіщень (не показуємо користувачу)
MADRID_TZ = ZoneInfo("Europe/Madrid")
WINDOW_START = os.getenv("WINDOW_START", "14:00")  # HH:MM
WINDOW_END = os.getenv("WINDOW_END", "16:00")      # HH:MM

# 💬 Скільки рандом-сповіщень на день (для кожного увімкненого користувача)
PINGS_PER_DAY = int(os.getenv("PINGS_PER_DAY", "6"))

# 💬 Авто-видалення сповіщення, щоб чат був чистий
ALERT_DELETE_AFTER_SEC = int(os.getenv("ALERT_DELETE_AFTER_SEC", "180"))

# 💬 “Мигалка” для повідомлення "не бачу підписку"
FLASH_SEC = 3


# =========================
# DEMO DATA (поки тест) — потім заміниш своїми
# =========================
# ✅ общие “якорные” названия как в ICP (без эмодзи)
# 💬 Важно: названия длинные — это нормально, зато 1:1 с сайтом.
PROVINCES: dict[str, dict[str, Any]] = {
    "Valencia": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},

            # 💬 Valencia (місто)
            {
                "id": "val_patraix_gremis_6",
                "title": "Valencia: Comisaría Patraix (C/ D' Els Gremis 6)",
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": True,  # 💬 як точка по TIE/expedición
                },
            },
            {
                "id": "val_zapadores_52",
                "title": "Valencia: Brigada Extranjería (C/ Zapadores 52)",
                "service_flags": {
                    # 💬 обережно: тут часто йде protección internacional/інфо, TIE може бути не по всіх потоках
                    "ua_card": True,
                    "huellas_tie": False,
                    "recogida_tie": False,
                },
            },

            # 💬 Міста провінції Valencia (за локатором Policía / держ. довідниками)
            {
                "id": "val_gandia_laval_5",
                "title": "Gandía: C/ Ciudad de Laval 5 (EXPEDICIÓN TIE)",
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": True,
                },
            },
            {
                "id": "val_sagunto_progreso_35",
                "title": "Sagunto: C/ Progreso 35",
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": False,  # 💬 поки не підтверджено = блокуємо
                },
            },
            {
                "id": "val_paterna_rosas_27",
                "title": "Paterna: C/ de las Rosas 27",
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": False,
                },
            },
            {
                "id": "val_onteniente_escura_2",
                "title": "Ontinyent: Placeta L'Escura 2",
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": False,
                },
            },
            {
                "id": "val_alzira_pere_morell_4",
                "title": "Alzira: C/ Pere Morell 4",
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": False,
                },
            },
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Madrid": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {
                "id": "mad_poblados_51",
                "title": "Madrid: Av. de los Poblados 51",
                # 💬 Якщо не вкажеш service_flags, дефолт працює так:
                # 💬 ua_card/huellas_tie = ✅, recogida_tie = 🚫
                "service_flags": {
                    "ua_card": True,
                    "huellas_tie": True,
                    "recogida_tie": False,
                },
            },
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },
}






# =========================
# STORAGE
# =========================
def _ensure_dir_for_file(path: str) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)


def _load_json(path: str) -> dict:
    _ensure_dir_for_file(path)
    if not os.path.exists(path):
        return {"users": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {"users": {}}
    except Exception:
        return {"users": {}}


def _save_json_atomic(path: str, data: dict) -> None:
    _ensure_dir_for_file(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _ensure_user(store: dict, user_id: str) -> dict:
    users = store.setdefault("users", {})
    u = users.setdefault(user_id, {})
    u.setdefault("enabled", False)          # 💬 /start = НЕ вмикаємо автоматом
    u.setdefault("ui_msg_id", None)         # 💬 id “якорного” повідомлення
    u.setdefault("province", None)
    u.setdefault("office_id", None)
    u.setdefault("service_id", None)
    # 💬 миграция старых значений service_id (если юзер выбирал раньше)
    legacy_map = {
        "ua_temp": "ua_card",
        "huellas": "huellas_tie",
    }
    if u.get("service_id") in legacy_map:
        u["service_id"] = legacy_map[u["service_id"]]

    u.setdefault("notify_minutes", [])      # 💬 хвилини доби, коли пінгати
    u.setdefault("daily_key", None)         # 💬 YYYY-MM-DD
    u.setdefault("last_notified", None)     # 💬 YYYY-MM-DD:MIN
    u.setdefault("ui_seq", 0)              # 💬 щоб “мигалка” не перетирала інший екран
    return u


# =========================
# UI HELPERS (чистий чат)
# =========================
bot: Bot  # 💬 буде ініціалізовано нижче


async def _safe_delete_message(chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def _main_text(u: dict) -> str:
    enabled = bool(u.get("enabled"))
    status = "✅ ON" if enabled else "⛔️ OFF"

    prov = u.get("province") or "не обрано"
    office = u.get("office_id") or "не обрано"
    svc = u.get("service_id") or "не обрано"

    # 💬 показуємо офіс красивіше, якщо він в словнику
    office_title = office
    if u.get("province") in PROVINCES:
        for o in PROVINCES[u["province"]]["offices"]:
            if o["id"] == office:
                office_title = o["title"]
                break

    svc_title = svc
    if u.get("province") in PROVINCES:
        for s in PROVINCES[u["province"]]["services"]:
            if s["id"] == svc:
                svc_title = s["title"]
                break

    # 💬 HTML-safe (щоб не ламати <b>/<i> якщо в назвах є спецсимволи)
    prov_h = _h(str(prov))
    office_h = _h(str(office_title))
    svc_h = _h(str(svc_title))
    status_h = _h(str(status))

    text = (
        "<b>🏛 Extranjería Citas</b>\n\n"
        f"<i>🔔 Сповіщення:</i> <b>{status_h}</b>\n\n"
        "🎯 <i>Обрано:</i>\n"
        f"<i>• Місто/провінція:</i> <b>{prov_h}</b>\n"
        f"<i>• Офіс:</i> <b>{office_h}</b>\n"
        f"<i>• Послуга:</i> <b>{svc_h}</b>"
    )
    return text



def _kb_main(u: dict) -> InlineKeyboardMarkup:
    enabled = bool(u.get("enabled"))

    toggle_text = "🔕 Вимкнути сповіщення" if enabled else "🔔 Увімкнути сповіщення"
    toggle_cb = "ui:toggle_off" if enabled else "ui:toggle_on"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)],
        [
            InlineKeyboardButton(text="🗺️ Обрати сервіс", callback_data="pick:province"),
            InlineKeyboardButton(text="📌 Важливо", callback_data="info:important:0"),
        ],
        [
            InlineKeyboardButton(text="ℹ️ Як це працює", callback_data="info:how:0"),
            InlineKeyboardButton(text="🌐 Сайт сіти", url=BOOKING_URL),  # 💬 прямий доступ
        ],
    ])



def _kb_back(to: str = "ui:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=to)]
    ])


def _grid_buttons(btns: list[InlineKeyboardButton], cols: int = 3) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in btns:
        row.append(b)
        if len(row) >= cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


async def _edit_or_send_ui(
    *,
    chat_id: int,
    store: dict,
    user_id: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    kb: InlineKeyboardMarkup | None = None,
    bot: Bot | None = None,
) -> None:
    # 💬 совместимость: где-то зовём reply_markup=..., где-то kb=...
    if reply_markup is None:
        reply_markup = kb

    bot_client = bot or globals()["bot"]
    u = _ensure_user(store, user_id)
    ui_msg_id = u.get("ui_msg_id")

    # 💬 чтобы “мигалка” не перетирала другой экран
    u["ui_seq"] = int(u.get("ui_seq", 0)) + 1
    current_seq = u["ui_seq"]

    if ui_msg_id:
        try:
            await bot_client.edit_message_text(
                chat_id=chat_id,
                message_id=ui_msg_id,
                text=text,
                parse_mode="HTML",  # 💬 включаем <b>/<i>
                reply_markup=reply_markup,
            )
            _save_json_atomic(DATA_PATH, store)
            return
        except TelegramBadRequest:
            pass
        except Exception:
            pass

    # 💬 если edit не вышел — шлём новый “якорь”
    msg = await bot_client.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",  # 💬 включаем <b>/<i>
        reply_markup=reply_markup,
    )
    u["ui_msg_id"] = msg.message_id
    # 💬 фиксируем seq (на всякий)
    u["ui_seq"] = current_seq
    _save_json_atomic(DATA_PATH, store)


async def _flash_then_main(chat_id: int, user_id: str, text: str, seconds: int = FLASH_SEC) -> None:
    store = _load_json(DATA_PATH)
    u = _ensure_user(store, user_id)
    seq = int(u.get("ui_seq", 0))

    await _edit_or_send_ui(chat_id=chat_id, store=store, user_id=user_id, text=text, kb=_kb_back("ui:main"))
    await asyncio.sleep(seconds)

    store2 = _load_json(DATA_PATH)
    u2 = _ensure_user(store2, user_id)
    # 💬 если пользователь уже ушёл на другой экран — не перетираем
    if int(u2.get("ui_seq", 0)) != seq + 1:
        return

    await _edit_or_send_ui(chat_id=chat_id, store=store2, user_id=user_id, text=_main_text(u2), kb=_kb_main(u2))


# =========================
# INFO PAGES (листать)
# =========================
IMPORTANT_PAGES = [
    "<b>📌 Важливо (1/5)</b>\n\n"
    "<i>Цей сервіс не продає слоти.</i>\n"
    "<i>Не “вирішує питання”.</i>\n"
    "<i>Він просто дає сигнал: “може з’явилось”.</i>",

    "<b>📌 Важливо (2/5)</b>\n\n"
    "<b>Сповіщення не гарантує запис.</b>\n"
    "<i>Конкуренція проста — хто перший, той і забрав.</i>\n\n"
    "<i>Побачив повідомлення —</i>\n"
    "<b>одразу перевіряй сайт.</b>",

    "<b>📌 Важливо (3/5)</b>\n\n"
    "<b>Сервіс залежить від сайту Extranjería.</b>\n"
    "<i>Іноді він лагає, падає або не пускає,</i>\n"
    "<i>особливо коли всі заходять одночасно.</i>",

    "<b>📌 Важливо (4/5)</b>\n\n"
    "<b>Жодних паспортів, NIE, карток чи “оплат за слот”.</b>\n"
    "<i>Ніяких чудес — тільки спроба зекономити тобі час.</i>\n\n"
    "<b>Сервіс “як є”.</b>\n"
    "<i>Без гарантій і без обіцянок.</i>",

    "<b>📌 Важливо (5/5)</b>\n\n"
    "<i>Користуючись сервісом, ти підтверджуєш, що прочитав</i>\n"
    "<b>і зрозумів ці умови.</b>",
]


HOW_PAGES = [
    "<b>ℹ️ Як це працює (1/6)</b>\n\n"
    "<i>Ти хочеш Сіту.</i>\n"
    "<i>Система хоче, щоб ти страждав.</i>\n"
    "<i>Щоб ти сам ловив момент, як рибу голими руками.</i>\n"
    "<i>Тому є помічник, який страждає за тебе.</i>\n"
    "<i>Він не ловить за тебе.</i>\n"
    "<i>Він просто дивиться частіше і каже, якщо щось спливло.</i>",

    "<b>ℹ️ Як це працює (2/6)</b>\n\n"
    "<i>1) Натисни “Обрати сервіс”.</i>\n"
    "<i>2) Вибери місто → офіс → послугу.</i>\n"
    "<i>3) Повернешся в меню.</i>",

    "<b>ℹ️ Як це працює (3/6)</b>\n\n"
    "<i>Увімкни сповіщення.</i>\n"
    "<b>Якщо повідомлень нема</b>\n"
    "<i>може не бути Сіти.</i>\n"
    "<i>може не працювати сайт.</i>\n"
    "<i>або може не спрацювати сам Бот.</i>\n"
    "<i>дуже важливо - перевіряй руками теж.</i>",

    "<b>ℹ️ Як це працює (4/6)</b>\n\n"
    "<b>Що саме він перевіряє</b>\n"
    "<i>Тільки одне: чи є доступність у вибраній послузі.</i>\n\n"
    "<i>Він не бачить дат.</i>\n"
    "<i>Він не бачить кількість місць.</i>\n"
    "<i>Це можна побачити тільки на сайті.</i>",

    "<b>ℹ️ Як це працює (5/6)</b>\n\n"
    "<b>Чому це не гарантія</b>\n"
    "<i>Сіта може з’явитися на хвилину.</i>\n"
    "<i>І зникнути, поки ти моргнув.</i>\n\n"
    "<i>А ще сайт може лагати, коли туди влітають всі одночасно.</i>\n\n"
    "<i>Тому сигнал <b>не є гарантія</b></i>",

    "<b>ℹ️ Як це працює (6/6)</b>\n\n"
    "<b>Бронюєш ти. Не він.</b>\n"
    "<i>Він лише каже “здається, щось з’явилось”.</i>\n\n"
    "<i>Сайт інколи лагає або не відкривається.</i>\n"
    "<i>Таке життя.</i>\n\n"
    "<b>Хто перший, того і тапки.</b>\n\n"
    "<i>Це помічник, а не чарівна паличка.</i>\n"
    "<b>Не покладайся на нього на 100%</b>",
]



def _kb_pager(prefix: str, page: int, total: int) -> InlineKeyboardMarkup:
    prev_page = max(0, page - 1)
    next_page = min(total - 1, page + 1)

    left_cb = f"info:{prefix}:{prev_page}" if page > 0 else "ui:noop"
    right_cb = f"info:{prefix}:{next_page}" if page < total - 1 else "ui:noop"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️", callback_data=left_cb),
            InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="ui:noop"),
            InlineKeyboardButton(text="▶️", callback_data=right_cb),
        ],
        [InlineKeyboardButton(text="🌐 Сайт сіти", url=BOOKING_URL)],  # 💬 сайт завжди під рукою
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ui:main")]
    ])



# =========================
# SUBSCRIBE GATE
# =========================
def _kb_subscribe_gate() -> InlineKeyboardMarkup:
    channel_url = f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Підписатися на канал", url=channel_url)],
        [InlineKeyboardButton(text="✅ Перевірити підписку", callback_data="sub:check")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ui:main")],
    ])


async def _is_subscribed(bot_client: Bot, user_id_int: int) -> bool:
    # 💬 поддерживаем @username и -100123... (если позже захочешь хранить id канала)
    chat_id = REQUIRED_CHANNEL
    if isinstance(chat_id, str):
        chat_id = chat_id.strip()
        if chat_id and chat_id[0].isdigit():
            # 💬 строка-число -> int
            try:
                chat_id = int(chat_id)
            except Exception:
                pass

    try:
        member = await bot_client.get_chat_member(chat_id=chat_id, user_id=user_id_int)
        return member.status in ("member", "administrator", "creator")
    except TelegramBadRequest as e:
        # 💬 ключевое: если бот НЕ админ/не видит канал -> тут будет "chat not found" или похожее
        try:
            print(f"[SUB_CHECK] TelegramBadRequest chat_id={chat_id} user_id={user_id_int} err={e}")
        except Exception:
            pass
        return False
    except Exception as e:
        try:
            print(f"[SUB_CHECK] ERROR chat_id={chat_id} user_id={user_id_int} err={e}")
        except Exception:
            pass
        return False



# =========================
# PICK FLOW
# =========================
def _kb_pick_province() -> InlineKeyboardMarkup:
    btns: list[InlineKeyboardButton] = []
    for name in PROVINCES.keys():
        btns.append(InlineKeyboardButton(text=name, callback_data=f"pick:prov:{name}"))
    rows = _grid_buttons(btns, cols=3)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ui:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_pick_office(province: str) -> InlineKeyboardMarkup:
    offices = PROVINCES.get(province, {}).get("offices", [])
    btns = [
        InlineKeyboardButton(text=o["title"], callback_data=f"pick:office:{province}:{o['id']}")
        for o in offices
    ]
    rows = _grid_buttons(btns, cols=1)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ui:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_pick_service(province: str, office_id: str) -> InlineKeyboardMarkup:
    services = PROVINCES.get(province, {}).get("services", [])
    offices = PROVINCES.get(province, {}).get("offices", [])

    # 💬 Ищем офис и его флаги доступности услуг
    office = next((o for o in offices if o.get("id") == office_id), None)
    flags = (office or {}).get("service_flags") or {}  # {service_id: True/False}

    rows: list[list[InlineKeyboardButton]] = []

    for s in services:
        sid = s["id"]
        title = s["title"]

        # 💬 Дефолты по доступности:
        # 💬 - recogida_tie: по умолчанию ЗАБЛОКИРОВАНА (пока явно не разрешишь для офиса)
        # 💬 - остальное: по умолчанию доступно (чтобы старые данные работали)
        default_allowed = False if sid == "recogida_tie" else True
        allowed = flags.get(sid, default_allowed)


        prefix = "✅ " if allowed else "🚫 "
        cb = (
            f"pick:service:{province}:{office_id}:{sid}"
            if allowed
            else f"pick:service_blocked:{province}:{office_id}:{sid}"
        )

        rows.append([InlineKeyboardButton(text=prefix + title, callback_data=cb)])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ui:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =========================
# NOTIFICATIONS (рандом)
# =========================
def _parse_hhmm(s: str) -> tuple[int, int]:
    hh, mm = s.split(":")
    return int(hh), int(mm)


def _generate_minutes_for_today() -> list[int]:
    sh, sm = _parse_hhmm(WINDOW_START)
    eh, em = _parse_hhmm(WINDOW_END)

    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if end_min <= start_min:
        end_min = start_min + 1

    pool = list(range(start_min, end_min))
    if not pool:
        pool = [start_min]

    k = min(PINGS_PER_DAY, len(pool))
    minutes = sorted(random.sample(pool, k=k))
    return minutes


def _today_key(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%d")


async def _send_alert(user_chat_id: int, text: str) -> None:
    try:
        msg = await bot.send_message(
            chat_id=user_chat_id,
            text=text,
            parse_mode="HTML",  # 💬 на будущее (если захочешь форматировать алерты)
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🌐 Відкрити сайт", url=BOOKING_URL)],
                [InlineKeyboardButton(text="🧷 Меню", callback_data="ui:main")],
            ])
        )

        # 💬 авто-видалення
        asyncio.create_task(_safe_delete_message(user_chat_id, msg.message_id))
        # 💬 але видаляти треба з затримкою
        async def _del_later():
            await asyncio.sleep(ALERT_DELETE_AFTER_SEC)
            await _safe_delete_message(user_chat_id, msg.message_id)
        asyncio.create_task(_del_later())
    except Exception:
        pass


async def notifier_loop() -> None:
    while True:
        try:
            now = dt.datetime.now(MADRID_TZ)
            store = _load_json(DATA_PATH)
            users = store.get("users", {})

            now_min = now.hour * 60 + now.minute
            key = _today_key(now)

            changed = False

            for user_id, u in users.items():
                u = _ensure_user(store, user_id)

                if not u.get("enabled"):
                    continue

                # 💬 если день сменился — генерим минуты заново
                if u.get("daily_key") != key or not u.get("notify_minutes"):
                    u["daily_key"] = key
                    u["notify_minutes"] = _generate_minutes_for_today()
                    u["last_notified"] = None
                    changed = True

                last = u.get("last_notified")
                stamp = f"{key}:{now_min}"

                if now_min in u.get("notify_minutes", []) and last != stamp:
                    u["last_notified"] = stamp
                    changed = True

                    # 💬 текст уведомления максимально короткий
                    alert_text = "⚡️ Можливо, з’явилось вікно. Перевір швидко."
                    await _send_alert(int(user_id), alert_text)

            if changed:
                _save_json_atomic(DATA_PATH, store)

        except Exception:
            pass

        await asyncio.sleep(20)


# =========================
# ROUTES
# =========================
router = Router()


@router.message(CommandStart())
async def on_start(message: Message):
    # 💬 удаляем /start пользователя, чтобы чат был чище
    user_msg_id = message.message_id

    store = _load_json(DATA_PATH)
    user_id = str(message.chat.id)
    u = _ensure_user(store, user_id)

    # 💬 /start не включает уведомления, просто показывает меню
    await _edit_or_send_ui(
        chat_id=message.chat.id,
        store=store,
        user_id=user_id,
        text=_main_text(u),
        kb=_kb_main(u),
    )

    _save_json_atomic(DATA_PATH, store)

    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=user_msg_id)
    except Exception:
        pass


@router.callback_query(F.data == "ui:noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "ui:main")
async def cb_main(call: CallbackQuery):
    await call.answer()
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=_main_text(u),
        kb=_kb_main(u),
    )


@router.callback_query(F.data == "ui:toggle_on")
async def cb_toggle_on(call: CallbackQuery):
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    # 💬 нельзя включить, если не выбран сервис
    if not u.get("province") or not u.get("office_id") or not u.get("service_id"):
        # 💬 ВАЖНО: отвечаем ОДИН раз, сразу show_alert=True (иначе второй answer может не показаться)
        try:
            await call.answer("Спочатку обери сервіс в меню.", show_alert=True)
        except Exception:
            pass
        return

    # 💬 гасим “крутилку” перед редактированием UI
    await call.answer()

    # 💬 показываем “ворота подписки” в том же якорном сообщении
    text = (
        "Щоб увімкнути сповіщення, потрібно бути підписаним на канал.\n\n"
        "Підпишись. Потім натисни “Перевірити”."
    )
    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=text,
        kb=_kb_subscribe_gate(),
    )



@router.callback_query(F.data == "sub:check")
async def cb_sub_check(call: CallbackQuery):
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    ok = await _is_subscribed(bot, call.from_user.id)

    if not ok:
        # 💬 Минимализм: показываем toast снизу и НЕ трогаем текущие кнопки/экран
        try:
            await call.answer("Не бачу підписку. Підпишись і натисни «Перевірити» ще раз.", show_alert=False)
        except Exception:
            pass
        return

    # 💬 подписка ок — включаем
    u["enabled"] = True
    _save_json_atomic(DATA_PATH, store)

    await call.answer()  # 💬 гасим крутилку


    # 💬 подписка ок — включаем
    u["enabled"] = True
    _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=_main_text(u),
        kb=_kb_main(u),
    )


@router.callback_query(F.data == "ui:toggle_off")
async def cb_toggle_off(call: CallbackQuery):
    await call.answer()
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    u["enabled"] = False
    _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=_main_text(u),
        kb=_kb_main(u),
    )


@router.callback_query(F.data == "pick:province")
async def cb_pick_province(call: CallbackQuery):
    await call.answer()
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    _ensure_user(store, user_id)

    text = "🗺️ Обери місто/провінцію:"
    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=text,
        kb=_kb_pick_province(),
    )


@router.callback_query(F.data.startswith("pick:prov:"))
async def cb_pick_prov_value(call: CallbackQuery):
    await call.answer()
    province = call.data.split("pick:prov:", 1)[1]

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    if province not in PROVINCES:
        await call.answer("Невідоме місто.", show_alert=True)
        return

    u["province"] = province
    u["office_id"] = None
    u["service_id"] = None
    u["enabled"] = False  # 💬 смена сервиса = лучше выключить, чтобы не путать

    _save_json_atomic(DATA_PATH, store)

    text = f"🏢 Обери офіс в {province}:"
    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=text,
        kb=_kb_pick_office(province),
    )


@router.callback_query(F.data.startswith("pick:office:"))
async def cb_pick_office(call: CallbackQuery):
    await call.answer()
    _, _, province, office_id = call.data.split(":", 3)  # pick:office:PROV:OFFICE

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    if province not in PROVINCES:
        await call.answer("Невідоме місто.", show_alert=True)
        return

    u["province"] = province
    u["office_id"] = office_id
    u["service_id"] = None
    u["enabled"] = False

    _save_json_atomic(DATA_PATH, store)

    text = "🧩 Обери послугу:"
    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=text,
        kb=_kb_pick_service(province, office_id),
    )


@router.callback_query(F.data.startswith("pick:service:"))
async def cb_pick_service(call: CallbackQuery):
    await call.answer()
    # pick:service:PROV:OFFICE:SVC
    parts = call.data.split(":")
    province = parts[2]
    office_id = parts[3]
    service_id = parts[4]

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    if province not in PROVINCES:
        await call.answer("Невідоме місто.", show_alert=True)
        return

    u["province"] = province
    u["office_id"] = office_id
    u["service_id"] = service_id
    u["enabled"] = False  # 💬 включение только после подписки

    _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=_main_text(u),
        kb=_kb_main(u),
    )
    
@router.callback_query(F.data.startswith("pick:service_blocked:"))
async def cb_pick_service_blocked(call: CallbackQuery):
    # pick:service_blocked:PROV:OFFICE:SVC
    await call.answer("🚫 Ця послуга недоступна в цьому офісі. \nОбери інший офіс або іншу послугу.", show_alert=True)


@router.callback_query(F.data.startswith("info:"))
async def cb_info(call: CallbackQuery):
    await call.answer()
    # info:important:0  или info:how:1
    parts = call.data.split(":")
    kind = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    _ensure_user(store, user_id)

    if kind == "important":
        pages = IMPORTANT_PAGES
        page = max(0, min(page, len(pages) - 1))
        text = pages[page]
        kb = _kb_pager("important", page, len(pages))
    else:
        pages = HOW_PAGES
        page = max(0, min(page, len(pages) - 1))
        text = pages[page]
        kb = _kb_pager("how", page, len(pages))

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=text,
        kb=kb,
    )


# =========================
# MAIN
# =========================
async def main() -> None:
    global bot
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Set Railway variable BOT_TOKEN.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # 💬 запускаем фоновую задачу уведомлений
    asyncio.create_task(notifier_loop())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
