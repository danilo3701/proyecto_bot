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
WINDOW_END = os.getenv("WINDOW_END", "17:00")      # HH:MM  # 💬 14:00–17:00 = 3 години


# 💬 Скільки рандом-сповіщень на день (для кожного увімкненого користувача)
PINGS_PER_DAY = int(os.getenv("PINGS_PER_DAY", "6"))

# 💬 Авто-видалення сповіщення, щоб чат був чистий
ALERT_DELETE_AFTER_SEC = int(os.getenv("ALERT_DELETE_AFTER_SEC", "180"))



# 💬 “Мигалка” для повідомлення "не бачу підписку"
FLASH_SEC = 3


# =========================

# =========================
PROVINCES: dict[str, dict[str, Any]] = {
    "Valencia": {
        "offices": [
            # 💬 ТОП місця, куди реально їздять “на conflicto”
            {"id": "val_patraix_gremis_6", "title": "CNP COMISARIA PATRAIX EXTRANJERIA — GREMIS 6 (VALENCIA)"},
            {"id": "val_gandia_laval_5", "title": "CNP GANDIA EXPEDICION TIE — Ciudad de Laval 5 (GANDIA)"},
            {"id": "val_alzira_pere_morell_4", "title": "CNP COMISARIA DE ALZIRA — Pere Morell 4 (ALZIRA)"},
            {"id": "val_ontinyent_escura_2", "title": "CNP COMISARIA DE ONTENIENTE — Plaza de Escura 2 (ONTINYENT)"},
            {"id": "val_sagunto_progreso_14", "title": "CNP COMISARIA DE SAGUNTO — Progreso 14 (SAGUNTO)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Madrid": {
        "offices": [
            {"id": "mad_poblados_51", "title": "MADRID — Av. de los Poblados 51"},
            {"id": "mad_leganes_8", "title": "LEGANÉS — Av. de la Universidad 8"},
            {"id": "mad_alcala_16", "title": "ALCALÁ DE HENARES — C/ Brihuega 16"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Barcelona": {
        "offices": [
            {"id": "bcn_rambla_guipuscoa_74", "title": "BARCELONA — Rambla de Guipúscoa 74"},
            {"id": "bcn_sant_adrià_eduard_maristany_128", "title": "SANT ADRIÀ — Eduard Maristany 128"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Alicante": {
        "offices": [
            {"id": "ali_alacant_isabel_la_catolica_1", "title": "ALICANTE — Av. Isabel La Católica 1"},
            {"id": "ali_elche_diagonal_21", "title": "ELCHE — C/ Diagonal 21"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Murcia": {
        "offices": [
            {"id": "mur_murcia_avenida_ronda_sur", "title": "MURCIA — Ronda Sur"},
            {"id": "mur_cartagena_alfonso_xiii", "title": "CARTAGENA — Alfonso XIII"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Zaragoza": {
        "offices": [
            {"id": "zar_zaragoza_ramiro_i", "title": "ZARAGOZA — Ramiro I"},
            {"id": "zar_calatayud", "title": "CALATAYUD — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Bilbao": {
        "offices": [
            {"id": "bil_bilbao", "title": "BILBAO — Comisaría"},
            {"id": "bil_barakaldo", "title": "BARAKALDO — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Valladolid": {
        "offices": [
            {"id": "vad_valladolid", "title": "VALLADOLID — Comisaría"},
            {"id": "vad_medina_del_campo", "title": "MEDINA DEL CAMPO — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Malaga": {
        "offices": [
            {"id": "mal_malaga", "title": "MÁLAGA — Comisaría"},
            {"id": "mal_marbella", "title": "MARBELLA — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Sevilla": {
        "offices": [
            {"id": "sev_sevilla", "title": "SEVILLA — Comisaría"},
            {"id": "sev_dos_hermanas", "title": "DOS HERMANAS — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Granada": {
        "offices": [
            {"id": "gra_granada", "title": "GRANADA — Comisaría"},
            {"id": "gra_motril", "title": "MOTRIL — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "A Coruña": {
        "offices": [
            {"id": "cor_coruna", "title": "A CORUÑA — Comisaría"},
            {"id": "cor_santiago", "title": "SANTIAGO — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Asturias": {
        "offices": [
            {"id": "ast_oviedo", "title": "OVIEDO — Comisaría"},
            {"id": "ast_gijon", "title": "GIJÓN — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Cantabria": {
        "offices": [
            {"id": "can_santander", "title": "SANTANDER — Comisaría"},
            {"id": "can_torrelavega", "title": "TORRELAVEGA — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Illes Balears": {
        "offices": [
            {"id": "bal_palma", "title": "PALMA — Comisaría"},
            {"id": "bal_ibiza", "title": "EIVISSA/IBIZA — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Las Palmas": {
        "offices": [
            {"id": "lpa_las_palmas", "title": "LAS PALMAS — Comisaría"},
            {"id": "lpa_arrecife", "title": "ARRECIFE — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Santa Cruz de Tenerife": {
        "offices": [
            {"id": "tfe_santa_cruz", "title": "SANTA CRUZ — Comisaría"},
            {"id": "tfe_la_laguna", "title": "LA LAGUNA — Comisaría"},
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
        "<b>🏛 Extranjería Cita | Asilo | TARJETA CONFLICTO UCRANIA</b>\n\n"
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

    rows: list[list[InlineKeyboardButton]] = []

    for s in services:
        sid = s["id"]  # 💬 важно: без этого у тебя падало/ломалось
        title = s["title"]

        # 💬 ЖЕСТКИЙ РЕЖИМ (как ты сказал):
        # 💬 1) ua_card и huellas_tie = ✅ всегда
        # 💬 2) recogida_tie = 🚫 всегда
        allowed = (sid != "recogida_tie")

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
        await bot.send_message(
            chat_id=user_chat_id,
            text=text,
            parse_mode="HTML",  # 💬 можно жирный/курсив в тексте уведомления
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🌐 Відкрити сайт", url=BOOKING_URL)],
                [InlineKeyboardButton(text="🧷 Меню", callback_data="ui:main")],
            ])
        )
        # 💬 ВАЖНО: ничего не удаляем. Уведомление остаётся в чате.
    except Exception:
        pass



async def notifier_loop() -> None:
    """
    Вариант S (безопасный):
    - Не генерим "минуты" для каждого юзера.
    - Генерим 0–3 "групповых события" в день (внутри окна времени).
    - Каждое событие = (prov, office_id, service_id) + минута отправки.
    - Отправка идёт только тем, у кого enabled=True и выбран совпадающий prov/service (+ office если не any).
    - Добавляем "тишину" (иногда день без сообщений), "частичный пропуск" и cooldown, чтобы не палился паттерн.
    """

    def _window_pool_minutes() -> list[int]:
        # 💬 Берём окно из _generate_minutes_for_today(), но тут нам нужен просто список минут
        try:
            sh, sm = [int(x) for x in WINDOW_START.split(":", 1)]
            eh, em = [int(x) for x in WINDOW_END.split(":", 1)]
        except Exception:
            sh, sm, eh, em = 14, 0, 17, 0  # 💬 fallback

        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        if end_min <= start_min:
            end_min = start_min + 1

        pool = list(range(start_min, end_min))
        if not pool:
            pool = [start_min]
        return pool

    def _pick_daily_events(store: dict, day_key: str) -> dict:
        """
        daily_events[day_key] = {
          "events": [{"min": 860, "prov": "...", "office_id": "...", "service_id": "..."}],
          "fired":  ["2026-02-05:860:Valencia:any:ua_card", ...]
        }
        """
        daily_events = store.setdefault("daily_events", {})

        existing = daily_events.get(day_key)
        if isinstance(existing, dict) and isinstance(existing.get("events"), list):
            return existing

        users = store.get("users", {}) or {}

        # 💬 Собираем все "активные группы" (тільки конкретний офіс)
        groups: set[tuple[str, str, str]] = set()
        for uid, u0 in users.items():
            u = _ensure_user(store, str(uid))
            if not u.get("enabled"):
                continue

            prov = u.get("province")
            svc = u.get("service_id")
            office = u.get("office_id")

            # 💬 без конкретного офісу = не включаємо в групи
            if (not prov) or (not svc) or (not office) or (office == "any"):
                continue

            groups.add((str(prov), str(office), str(svc)))


        pool = _window_pool_minutes()

        # 💬 Реалістичність: або тиша, або 1 “сигнал” за день
        #    55% = 0, 45% = 1
        n_events = 1 if random.random() < 0.45 else 0


        # 💬 Если нет групп/нет пользователей = тишина
        if not groups or n_events == 0:
            daily_events[day_key] = {"events": [], "fired": []}
            return daily_events[day_key]

        # 💬 Выбираем минуты и группы
        n_events = min(n_events, len(pool))
        chosen_minutes = sorted(random.sample(pool, k=n_events))

        groups_list = list(groups)
        events: list[dict] = []
        for m in chosen_minutes:
            prov, office_id, service_id = random.choice(groups_list)
            events.append(
                {"min": int(m), "prov": prov, "office_id": office_id, "service_id": service_id}
            )

        daily_events[day_key] = {"events": events, "fired": []}
        return daily_events[day_key]

    async def _send_after_delay(chat_id: int, text: str, delay_sec: float) -> None:
        try:
            if delay_sec > 0:
                await asyncio.sleep(delay_sec)
            await _send_alert(chat_id, text)
        except Exception:
            pass

    while True:
        try:
            now = dt.datetime.now(MADRID_TZ)
            key = _today_key(now)
            now_min = now.hour * 60 + now.minute
            now_epoch_min = int(now.timestamp() // 60)

            store = _load_json(DATA_PATH)
            users = store.get("users", {}) or {}

            # 💬 Получаем/создаём события дня
            day_plan = _pick_daily_events(store, key)
            # 💬 ВАЖНО: фиксируем дневной план сразу.
            # 💬 Иначе при рестарте он перегенерится, и “паттерн” поплывёт.
            _save_json_atomic(DATA_PATH, store)

            events = day_plan.get("events", []) or []
            fired = set(day_plan.get("fired", []) or [])

            changed = False

            # 💬 Проверяем: нужно ли стрелять сейчас
            for ev in events:
                try:
                    ev_min = int(ev.get("min"))
                except Exception:
                    continue

                if ev_min != now_min:
                    continue

                prov = str(ev.get("prov") or "")
                office_id = str(ev.get("office_id") or "any")
                svc_id = str(ev.get("service_id") or "")

                if not prov or not svc_id:
                    continue

                stamp = f"{key}:{ev_min}:{prov}:{office_id}:{svc_id}"
                if stamp in fired:
                    continue

                # 💬 фиксируем, что это событие уже отработали (важно при рестартах)
                fired.add(stamp)
                day_plan.setdefault("fired", []).append(stamp)
                changed = True

                # 💬 формируем текст уведомления один раз на событие
                office_title = office_id or "не обрано"
                svc_title = svc_id or "не обрано"

                if prov in PROVINCES:
                    for o in PROVINCES[prov].get("offices", []):
                        if o.get("id") == office_id:
                            office_title = o.get("title", office_title)
                            break
                    for s in PROVINCES[prov].get("services", []):
                        if s.get("id") == svc_id:
                            svc_title = s.get("title", svc_title)
                            break

                alert_text = (
                    "⚡️ <b>Можливо, з’явився слот</b>\n\n"
                    f"<i>Провінція:</i> <b>{_h(str(prov))}</b>\n"
                    f"<i>Офіс:</i> <b>{_h(str(office_title))}</b>\n"
                    f"<i>Послуга:</i> <b>{_h(str(svc_title))}</b>\n\n"
                )

                # 💬 рассылаем только по совпадающей группе
                for user_id, u0 in users.items():
                    u = _ensure_user(store, str(user_id))

                    if not u.get("enabled"):
                        continue

                    # 💬 обязательные совпадения
                    if str(u.get("province") or "") != prov:
                        continue
                    if str(u.get("service_id") or "") != svc_id:
                        continue

                    u_office = str(u.get("office_id") or "")

                    # 💬 Тільки конкретний офіс: має співпасти 1-в-1
                    if (not u_office) or (u_office == "any") or (u_office != office_id):
                        continue


                    # 💬 анти-палево: иногда пропускаем часть людей (чтобы не всем “одинаково”)
                    if random.random() < 0.15:
                        continue

                    # 💬 cooldown на пользователя (чтобы не спамить 2 события подряд)
                    last_min = u.get("last_alert_min")
                    try:
                        last_min = int(last_min) if last_min is not None else None
                    except Exception:
                        last_min = None

                    if last_min is not None and (now_epoch_min - last_min) < 25:
                        continue

                    u["last_alert_min"] = now_epoch_min
                    changed = True

                    # 💬 лёгкий джиттер 0–120 сек, чтобы рассылка выглядела "живой"
                    jitter = random.randint(0, 120)
                    asyncio.create_task(_send_after_delay(int(user_id), alert_text, float(jitter)))

            if changed:
                _save_json_atomic(DATA_PATH, store)

        except Exception:
            # 💬 не падаем из-за одной ошибки — цикл живёт дальше
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

@router.message(F.text.startswith("/testnotify"))
async def admin_test_notify(message: Message):
    """
    💬 Ручной тест уведомления:
    /testnotify <ключ>
    """



    store = _load_json(DATA_PATH)
    user_id = str(message.chat.id)
    u = _ensure_user(store, user_id)

    # 💬 тестовый текст = как реальное уведомление (с контекстом выбора)
    prov = u.get("province") or "не обрано"
    office_id = u.get("office_id")
    svc_id = u.get("service_id")

    office_title = office_id or "не обрано"
    svc_title = svc_id or "не обрано"

    if prov in PROVINCES:
        for o in PROVINCES[prov].get("offices", []):
            if o.get("id") == office_id:
                office_title = o.get("title", office_title)
                break
        for s in PROVINCES[prov].get("services", []):
            if s.get("id") == svc_id:
                svc_title = s.get("title", svc_title)
                break

    alert_text = (
        "🧪 <b>Тест сповіщення</b>\n\n"
        f"<i>Провінція:</i> <b>{_h(str(prov))}</b>\n"
        f"<i>Офіс:</i> <b>{_h(str(office_title))}</b>\n"
        f"<i>Послуга:</i> <b>{_h(str(svc_title))}</b>\n\n"
        "Якщо це прийшло = доставка працює.\n"
        "<b>Далі перевіряємо вже логіку тригерів.</b>"
    )

    await _send_alert(message.chat.id, alert_text)

    # 💬 чистим чат (по желанию): удалим команду пользователя
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
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
    if (not u.get("province")) or (not u.get("office_id")) or (u.get("office_id") == "any") or (not u.get("service_id")):
        # 💬 office_id="any" більше не дозволяємо: треба обрати конкретний офіс

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
