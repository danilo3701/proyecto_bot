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



# 💬 По выходным не шлём вообще
WEEKDAYS_ONLY = True  # Mon-Fri

# 💬 “Тихий день”: иногда вообще 0 уведомлений (правдоподобие)
QUIET_DAY_PROB = 0.40  # 40% дней тишина

# 💬 Редкие утренние всплески по будням
MORNING_BURST_PROB = 0.12  # 12% уведомлений могут попасть утром
MORNING_START = "09:10"
MORNING_END   = "11:20"

# 💬 Чтобы не долбило слишком часто
COOLDOWN_MINUTES = 18  # минимум 18 минут между уведомлениями

# 💬 Скільки рандом-сповіщень на день (для кожного увімкненого користувача)
PINGS_PER_DAY = int(os.getenv("PINGS_PER_DAY", "6"))

# 💬 Авто-видалення сповіщення, щоб чат був чистий
ALERT_DELETE_AFTER_SEC = int(os.getenv("ALERT_DELETE_AFTER_SEC", "180"))

# 💬 Адміни (через Railway env): "123,456"
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: set[int] = set()
for _x in ADMIN_IDS_RAW.split(","):
    _x = _x.strip()
    if _x.isdigit():
        ADMIN_IDS.add(int(_x))


def _is_admin_chat(chat_id: int) -> bool:
    # 💬 Якщо ADMIN_IDS не задано — ніхто не адмін (щоб випадково не відкрити статистику всім)
    return bool(ADMIN_IDS) and (int(chat_id) in ADMIN_IDS)


# 💬 “Мигалка” для повідомлення "не бачу підписку"
FLASH_SEC = 3


# =========================

