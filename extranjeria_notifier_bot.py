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

# 💬 Секрет для ручного теста уведомлений (админ-команда)
ADMIN_TEST_KEY = os.getenv("ADMIN_TEST_KEY", "").strip()


# 💬 “Мигалка” для повідомлення "не бачу підписку"
FLASH_SEC = 3


# =========================

# =========================
PROVINCES: dict[str, dict[str, Any]] = {
    "Valencia": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
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
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "mad_poblados_51", "title": "MADRID — Av. de los Poblados 51"},
            {"id": "mad_padre_piquer_18", "title": "MADRID — Av. del Padre Piquer 18"},
            {"id": "mad_general_pardinas_90", "title": "MADRID — General Pardiñas 90"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Barcelona": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "bcn_mallorca_213", "title": "BARCELONA — C/ Mallorca 213 (Enric Granados)"},
            {"id": "bcn_rambla_guipuzcoa_74", "title": "BARCELONA — Rambla Guipúzcoa 74"},
            {"id": "hospitalet_rep_8", "title": "L'HOSPITALET — Plaça del Repartidor 8"},
            {"id": "terrassa_baldrich_9", "title": "TERRASSA — C/ Baldrich 9-13"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Alicante": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "ali_alicante_centro", "title": "ALICANTE — Comisaría (Centro)"},
            {"id": "ali_elche", "title": "ELCHE — Comisaría"},
            {"id": "ali_torrevieja", "title": "TORREVIEJA — Comisaría"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },
    "Malaga": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Málaga (провінція): офіси, які реально фігурують у списках по cita previa
            {"id": "mal_creade_sorolla_145", "title": "CNP CREADE-MÁLAGA — Av. Pintor Joaquín Sorolla 145 (MÁLAGA)"},
            {"id": "mal_prov_manuel_azana_3", "title": "CNP MÁLAGA Provincial — Plaza de Manuel Azaña 3 (MÁLAGA)"},
            {"id": "mal_fuengirola_condes_98", "title": "CNP Fuengirola — Av. Condes de San Isidro 98 (FUENGIROLA)"},
            {"id": "mal_marbella_duque_lerma_l3", "title": "CNP Marbella — Av. Duque de Lerma L3 (MARBELLA)"},
            {"id": "mal_torremolinos_skal_12", "title": "CNP Torremolinos — C/ Skal 12 (TORREMOLINOS)"},
            {"id": "mal_estepona_valle_inclan_1", "title": "CNP Estepona — C/ Valle Inclán 1 (ESTEPONA)"},
            {"id": "mal_velez_puerta_mar_4", "title": "CNP Vélez-Málaga — C/ Puerta del Mar 4 (TORRE DEL MAR)"},
            {"id": "mal_antequera_oaxaca_sn", "title": "CNP Antequera — C/ Ciudad de Oaxaca S/N (ANTEQUERA)"},
            {"id": "mal_ronda_rio_tinto_2", "title": "CNP Ronda — C/ Río Tinto 2 (RONDA)"},
            {"id": "mal_benalmadena_flores_6", "title": "CNP Benalmádena — C/ Las Flores 6 (BENALMÁDENA)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Sevilla": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Sevilla (провінція): ключові точки (BPEF / Torre Norte)
            {"id": "sev_bpef_grupo_1_dr_rafael_sn", "title": "BPEF GRUPO 1 — C/ Doctor Rafael Martínez Domínguez S/N (SEVILLA)"},
            {"id": "sev_doc_extran_plaza_espana_torre_norte_sn", "title": "Documentación de Extranjeros — Plaza de España (Torre Norte) S/N (SEVILLA)"},
            {"id": "sev_policia_bpef_plaza_espana_torre_norte_sn", "title": "POLICÍA BPEF — Plaza de España (Torre Norte) S/N (SEVILLA)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Murcia": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Murcia (провінція): офіси, що є в переліку по cita previa
            {"id": "mur_cartagena_menendez_pelayo_6", "title": "CNP Cartagena — Menéndez y Pelayo 6 (CARTAGENA)"},
            {"id": "mur_lorca_pza_policia_1", "title": "CNP Lorca — Pza. Policía Nacional 1 (LORCA)"},
            {"id": "mur_molina_canonigo_moreno_11", "title": "CNP Molina de Segura — C/ Canónigo Moreno 11 (MOLINA DE SEGURA)"},
            {"id": "mur_sangonera_mercamurcia_15", "title": "CNP Murcia Sangonera — Avda. Mercamurcia 15 (SANGONERA LA VERDE)"},
            {"id": "mur_yecla_rambla_34", "title": "CNP Yecla — Rambla 34 (YECLA)"},
            {"id": "mur_oficina_extranjeros_n301_km388", "title": "Oficina de Extranjeros — Ctra Nacional 301 Km 388 (MURCIA)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },
    "Sevilla": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "sev_blas_infante_2", "title": "Sevilla: Avenida Blas Infante 2"},
            {"id": "sev_veintiocho_febrero_59", "title": "Sevilla: C/ Veintiocho de Febrero 59"},
            {"id": "sev_castillo_alcala_17a", "title": "Sevilla: C/ Castillo Alcalá de Guadaira 17A"},
        ],
        "services": [
            # 💬 единый набор сервисов по всем провинциям (2 доступны, 3-й всегда заблокирован логикой UI)
            {"id": "ua_card", "title": "Tarjeta conflicto Ucrania"},
            {"id": "huellas_tie", "title": "Toma de huellas (expedición TIE)"},
            {"id": "recogida_tie", "title": "Recogida / entrega TIE"},
        ],
    },

    "Malaga": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "mal_pl_manuel_azania_3", "title": "Málaga: Pl. Manuel Azaña 3"},
            {"id": "marbella_juan_xxiii_2", "title": "Marbella: C/ Juan XXIII 2"},
            {"id": "fuengirola_boliches_60", "title": "Fuengirola: Av. de los Boliches 60"},
        ],
        "services": [
            {"id": "ua_card", "title": "Tarjeta conflicto Ucrania"},
            {"id": "huellas_tie", "title": "Toma de huellas (expedición TIE)"},
            {"id": "recogida_tie", "title": "Recogida / entrega TIE"},
        ],
    },

    "Granada": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Granada (provincia): сейчас в списках по “conflicto” фигурирует Baza
            {"id": "gra_baza_alhondiga_18", "title": "BAZA — Comisaría de Baza, Alhóndiga 18"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Zaragoza": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "zar_udex_obispo_covarrubias_sn", "title": "ZARAGOZA — Unidad Doc. Extranjeros, C/ Obispo Covarrubias s/n"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Bizkaia": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            {"id": "biz_bilbao_gordoniz_8", "title": "BILBAO — CNP Bilbao (JSP País Vasco), Gordóniz 8"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },
    "Illes Balears": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Oficinas disponibles (Tarjeta conflicto Ucrania)
            {"id": "bal_ciutadella_republica_arg_4", "title": "CIUTADELLA (Menorca) — República Argentina 4"},
            {"id": "bal_mahon_san_sebastian_2", "title": "MAHÓN (Menorca) — C/ San Sebastian 2"},
            {"id": "bal_palma_felicia_fuster_7", "title": "PALMA (Mallorca) — Felicià Fuster 7"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Las Palmas": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Oficinas disponibles (Tarjeta conflicto Ucrania)
            {"id": "lp_maspalomas_moya_4", "title": "MASPALOMAS — Avenida de Moya 4"},
            {"id": "lp_puerto_rosario_herbania_28", "title": "PUERTO ROSARIO — Herbania 28"},
            {"id": "lp_santa_lucia_negrin_10", "title": "VECINDARIO — Doctor Negrín 10 (Santa Lucía de Tirajana)"},
            {"id": "lp_tuineje_paco_hierro_sn", "title": "TUINEJE — Paco Hierro s/n"},
            {"id": "lp_arrecife_mastelero_sn", "title": "ARRECIFE — Mastelero s/n"},
            {"id": "lp_las_palmas_concordia_5", "title": "LAS PALMAS G.C. — Plaza de la Concordia 5"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Santa Cruz de Tenerife": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Oficinas disponibles (Tarjeta conflicto Ucrania)
            {"id": "tfe_oue_marina_20", "title": "SANTA CRUZ — OUE, C/ La Marina 20"},
            {"id": "tfe_adeje_pueblos_2", "title": "ADEJE — Playa de las Américas, Av. de los Pueblos 2"},
            {"id": "tfe_puerto_cruz_campo_llarena_3", "title": "PUERTO DE LA CRUZ — Av. José del Campo y Llarena 3"},
            {"id": "tfe_laguna_nava_grimon_66", "title": "LA LAGUNA — C/ Nava y Grimón 66"},
            {"id": "tfe_sc_robayna_23", "title": "SANTA CRUZ — Robayna 23"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },
    "Illes Balears": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Oficinas disponibles (Tarjeta conflicto Ucrania)
            {"id": "bal_ciutadella_republica_arg_4", "title": "CIUTADELLA (Menorca) — República Argentina 4"},
            {"id": "bal_mahon_san_sebastian_2", "title": "MAHÓN (Menorca) — C/ San Sebastian 2"},
            {"id": "bal_palma_felicia_fuster_7", "title": "PALMA (Mallorca) — Felicià Fuster 7"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Las Palmas": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Oficinas disponibles (Tarjeta conflicto Ucrania)
            {"id": "lp_maspalomas_moya_4", "title": "MASPALOMAS — Avenida de Moya 4"},
            {"id": "lp_puerto_rosario_herbania_28", "title": "PUERTO ROSARIO — Herbania 28"},
            {"id": "lp_santa_lucia_negrin_10", "title": "VECINDARIO — Doctor Negrín 10 (Santa Lucía de Tirajana)"},
            {"id": "lp_tuineje_paco_hierro_sn", "title": "TUINEJE — Paco Hierro s/n"},
            {"id": "lp_arrecife_mastelero_sn", "title": "ARRECIFE — Mastelero s/n"},
            {"id": "lp_las_palmas_concordia_5", "title": "LAS PALMAS G.C. — Plaza de la Concordia 5"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Santa Cruz de Tenerife": {
        "offices": [
            {"id": "any", "title": "Будь-який офіс"},
            # 💬 Oficinas disponibles (Tarjeta conflicto Ucrania)
            {"id": "tfe_oue_marina_20", "title": "SANTA CRUZ — OUE, C/ La Marina 20"},
            {"id": "tfe_adeje_pueblos_2", "title": "ADEJE — Playa de las Américas, Av. de los Pueblos 2"},
            {"id": "tfe_puerto_cruz_campo_llarena_3", "title": "PUERTO DE LA CRUZ — Av. José del Campo y Llarena 3"},
            {"id": "tfe_laguna_nava_grimon_66", "title": "LA LAGUNA — C/ Nava y Grimón 66"},
            {"id": "tfe_sc_robayna_23", "title": "SANTA CRUZ — Robayna 23"},
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
                    # 💬 текст уведомления с контекстом (что выбрано)
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
                        "⚡️ <b>Можливо, з’явилось вікно</b>\n\n"
                        f"<i>Провінція:</i> <b>{_h(str(prov))}</b>\n"
                        f"<i>Офіс:</i> <b>{_h(str(office_title))}</b>\n"
                        f"<i>Послуга:</i> <b>{_h(str(svc_title))}</b>\n\n"
                    )
                    
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

@router.message(F.text.startswith("/testnotify"))
async def admin_test_notify(message: Message):
    """
    💬 Ручной тест уведомления:
    /testnotify <ключ>
    """
    try:
        parts = (message.text or "").strip().split(maxsplit=1)
        key = parts[1].strip() if len(parts) > 1 else ""
    except Exception:
        key = ""

    if not ADMIN_TEST_KEY or key != ADMIN_TEST_KEY:
        # 💬 не светим причину, просто отказываем
        try:
            await message.answer("🚫 Немає доступу.")
        except Exception:
            pass
        return

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