# =========================
PROVINCES: dict[str, dict[str, Any]] = {
    "Valencia": {
        "offices": [
            # 💬 куди реально їздять “на conflicto”
            {"id": "val_patraix_gremis_6", "title": "VALÈNCIA (Patraix) — C/ dels Gremis 6"},
            {"id": "val_valencia_zapadores_52", "title": "VALÈNCIA — C/ Zapadores 52"},
            {"id": "val_gandia_laval_5", "title": "GANDIA — C/ Ciudad de Laval 5"},
            {"id": "val_alzira_pere_morell_4", "title": "ALZIRA — C/ Pere Morell 4"},
            {"id": "val_ontinyent_escura_2", "title": "ONTINYENT — Plaça de l'Escura 2"},
            {"id": "val_sagunto_progreso_14", "title": "SAGUNT — C/ Progreso 14"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Madrid": {
        "offices": [
            {"id": "mad_poblados_51", "title": "MADRID (Latina) — Av. de los Poblados 51"},
            {"id": "mad_padre_piquer_18", "title": "MADRID — Av. Padre Piquer 18"},
            {"id": "mad_leganes_universidad_27", "title": "LEGANÉS — Av. de la Universidad 27"},
            {"id": "mad_alcala_meco_sn", "title": "ALCALÁ DE HENARES — Avda de Meco s/n"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Barcelona": {
        "offices": [
            # 💬 Часто встречается как офис TIE/huellas в Барселоне (Rambla Guipúscoa)
            {"id": "bcn_rambla_guipuscoa_74", "title": "BARCELONA — Rambla de Guipúscoa 74"},

            # 💬 Реальные comisarías в провинции Barcelona (часто выбирают при записи)
            {"id": "bcn_badalona_av_dels_vents_9_13", "title": "BADALONA — Av. dels Vents 9-13"},
            {"id": "bcn_santa_coloma_irlanda_67", "title": "SANTA COLOMA DE GRAMENET — C/ Irlanda 67"},
            {"id": "bcn_mataro_gatassa_15", "title": "MATARÓ — Av. Gatassa 15"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Alicante": {
        "offices": [
            # 💬 Реальные comisarías в провинции Alicante (локатор Policía Nacional)
            {"id": "ali_alicante_centro_medico_pascual_perez_27", "title": "ALICANTE — C/ Médico Pascual Pérez 27"},
            {"id": "ali_alicante_norte_joaquin_fuster_2", "title": "ALICANTE — C/ Diputado Joaquín Fuster 2"},

            # 💬 Elche/Elx: реальный адрес comisaría (administracion.gob.es)
            {"id": "ali_elche_abeto_1", "title": "ELCHE/ELX — C/ Abeto 1"},

            # 💬 Benidorm: часто нужен людям по провинции (administracion.gob.es)
            {"id": "ali_benidorm_apolo_xi_36", "title": "BENIDORM — C/ Apolo XI 36"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Murcia": {
        "offices": [
            {"id": "mur_murcia_el_carmen_pl_industria_1", "title": "MURCIA — Comisaría El Carmen (Pl. de la Industria 1)"},
            {"id": "mur_murcia_san_andres_escultor_sanchez_lozano_2", "title": "MURCIA — Comisaría San Andrés (C/ Escultor José Sánchez Lozano 2)"},
            {"id": "mur_cartagena_menendez_y_pelayo_6", "title": "CARTAGENA — Comisaría (C/ Menéndez y Pelayo 6)"},
            {"id": "mur_molina_de_segura_canarias_2", "title": "MOLINA DE SEGURA — Comisaría (C/ Canarias 2)"},
            {"id": "mur_lorca_pl_policia_nacional_1", "title": "LORCA — Comisaría (Pl. de la Policía Nacional 1)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Zaragoza": {
        "offices": [
            {"id": "zar_jefatura_aragon_maria_agustin_34", "title": "ZARAGOZA — Jefatura Superior de Policía de Aragón (P.º de María Agustín 34)"},
            {"id": "zar_actur_jose_atares_105", "title": "ZARAGOZA — Comisaría Actur-Rey Fernando (Avda. Jose Atarés 105)"},
            {"id": "zar_centro_general_mayandia_3", "title": "ZARAGOZA — Comisaría Zaragoza-Centro (C/ General Mayandía 3)"},
            {"id": "zar_delicias_av_valencia_50", "title": "ZARAGOZA — Comisaría Zaragoza-Delicias (Avda. de Valencia 50)"},
            {"id": "zar_arrabal_almadieros_roncal_5", "title": "ZARAGOZA — Comisaría Zaragoza-Arrabal (C/ Almadieros del Roncal 5)"},
            {"id": "zar_calatayud_coral_bilbilitana_8", "title": "CALATAYUD — Comisaría (C/ Coral Bilbilitana 8)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Bilbao": {
        "offices": [
            # 💬 Jefatura Superior в Bizkaia: официальный адрес (часто используют под trámites)
            {"id": "biz_bilbao_gordoniz_8", "title": "BILBAO — C/ Gordóniz 8 (Jefatura Superior País Vasco)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Valladolid": {
        "offices": [
            # 💬 Официальные dependencias в провинции Valladolid (Policía Nacional)
            {"id": "vad_delicias_gerona_sn", "title": "VALLADOLID — C/ Gerona s/n (Delicias)"},
            {"id": "vad_fray_luis_5", "title": "VALLADOLID — C/ Fray Luis de Granada 5"},
            {"id": "vad_parquesol_enrique_cubero_sn", "title": "VALLADOLID — C/ Enrique Cubero s/n (Parquesol)"},
            {"id": "vad_medina_del_campo_valladolid_30_32", "title": "MEDINA DEL CAMPO — C/ Valladolid 30-32"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "Malaga": {
        "offices": [
            # 💬 Официальные dependencias Policía Nacional по провинции Málaga
            {"id": "mal_malaga_oeste", "title": "MÁLAGA (Oeste) — Pl. Manuel Azaña, 3"},
            {"id": "mal_malaga_centro", "title": "MÁLAGA (Centro-La Merced) — C/ Ramos Marín, 4"},
            {"id": "mal_malaga_este", "title": "MÁLAGA (Este-El Palo) — Avda. Sebastián Elcano, 144"},
            {"id": "mal_marbella", "title": "MARBELLA — Avda. Arias de Velasco, 25"},
            {"id": "mal_fuengirola", "title": "FUENGIROLA — Avda. Conde San Isidro, 98"},
            {"id": "mal_torremolinos_benalmadena", "title": "TORREMOLINOS–BENALMÁDENA — C/ Skal, 12"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Sevilla": {
        "offices": [
            # 💬 Официальные dependencias Policía Nacional по провинции Sevilla
            {"id": "sev_centro", "title": "SEVILLA (Centro) — Pza. de la Alameda, 39"},
            {"id": "sev_nervion", "title": "SEVILLA (Nervión) — Avda. Cruz del Campo, 17"},
            {"id": "sev_triana", "title": "SEVILLA (Triana) — C.º de los Descubrimientos, 2"},
            {"id": "sev_sur", "title": "SEVILLA (Sur) — C/ Castillo Alcalá de Guadaira, 17 A"},
            {"id": "sev_dos_hermanas", "title": "DOS HERMANAS — C/ Luis Ortega Bru s/n"},
            {"id": "sev_alcala_guadaira", "title": "ALCALÁ DE GUADAÍRA — C/ Maestro Casado s/n"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "Granada": {
        "offices": [
            # 💬 Policía Nacional (Granada): Granada-Centro / Granada-Norte / Motril
            {"id": "gra_granada", "title": "GRANADA — Granada-Centro (Pl. de los Campos, 3)"},
            {"id": "gra_motril", "title": "MOTRIL — Comisaría (C/ Aguas del Hospital s/n)"},
            # 💬 если захочешь 3-й офис — можно добавить Granada-Norte отдельным пунктом
            # {"id": "gra_granada_norte", "title": "GRANADA — Granada-Norte (C/ La Palmita, 1)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "A Coruña": {
        "offices": [
            # 💬 A Coruña: Jefatura Superior (zona Puerto) / Santiago (Rodrigo del Padrón)
            {"id": "cor_coruna", "title": "A CORUÑA — Jefatura Superior (Avda. do Porto, 5–7)"},
            {"id": "cor_santiago", "title": "SANTIAGO DE COMPOSTELA — Comisaría (Avda. de Rodrigo del Padrón, 3)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "Asturias": {
        "offices": [
            {"id": "ast_oviedo_placido_arango_9", "title": "OVIEDO — C/ Plácido Arango Arias 9 (Jefatura Superior)"},
            {"id": "ast_gijon_padre_maximo_gonzalez", "title": "GIJÓN — Pl. Padre Máximo González s/n (Comisaría)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "Cantabria": {
        "offices": [
            {"id": "can_santander_avda_del_deporte_4", "title": "SANTANDER — Avda. del Deporte 4 (Jefatura Superior)"},
            {"id": "can_torrelavega_joaquin_hoyos_18", "title": "TORRELAVEGA — C/ Joaquín Hoyos 18 (Comisaría)"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "Illes Balears": {
        "offices": [
            # 💬 Palma (Mallorca): Comisaría Oeste / Ibiza: Comisaría de Eivissa
            {"id": "bal_palma", "title": "PALMA (Comisaría Oeste) — Ctra. Valldemossa, 13"},
            {"id": "bal_ibiza", "title": "EIVISSA/IBIZA — Avda. de la Paz s/n"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },


    "Las Palmas": {
        "offices": [
            # 💬 Las Palmas GC (Centro) / Arrecife (Lanzarote)
            {"id": "lpa_las_palmas", "title": "LAS PALMAS G.C. (Centro) — C/ Luis Doreste Silva, 68"},
            {"id": "lpa_arrecife", "title": "ARRECIFE (Lanzarote) — C/ Mastelero s/n"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Santa Cruz de Tenerife": {
        "offices": [
            # 💬 DIR3 (administracion.gob.es): Calle Robayna 23
            {"id": "tfe_santa_cruz_robayna_23", "title": "SANTA CRUZ DE TENERIFE — Calle Robayna 23"},
            # 💬 DIR3 (administracion.gob.es): Avenida Tres de Mayo 32
            {"id": "tfe_tenerife_sur_tres_de_mayo_32", "title": "TENERIFE-SUR (Distrito) — Avda. Tres de Mayo 32"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Girona": {
        "offices": [
            # 💬 DIR3 + localizador dependencias Policía: C/ Sant Pau 2
            {"id": "gir_girona_sant_pau_2", "title": "GIRONA — C/ Sant Pau 2 (Comisaría Provincial)"},
            # 💬 Localizador dependencias Policía: C/ Verge de Loreto 51
            {"id": "gir_lloret_de_mar_verge_de_loreto_51", "title": "LLORET DE MAR — C/ Verge de Loreto 51"},
        ],
        "services": [
            {"id": "ua_card", "title": "POLICÍA TARJETA CONFLICTO UCRANIA"},
            {"id": "huellas_tie", "title": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"},
            {"id": "recogida_tie", "title": "POLICIA - RECOGIDA DE TARJETA DE IDENTIDAD DE EXTRANJERO (TIE)"},
        ],
    },

    "Tarragona": {
        "offices": [
            # 💬 DIR3 (administracion.gob.es): Plaça d'Orleans s/n
            {"id": "tar_tarragona_orleans_sn", "title": "TARRAGONA — Plaça d'Orleans s/n (Comisaría Provincial)"},
            # 💬 Localizador dependencias Policía: C/ General Moragues 54
            {"id": "tar_reus_general_moragues_54", "title": "REUS — C/ General Moragues 54"},
            # 💬 DIR3 (administracion.gob.es): Paseo Joan Moreira 3
            {"id": "tar_tortosa_joan_moreira_3", "title": "TORTOSA — Paseo Joan Moreira 3 (Comisaría Local)"},
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

    # 💬 Статистика: не храним локально, всё в JSON
    u.setdefault("first_seen_date", None)  # "YYYY-MM-DD" (Madrid)
    u.setdefault("last_seen_date", None)   # "YYYY-MM-DD" (Madrid)

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
            InlineKeyboardButton(text="🧾 Як подавати", callback_data="info:apply:0"),
            InlineKeyboardButton(text="ℹ️ Як це працює", callback_data="info:how:0"),
        ],
        [
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
    
def _clip_btn_text(text: str, max_bytes: int = 56) -> str:
    # 💬 Telegram ограничивает длину текста кнопки (и в целом лучше не рисковать).
    # 💬 Режем по UTF-8 байтам, чтобы не ломать эмодзи/акценты.
    raw = (text or "").strip()
    b = raw.encode("utf-8")
    if len(b) <= max_bytes:
        return raw

    out_chars: list[str] = []
    used = 0
    # 💬 оставим место под "…"
    limit = max(1, max_bytes - len("…".encode("utf-8")))

    for ch in raw:
        cb = ch.encode("utf-8")
        if used + len(cb) > limit:
            break
        out_chars.append(ch)
        used += len(cb)

    return "".join(out_chars).rstrip() + "…"



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
    "<i>Бот не бронює слот.</i>"

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
    "<i>Це помічник, який страждає за тебе.</i>\n"
    "<i>Він не ловить за тебе.</i>\n"
    "<i>Він просто нагадує тобі, якщо щось з'явилось.</i>",

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

    "<b>ℹ️ Як це працює (4/6)</b>\n\n"
    "<b>Що саме він перевіряє</b>\n"
    "<i>Тільки одне: чи є доступність бронювання у вибраній послузі.</i>\n\n"
    "<i>Він не бачить дат.</i>\n"
    "<i>Він не бачить сіти</i>\n"
    "<i>Це можна перевiрити тільки на сайті самому.</i>",

    "<b>ℹ️ Як це працює (5/6)</b>\n\n"
    "<b>Чому це не гарантія</b>\n"
    "<i>Сіта може з’явитися на хвилину.</i>\n"
    "<i>І зникнути тотчас.</i>\n\n"
    "<i>А ще сайт може падать, коли туди влітають всі одночасно.</i>\n\n"
    "<i>Тому сигнал <b>НЕ є гарантія</b></i>",

    "<b>ℹ️ Як це працює (6/6)</b>\n\n"
    "<b>Бронюєш ти</b>\n"
    "<i>Він лише каже “здається, щось з’явилось”.</i>\n\n"
    "<i>Сайт інколи лагає або не відкривається.</i>\n"
    "<i>Таке життя.</i>\n\n"
    "<i>Це помічник, а не чарівна паличка.</i>\n"
    "<b>Не покладайся на 100%</b>",
]

APPLY_PAGES = [
    "<b>🧾 Як подавати (1/7)</b>\n\n"
    "<b>Тимчасовий захист</b>\n"
    "Це документ формату A4.\n"
    "Зазвичай містить\n"
    "• особисті дані\n"
    "• фото\n"
    "• відбитки пальців\n\n"
    "На документі буде <b>NIE</b> (присвоюється під час оформлення).",

    "<b>🧾 Як подавати (2/7)</b>\n\n"
    "<b>BOE</b>\n"
    "Офіційний документ тут\n"
    "👉 <a href=\"https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-4157\">Відкрити BOE</a>\n\n"
    "<b>Резолюція</b>\n"
    "Скачати резолюцію можна тут\n"
    "👉 <a href=\"https://servicio.mir.es/nfrontal/asi_desc_res.html\">Скачати резолюцію</a>",

    "<b>🧾 Як подавати (3/7)</b>\n\n"
    "<b>Сіта для тимчасового захисту</b>\n"
    "<i>POLICÍA - UCRANIA</i>\n"
    "<i>SOLICITUD PROTECCIÓN TEMPORAL DESPLAZADOS</i>\n\n"
    "У багатьох містах сіту беруть\n"
    "• телефоном\n"
    "• або через email\n\n"
    "Через сайт Extranjería це буває рідше.\n"
    "Сигнал від бота не є гарантія, але час економить.",

    "<b>🧾 Як подавати (4/7)</b>\n\n"
    "<b>Порядок</b>\n"
    "1) Отримуєш тимчасовий захист (NIE присвоюється автоматично)\n"
    "2) Потім оформляєш <b>TIE</b> (резиденція) по тимчасовому захисту\n\n"
    "<b>Відео</b>\n"
    "👉 <a href=\"https://youtu.be/7mVeBc6SRy0\">Як брати сіту на тимчасовий захист</a>\n"
    "👉 <a href=\"https://youtu.be/I2noggh5AKo\">Як брати сіту на TIE і заповнювати документи</a>",

    "<b>🧾 Як подавати (5/7)</b>\n\n"
    "<b>Телефони для запису</b>\n"
    "• Мадрид (9:00–17:00) <code>+34 666 800 194</code>\n"
    "• Малага (8:00–18:00) <code>+34 628 216 478</code>\n"
    "• Барселона <code>+34 932 382 199</code>\n\n"
    "<b>ЄС продовжив захист до 2027</b>\n"
    "Почитати\n"
    "👉 <a href=\"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025D1460\">Рішення ЄС</a>\n\n"
    "Для Іспанії орієнтуємось на публікацію в BOE.",

    "<b>🧾 Як подавати (6/7)</b>\n\n"
    "<b>Email для запису</b>\n"
    "<code>algeciras.ucrif3@policia.es</code>\n"
    "<code>cadiz.acilo@policia.es</code>\n"
    "<code>huelva.acilos@policia.es</code>\n"
    "<code>almeria.bdep@policia.es</code>\n"
    "<code>huesca.ucrania@policia.es</code>\n"
    "<code>teruel.bped@policia.es</code>\n"
    "<code>zaragoza.udeve@policia.es</code>\n"
    "<code>arrecife.dokumentacion@policia.es</code>\n"
    "<code>laspalmas.protecciontemporal@policia.es</code>\n"
    "<code>prosario.extdoc@policia.es</code>\n"
    "<code>sctenerife.citaudex@policia.es</code>\n"
    "<code>santander.protecciontemporal@policia.es</code>\n"
    "<code>albacete.asilo@policia.es</code>\n"
    "<code>albacete.goe@policia.es</code>\n"
    "<code>ciudadreal.extranjeria@policia.es</code>\n"
    "<code>paterna.ge@policia.es</code>\n"
    "<code>sagunto.bpef@policia.es</code>\n"
    "<code>valencia.proteccioninternacional1@policia.es</code>\n\n"
    "<i>Примітка</i>\n"
    "Про <code>sagunto.bpef@policia.es</code> писали, що зараз можуть не робити, але це може змінитися.",

    "<b>🧾 Як подавати (7/7)</b>\n\n"
    "<b>Що писати в листі</b>\n"
    "• <i>Nombre y apellido</i> Ім’я і прізвище як у закордонному паспорті\n"
    "• <i>Domicilio</i> Адреса проживання (часто має збігатися з провінцією)\n"
    "• <i>Copia del pasaporte</i> Копія першої сторінки паспорта\n\n"
    "<b>Тема листа</b>\n"
    "Дехто писав, що інколи відповідають швидше, якщо вказати\n"
    "<code>Asilo Ucrania urgente</code>\n"
    "але це не правило.",
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
    offices = PROVINCES.get(province, {}).get("offices", []) or []
    rows = []

    for i, o in enumerate(offices):
        title = o.get("title", "Office")
        # 💬 callback короткий: только индекс (влезает всегда)
        rows.append([InlineKeyboardButton(text=title, callback_data=f"pick:office:{i}")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pick:province")])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="ui:main")])

    return InlineKeyboardMarkup(inline_keyboard=rows)



def _kb_pick_service(province: str, office_id: str | None = None, selected_service_id: str | None = None) -> InlineKeyboardMarkup:
    services = PROVINCES.get(province, {}).get("services", []) or []
    rows: list[list[InlineKeyboardButton]] = []

    for i, s in enumerate(services):
        title = s.get("title", "Service")
        sid = s.get("id")

        # 💬 “как раньше”: первые 2 = ✅, третья = 🚫
        # 💬 если в будущем захочешь реальную матрицу доступности по офисам — сюда же вставим.
        is_blocked = (i == 2)  # 3-я услуга
        mark = "🚫 " if is_blocked else "✅ "

        # 💬 если выбрана именно эта услуга — добавим вторую метку (чтобы видно было выбор)
        if selected_service_id and sid == selected_service_id:
            mark = "✅✅ " if not is_blocked else "🚫 "

        btn_text = _clip_btn_text(f"{mark}{title}", max_bytes=56)

        cb = f"pick:service_blocked:{i}" if is_blocked else f"pick:service:{i}"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=cb)])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pick:office_back")])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="ui:main")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# =========================
# NOTIFICATIONS (рандом)
# =========================
def _parse_hhmm(s: str) -> tuple[int, int]:
    hh, mm = s.split(":")
    return int(hh), int(mm)


def _generate_minutes_for_today(now: dt.datetime | None = None) -> list[int]:
    """
    💬 Генерим уведомления правдоподобно:
    - Пн–Пт (если WEEKDAYS_ONLY)
    - иногда 0 уведомлений (QUIET_DAY_PROB)
    - в основном в окне 14:00–17:00
    - редко добавляем утренние минуты
    - неравномерный рандом (triangular, пик ближе к середине окна)
    - кулдаун между минутами
    """
    if now is None:
        now = dt.datetime.now(MADRID_TZ)

    # 💬 По выходным — тишина
    if WEEKDAYS_ONLY and now.weekday() >= 5:
        return []

    # 💬 Иногда “тихий день”
    if random.random() < QUIET_DAY_PROB:
        return []

    def _to_min(hhmm: str) -> int:
        hh, mm = _parse_hhmm(hhmm)
        return hh * 60 + mm

    def _pick_biased(start_m: int, end_m: int) -> int:
        # 💬 "колокол": чаще ближе к середине окна
        mid = (start_m + end_m) / 2
        x = random.triangular(start_m, end_m, mid)
        return int(x)

    main_start = _to_min(WINDOW_START)
    main_end   = _to_min(WINDOW_END)
    if main_end <= main_start:
        main_end = main_start + 1

    morning_start = _to_min(MORNING_START)
    morning_end   = _to_min(MORNING_END)
    if morning_end <= morning_start:
        morning_end = morning_start + 1

    # 💬 Сколько уведомлений на день (не всегда PINGS_PER_DAY!)
    # 1 — чаще всего, 2 — иногда, 3 — редко
    max_k = max(1, int(PINGS_PER_DAY))
    roll = random.random()
    if roll < 0.65:
        k = 1
    elif roll < 0.90:
        k = 2
    else:
        k = 3
    k = min(k, max_k)

    picked: list[int] = []
    tries = 0
    while len(picked) < k and tries < 200:
        tries += 1

        # 💬 Иногда берём утро (редко)
        use_morning = (random.random() < MORNING_BURST_PROB)

        if use_morning:
            cand = _pick_biased(morning_start, morning_end)
        else:
            cand = _pick_biased(main_start, main_end)

        # 💬 Кулдаун: не ближе COOLDOWN_MINUTES
        if any(abs(cand - m) < COOLDOWN_MINUTES for m in picked):
            continue

        picked.append(cand)

    return sorted(set(picked))



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
            # 💬 По выходным вообще не шлём (и не создаём минуты)
            if WEEKDAYS_ONLY and now.weekday() >= 5:
                await asyncio.sleep(60)
                continue

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
                # 💬 ВАЖНО: фиксируем fired СРАЗУ, до рассылки
                # 💬 Если будет redeploy/краш в середине отправки — событие не повторится
                _save_json_atomic(DATA_PATH, store)
                
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
                    "‼️ <b>Можливо, з’явився слот</b> ‼️\n\n"
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
                    jitter = random.randint(0, 30)
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

    # =========================
    # STATS (today)
    # =========================
    now = dt.datetime.now(MADRID_TZ)
    day_key = _today_key(now)

    stats = store.setdefault("stats", {})
    day = stats.setdefault(day_key, {})
    day.setdefault("starts", 0)
    day.setdefault("new_users", 0)
    day.setdefault("active_users", 0)

    # 💬 starts = кожен /start
    day["starts"] += 1

    # 💬 new user = перший раз у житті
    if not u.get("first_seen_date"):
        u["first_seen_date"] = day_key
        day["new_users"] += 1

    # 💬 active today = унікальні за день (по last_seen_date)
    if u.get("last_seen_date") != day_key:
        u["last_seen_date"] = day_key
        day["active_users"] += 1


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

@router.message(F.text.startswith("/stats"))
async def admin_stats(message: Message):

    store = _load_json(DATA_PATH)
    users = store.get("users", {}) or {}

    now = dt.datetime.now(MADRID_TZ)
    day_key = _today_key(now)

    day = (store.get("stats", {}) or {}).get(day_key, {}) or {}
    starts = int(day.get("starts", 0) or 0)
    new_users = int(day.get("new_users", 0) or 0)
    active_users = int(day.get("active_users", 0) or 0)

    total_users = len(users)

    enabled_total = 0
    enabled_by_service: dict[str, int] = {"ua_card": 0, "huellas_tie": 0, "recogida_tie": 0}
    enabled_by_province: dict[str, int] = {}

    # 💬 “живой пересчёт” на момент вызова /stats
    for uid, u0 in users.items():
        u = _ensure_user(store, str(uid))
        if not u.get("enabled"):
            continue
        enabled_total += 1

        prov = str(u.get("province") or "—")
        svc = str(u.get("service_id") or "—")

        enabled_by_province[prov] = enabled_by_province.get(prov, 0) + 1
        if svc in enabled_by_service:
            enabled_by_service[svc] += 1

    # 💬 красивее названия сервисов
    svc_names = {
        "ua_card": "POLICÍA TARJETA CONFLICTO UCRANIA",
        "huellas_tie": "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA)...",
        "recogida_tie": "POLICIA - RECOGIDA DE TARJETA (TIE)",
    }

    prov_lines = ""
    for prov, cnt in sorted(enabled_by_province.items(), key=lambda x: (-x[1], x[0])):
        prov_lines += f"<i>• { _h(prov) }:</i> <b>{cnt}</b>\n"

    svc_lines = ""
    for sid in ["ua_card", "huellas_tie", "recogida_tie"]:
        svc_lines += f"<i>• { _h(svc_names.get(sid, sid)) }:</i> <b>{enabled_by_service.get(sid, 0)}</b>\n"

    text = (
        "<b>📊 Stats</b>\n\n"
        f"<i>Дата (Madrid):</i> <b>{_h(day_key)}</b>\n\n"
        "<b>За сьогодні</b>\n"
        f"<i>• /start натиснули:</i> <b>{starts}</b>\n"
        f"<i>• Нові користувачі:</i> <b>{new_users}</b>\n"
        f"<i>• Активні (унікальні):</i> <b>{active_users}</b>\n\n"
        "<b>Зараз у базі</b>\n"
        f"<i>• Всього користувачів:</i> <b>{total_users}</b>\n"
        f"<i>• Увімкнули сповіщення:</i> <b>{enabled_total}</b>\n\n"
        "<b>Увімкнені по провінціях</b>\n"
        f"{prov_lines if prov_lines else '<i>• —</i>'}\n"
        "<b>Увімкнені по послугах</b>\n"
        f"{svc_lines}"
    )

    await message.answer(text, parse_mode="HTML")

    # 💬 чистим чат: удалим команду /stats
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
    u.pop("last_alert_min", None)  # 💬 сбрасываем cooldown при смене выбора


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
    try:
        await call.answer()
    except Exception:
        pass

    parts = (call.data or "").split(":")
    if len(parts) < 3:
        return await _go_pick_province(call)

    # 💬 получаем индекс офиса
    try:
        office_idx = int(parts[2])
    except Exception:
        return await _go_pick_province(call)

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    province = u.get("province")
    if not province or province not in PROVINCES:
        return await _go_pick_province(call)

    offices = PROVINCES[province].get("offices", []) or []
    if office_idx < 0 or office_idx >= len(offices):
        # 💬 если список обновился — показываем заново офисы
        await _edit_or_send_ui(
            chat_id=call.message.chat.id,
            store=store,
            user_id=user_id,
            text=f"🏢 Обери офіс в {province}:",
            kb=_kb_pick_office(province),
        )
        return

    office_id = offices[office_idx].get("id")

    # 💬 сохраняем как раньше
    u["office_id"] = office_id
    u["service_id"] = None
    u["enabled"] = False
    u.pop("last_alert_min", None)

    _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text="🧩 Обери послугу:",
        kb=_kb_pick_service(province, office_id=office_id, selected_service_id=u.get("service_id")),

    )


async def _go_pick_province(call: CallbackQuery) -> None:
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    _ensure_user(store, user_id)
    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text="🗺️ Обери місто/провінцію:",
        kb=_kb_pick_province(),
    )

@router.callback_query(F.data == "pick:office_back")
async def cb_pick_office_back(call: CallbackQuery):
    try:
        await call.answer()
    except Exception:
        pass

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    province = u.get("province")
    if not province or province not in PROVINCES:
        await _go_pick_province(call)
        return

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=f"🏢 Обери офіс в {province}:",
        kb=_kb_pick_office(province),
    )

@router.callback_query(F.data.startswith("pick:service:"))
async def cb_pick_service(call: CallbackQuery):
    # 💬 один ответ на callback
    try:
        await call.answer()
    except Exception:
        pass

    parts = (call.data or "").split(":")
    if len(parts) < 3:
        return

    try:
        service_idx = int(parts[2])
    except Exception:
        return

    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)
    u = _ensure_user(store, user_id)

    province = u.get("province")
    office_id = u.get("office_id")

    # 💬 если контекста нет — возвращаем в выбор провинции
    if (not province) or (province not in PROVINCES) or (not office_id):
        await _go_pick_province(call)
        return

    services = PROVINCES[province].get("services", []) or []
    if service_idx < 0 or service_idx >= len(services):
        # 💬 список обновился/битый индекс — перерисуем услуги
        await _edit_or_send_ui(
            chat_id=call.message.chat.id,
            store=store,
            user_id=user_id,
            text="🧩 Обери послугу:",
            kb=_kb_pick_service(province, office_id=office_id, selected_service_id=u.get("service_id")),

        )
        return

    service_id = services[service_idx].get("id")

    u["service_id"] = service_id
    u["enabled"] = False
    u.pop("last_alert_min", None)

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
    # 💬 callback короткий: pick:service_blocked:<idx>
    try:
        await call.answer("🚫 Ця послуга недоступна. Обери іншу.", show_alert=True)
    except Exception:
        pass


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

    elif kind == "apply":
        pages = APPLY_PAGES
        page = max(0, min(page, len(pages) - 1))
        text = pages[page]
        kb = _kb_pager("apply", page, len(pages))

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
