# === КОНСТРУКТОР УРОКОВ: СОХРАНЕНИЕ В STRUCTURE С TYPE ===

import json, random
import os
import uuid  # 💬 Для генерации уникальных имён файлов
import re
import logging  # 💬 для логирования в receive_ad_source

from pathlib import Path

def atomic_save_json(path: str | Path, data: dict) -> bool:
    # 💬 что делает эта часть: атомарно сохраняем JSON (tmp файл + replace), чтобы не получить битый файл при падении
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = p.with_suffix(p.suffix + f".tmp_{uuid.uuid4().hex}")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        os.replace(tmp_path, p)
        return True
    except Exception as e:
        logging.exception("atomic_save_json: failed to save %s: %s", path, e)
        try:
            if "tmp_path" in locals() and Path(tmp_path).exists():
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _insert_or_append(target_list: list, item, insert_index):
    # 💬 вставляет по 1-based индексу админки, иначе добавляет в конец
    try:
        idx = int(insert_index) if insert_index is not None else None
    except Exception:
        idx = None

    if idx is None:
        target_list.append(item)
        return

    if idx < 1:
        idx = 1

    pos = idx - 1
    if pos > len(target_list):
        pos = len(target_list)

    target_list.insert(pos, item)


def get_topics_dir() -> Path:
    # 💬 что делает эта часть: работаем только с Railway Volume (/data/topics), без локального fallback
    d = Path("/data/topics")
    d.mkdir(parents=True, exist_ok=True)
    test = d / ".write_test"
    test.write_text("ok", encoding="utf-8")
    try:
        test.unlink()
    except Exception:
        pass
    return d


def _is_railway_topics_file(path: str | Path) -> bool:
    # 💬 проверяем что файл реально лежит в Railway Volume (/data/topics)
    try:
        topics_dir = Path("/data/topics").resolve()
        p = Path(path).resolve()
        return str(p).startswith(str(topics_dir) + os.sep) and p.suffix.lower() == ".json"
    except Exception:
        return False




from aiogram import Router, Bot
from aiogram import F
from aiogram.filters import StateFilter


from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery  # 💬 inline меню на callback
from aiogram.exceptions import TelegramBadRequest  # 💬 защита от "message is not modified"
import hashlib  # 💬 короткие id для callback_data

from aiogram.filters.command import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

router = Router()

ADMIN_INLINE_MSG_ID_KEY = "admin_inline_msg_id"  # 💬 где хранится id последнего inline-меню
ADMIN_TOPIC_MAP_KEY = "admin_topic_map"          # 💬 tid -> filename stem для callback

ADMIN_EDIT_MODE_KEY = "admin_edit_mode"            # 💬 режим фильтрованного редактирования
ADMIN_TOPIC_FLOW_KEY = "admin_topic_flow"          # 💬 маркер сценария /addtopic для fallback
ADMIN_EDIT_CATEGORY_KEY = "admin_edit_category"    # 💬 выбранная категория (lex/gram)
ADMIN_EDIT_LEVEL_KEY = "admin_edit_level"          # 💬 выбранный уровень (A0/A1-A2/B1-B2/C1)

ADMIN_CURRENT_TID_KEY = "adm_current_tid"          # 💬 tid текущей открытой темы
ADMIN_EDIT_VIEW_KEY = "adm_view"                   # 💬 какой экран сейчас открыт в админ-редакторе
ADMIN_EDIT_SCOPE_KEY = "adm_scope"                 # 💬 над каким списком сейчас работаем (practice/video/theory_items/...)
ADMIN_EDIT_PAGE_KEY = "adm_page"                   # 💬 текущая страница списка
ADMIN_EDIT_PHASE_INDEX_KEY = "adm_phase_index"     # 💬 индекс фазы (0-based) в topic["vocab"]
ADMIN_EDIT_PACK_INDEX_KEY = "adm_pack_index"       # 💬 индекс пака чтения (0-based) в topic["reading"]
ADMIN_EDIT_SUBLIST_KEY = "adm_sublist"             # 💬 fragments | assets

ADMIN_PENDING_ACTION_KEY = "adm_pending_action"            # 💬 delete | move | insert
ADMIN_PENDING_INSERT_KIND_KEY = "adm_insert_kind"          # 💬 text | photo | link | fragment | asset
ADMIN_PENDING_INSERT_PAYLOAD_KEY = "adm_insert_payload"    # 💬 dict | list для вставки
ADMIN_PENDING_MOVE_FROM_KEY = "adm_move_from"              # 💬 from index для перемещения
ADMIN_PAGE_SIZE = 6  # 💬 сколько элементов показываем на одной странице в админ-листах


def _ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    # 💬 собираем InlineKeyboardMarkup из (text, callback_data)
    keyboard = []
    for row in rows:
        keyboard.append([InlineKeyboardButton(text=t, callback_data=cb) for t, cb in row])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _admin_topic_card_kb(tid: str) -> InlineKeyboardMarkup:
    # 💬 единая клавиатура карточки темы (без home/close)
    return _ikb([
        [("👁 Просмотр", "adm:topic_preview"), ("✏️ Редактировать", "adm:topic_edit")],
        [("🗑 Удалить тему", f"adm:topic_del:{tid}")],
        [("⬅️ К списку тем", "adm:topics")],
    ])

async def _inline_replace(cb: CallbackQuery, state: FSMContext, text: str, kb: InlineKeyboardMarkup):
    # 💬 редактируем текущее сообщение, чтобы не плодить новые
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        # 💬 если Telegram ругается на "not modified" или другое = просто игнорируем
        try:
            await cb.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
    except Exception:
        # 💬 fallback: если edit невозможен, отправим новое и запомним id
        msg = await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.update_data(**{ADMIN_INLINE_MSG_ID_KEY: msg.message_id})

async def _inline_open(message: Message, state: FSMContext, text: str, kb: InlineKeyboardMarkup):
    # 💬 при входе в админ-inline режим удаляем прошлое меню и показываем одно новое
    st = await state.get_data()
    old_id = st.get(ADMIN_INLINE_MSG_ID_KEY)
    if old_id:
        try:
            await message.bot.delete_message(message.chat.id, int(old_id))
        except Exception:
            pass

    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(**{ADMIN_INLINE_MSG_ID_KEY: msg.message_id})

def _make_tid(name: str) -> str:
    # 💬 короткий id для callback_data (лимит длины в Telegram)
    return hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:10]

def _load_topics_index() -> tuple[dict, list[str]]:
    # 💬 собираем индекс тем из /data/topics
    topics_dir = get_topics_dir()
    files = sorted([p.stem for p in topics_dir.glob("*.json")])
    topic_map = {}
    for name in files:
        topic_map[_make_tid(name)] = name
    return topic_map, files

# 💬 Уровни, которые сохраняем в JSON (без эмодзи)
ALLOWED_LEVELS = ["A0", "A1-A2", "B1-B2", "C1"]

# 💬 Маппинг текста кнопок -> нормализованное значение уровня
LEVEL_FROM_BUTTON = {
    "😇 Новичку": "A0",
    "🌱 A1-A2":  "A1-A2",
    "🔥 B1-B2":  "B1-B2",
    "🧠 C1":     "C1",
}

#from core8_1 import load_ads_data, save_ads_data

ADS_DATA_PATH = "/data/ads_data.json"  # 💬 хранение в Railway Volume (не теряется при redeploy)
os.makedirs("/data", exist_ok=True)    # 💬 гарантируем папку Volume

SUBSCRIPTION_CHANNELS_PATH = "subscription_channels.json"  # 💬 общий список каналов для рекламной подписки


def load_ads_data():
    if not os.path.exists(ADS_DATA_PATH):
        with open(ADS_DATA_PATH, "w", encoding="utf-8") as f:
            f.write("[]")
    with open(ADS_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_ads_data(data):
    with open(ADS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

import base64
import logging

from urllib.request import Request, urlopen  # 💬 GitHub API без requests
from urllib.error import HTTPError, URLError  # 💬 обработка ошибок HTTP
from urllib.parse import urlencode            # 💬 ref=branch в query


def github_put_file(local_path: str, repo_path: str, commit_message: str):
    """
    💬 Upload or update a file to GitHub via REST API (urllib, без requests).
    Uses env: GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH (optional)
    If GITHUB_PAT is not set — функция тихо возвращает (не ломает основной flow).
    """
    token = os.environ.get("GITHUB_PAT")
    if not token:
        logging.info("github_put_file: no GITHUB_PAT set — skipping GitHub upload")
        return False, "no_token"

    owner = os.environ.get("GITHUB_OWNER")
    repo  = os.environ.get("GITHUB_REPO")
    branch = os.environ.get("GITHUB_BRANCH", "main")

    if not owner or not repo:
        logging.error("github_put_file: GITHUB_OWNER or GITHUB_REPO not set in env")
        return False, "no_owner_repo"

    # 💬 читаем локальный файл и кодируем в base64
    try:
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        logging.exception("github_put_file: cannot read local file %s: %s", local_path, e)
        return False, str(e)

    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ProyectoBot",  # 💬 GitHub иногда требует User-Agent
    }

    # 1) 💬 пытаемся получить существующий файл, чтобы взять sha (если есть)
    sha = None
    try:
        url = api_url + "?" + urlencode({"ref": branch})
        req = Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=15) as resp:
            if resp.getcode() == 200:
                data = json.loads(resp.read().decode("utf-8") or "{}")
                sha = (data or {}).get("sha")
    except HTTPError as e:
        if e.code != 404:
            logging.exception("github_put_file: GET failed (HTTP %s)", e.code)
    except (URLError, Exception) as e:
        logging.exception("github_put_file: GET request failed: %s", e)

    payload = {
        "message": commit_message,
        "content": content_b64,
        "branch": branch
    }
    if sha:
        payload["sha"] = sha

    # 2) 💬 PUT (создать/обновить)
    put_headers = dict(headers)
    put_headers["Content-Type"] = "application/json"
    body = json.dumps(payload).encode("utf-8")

    try:
        req = Request(api_url, headers=put_headers, data=body, method="PUT")
        with urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            text = resp.read().decode("utf-8") or ""
        if status in (200, 201):
            logging.info("github_put_file: uploaded %s -> %s (status=%s)", local_path, repo_path, status)
            return True, (json.loads(text) if text else {"status": status})
        logging.error("github_put_file: upload failed status=%s text=%s", status, text)
        return False, {"status": status, "text": text}
    except HTTPError as e:
        try:
            err_text = e.read().decode("utf-8")
        except Exception:
            err_text = ""
        logging.error("github_put_file: upload failed HTTP=%s text=%s", e.code, err_text)
        return False, {"status": e.code, "text": err_text}
    except (URLError, Exception) as e:
        logging.exception("github_put_file: PUT request exception: %s", e)
        return False, str(e)


class NewTopicStates(StatesGroup):
    waiting_category = State()
    # ---------- БАЗОВЫЕ СОСТОЯНИЯ ------------
    adding_category         = State()  # 💬 состояние ожидания выбора уровня
    waiting_topic_name      = State()
    waiting_topic_description = State() # 💬 ввод описания темы
    waiting_first_choice    = State()
    waiting_admin_choice    = State()
    waiting_edit_topic_choice = State()  # 💬 что делает эта часть: выбор существующей темы для редактирования
    waiting_delete_topic_confirm = State()  # 💬 подтверждение удаления темы (файл из /data/topics)
    waiting_post_action     = State()  # 💬 после сохранения словаря/упражнения/видео: создать еще или вернуться

    # ----------- БЛОК “СЛОВАРЬ” -------------
    waiting_phase_choice      = State()  # 💬 выбор существующей фазы или создание новой
    waiting_phase_name        = State()  # 💬 вводим название новой фазы

    waiting_vocab_title     = State()  # 💬 вводим заголовок словаря
    waiting_vocab_link      = State()  # 💬 вводим ссылку или текст словаря



    # ——— BULK-ИМПОРТ ДЛЯ KVIZ ———
    waiting_vocab_textquiz_bulk = State()  # 💬 пакетный ввод: по строкам "вопрос | ответ" для TEXT_QUIZ
    waiting_vocab_allin_bulk = State()  # 💬 ждём вставку блока ALL IN
    waiting_vocab_quiz_bulk     = State()  # 💬 пакетный ввод: по строкам "вопрос | правильный | неверный1 | неверный2 | объяснение(опц.)"


    waiting_vocab_photo_text = State()  # 💬  необязательный текст перед фото
    waiting_vocab_photo     = State()



   

    


    waiting_vocab_text     = State()

    # — после добавления текста — опциональный quiz
    waiting_vocab_text_quiz        = State()  # ввод всего квиза или '-' для пропуска
    waiting_vocab_text_quiz_block  = State()  # парсинг и сохранение quiz

    # ------------ БЛОК “УПРАЖНЕНИЕ (ОБЩЕЕ)” ----------
    waiting_ex_title        = State()  # 💬 вводим название упражнения
    waiting_ex_instr        = State()  # 💬 вводим инструкцию
    waiting_ex_url          = State()  # 💬 вводим ссылку или контент упражнения


 
    waiting_ex_text       = State()  # 💬 Ожидание ввода текст-блока для упражнения
    waiting_ex_photo_text = State()  # 💬 Ожидание подписи к фото упражнения

    waiting_ex_photo      = State()  # 💬 Ожидание фото или URL картинки для упражнения


    # --------- БЛОК “ВИДЕО” -----------
    waiting_video_title     = State()  # 💬 вводим заголовок видео
    waiting_video_link      = State()  # 💬 вводим ссылку на видео

    # ----------- БЛОК “ЧТЕНИЕ” -----------
    waiting_reading_title = State()          # 💬 вводим заголовок чтения (как "мини-эпизод")
    waiting_reading_fragments_text = State() # 💬 ждём фрагменты (ES | RU | 💡 hint)

    waiting_reading_action = State()      # 💬 меню внутри пакета чтения: фото или фрагменты
    waiting_reading_photo_text = State()  # 💬 подпись к фото чтения или '-'
    waiting_reading_photo = State()       # 💬 приём фото/GIF/видео/стикера/URL для чтения



    waiting_channel = State()  # Новое состояние для канала

    # ——— БЛОК “РЕКЛАМА” ———
    waiting_ad_source = State()  # ждем пересланного сообщения из канала
    waiting_ad_buttons = State()   # ждем: вопрос|кнопка1|кнопка2|реакция1|реакция2

    waiting_ad_action = State()        # 💬 выбор: добавить рекламу / удалить по индексу
    waiting_ad_delete_index = State()  # 💬 ждём номер индекса для удаления





class NewDialogStates(StatesGroup):
    waiting_dialog_phase_name = State()      # 💬 имя фазы диалогов ("Fase 1 — ir al médico (pack 1)")
    waiting_dialog_markdown_block = State()  # 💬 весь Markdown-блок с репликами (по 4 строки)



# ✏️ Состояния для потока редактирования темы
class EditTopicStates(StatesGroup):
    choose_action           = State()   # ждем выбора действия: Добавить/Отмена
    # — Добавление словаря
    waiting_vocab_title     = State()
    waiting_vocab_link      = State()
    # — Добавление произвольного текста
    waiting_text_block      = State()
    # — Добавление QUIZ
    waiting_quiz_block      = State()
    # — Добавление упражнения
    waiting_ex_title        = State()
    waiting_ex_instr        = State()
    waiting_ex_url          = State()
    # — Добавление видео
    waiting_video_title     = State()
    waiting_video_link      = State()
    # — Добавление диалога
    waiting_dialog_title    = State()
    waiting_dialog_description = State()
    waiting_dialog_photo    = State()

    waiting_vocab_phase_delete_index = State()   # 💬 удаление фазы словаря по индексу
    waiting_dialog_phase_delete_index = State()  # 💬 удаление фазы диалогов по индексу
    waiting_video_delete_index = State()         # 💬 удаление видео по индексу
    waiting_reading_delete_index = State()       # 💬 удаление пака чтения по индексу


class EditGrammarStates(StatesGroup):
    waiting_section = State()        # 💬 выбор: теория, практика, видео, читать
    waiting_phase = State()          # 💬 выбор фазы теории
    waiting_delete_index = State()   # 💬 ввод индекса для удаления
    waiting_insert_index = State()  # 💬 ждём индекс, куда вставить новый блок



class AdminInlineEditStates(StatesGroup):
    # 💬 FSM для ввода индексов и контента в админ-inline редакторе
    idle = State()  # 💬 нейтральное состояние, когда ждём inline-действие (без ввода текста)
    waiting_phase_name = State()        # 💬 добавление фазы
    waiting_reading_title = State()     # 💬 добавление пака чтения
    waiting_delete_index = State()      # 💬 ввод индекса для удаления
    waiting_move_from = State()         # 💬 откуда перемещаем
    waiting_move_to = State()           # 💬 куда перемещаем
    waiting_insert_payload = State()    # 💬 ждём контент для вставки
    waiting_insert_index = State()      # 💬 ждём индекс вставки



def get_main_menu(category: str | None = None) -> ReplyKeyboardMarkup:
    # 💬 что делает эта часть: разные кнопки для lex и gram, но структура JSON та же
    if category == "gram":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📖 Теория"),     KeyboardButton(text="📝 Практика")],
                [KeyboardButton(text="🎥 Видео"),      KeyboardButton(text="📚 Читать")],
                [KeyboardButton(text="👁 Просмотреть"), KeyboardButton(text="✏️ Редактировать")]
            ],
            resize_keyboard=True
        )
    return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
                [KeyboardButton(text="🎥 Добавить видео"), KeyboardButton(text="💾 Сохранить")], 
                [KeyboardButton(text="📖 Добавить чтение"), KeyboardButton(text="📝 Добавить перевод")],  # 💬 два разных режима
                [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")]
            ],
            resize_keyboard=True
        )



def get_edit_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📚 Добавить словарь"),
                KeyboardButton(text="➕ Добавить QUIZ"),
            ],
            [
                KeyboardButton(text="➕ Добавить видео"),
                KeyboardButton(text="📝 Добавить ТЕКСТ"),
            ],
            [
                KeyboardButton(text="📚 Добавить чтение"),
                KeyboardButton(text="➕ Добавить бонус"),
            ],
            [
                KeyboardButton(text="📊 Статус темы"),
                KeyboardButton(text="✅ Закончить редактирование"),
            ],
        ],
        resize_keyboard=True,
    )


@router.message(Command("addtopic"))
async def start_adding_topic(message: Message, state: FSMContext):
    try:
        logging.info(
            "[addtopic.lex.debug] start_adding_topic user_id=%s prev_state=%s",
            getattr(getattr(message, "from_user", None), "id", None),
            await state.get_state(),
        )
        await state.clear()
        await state.update_data(**{ADMIN_TOPIC_FLOW_KEY: True})
        keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика")],
            [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
            [KeyboardButton(text="✏️ Редактировать темы")],  # 💬 переход в EditTopic
        ],
        resize_keyboard=True
    )

        await message.answer("📂 Выбери КАТЕГОРИЮ темы:", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_category)
    except Exception as e:
        logging.exception("[addtopic.lex.debug] start_adding_topic exception: %s", e)
        raise


async def _enter_edit_topics_mode(message: Message, state: FSMContext) -> None:
    """💬 Общий вход в режим «Редактировать темы» (кнопка и /edittopic)."""
    await state.clear()
    await state.update_data(**{ADMIN_EDIT_MODE_KEY: True, ADMIN_TOPIC_FLOW_KEY: True})

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )

    await message.answer("✏️ Редактирование тем.\nВыбери категорию:", reply_markup=kb)
    await state.set_state(NewTopicStates.waiting_category)


@router.message(Command("edittopic"))
async def start_edit_topic(message: Message, state: FSMContext):
    logging.info(
        "[addtopic.lex.debug] start_edit_topic user_id=%s prev_state=%s",
        getattr(getattr(message, "from_user", None), "id", None),
        await state.get_state(),
    )
    await _enter_edit_topics_mode(message, state)

# === Шаг 1: выбор категории ===

@router.message(NewTopicStates.waiting_category)
async def get_category_or_ads(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    try:
        st_debug = await state.get_data()
        logging.info(
            "[addtopic.lex.debug] category_handler_enter user_id=%s text=%r state=%s state_keys=%s",
            getattr(getattr(message, "from_user", None), "id", None),
            message.text,
            await state.get_state(),
            sorted(list((st_debug or {}).keys())),
        )
    except Exception as e:
        logging.exception("[addtopic.lex.debug] failed to log category_handler_enter: %s", e)

    st = await state.get_data()
    if text == "⬅️ Назад" and st.get(ADMIN_EDIT_MODE_KEY):
        return await start_adding_topic(message, state)  # 💬 выход из режима редактирования


    # 💬 вход в режим редактирования тем = сначала фильтр (категория -> уровень)
    if text == "✏️ Редактировать темы":
        logging.info(
            "[addtopic.lex.debug] handled_by=create_lesson_block:get_category_or_ads branch=edit_topics user_id=%s state=%s",
            getattr(getattr(message, "from_user", None), "id", None),
            await state.get_state(),
        )
        await _enter_edit_topics_mode(message, state)
        return



    if text == "ADD":
        logging.info(
            "[addtopic.lex.debug] handled_by=create_lesson_block:get_category_or_ads branch=add_ads user_id=%s state=%s",
            getattr(getattr(message, "from_user", None), "id", None),
            await state.get_state(),
        )
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Добавить рекламу"), KeyboardButton(text="🗑 Удалить по индексу")],
                [KeyboardButton(text="⬅️ Назад")]
            ],
            resize_keyboard=True
        )
        await message.answer("Выбери действие с рекламой:", reply_markup=keyboard)
        return await state.set_state(NewTopicStates.waiting_ad_action)


    if text == "CHANALS":
        logging.info(
            "[addtopic.lex.debug] handled_by=create_lesson_block:get_category_or_ads branch=channels user_id=%s state=%s",
            getattr(getattr(message, "from_user", None), "id", None),
            await state.get_state(),
        )
        await message.answer(
            "Введи ссылку (https://t.me/username) или имя канала (@username).\n"
            "Если несколько — раздели через запятую."
        )
        return await state.set_state(NewTopicStates.waiting_channel)

    normalized = (text or "").strip().lower()
    is_lex_pick = normalized in {"📚 лексика", "лексика"}

    if not is_lex_pick:
        await message.answer("❗ Выбери одну из кнопок.")
        return

    logging.info(
        "[addtopic.lex.debug] handled_by=create_lesson_block:get_category_or_ads branch=lex_category user_id=%s state=%s",
        getattr(getattr(message, "from_user", None), "id", None),
        await state.get_state(),
    )

    category = "lex"

    await state.update_data(topic={"category": category})

    st = await state.get_data()
    if st.get(ADMIN_EDIT_MODE_KEY):
        await state.update_data(**{ADMIN_EDIT_CATEGORY_KEY: category})  # 💬 фиксируем категорию для фильтра


    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="😇 Новичку"), KeyboardButton(text="🌱 A1-A2")],
            [KeyboardButton(text="🔥 B1-B2"),   KeyboardButton(text="🧠 C1")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("Теперь выбери уровень темы:", reply_markup=keyboard)

    await state.set_state(NewTopicStates.adding_category)

@router.message(StateFilter("*"), F.text.in_(["📚 Лексика", "Лексика", "⬅️ Назад", "Назад"]))
async def _admin_editmode_category_fallback(message: Message, state: FSMContext):
    st = await state.get_data()
    logging.info(
        "[addtopic.lex.debug] category_fallback_hit user_id=%s text=%r state=%s admin_edit_mode=%s admin_topic_flow=%s state_keys=%s",
        getattr(getattr(message, "from_user", None), "id", None),
        message.text,
        await state.get_state(),
        bool(st.get(ADMIN_EDIT_MODE_KEY)),
        bool(st.get(ADMIN_TOPIC_FLOW_KEY)),
        sorted(list((st or {}).keys())),
    )
    if not (st.get(ADMIN_EDIT_MODE_KEY) or st.get(ADMIN_TOPIC_FLOW_KEY)):
        return

    cur = await state.get_state()
    if cur in {
        NewTopicStates.waiting_category.state,
        NewTopicStates.adding_category.state
    }:
        return  # 💬 не перехватываем тут, чтобы основной хендлер категории успел отработать


    await state.set_state(NewTopicStates.waiting_category)  # 💬 чинит “залипший” state, чтобы кнопки снова ловились
    try:
        return await get_category_or_ads(message, state)
    except Exception as e:
        logging.exception("[addtopic.lex.debug] category_fallback delegation exception: %s", e)
        raise


@router.callback_query(F.data == "adm:close")
async def adm_close(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        await cb.message.delete()
    except Exception:
        pass

    # 💬 выходим из режима админ-редактирования и возвращаемся в /addtopic
    await state.update_data(
        **{
            ADMIN_EDIT_MODE_KEY: False,
            ADMIN_TOPIC_FLOW_KEY: False,
            ADMIN_INLINE_MSG_ID_KEY: None,
            ADMIN_EDIT_CATEGORY_KEY: None,
            ADMIN_EDIT_LEVEL_KEY: None,
        }
    )
    return await start_adding_topic(cb.message, state)

@router.callback_query(F.data == "adm:home")
async def admin_home(cb: CallbackQuery, state: FSMContext):
    # 💬 выходим из inline меню и возвращаемся в /addtopic
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()
    await state.update_data(**{ADMIN_TOPIC_FLOW_KEY: False})
    return await start_adding_topic(cb.message, state)


@router.callback_query(F.data.startswith("adm:topic:"))
async def admin_open_topic(cb: CallbackQuery, state: FSMContext):
    # 💬 открываем тему по callback (без ввода названия)
    tid = (cb.data or "").split("adm:topic:", 1)[1].strip()

    st = await state.get_data()
    topic_map = st.get(ADMIN_TOPIC_MAP_KEY) or {}

    name = topic_map.get(tid)
    if not name:
        topic_map, _ = _load_topics_index()
        await state.update_data(**{ADMIN_TOPIC_MAP_KEY: topic_map})
        name = topic_map.get(tid)

    if not name:
        await cb.answer("Тема не найдена", show_alert=True)
        return

    topics_dir = get_topics_dir()
    path = topics_dir / f"{name}.json"
    if not path.exists():
        await cb.answer("Файл темы не найден", show_alert=True)
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            topic_data = json.load(f) or {}
    except Exception:
        await cb.answer("Ошибка чтения JSON", show_alert=True)
        return

    st_prev = await state.get_data()
    edit_mode = st_prev.get(ADMIN_EDIT_MODE_KEY)
    edit_cat = st_prev.get(ADMIN_EDIT_CATEGORY_KEY)
    edit_lvl = st_prev.get(ADMIN_EDIT_LEVEL_KEY)

    await state.clear()
    await state.update_data(
        topic=topic_data,
        topic_path=str(path),
        topic_level=topic_data.get("level"),
        **{ADMIN_TOPIC_MAP_KEY: topic_map},
        **{ADMIN_INLINE_MSG_ID_KEY: cb.message.message_id},
        **{ADMIN_EDIT_MODE_KEY: edit_mode},
        **{ADMIN_EDIT_CATEGORY_KEY: edit_cat},
        **{ADMIN_EDIT_LEVEL_KEY: edit_lvl},
        **{ADMIN_CURRENT_TID_KEY: tid},          # 💬 запоминаем tid, чтобы вернуться к карточке темы
        **{ADMIN_EDIT_VIEW_KEY: "topic_card"},   # 💬 стартовый экран
    )
    title = str(topic_data.get("visible_title") or topic_data.get("title") or topic_data.get("name") or tid).strip()  # 💬 заголовок темы как в grammar_feature

    
    kb = _admin_topic_card_kb(tid)


    await _inline_replace(cb, state, f"✅ Открыта тема: <b>{title}</b>\nЧто сделать?", kb)
    await cb.answer()

@router.callback_query(F.data == "adm:topic_card")
async def admin_topic_card(cb: CallbackQuery, state: FSMContext):
    # 💬 возвращаем inline карточку темы с кнопками Просмотр и Редактировать
    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await cb.answer("Тема не загружена", show_alert=True)
        return

    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""

    title = str(topic_data.get("visible_title") or topic_data.get("name") or tid).strip()

    kb = _admin_topic_card_kb(tid)

    await state.update_data(**{ADMIN_EDIT_VIEW_KEY: "topic_card"})
    await _inline_replace(
        cb,
        state,
        f"✅ Открыта тема: <b>{_preview_text(str(title), 80)}</b>\nЧто сделать?",
        kb
    )
    await cb.answer()


async def _admin_show_topic_view_menu(cb: CallbackQuery, state: FSMContext, tid: str):
    topic_data, _ = await _admin_load_topic_from_disk(state)
    if not topic_data:
        await cb.answer("Тема не загружена", show_alert=True)
        return

    title = str(topic_data.get("visible_title") or topic_data.get("name") or tid).strip()
    text_preview = _admin_render_preview_text(topic_data)

    kb = _ikb([
        [("📘 Словарь", f"adm:topic_view:vocab:{tid}")],
        [("🎥 Видео", f"adm:topic_view:videos:{tid}")],
        [("📖 Читать", f"adm:topic_view:read:{tid}")],
        [("⬅️ К списку тем", "adm:topics")],
        [("⬅️ К карточке темы", "adm:topic_card")],
        [("🏠 В меню /addtopic", "adm:home")],
        [("⬅️ Закрыть", "adm:close")],
    ])

    await state.update_data(**{ADMIN_EDIT_VIEW_KEY: "topic_view_menu"})
    await _inline_replace(
        cb,
        state,
        f"👁 <b>Просмотр темы: {_preview_text(title, 80)}</b>\n\n{text_preview}",
        kb,
    )
    await cb.answer()


@router.callback_query(F.data == "adm:topic_preview")
async def admin_topic_preview(cb: CallbackQuery, state: FSMContext):
    # 💬 вместо summary-экрана открываем меню просмотра темы
    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""
    if not tid:
        await cb.answer("Тема не выбрана", show_alert=True)
        return

    await _admin_show_topic_view_menu(cb, state, tid)


@router.callback_query(F.data.startswith("adm:topic_view:menu:"))
async def admin_topic_view_menu(cb: CallbackQuery, state: FSMContext):
    tid = (cb.data or "").split("adm:topic_view:menu:", 1)[1].strip()
    await _admin_show_topic_view_menu(cb, state, tid)


def _adm_vocab_packs(topic_data: dict) -> list[tuple[str, list[str]]]:
    raw = topic_data.get("vocab") if isinstance(topic_data, dict) else []
    packs: list[tuple[str, list[str]]] = []

    if not isinstance(raw, list):
        return packs

    for idx, pack in enumerate(raw, start=1):
        pack_name = f"Пак {idx}"
        words: list[str] = []
        items = []
        blocks = []

        if isinstance(pack, dict):
            pack_name = str(pack.get("phase_name") or pack.get("name") or pack_name).strip() or pack_name
            items = pack.get("vocab") or pack.get("phrases") or pack.get("words") or []
            blocks = pack.get("blocks") or []
        if not isinstance(pack, dict):
            items = pack

        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            items = [items]

        for item in items:
            line = ""
            if isinstance(item, dict):
                src = str(item.get("word") or item.get("text") or item.get("phrase") or "").strip()
                dst = str(item.get("translate") or item.get("translation") or item.get("ru") or item.get("meaning") or "").strip()
                if src and dst:
                    line = f"{src} — {dst}"
                else:
                    line = src or dst
            else:
                line = str(item).strip()

            if line:
                words.append(line)

        if isinstance(blocks, dict):
            blocks = [blocks]
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                src = str(
                    block.get("es")
                    or block.get("word")
                    or block.get("text")
                    or block.get("phrase")
                    or ""
                ).strip()
                dst = str(
                    block.get("ru")
                    or block.get("translate")
                    or block.get("translation")
                    or block.get("meaning")
                    or ""
                ).strip()
                if src and dst:
                    words.append(f"{src} — {dst}")
                elif src or dst:
                    words.append(src or dst)

        packs.append((pack_name, words))

    return packs


@router.callback_query(F.data.startswith("adm:topic_view:vocab:"))
async def admin_topic_view_vocab(cb: CallbackQuery, state: FSMContext):
    try:
        st = await state.get_state()
        logging.info(
            "[addtopic.lex.debug] topic_view_vocab user_id=%s cb_data=%r state=%s",
            getattr(getattr(cb, "from_user", None), "id", None),
            cb.data,
            st,
        )
        topic_data, _ = await _admin_load_topic_from_disk(state)
        if not topic_data:
            await cb.answer("Сначала открой карточку темы", show_alert=False)
            return

        packs = _adm_vocab_packs(topic_data)
        body: list[str] = []
        for idx, (pack_name, words) in enumerate(packs, start=1):
            if body:
                body.append("")
            body.append(f"Пак {idx}: {pack_name}")
            body.append("")
            body.extend(words or ["пока нет слов"])

        if not body:
            body = ["Словарь пуст"]

        await _adm_topic_view_render(cb, state, "📚 Словарь", body)
        logging.info("[addtopic.lex.debug] topic_view_vocab handled ok user_id=%s", getattr(getattr(cb, "from_user", None), "id", None))
    except Exception as e:
        logging.exception("[addtopic.lex.debug] topic_view_vocab failed: %s", e)
        await cb.answer("Не удалось открыть словарь. Попробуй ещё раз.", show_alert=False)


@router.callback_query(F.data.startswith("adm:topic_view:videos:"))
async def admin_topic_view_videos(cb: CallbackQuery, state: FSMContext):
    try:
        st = await state.get_state()
        logging.info(
            "[addtopic.lex.debug] topic_view_videos user_id=%s cb_data=%r state=%s",
            getattr(getattr(cb, "from_user", None), "id", None),
            cb.data,
            st,
        )
        topic_data, _ = await _admin_load_topic_from_disk(state)
        if not topic_data:
            await cb.answer("Сначала открой карточку темы", show_alert=False)
            return

        videos = topic_data.get("videos") if isinstance(topic_data, dict) else []
        body: list[str] = []
        if isinstance(videos, list):
            for video in videos:
                if isinstance(video, dict):
                    link = str(video.get("link") or video.get("url") or "").strip()
                    if link:
                        body.append(link)
                else:
                    txt = str(video).strip()
                    if txt:
                        body.append(txt)

        if not body:
            body = ["Видео пока нет"]

        await _adm_topic_view_render(cb, state, "🎥 Видео", body)
        logging.info("[addtopic.lex.debug] topic_view_videos handled ok user_id=%s", getattr(getattr(cb, "from_user", None), "id", None))
    except Exception as e:
        logging.exception("[addtopic.lex.debug] topic_view_videos failed: %s", e)
        await cb.answer("Не удалось открыть видео. Попробуй ещё раз.", show_alert=False)


def _adm_reading_items(topic_data: dict) -> list:
    # 💬 поддерживаем разные схемы: reading/list, reading_packs/list, одиночный reading-dict
    reading_raw = topic_data.get("reading")
    if isinstance(reading_raw, list):
        return reading_raw
    if isinstance(reading_raw, dict):
        return [reading_raw]

    packs = topic_data.get("reading_packs")
    if isinstance(packs, list):
        return packs
    if isinstance(packs, dict):
        return [packs]
    return []


def _adm_reading_pack_to_lines(pack, idx: int) -> list[str]:
    if isinstance(pack, str):
        val = pack.strip()
        return [f"Reading {idx}:", val if val else "пока нет"]

    if not isinstance(pack, dict):
        return [f"Reading {idx}:", "пока нет"]

    title = str(pack.get("title") or pack.get("name") or f"Reading {idx}").strip()
    lines = [f"Название: {title}"]

    txt = str(pack.get("text") or "").strip()
    if txt:
        lines.append(txt)

    fragments = pack.get("fragments")
    if isinstance(fragments, list):
        for frag in fragments:
            if isinstance(frag, dict):
                es = str(frag.get("es") or frag.get("text") or "").strip()
                ru = str(frag.get("ru") or frag.get("translate") or frag.get("translation") or "").strip()
                if es and ru:
                    lines.append(es)
                    lines.append(ru)
                    lines.append("")
                elif es or ru:
                    lines.append(es or ru)
            else:
                frag_txt = str(frag).strip()
                if frag_txt:
                    lines.append(frag_txt)
    elif isinstance(fragments, str) and fragments.strip():
        lines.append(fragments.strip())

    dialogs = pack.get("dialogs")
    if isinstance(dialogs, list):
        for row in dialogs:
            if not isinstance(row, dict):
                txt = str(row).strip()
                if txt:
                    lines.append(txt)
                continue
            es = str(row.get("es") or row.get("text") or "").strip()
            ru = str(row.get("ru") or row.get("translate") or row.get("translation") or "").strip()
            if es:
                lines.append(es)
            if ru:
                lines.append(ru)
            if es or ru:
                lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()

    if len(lines) == 1:
        lines.append("пока нет")
    return lines


async def _adm_topic_view_render(cb: CallbackQuery, state: FSMContext, heading: str, body_lines: list[str]):
    text = f"{heading}\n```\n" + "\n".join(body_lines or ["пока нет"]) + "\n```"
    kb = _ikb([
        [("⬅️ Назад к просмотру", "adm:topic_preview")],
        [("⬅️ К карточке темы", "adm:topic_card"), ("⬅️ Закрыть", "adm:close")],
    ])
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest:
        try:
            await cb.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data == "adm:topic_view:vocab")
async def admin_topic_view_vocab(cb: CallbackQuery, state: FSMContext):
    topic_data, _ = await _admin_load_topic_from_disk(state)
    phases = topic_data.get("vocab") if isinstance(topic_data, dict) else []
    body = []

    if isinstance(phases, list):
        for p_idx, ph in enumerate(phases, start=1):
            if isinstance(ph, dict):
                items = ph.get("vocab") or ph.get("phrases") or []
                if not isinstance(items, list):
                    items = [items]
            else:
                items = [ph]

            rendered_items = [str(x).strip() for x in items if str(x).strip()]
            line = "; ".join(rendered_items) if rendered_items else "пока нет"
            body.append(f"Phase {p_idx}: {line}")

    if not body:
        body = ["пока нет"]

    await _adm_topic_view_render(cb, state, "📚 Словарь", body)


@router.callback_query(F.data == "adm:topic_view:videos")
async def admin_topic_view_videos(cb: CallbackQuery, state: FSMContext):
    topic_data, _ = await _admin_load_topic_from_disk(state)
    videos = topic_data.get("videos") if isinstance(topic_data, dict) else []
    body = []

    if isinstance(videos, list):
        for video in videos:
            if isinstance(video, dict):
                link = str(video.get("link") or video.get("url") or "").strip()
                if link:
                    body.append(link)
            else:
                txt = str(video).strip()
                if txt:
                    body.append(txt)

    if not body:
        body = ["пока нет"]

    await _adm_topic_view_render(cb, state, "🎥 Видео", body)


@router.callback_query(F.data == "adm:topic_view:read")
async def admin_topic_view_read(cb: CallbackQuery, state: FSMContext):
    topic_data, _ = await _admin_load_topic_from_disk(state)
    body = []
    for idx, pack in enumerate(_adm_reading_items(topic_data if isinstance(topic_data, dict) else {}), start=1):
        if body:
            body.append("")
        body.extend(_adm_reading_pack_to_lines(pack, idx))

    if not body:
        body = ["пока нет"]

    await _adm_topic_view_render(cb, state, "📖 Читать", body)


@router.callback_query(F.data.startswith("adm:topic_view:read:"))
async def admin_topic_view_read_tid(cb: CallbackQuery, state: FSMContext):
    try:
        st = await state.get_state()
        logging.info(
            "[addtopic.lex.debug] topic_view_read user_id=%s cb_data=%r state=%s",
            getattr(getattr(cb, "from_user", None), "id", None),
            cb.data,
            st,
        )
        topic_data, _ = await _admin_load_topic_from_disk(state)
        if not topic_data:
            await cb.answer("Сначала открой карточку темы", show_alert=False)
            return

        body = []
        for idx, pack in enumerate(_adm_reading_items(topic_data if isinstance(topic_data, dict) else {}), start=1):
            if body:
                body.append("")
            body.extend(_adm_reading_pack_to_lines(pack, idx))

        if not body:
            body = ["Читать пока нечего"]

        await _adm_topic_view_render(cb, state, "📖 Читать", body)
        logging.info("[addtopic.lex.debug] topic_view_read handled ok user_id=%s", getattr(getattr(cb, "from_user", None), "id", None))
    except Exception as e:
        logging.exception("[addtopic.lex.debug] topic_view_read failed: %s", e)
        await cb.answer("Не удалось открыть раздел «Читать». Попробуй ещё раз.", show_alert=False)


@router.callback_query(F.data.startswith("adm:topic_view:back:"))
async def admin_topic_view_back(cb: CallbackQuery, state: FSMContext):
    tid = (cb.data or "").split("adm:topic_view:back:", 1)[1].strip()
    await _admin_show_topic_view_menu(cb, state, tid)


@router.callback_query(F.data == "adm:topic_view:back")
async def admin_topic_view_back_plain(cb: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""
    if not tid:
        await cb.answer("Тема не выбрана", show_alert=True)
        return
    await _admin_show_topic_view_menu(cb, state, tid)


@router.callback_query(F.data == "adm:topic_edit")
async def admin_topic_edit(cb: CallbackQuery, state: FSMContext):
    # 💬 Единый inline-редактор: Действие -> Раздел -> Данные -> Индекс
    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await cb.answer("❌ Тема не загружена", show_alert=True)
        return

    # 💬 синхронизируем FSM, чтобы message-хендлеры работали без рассинхрона
    await state.update_data(topic=topic_data, topic_path=topic_path)

    # 💬 сбрасываем контекст редактирования
    await state.update_data(
        **{
            ADMIN_EDIT_VIEW_KEY: "edit_actions",
            ADMIN_PENDING_ACTION_KEY: None,          # insert | delete
            ADMIN_EDIT_SCOPE_KEY: None,              # vocab | dialogs | videos | reading | translate | exercises
            ADMIN_PENDING_INSERT_KIND_KEY: None,     # phase_vocab | phase_dialog | video | pack | exercise
            ADMIN_PENDING_INSERT_PAYLOAD_KEY: None,  # dict
        }
    )

    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""
    title = str(topic_data.get("visible_title") or topic_data.get("name") or tid).strip()

    kb = _ikb(
        [
            [("➕ Добавить", "adm:edit_action:insert"), ("🗑 Удалить", "adm:edit_action:delete")],
            [("👁 Просмотр", "adm:topic_preview")],
            [("⬅️ К карточке темы", "adm:topic_card")],
            [("⬅️ К списку тем", "adm:topics"), ("⬅️ Закрыть", "adm:close")],
        ]
    )

    await _inline_replace(
        cb,
        state,
        f"✏️ Редактирование: <b>{_preview_text(title, 80)}</b>\n\nЧто сделать?",
        kb,
    )
    await cb.answer()


def _adm_scope_buttons(topic_data: dict) -> list:
    # 💬 что делает эта часть: единый список разделов для inline-редактирования (без «диалогов»)
    category_now = ((topic_data.get("category") or "").strip().lower())

    if category_now == "gram":
        return [
            ("📖 Теория", "theory", "pack"),
            ("📝 Практика", "practice", "pack"),
            ("🎥 Видео", "videos", "video"),
            ("📚 Читать", "reading", "pack"),
        ]

    return [
        ("📚 Словарь", "vocab", "phase_vocab"),
        ("🧩 Упражнения", "exercises", "exercise"),
        ("🎥 Видео", "videos", "video"),
        ("📚 Читать", "reading", "pack"),
        ("📝 Переводить", "translate", "pack"),
    ]


def _adm_nav_kb(back_cb: str) -> InlineKeyboardMarkup:
    return _ikb(
        [
            [("⬅️ Назад", back_cb)],
            [("🏠 В меню редактирования", "adm:edit_actions")],
            [("⬅️ К карточке темы", "adm:topic_card"), ("⬅️ Закрыть", "adm:close")],
        ]
    )


async def _adm_show_sections_cb(cb: CallbackQuery, state: FSMContext):
    # 💬 Экран выбора раздела по текущему действию insert/delete
    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await cb.answer("❌ Тема не загружена", show_alert=True)
        return

    await state.update_data(topic=topic_data, topic_path=topic_path, **{ADMIN_EDIT_VIEW_KEY: "edit_sections"})

    data = await state.get_data()
    action = data.get(ADMIN_PENDING_ACTION_KEY) or "insert"

    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""
    title = str(topic_data.get("visible_title") or topic_data.get("name") or tid).strip()

    header = "➕ Добавление" if action == "insert" else "🗑 Удаление"

    rows = []
    for label, scope, _kind in _adm_scope_buttons(topic_data):
        rows.append([(label, f"adm:edit_scope:{scope}")])

    rows.append([("⬅️ Назад", "adm:edit_actions")])
    rows.append([("⬅️ К карточке темы", "adm:topic_card"), ("⬅️ Закрыть", "adm:close")])

    await _inline_replace(
        cb,
        state,
        f"{header}: <b>{_preview_text(title, 80)}</b>\n\nВыберите раздел:",
        _ikb(rows),
    )
    await cb.answer()


async def _adm_show_actions_msg(message: Message, state: FSMContext, note_text: str = ""):
    # 💬 Возврат к меню редактирования через сохранённый inline-msg
    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await message.answer("❌ Тема не загружена")
        return

    await state.update_data(topic=topic_data, topic_path=topic_path)
    await state.set_state(None)

    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""
    title = str(topic_data.get("visible_title") or topic_data.get("name") or tid).strip()

    text = f"✏️ Редактирование: <b>{_preview_text(title, 80)}</b>\n\nЧто сделать?"
    if note_text:
        text = f"{note_text}\n\n{text}"

    kb = _ikb(
        [
            [("➕ Добавить", "adm:edit_action:insert"), ("🗑 Удалить", "adm:edit_action:delete")],
            [("👁 Просмотр", "adm:topic_preview")],
            [("⬅️ К карточке темы", "adm:topic_card")],
            [("⬅️ К списку тем", "adm:topics"), ("⬅️ Закрыть", "adm:close")],
        ]
    )

    await _inline_edit_by_id(message, state, text, kb)


async def _adm_show_sections_msg(message: Message, state: FSMContext):
    # 💬 Возврат к меню разделов через сохранённый inline-msg
    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await message.answer("❌ Тема не загружена")
        return

    await state.update_data(topic=topic_data, topic_path=topic_path, **{ADMIN_EDIT_VIEW_KEY: "edit_sections"})
    data = await state.get_data()
    action = data.get(ADMIN_PENDING_ACTION_KEY) or "insert"

    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY) or ""
    title = str(topic_data.get("visible_title") or topic_data.get("name") or tid).strip()

    header = "➕ Добавление" if action == "insert" else "🗑 Удаление"

    rows = []
    for label, scope, _kind in _adm_scope_buttons(topic_data):
        rows.append([(label, f"adm:edit_scope:{scope}")])

    rows.append([("⬅️ Назад", "adm:edit_actions")])
    rows.append([("⬅️ К карточке темы", "adm:topic_card"), ("⬅️ Закрыть", "adm:close")])

    await _inline_edit_by_id(
        message,
        state,
        f"{header}: <b>{_preview_text(title, 80)}</b>\n\nВыберите раздел:",
        _ikb(rows),
    )


@router.callback_query(F.data == "adm:edit_actions")
async def admin_edit_actions(cb: CallbackQuery, state: FSMContext):
    # 💬 Возврат к экрану действий
    await admin_topic_edit(cb, state)


@router.callback_query(F.data == "adm:edit_sections")
async def admin_edit_sections(cb: CallbackQuery, state: FSMContext):
    # 💬 Возврат к экрану разделов
    await _adm_show_sections_cb(cb, state)


@router.callback_query(F.data == "adm:edit_action:insert")
async def admin_edit_action_insert(cb: CallbackQuery, state: FSMContext):
    # 💬 Действие insert
    await state.update_data(**{ADMIN_PENDING_ACTION_KEY: "insert"})
    await _adm_show_sections_cb(cb, state)


@router.callback_query(F.data == "adm:edit_action:delete")
async def admin_edit_action_delete(cb: CallbackQuery, state: FSMContext):
    # 💬 Действие delete
    await state.update_data(**{ADMIN_PENDING_ACTION_KEY: "delete"})
    await _adm_show_sections_cb(cb, state)



@router.callback_query(F.data.startswith("adm:edit_scope:"))  # 💬 используем общий router, чтобы не падало на импорте
async def admin_edit_scope(cb: CallbackQuery, state: FSMContext):
    # 💬 что делает эта часть: выбираем раздел и переводим в ввод (add/delete) через inline
    ui_scope = cb.data.split("adm:edit_scope:", 1)[1].strip()

    data = await state.get_data()
    action = (data.get(ADMIN_PENDING_ACTION_KEY) or "insert").strip()

    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await cb.answer("❗ Не нашёл файл темы", show_alert=True)
        return

    # 💬 алиас: если старая тема хранит packs в translation, не плодим второй ключ
    scope = ui_scope
    if ui_scope == "translate" and "translate" not in topic_data and isinstance(topic_data.get("translation"), list):
        scope = "translation"

    # 💬 подтягиваем label и kind из _adm_scope_buttons
    label = "Раздел"
    kind = "pack"
    for lb, sc, kd in _adm_scope_buttons(topic_data):
        if sc == ui_scope:
            label, kind = lb, kd
            break

    await state.update_data(
        **{
            ADMIN_EDIT_SCOPE_KEY: scope,
            ADMIN_PENDING_INSERT_KIND_KEY: kind,
            "admin_selected_label": label,
        }
    )

    nav_kb = _adm_nav_kb("adm:edit_sections")

    if action == "delete":
        items = topic_data.get(scope) or []
        if not isinstance(items, list) or not items:
            await cb.answer("Нечего удалять", show_alert=True)
            return

        max_idx_user = len(items)
        await state.set_state(AdminInlineEditStates.waiting_delete_index)

        text = (
            f"🗑 Удаление: <b>{label}</b>\n"
            f"Тема: <b>{topic_data.get('name', '')}</b>\n\n"
            f"Введите индекс (1..{max_idx_user})\n"
            f"или напиши Отмена"
        )
        await _inline_replace(cb, state, text, nav_kb)
        await cb.answer()
        return

    # 💬 default: insert
    await state.set_state(AdminInlineEditStates.waiting_insert_payload)

    if kind == "phase_vocab":
        hint = "Пришли название фазы\nили '-' для авто"
    elif kind == "video":
        hint = "Пришли 1 строку\nссылка или iframe"
    elif kind == "exercise":
        hint = "Пришли 2 строки\n1) название\n2) ссылка или iframe"
    else:
        hint = "Пришли название пака"

    text = (
        f"➕ Добавление: <b>{label}</b>\n"
        f"Тема: <b>{topic_data.get('name', '')}</b>\n\n"
        f"{hint}\n\n"
        f"или напиши Отмена"
    )
    await _inline_replace(cb, state, text, nav_kb)
    await cb.answer()

@router.message(AdminInlineEditStates.waiting_insert_payload)
async def admin_edit_waiting_insert_payload(message: Message, state: FSMContext):
    # 💬 принимает payload, считает пропуски, затем спрашивает индекс вставки (1-based)
    nav_kb = _adm_nav_kb("adm:edit_sections")

    payload_raw = (message.text or "").strip()
    if payload_raw.lower() in {"отмена", "cancel"}:
        await _adm_show_actions_msg(message, state)
        return

    data = await state.get_data()
    scope = data.get(ADMIN_EDIT_SCOPE_KEY)
    kind = data.get(ADMIN_PENDING_INSERT_KIND_KEY)

    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await _inline_edit_by_id(message, state, "❗ Ошибка: не найден файл темы", nav_kb)
        return

    if not scope or not kind:
        await _inline_edit_by_id(message, state, "❗ Ошибка: не выбран раздел", nav_kb)
        return

    category_now = ((topic_data.get("category") or "").strip().lower())

    lines = [l.strip() for l in payload_raw.splitlines() if l.strip()]
    skipped = 0
    new_item = None

    if kind == "phase_vocab":
        if not lines:
            await _inline_edit_by_id(message, state, "❌ Пусто. Пришли название фазы", nav_kb)
            return
        skipped = max(0, len(lines) - 1)
        name = lines[0] if lines[0] != "-" else ""
        new_item = {"phase_id": 0, "done": 0, "phase_name": name, "blocks": [], "vocab": []}
        if category_now != "gram":
            new_item.setdefault("phrases", [])

    elif kind == "video":
        if len(lines) < 1:
            await _inline_edit_by_id(message, state, "❌ Пришли ссылку или iframe", nav_kb)
            return

        items_now = topic_data.get(scope) or []
        if not isinstance(items_now, list):
            items_now = []

        if len(lines) >= 2:
            skipped = max(0, len(lines) - 2)
            new_item = {"title": lines[0], "link": _extract_src(lines[1])}
        else:
            skipped = max(0, len(lines) - 1)
            auto_title = f"Video {len(items_now) + 1}"
            new_item = {"title": auto_title, "link": _extract_src(lines[0])}


    elif kind == "exercise":
        if len(lines) < 2:
            await _inline_edit_by_id(message, state, "❌ Нужно 2 строки: название и ссылка или iframe", nav_kb)
            return
        skipped = max(0, len(lines) - 2)
        new_item = {"title": lines[0], "link": _extract_src(lines[1])}

    else:
        if not lines:
            await _inline_edit_by_id(message, state, "❌ Пусто. Пришли название пака", nav_kb)
            return
        skipped = max(0, len(lines) - 1)
        new_item = {"title": lines[0], "fragments": [], "assets": []}

    items = topic_data.get(scope) or []
    if not isinstance(items, list):
        items = []

    max_idx_user = max(1, len(items) + 1)

    await state.update_data(
        **{
            ADMIN_PENDING_INSERT_PAYLOAD_KEY: new_item,
            "adm_skipped_count": skipped,
        }
    )
    await state.set_state(AdminInlineEditStates.waiting_insert_index)

    section_label = data.get("admin_selected_label") or "Раздел"
    await _inline_edit_by_id(
        message,
        state,
        f"✅ Payload принят: <b>{section_label}</b>\n\n"
        f"Введите индекс (1..{max_idx_user})\n"
        f"или напиши Отмена",
        nav_kb,
    )

@router.message(AdminInlineEditStates.waiting_insert_index)
async def admin_edit_waiting_insert_index(message: Message, state: FSMContext):
    # 💬 вставляет элемент по индексу (1-based), сохраняет, показывает отчёт
    nav_kb = _adm_nav_kb("adm:edit_sections")

    idx_raw = (message.text or "").strip()
    if idx_raw.lower() in {"отмена", "cancel"}:
        await _adm_show_actions_msg(message, state)
        return

    try:
        insert_idx_user = int(idx_raw)
    except Exception:
        await _inline_edit_by_id(message, state, "❌ Индекс должен быть числом", nav_kb)
        return

    data = await state.get_data()
    scope = data.get(ADMIN_EDIT_SCOPE_KEY)
    new_item = data.get(ADMIN_PENDING_INSERT_PAYLOAD_KEY)

    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await _inline_edit_by_id(message, state, "❗ Ошибка: не найден файл темы", nav_kb)
        return

    if not scope or new_item is None:
        await _inline_edit_by_id(message, state, "❗ Ошибка: нет данных для вставки", nav_kb)
        return

    items = topic_data.get(scope) or []
    if not isinstance(items, list):
        items = []
        topic_data[scope] = items

    max_idx_user = max(1, len(items) + 1)
    if not (1 <= insert_idx_user <= max_idx_user):
        await _inline_edit_by_id(message, state, f"❌ Индекс должен быть 1..{max_idx_user}", nav_kb)
        return

    _insert_or_append(items, new_item, insert_idx_user)  # 💬 вставка по индексу

    if scope == "vocab":
        category_now = ((topic_data.get("category") or "").strip().lower())
        for i, ph in enumerate(items, start=1):
            ph["phase_id"] = i
            ph.setdefault("done", 0)
            ph.setdefault("blocks", [])
            ph.setdefault("vocab", [])
            if category_now != "gram":
                ph.setdefault("phrases", [])
            if not ph.get("phase_name"):
                ph["phase_name"] = f"📦 Пак слов {i}"

    topic_data[scope] = items
    atomic_save_json(topic_path, topic_data)  # 💬 моментально в Railway

    section_label = data.get("admin_selected_label") or "Раздел"
    skipped = int(data.get("adm_skipped_count") or 0)
    total_now = len(items)

    note_text = (
        f"✅ Сохранено: <b>{section_label}</b>\n"
        f"Добавлено: 1\n"
        f"Индекс: {insert_idx_user}\n"
        f"Всего в разделе: {total_now}\n"
        f"Пропущено: {skipped}"
    )

    await state.update_data(
        topic=topic_data,
        topic_path=topic_path,
        **{
            "adm_skipped_count": 0,
            ADMIN_PENDING_INSERT_PAYLOAD_KEY: None,
            ADMIN_PENDING_INSERT_KIND_KEY: None,
        },
    )
    await _adm_show_actions_msg(message, state, note_text=note_text)



@router.message(AdminInlineEditStates.waiting_delete_index)
async def admin_edit_waiting_delete_index(message: Message, state: FSMContext):
    # 💬 удаляет элемент по индексу (1-based), сохраняет, показывает отчёт
    nav_kb = _adm_nav_kb("adm:edit_sections")

    idx_raw = (message.text or "").strip()
    if idx_raw.lower() in {"отмена", "cancel"}:
        await _adm_show_actions_msg(message, state)
        return

    try:
        idx_user = int(idx_raw)
    except Exception:
        await _inline_edit_by_id(message, state, "❌ Индекс должен быть числом", nav_kb)
        return

    data = await state.get_data()
    scope = data.get(ADMIN_EDIT_SCOPE_KEY)

    topic_data, topic_path = await _admin_load_topic_from_disk(state)
    if not topic_data or not topic_path:
        await _inline_edit_by_id(message, state, "❗ Ошибка: не найден файл темы", nav_kb)
        return

    items = topic_data.get(scope) or []
    if not isinstance(items, list) or not items:
        await _inline_edit_by_id(message, state, "Нечего удалять", nav_kb)
        return

    max_idx_user = len(items)
    if not (1 <= idx_user <= max_idx_user):
        await _inline_edit_by_id(message, state, f"❌ Индекс должен быть 1..{max_idx_user}", nav_kb)
        return

    items.pop(idx_user - 1)

    if scope == "vocab":
        category_now = ((topic_data.get("category") or "").strip().lower())
        for i, ph in enumerate(items, start=1):
            ph["phase_id"] = i
            ph.setdefault("done", 0)
            ph.setdefault("blocks", [])
            ph.setdefault("vocab", [])
            if category_now != "gram":
                ph.setdefault("phrases", [])
            if not ph.get("phase_name"):
                ph["phase_name"] = f"📦 Пак слов {i}"

    topic_data[scope] = items
    atomic_save_json(topic_path, topic_data)  # 💬 моментально в Railway

    section_label = data.get("admin_selected_label") or "Раздел"
    total_now = len(items)

    note_text = (
        f"✅ Сохранено: <b>{section_label}</b>\n"
        f"Удалено: 1\n"
        f"Индекс: {idx_user}\n"
        f"Всего в разделе: {total_now}\n"
        f"Пропущено: 0"
    )

    await state.update_data(topic=topic_data, topic_path=topic_path)
    await _adm_show_actions_msg(message, state, note_text=note_text)




# ===========================
# ✅ Админ-inline редактор темы
# ===========================

async def _inline_edit_by_id(message: Message, state: FSMContext, text: str, kb: InlineKeyboardMarkup):
    # 💬 редактируем сохранённое inline-сообщение по message_id (когда ввод идёт обычным сообщением)
    st = await state.get_data()
    msg_id = st.get(ADMIN_INLINE_MSG_ID_KEY)
    if not msg_id:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=int(msg_id),
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


def _admin_is_gram(topic: dict) -> bool:
    # 💬 определяем, что тема относится к грамматике
    cat = str((topic or {}).get("category") or "").strip().lower()
    return cat.startswith("gram")


def _admin_clamp_page(total: int, page: int) -> tuple[int, int]:
    # 💬 ограничиваем номер страницы и возвращаем max_page
    if total <= 0:
        return 0, 0
    max_page = max(0, (total - 1) // ADMIN_PAGE_SIZE)
    page = max(0, min(int(page), max_page))
    return page, max_page


def _admin_page_slice(items: list, page: int) -> tuple[list, int]:
    # 💬 берём срез списка под текущую страницу
    start = page * ADMIN_PAGE_SIZE
    return items[start:start + ADMIN_PAGE_SIZE], start


def _admin_preview_reading_fragment(item: dict) -> str:
    # 💬 короткое превью фрагмента чтения (es + ru)
    if not isinstance(item, dict):
        return "фрагмент"
    es = str(item.get("es") or "").strip()
    ru = str(item.get("ru") or "").strip()
    if es and ru:
        return f"🧩 {_preview_text(es, 34)} | {_preview_text(ru, 34)}"
    if es:
        return f"🧩 {_preview_text(es, 48)}"
    return "🧩 фрагмент"


async def _admin_load_topic_from_disk(state: FSMContext) -> tuple[dict, str | None]:
    # 💬 всегда читаем тему с диска, чтобы правки были актуальны
    st = await state.get_data()
    topic_path = st.get("topic_path")
    if not topic_path:
        return {}, None
    try:
        with open(topic_path, "r", encoding="utf-8") as f:
            return (json.load(f) or {}), topic_path
    except Exception:
        return {}, topic_path


async def _admin_save_topic_to_disk(state: FSMContext, topic: dict, topic_path: str) -> bool:
    # 💬 атомарно сохраняем тему и обновляем FSM data
    ok = atomic_save_json(topic_path, topic)
    if ok:
        await state.update_data(topic=topic)  # 💬 держим актуальную тему в FSM
    return ok


async def _admin_try_reload_topics_cache():
    # 💬 пробуем обновить кэш тем в core (если он есть), чтобы не требовался рестарт
    try:
        import core8_1  # type: ignore
        if hasattr(core8_1, "load_topics"):
            new_topics = core8_1.load_topics()
            if hasattr(core8_1, "topics"):
                core8_1.topics = new_topics
            if hasattr(core8_1, "TOPICS"):
                core8_1.TOPICS = new_topics
    except Exception:
        pass


def _admin_kb_footer(back_cb: str) -> list[list[tuple[str, str]]]:
    # 💬 общий футер меню (назад + домой + закрыть)
    return [
        [("⬅️ Назад", back_cb)],
        [("⬅️ К списку тем", "adm:topics")],
        [("🏠 В меню /addtopic", "adm:home")],
        [("⬅️ Закрыть", "adm:close")],
    ]


async def _admin_show_topic_card(cb: CallbackQuery, state: FSMContext):
    # 💬 рисуем карточку темы снова
    st = await state.get_data()
    tid = st.get(ADMIN_CURRENT_TID_KEY)
    topic, _ = await _admin_load_topic_from_disk(state)
    if not tid:
        await cb.answer("Нет открытой темы", show_alert=True)
        return
    title = topic.get("visible_title") or topic.get("name") or "тема"
    kb = _admin_topic_card_kb(tid)
    await state.update_data(**{ADMIN_EDIT_VIEW_KEY: "topic_card"})
    await _inline_replace(cb, state, f"✅ Открыта тема: <b>{_preview_text(str(title), 80)}</b>\nЧто сделать?", kb)
    await cb.answer()


def _admin_render_preview_text(topic_data: dict) -> str:
    # 💬 компактный предпросмотр структуры темы
    title = topic_data.get("visible_title") or topic_data.get("name") or "тема"
    level = topic_data.get("level") or "-"
    category = topic_data.get("category") or "-"
    phases = topic_data.get("vocab") or []
    exercises = topic_data.get("exercises") or []
    videos = topic_data.get("videos") or []
    reading = topic_data.get("reading") or []
    is_lex = str(category).strip().lower() in {"lex", "lexics", "lexic", "vocab", "лексика"}

    lines = [
        f"👁 <b>{_preview_text(str(title), 90)}</b>",
        f"Категория: <b>{_preview_text(str(category), 30)}</b>",
        f"Уровень: <b>{_preview_text(str(level), 12)}</b>",
        "",
    ]

    if is_lex:
        lines += [
            f"📘 Словарь (паков): <b>{len(phases)}</b>",
            f"🎥 Видео (ссылки): <b>{len(videos)}</b>",
            f"📚 Читать (паки): <b>{len(reading)}</b>",
        ]
    else:
        lines += [
            f"📖 Теория (фазы): <b>{len(phases)}</b>",
            f"📝 Практика (блоки): <b>{len(exercises)}</b>",
            f"🎥 Видео (ссылки): <b>{len(videos)}</b>",
            f"📚 Читать (паки): <b>{len(reading)}</b>",
        ]

    return "\n".join(lines)




def _admin_render_topic_view_section(topic_data: dict, section: str) -> str:
    # 💬 текст для экранов просмотра разделов темы
    title = topic_data.get("visible_title") or topic_data.get("name") or "тема"

    if section == "vocab":
        phases = topic_data.get("vocab") or []
        lines = [
            f"📘 <b>Словарь: {_preview_text(str(title), 80)}</b>",
            f"Фаз: <b>{len(phases)}</b>",
            "",
        ]
        if not phases:
            lines.append("Пока пусто.")
            return "\n".join(lines)

        for idx, phase in enumerate(phases, start=1):
            phase_name = _preview_text(str((phase or {}).get("phase_name") or f"Фаза {idx}"), 60)
            vocab_count = len((phase or {}).get("vocab") or [])
            blocks_count = len((phase or {}).get("blocks") or [])
            lines.append(f"{idx}. <b>{phase_name}</b> — vocab: {vocab_count}, blocks: {blocks_count}")
        return "\n".join(lines)

    if section == "videos":
        videos = topic_data.get("videos") or []
        lines = [
            f"🎥 <b>Видео: {_preview_text(str(title), 80)}</b>",
            f"Ссылок: <b>{len(videos)}</b>",
            "",
        ]
        if not videos:
            lines.append("Пока пусто.")
            return "\n".join(lines)

        for idx, video in enumerate(videos, start=1):
            if isinstance(video, dict):
                v_title = _preview_text(str(video.get("title") or f"Видео {idx}"), 60)
                v_link = _preview_text(str(video.get("url") or video.get("link") or "—"), 70)
                lines.append(f"{idx}. <b>{v_title}</b>\n   🔗 {v_link}")
            else:
                lines.append(f"{idx}. {_preview_text(str(video), 70)}")
        return "\n".join(lines)

    reading = topic_data.get("reading") or []
    lines = [
        f"📖 <b>Читать: {_preview_text(str(title), 80)}</b>",
        f"Паков: <b>{len(reading)}</b>",
        "",
    ]
    if not reading:
        lines.append("Пока пусто.")
        return "\n".join(lines)

    for idx, pack in enumerate(reading, start=1):
        pack_title = _preview_text(str((pack or {}).get("title") or f"Пак {idx}"), 60)
        fragments_count = len((pack or {}).get("fragments") or [])
        assets_count = len((pack or {}).get("assets") or [])
        lines.append(f"{idx}. <b>{pack_title}</b> — фрагменты: {fragments_count}, медиа: {assets_count}")
    return "\n".join(lines)
async def _admin_show_sections(cb: CallbackQuery, state: FSMContext):
    # 💬 меню выбора раздела
    topic, _ = await _admin_load_topic_from_disk(state)
    if not _admin_is_gram(topic):
        kb = _ikb(_admin_kb_footer("adm:topic_card"))
        await _inline_replace(cb, state, "⚠️ Редактор тут включён только для грамматики.", kb)
        await cb.answer()
        return
    kb = _ikb([
        [("📖 Теория", "adm:edit:theory"), ("📝 Практика", "adm:edit:practice")],
        [("🎥 Видео", "adm:edit:video"), ("📚 Читать", "adm:edit:reading")],
        [("⬅️ К теме", "adm:topic_card")],
        [("⬅️ К списку тем", "adm:topics")],
        [("🏠 В меню /addtopic", "adm:home")],
        [("⬅️ Закрыть", "adm:close")],
    ])
    await state.update_data(**{ADMIN_EDIT_VIEW_KEY: "edit_sections"})
    await _inline_replace(cb, state, "✏️ Редактирование\nВыбери раздел:", kb)
    await cb.answer()

# --- дальше идёт: теория фазы, теория элементы, практика, видео, чтение (паки, фрагменты, картинки)
# --- операции: удалить индекс, вставить (с типами), переместить, очистить
# --- FSM ввод: phase_name, reading_title, delete_index, move_from/to, insert_payload, insert_index
# --- пагинация кнопками: "⬅️ Назад" и "Еще"

# ВАЖНО: этот блок большой
# чтобы не перегружать ответ, я продолжу ровно тем же блоком в следующем сообщении
# и дам его целиком одним куском, без пропусков



@router.callback_query(F.data == "adm:topics")
async def admin_topics_list(cb: CallbackQuery, state: FSMContext):
    # 💬 возвращаемся к списку тем в том же сообщении (с учётом фильтра, если он есть)
    st = await state.get_data()

    category = st.get(ADMIN_EDIT_CATEGORY_KEY) or ((st.get("topic") or {}).get("category"))
    level = st.get(ADMIN_EDIT_LEVEL_KEY) or st.get("topic_level") or ((st.get("topic") or {}).get("level"))

    topic_map_all, files = _load_topics_index()
    show_files = files
    titles = {}

    if category and level:
        topics_dir = get_topics_dir()
        filtered = []

        for name in files:
            path = topics_dir / f"{name}.json"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    topic_data = json.load(f) or {}
            except Exception:
                continue

            if topic_data.get("category") != category:
                continue
            if topic_data.get("level") != level:
                continue

            filtered.append(name)
            titles[name] = topic_data.get("visible_title") or topic_data.get("name") or name

        show_files = filtered
        topic_map = {_make_tid(n): n for n in filtered}
        await state.update_data(**{
            ADMIN_EDIT_MODE_KEY: True,
            ADMIN_EDIT_CATEGORY_KEY: category,
            ADMIN_EDIT_LEVEL_KEY: level,
            ADMIN_TOPIC_MAP_KEY: topic_map
        })
    else:
        await state.update_data(**{ADMIN_TOPIC_MAP_KEY: topic_map_all})

    if not show_files:
        kb = _ikb([
            [("🏠 В меню /addtopic", "adm:home")],
            [("⬅️ Закрыть", "adm:close")]
        ])
        await _inline_replace(cb, state, "⚠️ Нет тем для выбранной категории или уровня.", kb)
        await cb.answer()
        return

    rows = []
    for name in show_files[:30]:
        tid = _make_tid(name)
        label = titles.get(name) or name
        rows.append([(label, f"adm:topic:{tid}")])

    rows.append([("🏠 В меню /addtopic", "adm:home")])
    rows.append([("⬅️ Закрыть", "adm:close")])

    cat_label = ""
    if category:
        cat_label = "Лексика" if category == "lex" else "Грамматика"

    header = "✏️ <b>Редактировать темы</b>\nВыбери тему:"
    if category and level and cat_label:
        header = f"✏️ <b>Редактировать темы</b>\nКатегория: {cat_label} | Уровень: {level}\nВыбери тему:"

    kb = _ikb(rows)
    await _inline_replace(cb, state, header, kb)
    await cb.answer()

@router.callback_query(F.data.startswith("adm:topic_del:"))
async def admin_delete_topic_ask(cb: CallbackQuery, state: FSMContext):
    # 💬 подтверждение удаления
    tid = (cb.data or "").split("adm:topic_del:", 1)[1].strip()

    st = await state.get_data()
    topic_map = st.get(ADMIN_TOPIC_MAP_KEY) or {}
    name = topic_map.get(tid)

    title = ""
    topic = st.get("topic") or {}
    if topic:
        title = topic.get("visible_title") or topic.get("name") or ""

    if not name:
        await cb.answer("Тема не найдена", show_alert=True)
        return

    shown = title or name
    kb = _ikb([
        [("✅ Удалить", f"adm:topic_del_ok:{tid}"), ("🚫 Отмена", f"adm:topic:{tid}")],
        [("⬅️ К списку тем", "adm:topics")],
        [("🏠 В меню /addtopic", "adm:home")],  # 💬 выход без тупика
        [("⬅️ Закрыть", "adm:close")],
    ])

    await _inline_replace(cb, state, f"🗑 Удалить тему: <b>{shown}</b>\nПодтверди действие.", kb)
    await cb.answer()

@router.callback_query(F.data.startswith("adm:topic_del_ok:"))
async def admin_delete_topic_do(cb: CallbackQuery, state: FSMContext):
    # 💬 удаляем файл темы из /data/topics и возвращаемся в список
    tid = (cb.data or "").split("adm:topic_del_ok:", 1)[1].strip()

    st = await state.get_data()
    topic_map = st.get(ADMIN_TOPIC_MAP_KEY) or {}
    name = topic_map.get(tid)

    if not name:
        await cb.answer("Тема не найдена", show_alert=True)
        return

    topics_dir = get_topics_dir()
    path = topics_dir / f"{name}.json"
    if not path.exists():
        await cb.answer("Файл уже отсутствует", show_alert=True)
        return
    if not _is_railway_topics_file(path):
        # 💬 запрещаем удаление вне RailwayData (/data/topics)
        await cb.answer("Удаление разрешено только для /data/topics", show_alert=True)
        return


    try:
        os.remove(path)
    except Exception:
        logging.exception("admin_delete_topic_do: cannot remove %s", path)
        await cb.answer("Не смог удалить файл", show_alert=True)
        return

    # 💬 после удаления сразу обновляем индекс и показываем список тем
    topic_map, files = _load_topics_index()
    await state.clear()
    await state.update_data(
        **{ADMIN_TOPIC_MAP_KEY: topic_map},
        **{ADMIN_INLINE_MSG_ID_KEY: cb.message.message_id},
    )

    if not files:
        kb = _ikb([
            [("🏠 В меню /addtopic", "adm:home")],  # 💬 выход из админки
            [("⬅️ Закрыть", "adm:close")]
        ])

        await _inline_replace(cb, state, "✅ Тема удалена.\nТем больше нет.", kb)
        await cb.answer()
        return

    rows = []
    for nm in files[:30]:
        t = _make_tid(nm)
        rows.append([(nm, f"adm:topic:{t}")])
        
    rows.append([("🏠 В меню /addtopic", "adm:home")])
    rows.append([("⬅️ Закрыть", "adm:close")])

    kb = _ikb(rows)
    await _inline_replace(cb, state, "✅ Тема удалена.\nВыбери следующую тему:", kb)
    await cb.answer()



@router.message(NewTopicStates.waiting_edit_topic_choice)
async def handle_edit_topic_choice(message: Message, state: FSMContext):
    # 💬 что делает эта часть: открываем существующую тему из /data/topics и переходим в главное меню редактирования
    name = (message.text or "").strip()

    if name == "🚫 Отмена":
        return await start_adding_topic(message, state)

    topics_dir = get_topics_dir()  # 💬 что делает эта часть: читаем темы из Volume (/data/topics)
    path = topics_dir / f"{name}.json"

    if not exists:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚫 Отмена")]],
            resize_keyboard=True
        )
        await message.answer(
            "⚠️ Тема не найдена.\nНажми «🚫 Отмена».",  # 💬 даём реальную кнопку выхода, без тупика
            reply_markup=kb
        )
        return


    try:
        with open(path, "r", encoding="utf-8") as f:
            topic_data = json.load(f) or {}
    except Exception:
        await message.answer("⚠️ Не смог прочитать файл темы. Проверь JSON.")
        return

    await state.clear()  # 💬 что делает эта часть: начинаем редактирование как чистый flow
    await state.update_data(
        topic=topic_data,
        topic_path=str(path),  # 💬 что делает эта часть: дальше все сохранения будут идти в этот же файл
        topic_level=topic_data.get("level"),
    )

    category = topic_data.get("category")
    keyboard = get_main_menu(category)  # 💬 что делает эта часть: для gram покажем Теория/Практика/Видео/Читать
    # 💬 добавляем кнопку удаления темы в меню редактирования
    if keyboard and hasattr(keyboard, "keyboard"):
        keyboard.keyboard.append([KeyboardButton(text="🗑 Удалить тему")])

    title = topic_data.get("name") or name

    await message.answer(f"✏️ Редактируем тему: <b>{title}</b>", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_first_choice)



@router.message(NewTopicStates.adding_category)
async def get_level_for_topic(message: Message, state: FSMContext):
    raw = (message.text or "").strip()

    # «Назад» — возвращаемся к выбору категории
    if raw == "⬅️ Назад":
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📚 Лексика")]],
            resize_keyboard=True
        )
        await message.answer("📂 Выбери КАТЕГОРИЮ темы:", reply_markup=kb)
        return await state.set_state(NewTopicStates.waiting_category)

    # Нормализация: кнопка с эмодзи -> чистое значение уровня
    level = LEVEL_FROM_BUTTON.get(raw, raw)

    # 💬 что делает эта часть: приводим "B1"/"B2"/"B1/B2" к единому формату "B1-B2" (и так же для A1/A2)
    _lvl = str(level).strip().upper().replace("–", "-").replace("—", "-")
    _lvl = _lvl.replace(" ", "")
    if _lvl in ("A1", "A2", "A1/A2", "A1A2"):
        level = "A1-A2"
    elif _lvl in ("B1", "B2", "B1/B2", "B1B2"):
        level = "B1-B2"
    elif _lvl == "C1":
        level = "C1"
    elif _lvl == "A0":
        level = "A0"


    if level == "A0":
        data_tmp = await state.get_data()
        category_tmp = (data_tmp.get("topic") or {}).get("category")

        if category_tmp == "gram":
            await message.answer(
                "⚠️ Для грамматики уровень «Новичок» не используется.\n"
                "Выбери Начальный, Средний или Продвинутый."
            )
            return  # 💬 блокируем создание грамматики на A0


    if level not in ALLOWED_LEVELS:
        await message.answer("❗ Выбери корректный уровень из кнопок ниже.")
        return

    await state.update_data(topic_level=level)
    # 💬 что делает эта часть: сохраняем 'A0' / 'A1-A2' / 'B1-B2' / 'C1' в state, без эмодзи

    st = await state.get_data()
    if st.get(ADMIN_EDIT_MODE_KEY):
        category = (st.get("topic") or {}).get("category") or st.get(ADMIN_EDIT_CATEGORY_KEY)
        await state.update_data(**{ADMIN_EDIT_CATEGORY_KEY: category, ADMIN_EDIT_LEVEL_KEY: level})  # 💬 фильтр списка тем

        topic_map_all, files = _load_topics_index()
        topics_dir = get_topics_dir()

        filtered = []
        titles = {}

        for name in files:
            path = topics_dir / f"{name}.json"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    topic_data = json.load(f) or {}
            except Exception:
                continue

            if topic_data.get("category") != category:
                continue
            if topic_data.get("level") != level:
                continue

            filtered.append(name)
            titles[name] = topic_data.get("visible_title") or topic_data.get("name") or name  # 💬 показываем человеко-читаемый тайтл

        topic_map = {_make_tid(n): n for n in filtered}
        await state.update_data(**{ADMIN_TOPIC_MAP_KEY: topic_map})

        if not filtered:
            await message.answer("⚠️ Нет тем для редактирования в выбранном уровне.\nНажми ⬅️ Назад и выбери другой уровень.")  # 💬 защита от пустого фильтра
            return

        cat_label = "Лексика" if category == "lex" else "Грамматика"

        rows = []
        for name in filtered[:30]:
            tid = _make_tid(name)
            label = titles.get(name) or name
            rows.append([(label, f"adm:topic:{tid}")])

        rows.append([("🏠 В меню /addtopic", "adm:home")])  # 💬 быстрый выход без тупиков
        rows.append([("⬅️ Закрыть", "adm:close")])

        kb = _ikb(rows)
        await _inline_open(
            message,
            state,
            f"✏️ <b>Редактировать темы</b>\nКатегория: {cat_label} | Уровень: {level}\nВыбери тему:",
            kb
        )
        await state.set_state(NewTopicStates.waiting_edit_topic_choice)  # 💬 фиксируем режим редактирования
        return

    await message.answer("Уровень выбран. Теперь введи НАЗВАНИЕ новой темы:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(NewTopicStates.waiting_topic_name)
    # 💬 После выбора уровня переходим к вводу названия темы.




# === Шаг 2: название темы ===
@router.message(NewTopicStates.waiting_topic_name)
async def get_topic_name(message: Message, state: FSMContext):
    import os, re
    from pathlib import Path  # 💬 нужен для exists() и работы с путями

    raw = (message.text or "").strip()
    clean = re.sub(r"[^\w\s]", "", raw).lower().replace(" ", "_")

    # 💬 запрещаем локаль и проверяем что /data/topics реально writable
    topics_dir = get_topics_dir()
    if str(topics_dir) != "/data/topics":
        await message.answer(
            "❗ Volume /data/topics недоступен.\n"
            "Тема не будет сохранена после редеплоя. Проверь Railway Volume mount.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return

    try:
        topics_dir.mkdir(parents=True, exist_ok=True)  # 💬 гарантируем что папка есть
        test_path = topics_dir / ".write_test"  # 💬 тест записи в volume
        test_path.write_text("ok", encoding="utf-8")
        try:
            test_path.unlink()
        except Exception:
            pass
    except Exception:
        await message.answer(
            "❗ Volume /data/topics не writable.\n"
            "Тема не будет сохранена после редеплоя. Проверь права и mount.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return

    # 💬 что делает эта часть: если файл уже существует, добавляем суффикс 1,2,3 чтобы не затирать тему
    base_clean = clean
    base_raw = raw

    filename = str(topics_dir / f"{base_clean}.json")  # 💬 базовый путь в /data/topics
    if Path(filename).exists():
        suffix = 1
        while True:
            candidate_clean = f"{base_clean}_{suffix}"
            candidate_filename = str(topics_dir / f"{candidate_clean}.json")
            if not Path(candidate_filename).exists():
                clean = candidate_clean  # 💬 обновляем машинное имя темы
                raw = base_raw  # 💬 отображаемое имя не меняем, суффикс только для файла и системного title
                filename = candidate_filename  # 💬 обновляем путь файла
                break
            suffix += 1

    # 💬 Собираем базовую структуру темы
    data = await state.get_data()
    category = data["topic"]["category"]
    topic = {
        "title": clean,
        "visible_title": raw,
        "visible_title": base_raw,  # 💬 в боте всегда исходное название, без суффиксов
        "category": category,
        "level": data.get("topic_level"),  # 💬 добавляем выбранный уровень
        "vocab": [],
        "exercises": [],
        "videos": [],
        "dialogs": [],
        "reading": [],  # 💬 хранит пакеты чтения
        "translate": [],  # 💬 отдельные пакеты для кнопки «Переводи»
    }

    # 💾 Сохраняем в файл (уже в Volume)
    try:
        atomic_save_json(filename, topic)  # 💬 сохраняем тему на диск
    except Exception:
        await message.answer(
            "❗ Не удалось сохранить тему. Проверь, что /data/topics доступен и writable.",
            reply_markup=ReplyKeyboardRemove()
        )  # 💬 показываем причину вместо “тишины”
        await state.clear()
        return

    # 💬 Обновляем состояние
    await state.update_data(topic=topic, topic_path=filename)  # 💬 сохраняем в FSM путь и данные темы

    # 💬 Запрос описания темы
    await message.answer("Теперь введи ОПИСАНИЕ темы:", reply_markup=ReplyKeyboardRemove())  # 💬 идём дальше по flow
    await state.set_state(NewTopicStates.waiting_topic_description)
    return



@router.message(NewTopicStates.waiting_topic_description)
async def get_topic_description(message: Message, state: FSMContext):
    # 💬 Сохраняем описание темы и перестраиваем порядок полей
    desc = message.text.strip()
    data = await state.get_data()
    topic = data.get("topic", {})

    new_topic = {
        "title":         topic["title"],
        "visible_title": topic["visible_title"],
        "description":   desc,
        "category":      topic["category"],
        "level":         topic.get("level"),
        "vocab":         topic.get("vocab", []),
        "exercises":     topic.get("exercises", []),
        "videos":        topic.get("videos", []),
        "dialogs":       topic.get("dialogs", []),
        "reading":       topic.get("reading", []),  # 💬 что делает эта часть: не теряем пакеты чтения при сохранении описания
        "translate":     topic.get("translate", []),  # 💬 что делает эта часть: отдельные фазы «Переводить»

    }

    # 💾 Сохраняем в файл
    filename = data.get("topic_path")
    atomic_save_json(filename, new_topic)  # 💬 сохраняем в volume Railway безопасно (atomic)

    await state.update_data(topic=new_topic)

    # ⌨️ Главное меню
    keyboard = get_main_menu(topic.get("category"))  # 💬 показываем правильное меню (lex/gram)

    await message.answer("🧩 С чего начнём?", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_first_choice)




def _preview_text(s: str, limit: int = 30) -> str:
    # 💬 короткое превью текста без падений
    s = (s or "").strip().replace("\n", " ")
    if not s:
        return "<пусто>"
    return s[:limit] + ("…" if len(s) > limit else "")


def _preview_url_title(url: str) -> str:
    # 💬 имя ссылки по домену если нет title
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").replace("www.", "")
        return host or "ссылка"
    except Exception:
        return "ссылка"


def _preview_item(item: dict) -> str:
    # 💬 универсальное превью для блоков грамматики (text, photo, quiz, poll, link, asset)
    if not isinstance(item, dict):
        return "элемент"

    t = (item.get("type") or item.get("media_type") or "").strip().lower()

    # text
    if t in {"text"}:
        return f"📝 {_preview_text(str(item.get('text') or item.get('content') or ''))}"

    # quiz
    if t in {"quiz", "textquiz"}:
        q = str(item.get("question") or item.get("q") or "вопрос")
        return f"🎯 {_preview_text(q)}"

    # poll (на всякий)
    if t in {"poll"}:
        q = str(item.get("question") or "вопрос")
        return f"📊 {_preview_text(q)}"

    # photo blocks from vocab or exercises
    if t in {"photo"}:
        mt = (item.get("media_type") or "").lower()
        if mt == "sticker":
            return "🖼 стикер"
        if mt == "animation":
            return "🖼 гиф/видео"
        return "🖼 фото"

    # assets inside reading
    if t in {"asset"}:
        mt = (item.get("media_type") or "").lower()
        if mt == "photo":
            return "🖼 фото"
        if mt == "document":
            return "📎 файл"
        if mt == "url":
            return f"🔗 {_preview_url_title(str(item.get('file') or ''))}"
        return "📎 ассет"

    # link blocks
    if "link" in item:
        url = str(item.get("link") or "")
        title = str(item.get("title") or "") or _preview_url_title(url)
        return f"🔗 {_preview_text(title)}"

    # fallback by fields
    if item.get("title"):
        return f"📌 {_preview_text(str(item.get('title')))}"
    if item.get("file"):
        return "📎 ассет"
    return "элемент"



# === Шаг 2: выбор действия
# === Главное меню: обработка выбора блока или просмотр/сохранение ===
@router.message(NewTopicStates.waiting_first_choice)
async def handle_main_menu(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    topic_path = data.get("topic_path")  # 💬 вытаскиваем путь темы заранее, чтобы не ловить UnboundLocalError

    tp = data.get("topic")
    path = data.get("topic_path")

    if text == "🗑 Удалить тему":
        # 💬 просим подтверждение, чтобы случайно не удалить
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Удалить"), KeyboardButton(text="🚫 Отмена")],
            ],
            resize_keyboard=True
        )
        title = (tp or {}).get("visible_title") or (tp or {}).get("title") or "тема"
        await message.answer(f"Подтверди удаление темы: {title}", reply_markup=kb)
        await state.set_state(NewTopicStates.waiting_delete_topic_confirm)
        return

    category = (tp or {}).get("category")

    # 💬 что делает эта часть: кнопки грамматики перекидываем на существующие ветки (vocab/exercise/video/reading)
    if category == "gram":
        if text == "📖 Теория":
            text = "📚 словарь"
        elif text == "📝 Практика":
            text = "✏️ Добавить упражнение"
        elif text == "🎥 Видео":
            text = "🎥 Добавить видео"
        elif text == "📚 Читать":
            text = "📖 Добавить чтение"

    #ть чтение -----------------------
    if text in ("➕ Добавить чтение", "📖 Читать", "📖 читать"):
        await state.update_data(last_block="reading")  # 💬 помечаем режим "Читать", дальше общий FSM сохранит в topic["reading"]
        await message.answer(
            "📖 Впишите название фазы чтения:\n\n"
            "Примеры:\n"
            "Читать = Кухня\n"
            "Читать = Еда в кафе\n\n"
            "Потом пришлёшь фрагменты (каждый фрагмент отдельно)."
        )  # 💬 отдельная инструкция для чтения, чтобы не путалось с переводом
        return await state.set_state(NewTopicStates.waiting_reading_title)  # 💬 общий state, различаем по last_block

    
    #ть перевод -----------------------
    if text == "📝 Добавить перевод":
        await state.update_data(last_block="translate")  # 💬 что делает эта часть: помечаем режим «Переводить»
    
        prompt = (
            "📝 Впишите название фазы перевода:\n\n"
            "Примеры:\n"
            "• Перевод = Кухня\n"
            "• Перевод = В магазине\n"
            "• Перевод = Диалоги A1"
        )  # 💬 показываем примеры именно для режима «Перевод»
        await message.answer(prompt, reply_markup=ReplyKeyboardRemove())
        return await state.set_state(NewTopicStates.waiting_reading_title)  # 💬 FSM общий, различаем по last_block


        #ть словарь -----------------------
    if text == "📚 словарь":
        await state.update_data(
            last_block="vocab",
            allin_force_new_phase=True  # 💬 каждый вход в словарь = готовим новую фазу под ближайший ALL IN
        )

        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="↩️ Назад")],
                [KeyboardButton(text="🆕 Новая тема")],
            ],
            resize_keyboard=True
        )

        await message.answer(
            "Вставь ALL IN блок одним сообщением.\n"
            "Пустые строки игнорируются.\n\n"
            "[PHRASE]\n"
            "ES: pagar con tarjeta\n"
            "RU: платить картой\n"
            "[POLL]\n"
            "...\n"
            "...\n"
            "...\n"
            "...\n"
            "[TEXT]\n"
            "...\n"
            "[/PHRASE]",
            reply_markup=kb
        )  # 💬 сразу уходим в bulk-вставку, без VOC
        await state.set_state(NewTopicStates.waiting_vocab_allin_bulk)
        return

    if text == "💾 Сохранить":
        topic = data.get("topic") or {}  # 💬 берём текущую тему из state
        if not topic_path:
            await message.answer("❗ Не вижу путь темы. Открой или создай тему заново.")  # 💬 защита от пустого topic_path
            return

        file_topic = None
        if os.path.exists(topic_path):
            try:
                with open(topic_path, "r", encoding="utf-8") as f:
                    file_topic = json.load(f) or {}
            except Exception:
                file_topic = None

        try:
            cur_dump = json.dumps(topic, ensure_ascii=False, sort_keys=True)
            file_dump = json.dumps(file_topic, ensure_ascii=False, sort_keys=True) if isinstance(file_topic, dict) else None
        except Exception:
            cur_dump = None
            file_dump = None

        if file_dump is not None and cur_dump is not None and file_dump == cur_dump:
            await message.answer("✅ Уже сохранено")  # 💬 верификация: файл уже совпадает со state
        else:
            try:
                with open(topic_path, "w", encoding="utf-8") as f:
                    json.dump(topic, f, ensure_ascii=False, indent=2)  # 💬 принудительно перезаписываем файл без дублей
                await message.answer("✅ А вот теперь сохранено")  # 💬 верификация: файл обновили
            except Exception:
                await message.answer("❗ Не смог сохранить файл темы. Проверь права на /data/topics.")  # 💬 защита от падений

        # 💬 возвращаем клавиатуру главного меню и остаёмся в том же состоянии
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Добавить словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
                [KeyboardButton(text="🎥 Добавить видео"), KeyboardButton(text="💾 Сохранить"), KeyboardButton(text="💬 Добавить диалог")],
                [KeyboardButton(text="👁 Просмотреть"), KeyboardButton(text="✏️ Редактировать")]
            ],
            resize_keyboard=True
        )
        await message.answer("С чего начнём?", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return


    # ----------------------- Добавить упражнение -----------------------
    if text == "✏️ Добавить упражнение":
        # 💬 Последний блок = exercise
        await state.update_data(last_block="exercise")
        await message.answer("Введите НАЗВАНИЕ упражнения:")
        await state.set_state(NewTopicStates.waiting_ex_title)
        return

    #ть видео -----------------------
    if text == "🎥 Добавить видео":
        # 💬 Последний блок = video
        await state.update_data(last_block="video")

        data = await state.get_data()
        topic = data.get("topic") or {}

        # 💬 авто-тайтл по количеству уже добавленных видео
        existing_videos = topic.get("videos") or []
        auto_title = f"Video {len(existing_videos) + 1}"

        await state.update_data(current_video_title=auto_title)

        # 💬 сразу просим ссылку, без шага ввода названия
        await message.answer("Пришли ссылку на видео (или iframe):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(NewTopicStates.waiting_video_link)
        return

    #ть чтение -----------------------
    if text == "📖 Добавить чтение":
        await state.update_data(last_block="reading")  # 💬 помечаем текущий раздел

        data = await state.get_data()
        topic = data.get("topic") or {}
        category_now = ((topic.get("category") or "").strip().lower())
        category_now = "gram" if category_now.startswith("gram") else "lex"  # 💬 нормализуем категорию

        prompt = "📚 Впишите название фазы чтения:" if category_now == "gram" else "Введите ЗАГОЛОВОК чтения:"  # 💬 в грамматике заголовок = фаза
        await message.answer(prompt, reply_markup=ReplyKeyboardRemove())
        return await state.set_state(NewTopicStates.waiting_reading_title)




  


    # ----------------------- Просмотреть то, что уже создали -----------------------

    if text == "👁 Просмотреть":
        # 💬 всегда читаем JSON с диска, чтобы обзор был актуальный
        topic_path = data.get("topic_path")
        if not topic_path or not os.path.exists(topic_path):
            await message.answer("Ошибка: файл темы не найден.", disable_web_page_preview=True)
            keyboard = get_main_menu((data.get("topic") or {}).get("category"))
            await message.answer("С чего начнём?", reply_markup=keyboard)
            await state.set_state(NewTopicStates.waiting_first_choice)
            return

        with open(topic_path, "r", encoding="utf-8") as f:
            topic_data = json.load(f) or {}

        category_now = (topic_data.get("category") or (data.get("topic") or {}).get("category") or "").strip()

        lines = []
        lines.append(f"📌 <b>{topic_data.get('visible_title') or topic_data.get('title') or 'Тема'}</b>")
        if topic_data.get("description"):
            lines.append(f"🧾 {_preview_text(str(topic_data.get('description')), 80)}")
        lines.append("")

        if category_now == "gram":
            # ====== ТЕОРИЯ (vocab phases) ======
            phases = topic_data.get("vocab") or []
            lines.append("📖 <b>Теория (фазы):</b>")
            if not phases:
                lines.append("  — пусто")
            else:
                for p_idx, ph in enumerate(phases, start=1):
                    ph_name = str(ph.get("phase_name") or f"Фаза {p_idx}")
                    phrases = ph.get("phrases") or []  # 💬 для лексики считаем именно фразы внутри пака
                    lines.append(f"  {i}) 📦 {name} (фраз: {len(phrases)})")  # 💬 показываем корректный счётчик

                    for i_idx, it in enumerate(items[:8], start=1):
                        lines.append(f"      {p_idx}.{i_idx}) {_preview_item(it)}")
                    if len(items) > 8:
                        lines.append("      …")
            lines.append("")

            # ====== ПРАКТИКА (exercises) ======
            ex_list = topic_data.get("exercises") or []
            lines.append("📝 <b>Практика:</b>")
            if not ex_list:
                lines.append("  — пусто")
            else:
                for idx, it in enumerate(ex_list[:15], start=1):
                    lines.append(f"  {idx}) {_preview_item(it)}")
                if len(ex_list) > 15:
                    lines.append("  …")
            lines.append("")

            # ====== ВИДЕО ======
            vid_list = topic_data.get("videos") or []
            lines.append("🎥 <b>Видео:</b>")
            if not vid_list:
                lines.append("  — пусто")
            else:
                for idx, v in enumerate(vid_list[:15], start=1):
                    title = str(v.get("title") or _preview_url_title(str(v.get("link") or "")) or "видео")
                    lines.append(f"  {idx}) 🎬 {_preview_text(title, 50)}")
                if len(vid_list) > 15:
                    lines.append("  …")
            lines.append("")

            # ====== ЧИТАТЬ (reading packs) ======
            reading_list = topic_data.get("reading") or []
            lines.append("📚 <b>Читать:</b>")
            if not reading_list:
                lines.append("  — пусто")
            else:
                for r_idx, pack in enumerate(reading_list[:15], start=1):
                    ttl = str(pack.get("title") or "Чтение")
                    fr = pack.get("fragments") or []
                    assets = pack.get("assets") or []
                    first = ""
                    if fr:
                        first = _preview_text(str(fr[0]), 40)
                    elif assets:
                        first = _preview_item(assets[0])
                    lines.append(f"  {r_idx}) 📖 <b>{_preview_text(ttl, 40)}</b> (фраз: {len(fr) + len(assets)})")  # 💬 считаем фразы как fragments+assets

                    if first:
                        lines.append(f"      ↳ {first}")
                if len(reading_list) > 15:
                    lines.append("  …")
            lines.append("")

        

        else:
            # ====== ЛЕКСИКА: словарь/упражнения/видео + Читать/Переводить ======
            vocab_phases = topic_data.get("vocab") or []
            lines.append("📖 <b>Словарь (фазы):</b>")
            if not vocab_phases:
                lines.append("  — пусто")
            else:
                for p_idx, ph in enumerate(vocab_phases[:20], start=1):
                    ph_name = str(ph.get("phase_name") or f"Фаза {p_idx}")
                    phrases = ph.get("phrases") or []  # 💬 для лексики считаем именно фразы внутри пака
                    lines.append(f"  {p_idx}) 📦 {ph_name} (фраз: {len(phrases)})")  # 💬 показываем корректный счётчик


            lines.append("")
        
            ex_list = topic_data.get("exercises") or []
            lines.append("✏️ <b>Упражнения:</b>")
            lines.append(f"  — всего: {len(ex_list)}")  # 💬 что делает эта часть: быстрый счётчик
            lines.append("")
        
            vid_list = topic_data.get("videos") or []
            lines.append("🎥 <b>Видео:</b>")
            if not vid_list:
                lines.append("  — пусто")
            else:
                for idx, v in enumerate(vid_list[:15], start=1):
                    title = str(v.get("title") or _preview_url_title(str(v.get("link") or "")) or "видео")
                    lines.append(f"  {idx}) 🎬 {_preview_text(title, 50)}")
                if len(vid_list) > 15:
                    lines.append("  …")
            lines.append("")
        
            reading_list = topic_data.get("reading") or []
            lines.append("📖 <b>Читать:</b>")
            if not reading_list:
                lines.append("  — пусто")
            else:
                for r_idx, pack in enumerate(reading_list[:15], start=1):
                    ttl = str(pack.get("title") or "Чтение")
                    fr = pack.get("fragments") or []
                    assets = pack.get("assets") or []
                    lines.append(f"  {r_idx}) 📖 <b>{_preview_text(ttl, 40)}</b> (фраз: {len(fr) + len(assets)})")  # 💬 считаем фразы как fragments+assets

            lines.append("")
        
            translate_list = topic_data.get("translate") or []
            lines.append("📝 <b>Переводить:</b>")
            if not translate_list:
                lines.append("  — пусто")
            else:
                for t_idx, pack in enumerate(translate_list[:15], start=1):
                    ttl = str(pack.get("title") or "Перевод")
                    fr = pack.get("fragments") or []
                    assets = pack.get("assets") or []
                    lines.append(f"  {t_idx}) 📝 <b>{_preview_text(ttl, 40)}</b> (фраз: {len(fr) + len(assets)})")  # 💬 считаем фразы как fragments+assets

            lines.append("")


        

        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

        keyboard = get_main_menu(category_now)
        await message.answer("С чего начнём?", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return



    # ----------------------- Редактировать тему -----------------------
    if text == "✏️ Редактировать":
        # 💬 единая точка редактирования через inline
        await state.set_state(AdminInlineEditStates.idle)
        await _adm_show_actions_msg(message, state, note_text="ℹ️ Редактирование через inline-кнопки")
        return

    # 💬 защита от "тихого" зависания: если кнопка/текст не распознаны, даём явный ответ
    keyboard = get_main_menu(category)
    await message.answer("❗ Не понял действие. Нажми кнопку из меню ниже.", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_first_choice)
    return


@router.message(NewTopicStates.waiting_delete_topic_confirm)
async def confirm_delete_topic(message: Message, state: FSMContext):
    # 💬 удаляем файл темы из Railway Volume (/data/topics) после подтверждения
    txt = (message.text or "").strip()

    if txt == "🚫 Отмена":
        data = await state.get_data()
        topic = data.get("topic") or {}
        category = (topic.get("category") or "").strip()
        kb = get_main_menu(category)
        if kb and hasattr(kb, "keyboard"):
            kb.keyboard.append([KeyboardButton(text="🗑 Удалить тему")])  # 💬 возвращаем кнопку
        await message.answer("Ок, не удаляю.", reply_markup=kb)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    if txt != "✅ Удалить":
        await message.answer("Нажми кнопку ✅ Удалить или 🚫 Отмена.")
        return

    data = await state.get_data()
    topic_path = data.get("topic_path")

    if not topic_path or not os.path.exists(topic_path):
        await message.answer("⚠️ Файл темы не найден. Возможно, тема не из /data/topics.")
        return await start_adding_topic(message, state)
    if not _is_railway_topics_file(topic_path):
        # 💬 запрещаем удаление вне RailwayData (/data/topics)
        await message.answer("⚠️ Удаление разрешено только для тем из RailwayData: /data/topics.")
        return await start_adding_topic(message, state)

    try:
        os.remove(topic_path)
        
    except Exception:
        logging.exception("confirm_delete_topic: cannot remove %s", topic_path)
        await message.answer("❌ Не смог удалить файл темы. Проверь права Railway Volume.")
        return await start_adding_topic(message, state)

    await state.clear()

    # 💬 возвращаемся в то же меню "Редактировать темы" (список файлов из /data/topics)
    topics_dir = get_topics_dir()
    files = [p.stem for p in topics_dir.glob("*.json")]

    if not files:
        await message.answer("✅ Тема удалена. Больше нет тем для редактирования.")
        return await start_adding_topic(message, state)

    buttons = [[KeyboardButton(text="🚫 Отмена")]] + [[KeyboardButton(text=name)] for name in files]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    await message.answer("✅ Тема удалена. Выберите следующую тему для редактирования:", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_edit_topic_choice)
    return




@router.message(EditGrammarStates.waiting_section)
async def edit_grammar_choose_section(message: Message, state: FSMContext):
    # 💬 выбираем раздел грамматики для удаления
    section = (message.text or "").strip()
    data = await state.get_data()
    topic_path = data.get("topic_path")

    if section == "🚫 Отмена":
        keyboard = get_main_menu("gram")
        await message.answer("Ок. Возвращаемся в меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    if not topic_path or not os.path.exists(topic_path):
        await message.answer("❗ Ошибка: файл темы не найден.")
        keyboard = get_main_menu("gram")
        await message.answer("Возвращаемся в меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    with open(topic_path, "r", encoding="utf-8") as f:
        topic_data = json.load(f) or {}

    await state.update_data(topic=topic_data, edit_gram_section=section)

    if section == "📖 Теория":
        phases = topic_data.get("vocab") or []
        if not phases:
            await message.answer("Теория пустая.")
            kb = get_main_menu("gram")
            await message.answer("Меню.", reply_markup=kb)
            await state.set_state(NewTopicStates.waiting_first_choice)
            return

        buttons = [[KeyboardButton(text=f"{i}. {p.get('phase_name') or f'Фаза {i}'}")] for i, p in enumerate(phases, 1)]
        buttons.append([KeyboardButton(text="↩️ Назад")])
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer("Выбери фазу для редактирования:", reply_markup=kb)
        await state.set_state(EditGrammarStates.waiting_phase)
        return

    # Практика, Видео, Читать сразу показываем список
    await _edit_grammar_show_list(message, state)


@router.message(EditGrammarStates.waiting_phase)
async def edit_grammar_choose_phase(message: Message, state: FSMContext):
    # 💬 выбор фазы теории для удаления элемента
    text = (message.text or "").strip()
    if text == "↩️ Назад":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📖 Теория"), KeyboardButton(text="📝 Практика")],
                [KeyboardButton(text="🎥 Видео"), KeyboardButton(text="📚 Читать")],
                [KeyboardButton(text="🚫 Отмена")],
            ],
            resize_keyboard=True,
        )
        await message.answer("Выбери раздел:", reply_markup=kb)
        await state.set_state(EditGrammarStates.waiting_section)
        return

    try:
        phase_idx = int(text.split(".", 1)[0].strip()) - 1
    except Exception:
        await message.answer("❗ Нажми кнопку фазы.")
        return

    data = await state.get_data()
    topic = data.get("topic") or {}
    phases = topic.get("vocab") or []
    if not (0 <= phase_idx < len(phases)):
        await message.answer("❗ Фаза не найдена.")
        return

    await state.update_data(edit_gram_phase_index=phase_idx)
    await _edit_grammar_show_list(message, state)


async def _edit_grammar_show_list(message: Message, state: FSMContext):
    # 💬 показываем список элементов выбранного раздела и просим индекс для удаления
    data = await state.get_data()
    topic = data.get("topic") or {}
    section = data.get("edit_gram_section")
    phase_idx = data.get("edit_gram_phase_index")

    lines = ["👁 Вот что есть сейчас:"]
    items = []

    if section == "📖 Теория":
        phases = topic.get("vocab") or []
        ph = phases[phase_idx] if isinstance(phase_idx, int) and 0 <= phase_idx < len(phases) else None
        items = (ph or {}).get("vocab") or []
        lines.append(f"📖 Фаза: {ph.get('phase_name') if ph else 'не найдена'}")
        if not items:
            lines.append("— пусто")
    elif section == "📝 Практика":
        items = topic.get("exercises") or []
        if not items:
            lines.append("— пусто")
    elif section == "🎥 Видео":
        items = topic.get("videos") or []
        if not items:
            lines.append("— пусто")
    elif section == "📚 Читать":
        items = topic.get("reading") or []
        if not items:
            lines.append("— пусто")
    else:
        await message.answer("❗ Неизвестный раздел.")
        return

    # формируем строки
    for i, it in enumerate(items, start=1):
        if section == "🎥 Видео":
            title = str((it or {}).get("title") or _preview_url_title(str((it or {}).get("link") or "")) or "видео")
            lines.append(f"{i}) 🎬 {_preview_text(title, 50)}")
        elif section == "📚 Читать":
            ttl = str((it or {}).get("title") or "Чтение")
            fr = (it or {}).get("fragments") or []
            assets = (it or {}).get("assets") or []
            lines.append(f"{i}) 📖 {_preview_text(ttl, 40)} (фраз: {len(fr) + len(assets)})")  # 💬 считаем фразы как fragments+assets

        else:
            lines.append(f"{i}) {_preview_item(it)}")

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить по индексу"), KeyboardButton(text="🗑 Удалить по индексу")],
            [KeyboardButton(text="↩️ Назад"), KeyboardButton(text="🚫 Отмена")],
        ],
        resize_keyboard=True
    )


    await message.answer("\n".join(lines), reply_markup=kb, disable_web_page_preview=True)
    await state.set_state(EditGrammarStates.waiting_delete_index)


@router.message(EditGrammarStates.waiting_delete_index)
async def edit_grammar_delete_index(message: Message, state: FSMContext):
    # 💬 удаляем элемент по индексу и сохраняем JSON
    text = (message.text or "").strip()

    if text in ("➕ Добавить по индексу", "⌨️ Ввести"):
        await message.answer(
            "Введите индекс, КУДА вставить (1 = в начало, 2 = перед вторым и т.д.):",
        )  # 💬 просим позицию вставки
        await state.set_state(EditGrammarStates.waiting_insert_index)
        return


    if text == "🚫 Отмена":
        keyboard = get_main_menu("gram")
        await message.answer("Ок. Меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    if text == "↩️ Назад":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📖 Теория"), KeyboardButton(text="📝 Практика")],
                [KeyboardButton(text="🎥 Видео"), KeyboardButton(text="📚 Читать")],
                [KeyboardButton(text="🚫 Отмена")],
            ],
            resize_keyboard=True,
        )
        await message.answer("Выбери раздел:", reply_markup=kb)
        await state.set_state(EditGrammarStates.waiting_section)
        return

    if text == "🗑 Удалить по индексу":
        await message.answer("Напиши номер индекса (например 1):", reply_markup=ReplyKeyboardRemove())
        return

    if not text.isdigit():
        await message.answer("❗ Напиши номер (например 1) или нажми «↩️ Назад».")
        return

    idx = int(text) - 1

    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")
    section = data.get("edit_gram_section")
    phase_idx = data.get("edit_gram_phase_index")

    if not topic_path:
        await message.answer("❗ Ошибка: topic_path не найден.")
        return

    # выбираем список
    if section == "📖 Теория":
        phases = topic.get("vocab") or []
        if not (isinstance(phase_idx, int) and 0 <= phase_idx < len(phases)):
            await message.answer("❗ Фаза не найдена.")
            return
        items = phases[phase_idx].get("vocab") or []
        if not (0 <= idx < len(items)):
            await message.answer("❗ Индекс вне диапазона.")
            return
        items.pop(idx)
        phases[phase_idx]["vocab"] = items
        topic["vocab"] = phases
    elif section == "📝 Практика":
        items = topic.get("exercises") or []
        if not (0 <= idx < len(items)):
            await message.answer("❗ Индекс вне диапазона.")
            return
        items.pop(idx)
        topic["exercises"] = items
    elif section == "🎥 Видео":
        items = topic.get("videos") or []
        if not (0 <= idx < len(items)):
            await message.answer("❗ Индекс вне диапазона.")
            return
        items.pop(idx)
        topic["videos"] = items
    elif section == "📚 Читать":
        items = topic.get("reading") or []
        if not (0 <= idx < len(items)):
            await message.answer("❗ Индекс вне диапазона.")
            return
        items.pop(idx)
        topic["reading"] = items
    else:
        await message.answer("❗ Неизвестный раздел.")
        return

    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)
    await message.answer("✅ Удалено. Обновляю список…")
    await _edit_grammar_show_list(message, state)


@router.message(EditGrammarStates.waiting_insert_index)
async def edit_grammar_insert_by_index(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text in ("↩️ Назад", "🚫 Отмена"):
        return await _edit_grammar_show_list(message, state)  # 💬 возвращаемся к списку без изменений

    if not text.isdigit():
        await message.answer("⚠️ Введите число (индекс), например 1 или 2.")  # 💬 защита от мусорного ввода
        return

    insert_index = int(text)

    data = await state.get_data()
    section_label = (data.get("edit_gram_section") or "").strip()  # 💬 берём реальный выбранный раздел (📖 Теория и т.д.)


    # 💬 включаем режим вставки и запоминаем индекс
    await state.update_data(edit_insert_mode=True, edit_insert_index=insert_index)

    # 💬 выставляем last_block и (для теории) current_phase_id, чтобы переиспользовать CreateLessonBlock-ветки
    if section_label == "📖 Теория":
        phase_idx = data.get("edit_gram_phase_index")  # 💬 берём выбранную фазу теории из FSM (0-based)
        if phase_idx is None:
            await message.answer("⚠️ Сначала выбери фазу теории.")  # 💬 защита, чтобы current_phase_id не стал None
            await state.set_state(EditGrammarStates.waiting_phase)  # 💬 возвращаем на выбор фазы
            return
        await state.update_data(last_block="vocab", current_phase_id=int(phase_idx) + 1)  # 💬 переводим в 1-based для CreateLessonBlock
    else:
        await state.update_data(last_block="exercise")  # 💬 остальные разделы не используют current_phase_id


    await send_insert_post_menu(message, state)  # 💬 показываем меню “что вставляем”
    return



@router.message(NewDialogStates.waiting_dialog_phase_name)
async def get_dialog_phase_name(message: Message, state: FSMContext):
    """
    💬 Шаг 1: создаём фазу диалогов в topic["dialogs"] с phase_id / phase_name.
    """
    phase_name = message.text.strip()

    data = await state.get_data()
    topic = data["topic"]
    dialogs = topic.get("dialogs", [])

    # 💬 Аккуратно считаем следующий phase_id (игнорируем старые записи без phase_id)
    existing_ids = [
        d.get("phase_id")
        for d in dialogs
        if isinstance(d, dict) and isinstance(d.get("phase_id"), int)
    ]
    if existing_ids:
        next_id = max(existing_ids) + 1
    else:
        next_id = len(dialogs) + 1 or 1

    new_phase = {
        "phase_id":   next_id,
        "phase_name": phase_name,
        "blocks":     []          # 💬 сюда позже положим блоки по 2 реплики (RU + ES)
    }
    dialogs.append(new_phase)
    topic["dialogs"] = dialogs

    topic_path = data.get("topic_path")
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем фазу сразу в JSON, чтобы не потерять при падении

    # 💾 Обновляем topic в FSM, запоминаем индекс созданной фазы
    await state.update_data(topic=topic, dialog_phase_index=len(dialogs) - 1)

    await message.answer(
        "Теперь пришлите ВЕСЬ диалог-блок в Markdown.\n"
        "Каждый мини-диалог — ровно 2 строки (RU + ES).\n"
        "Пустые строки будут проигнорированы.",
    )
    await state.set_state(NewDialogStates.waiting_dialog_markdown_block)


@router.message(NewDialogStates.waiting_dialog_markdown_block)
async def save_dialog_markdown(message: Message, state: FSMContext):
    """
    💬 Шаг 2: режем Markdown по 2 строкам (RU + ES) и сохраняем в topic['dialogs'][idx]['blocks'].
    """
    import json  # 💬 на случай, если не импортирован выше (дублирование не критично)

    raw = (message.text or "").strip()

    # 💬 Срезаем ``` если пользователь вставил код-блок
    if raw.startswith("```"):
        raw = raw.lstrip("`").strip()
    if raw.endswith("```"):
        raw = raw.rstrip("`").strip()

    # 💬 Берём только НЕпустые строки
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]

    if not lines:
        await message.answer("❗ Не вижу строк в сообщении. Пришлите, пожалуйста, диалог ещё раз.")
        return

    # 💬 Проверяем, что строк чётное количество (каждый блок = 2 строки: RU + ES)
    if len(lines) % 2 != 0:
        await message.answer(
            f"❗ Количество НЕпустых строк должно делиться на 2.\n"
            f"Сейчас строк: {len(lines)}.\n"
            "Каждый мини-диалог должен быть из 2 строк (RU + ES).\n"
            "Проверь формат и пришли блок ещё раз."
        )
        return

    # 💬 Режем в blocks по 2 строки (RU + ES в одном блоке)
    blocks = []
    for i in range(0, len(lines), 2):
        chunk = lines[i:i+2]
        blocks.append({"lines": chunk})   # 💬 каждый блок — одна пара RU/ES

    data = await state.get_data()
    topic = data["topic"]
    idx = data.get("dialog_phase_index")

    topic.setdefault("dialogs", [])

    # 💬 Защита от рассинхрона индекса
    if not isinstance(idx, int) or idx < 0 or idx >= len(topic["dialogs"]):
        await message.answer("❗ Ошибка индекса фазы диалога. Попробуйте создать фазу заново.")
        return

    topic["dialogs"][idx]["blocks"] = blocks  # 💬 сохраняем список блоков-пар в JSON

    topic_path = data["topic_path"]
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # 💬 Обновляем state и возвращаем пользователя в главное меню темы
    await state.update_data(topic=topic, dialog_phase_index=None, last_block="dialog")

    keyboard = get_main_menu((topic.get("category") or (data.get("topic") or {}).get("category")))  # 💬 возвращаем меню по категории темы

    total_lines = len(lines)  # 💬 сколько НЕпустых строк пришло
    total_sets = len(blocks)  # 💬 сколько сетов RU+ES сохранено

    await message.answer(
        "✅ Диалоговая фаза сохранена.\n"
        f"📌 Строк получено: {total_lines}\n"
        f"✅ Сетов (RU+ES) добавлено: {total_sets}\n"
        f"✅ Строк сохранено: {total_sets * 2}",  # 💬 каждая пара = 2 строки
        reply_markup=keyboard
    )

    await state.set_state(NewTopicStates.waiting_first_choice)



@router.message(StateFilter(NewTopicStates.waiting_channel))
async def save_channel_to_topic(message: Message, state: FSMContext):
    raw = message.text.strip()
    # 💬 Распарсим URL или username
    inputs = [c.strip() for c in raw.split(",") if c.strip()]
    parsed = []
    for ch in inputs:
        m = re.search(r"(?:https?://)?t\.me/(@?[\w\d_]+)", ch)
        if m:
            uname = m.group(1)
        else:
            uname = ch.lstrip("@")
        if not uname.startswith("@"):
            uname = "@" + uname
        parsed.append(uname)
    # 💬 добавляем каналы в общий список subscription_channels.json (для рекламной подписки)
    try:
        if not os.path.exists(SUBSCRIPTION_CHANNELS_PATH):
            with open(SUBSCRIPTION_CHANNELS_PATH, "w", encoding="utf-8") as f:
                json.dump({"channels": []}, f, ensure_ascii=False, indent=2)

        with open(SUBSCRIPTION_CHANNELS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}

        channels = payload.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        changed = False
        for ch in parsed:
            if ch and ch not in channels:
                channels.append(ch)
                changed = True

        if changed:
            payload["channels"] = channels
            with open(SUBSCRIPTION_CHANNELS_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            # 💬 Пушим обновлённый subscription_channels.json в GitHub, чтобы Railway подтянул изменения
            try:
                github_put_file(
                    local_path=SUBSCRIPTION_CHANNELS_PATH,
                    repo_path="subscription_channels.json",
                    commit_message="Update subscription channels via bot"
                )
            except Exception:
                logging.exception("save_channel_to_topic: cannot push subscription_channels.json to GitHub")


    except Exception:
        logging.exception("save_channel_to_topic: cannot update subscription_channels.json")


    data = await state.get_data()
    topic = data.get("topic", {})
    # 💬 Обновляем поля в памяти
    if len(parsed) == 1:
        topic["required_channel"] = parsed[0]
        topic.pop("required_channels", None)
    else:
        topic["required_channels"] = parsed
        topic.pop("required_channel", None)

    # 💾 Сохраняем в файл JSON
    path = data.get("topic_path")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)
    # 💬 Возвращаем Главное меню
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика")],
            [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
            [KeyboardButton(text="✏️ Редактировать темы")]  # 💬 та же кнопка EditTopic
        ],
        resize_keyboard=True
    )

    await message.answer("✅ Канал добавлен!\n\n📂 Выбери КАТЕГОРИЮ темы:", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_category)
    # 💬 После добавления каналов возвращаемся в главное меню тем






# ——— Хелпер: отправляет общее пост-меню для vocab/exercise/video ———

async def send_post_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    last = data.get("last_block")

    # Составляем кнопки под тип последнего блока
    if last == "vocab":
        category = ((data.get("topic") or {}).get("category") or "").strip().lower()  # 💬 нормализуем lex/gram для меню
        if category.startswith("gram"):
            category = "gram"
        elif category.startswith("lex"):
            category = "lex"


        if category == "gram":
            # 💬 грамматика (теория) = только текст, фото, пулквизы (без VOC и без ALL IN)
            rows = [
                [KeyboardButton(text="📝ТЕКСТ"), KeyboardButton(text="🖼FOTO")],
            ]

        else:
            # 💬 лексика = VOC выключен, оставляем только ALL IN
            rows = [
                [KeyboardButton(text="🧩 ALL IN")],
            ]







    elif last == "exercise":
        rows = [
            # 💬 практика = только создание упражнений (в GrammarFuture считаем прогресс по ссылкам)
            [KeyboardButton(text="🔄 Создать ещё упражнение")],
        ]


    elif last == "video":
        rows = [
            [KeyboardButton(text="🔄 Создать ещё видео")]
        ]
    else:
        rows = []

    # Внизу общий «Вернуться»
    rows.append([KeyboardButton(text="↩️ Вернуться в Главное меню")])

    kb = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
    await message.answer("Что дальше?", reply_markup=kb)
    await state.set_state(NewTopicStates.waiting_post_action)





async def send_insert_post_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    last_block = data.get("last_block")

    if last_block == "vocab":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝ТЕКСТ"), KeyboardButton(text="🖼FOTO")],
                [KeyboardButton(text="↩️ Назад")],
            ],
            resize_keyboard=True
        )  # 💬 меню вставки для теории (как в грамматике)
    elif last_block == "exercise":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🔄 Создать ещё упражнение")],
                [KeyboardButton(text="↩️ Назад")],
            ],
            resize_keyboard=True
        )  # 💬 меню вставки для практики
    else:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="↩️ Назад")]],
            resize_keyboard=True
        )  # 💬 безопасный fallback

    await message.answer("Что вставляем?", reply_markup=kb)
    await state.set_state(NewTopicStates.waiting_post_action)  # 💬 переиспользуем общий роутер post_action




# === БЛОК “СЛОВАРЬ” ===
# Создание Потока "Учить слова"
async def _create_vocab_phase_auto(state: FSMContext) -> dict:
    data = await state.get_data()
    topic = data.get("topic") or {}
    phases = topic.setdefault("vocab", [])

    phase_id = len(phases) + 1
    phase_name = f"📦 Пак слов {phase_id}"  # 💬 авто-название пака без ввода

    category_now = ((topic.get("category") or "").strip().lower())
    category_now = "gram" if category_now.startswith("gram") else "lex"  # 💬 нормализуем категорию

    new_phase = {
        "phase_id": phase_id,
        "phase_name": phase_name,
        "vocab": []  # 💬 в грамматике тут храним text/photo/quiz_pool
    }

    if category_now == "lex":
        new_phase["phrases"] = []  # 💬 phrases нужны только для лексики, в грамматике не используем

    phases.append(new_phase)

    topic_path = data.get("topic_path")
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем фазу сразу в JSON, чтобы не было рассинхрона

    await state.update_data(topic=topic, current_phase_id=new_phase["phase_id"])
    return new_phase


@router.message(NewTopicStates.waiting_phase_name)
async def create_phase(message: Message, state: FSMContext):
    # 💬 сохраняем новую фазу
    data = await state.get_data()

    topic = data.get("topic") or {}  # 💬 берём тему из FSM, чтобы topic был определён
    phases = topic.setdefault("vocab", [])  # 💬 список фаз внутри темы

    phase_name = (message.text or "").strip()
    if not phase_name:
        await message.answer("⚠️ Введите название фазы.")
        return  # 💬 защита от пустого ввода

    phase_id = len(phases) + 1  # 💬 автонумерация фаз как в choose_phase (1,2,3...)

    category_now = ((topic.get("category") or "").strip().lower())
    if category_now.startswith("gram"):
        category_now = "gram"
    else:
        category_now = "lex"

    new_phase = {
        "phase_id": phase_id,
        "phase_name": phase_name,
        "vocab": []  # 💬 в грамматике тут храним text/photo/quiz_pool
    }

    if category_now == "lex":
        new_phase["phrases"] = []  # 💬 phrases нужны только для лексики, в грамматике не используем

    phases.append(new_phase)

    topic_path = data.get("topic_path")
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем фазу сразу в JSON, чтобы не было рассинхрона

    await state.update_data(topic=topic, current_phase_id=new_phase["phase_id"])
    await message.answer(f"Фаза «{phase_name}» создана.")
    # 💬 После создания фазы = показываем меню действий
    await send_post_menu(message, state)


@router.message(NewTopicStates.waiting_phase_choice)
async def choose_phase(message: Message, state: FSMContext):
    text = message.text.strip()
    # — Создать новую фазу
    if text == "➕ Новая фаза":
        new_phase = await _create_vocab_phase_auto(state)  # 💬 создаём пак автоматически
        await message.answer(
            f"Создан: {new_phase['phase_name']}",
            reply_markup=ReplyKeyboardRemove()
        )  # 💬 пропускаем ввод названия
        await state.update_data(last_block="vocab")  # 💬 фиксируем блок словаря
        await send_post_menu(message, state)         # 💬 сразу показываем кнопки добавления словаря
        return


    # — Выбрать существующую фазу по номеру
    #    ожидаем формат "1. Фразовые глаголы"
    try:
        phase_id = int(text.split(".", 1)[0].strip())
    except ValueError:
        await message.answer(
            "⚠️ Сначала выбери фазу номером (пример: 1. ...), либо нажми «➕ Новая фаза».",
        )  # 💬 защита от ValueError, если прислали ALL IN не в том состоянии
        return

    await state.update_data(current_phase_id=phase_id)


    # 💬 подтвердить выбор и убрать клавиатуру
    await message.answer(f"Фаза выбрана: {text}", reply_markup=ReplyKeyboardRemove())
    
    data = await state.get_data()
    topic = data.get("topic") or {}
    
    await state.update_data(last_block="vocab")  # 💬 после выбора фазы сразу открываем меню словаря
    await send_post_menu(message, state)         # 💬 там уже есть ALL IN для быстрой заливки
    return


    # 💬 для лексики оставляем старое поведение (заголовок + link)
    await message.answer("Введите ЗАГОЛОВОК словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_title)






@router.message(NewTopicStates.waiting_vocab_textquiz_bulk)
async def import_vocab_textquiz_bulk(message: Message, state: FSMContext):
    # 💬 bulk TEXT_QUIZ отключён = всё добавляем через ALL IN (phrases)
    await message.answer(
        "❌ Импорт TEXT_QUIZ отключён.\n"
        "Используй 🧩 ALL IN и секции [TEXT]/[POLL] внутри [PHRASE].",
        reply_markup=ReplyKeyboardRemove()
    )
    await send_post_menu(message, state)



def _parse_allin_block(text: str):
    # 💬 парсим ALL IN блок и возвращаем (phrases, errors, meta) как ожидает import_vocab_allin_bulk
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    def _nl(s: str) -> str:
        # 💬 что делает эта часть: чиним переносы из админского текста (\\n и \\\\n) и убираем лишний слэш
        return (s or "").replace("\\\\n", "\n").replace("\\n", "\n")


    phrases: list[dict] = []
    errors: list[str] = []

    total_blocks = 0
    invalid_blocks = 0
    truncated_at: dict | None = None

    i = 0
    while i < len(lines):
        if lines[i] != "[PHRASE]":
            i += 1
            continue

        total_blocks += 1
        i += 1

        es = None
        ru = None
        polls: list[dict] = []
        textquizzes: list[dict] = []
        section = None  # 💬 None | "POLL" | "TEXT"

        while i < len(lines) and lines[i] != "[/PHRASE]":
            line = lines[i].strip()

            up = line.upper()
            if up == "[POLL]":
                section = "POLL"  # 💬 далее каждая строка = один poll-quiz
                i += 1
                continue
            if up in ("[TEXT]", "[TEXTQUIZ]"):
                section = "TEXT"  # 💬 далее каждая строка = один text-quiz
                i += 1
                continue

            if line.startswith("ES:"):
                es = line[3:].strip()
                section = None
                i += 1
                continue

            if line.startswith("RU:"):
                ru = line[3:].strip()
                section = None
                i += 1
                continue

            # 💬 совместимость со старым форматом
            if line.startswith("POLL:"):
                payload = _nl(line.split(":", 1)[1].strip())
                parts = [p.strip() for p in payload.split("|") if p.strip()]
                # 💬 формат: вопрос | correct | wrong1 | wrong2
                if len(parts) >= 4:
                    q = parts[0]
                    correct, wrong1, wrong2 = parts[1], parts[2], parts[3]
                    polls.append({
                        "type": "quiz",
                        "question": q,
                        "options": [correct, wrong1, wrong2],
                        "correct_answer": correct
                    })
                else:
                    errors.append(f"PHRASE #{total_blocks}: строка POLL мало полей")
                i += 1
                continue


            if line.startswith("TEXTQUIZ:") or line.startswith("TEXT:"):
                payload = _nl(line)
                parts = [p.strip() for p in payload.split("|") if p.strip()]

                # 💬 поддержка обоих форматов:
                # 1) новый: вопрос | correct | wrong1 | wrong2
                # 2) старый: вопрос | w1 | w2 | w3 | correct(последний)
                if len(parts) >= 4:
                    q = parts[0]
                    answers = parts[1:]

                    if len(answers) == 3:
                        correct = answers[0]
                        wrongs = answers[1:]
                    else:
                        correct = answers[-1]
                        wrongs = [a for a in answers[:-1] if a != correct]

                    options = [correct] + wrongs[:2]

                    if len(options) < 3 or not correct:
                        errors.append(f"PHRASE #{total_blocks}: строка [TEXT] не собрала 3 варианта")  # 💬 чтобы не путало с POLL

                    else:
                        polls.append({
                            "type": "quiz",
                            "question": q,
                            "options": options,          # 💬 всегда 3 варианта
                            "correct_answer": correct    # 💬 правильный до перемешки всегда первый
                        })
                else:
                    errors.append(f"PHRASE #{total_blocks}: строка [TEXT] мало полей")  # 💬 чтобы не путало с POLL


                i += 1
                continue


            # 💬 новый формат внутри [POLL]
            if section == "POLL":
                # 💬 фикс зависания: всегда двигаем индекс строки, иначе бесконечный цикл
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    errors.append(f"PHRASE #{total_blocks}: строка [POLL] мало полей")
                    i += 1
                    continue

                q = parts[0]
                correct = parts[1]          # 💬 правильный всегда первый после |
                wrongs = parts[2:4]         # 💬 только 2 ошибки = всего 3 варианта
                extra_correct = parts[4] if len(parts) >= 5 else ""  # 💬 старый формат: лишнее как пояснение

                polls.append({
                    "type": "quiz",
                    "question": q,
                    "options": [correct] + [w for w in wrongs if w],
                    "correct_answer": correct,
                    "explanation_correct": extra_correct,
                })
                i += 1
                continue





            # 💬 новый формат внутри [TEXT]
            if section == "TEXT":
                payload = _nl(line)
                parts = [p.strip() for p in payload.split("|") if p.strip()]
                # формат: вопрос | ответ
                if len(parts) >= 2:
                    q = "|".join(parts[:-1]).strip()
                    ans = parts[-1].strip()
                    textquizzes.append({
                        "type": "textquiz",
                        "question": q,
                        "correct_answer": ans
                    })
                else:
                    errors.append(f"PHRASE #{total_blocks}: строка [TEXT] мало полей")
                i += 1
                continue

            # 💬 неизвестное содержимое внутри PHRASE игнорируем
            i += 1

        # 💬 если [/PHRASE] не найден = сообщение оборвалось = этот блок не сохраняем
        if i >= len(lines) or lines[i] != "[/PHRASE]":
            truncated_at = {"block": total_blocks, "es_preview": (es or "")[:60]}
            break

        # 💬 пропускаем [/PHRASE]
        i += 1

        if not es or not ru:
            invalid_blocks += 1
            errors.append(f"PHRASE #{total_blocks}: нет ES или RU")
            continue

        ph = {"es": es, "ru": ru}
        if polls:
            ph["polls"] = polls
        if textquizzes:
            ph["textquizzes"] = textquizzes  # 💬 core8_1 v100 это понимает

        phrases.append(ph)

    meta = {
        "found": total_blocks,
        "saved": len(phrases),
        "invalid": invalid_blocks,
        "truncated": 1 if truncated_at else 0,
        "truncated_at": truncated_at
    }
    return phrases, errors, meta




@router.message(NewTopicStates.waiting_vocab_allin_bulk)
async def import_vocab_allin_bulk(message: Message, state: FSMContext):
    # 💬 авто-режим: вставил блок = сохранили = остаёмся в ожидании следующей вставки
    text = (message.text or "").strip()
    if text == "🆕 Новая тема":
        data = await state.get_data()
        topic_data = data.get("topic")
        topic_path = data.get("topic_path")
        category = (topic_data or {}).get("category")
        level = data.get("topic_level")

        if isinstance(topic_data, dict) and topic_path:
            atomic_save_json(topic_path, topic_data)  # 💬 сохраняем черновик темы перед переходом

        if category and level:
            await state.set_data({
                "topic": {"category": category},
                "topic_level": level,
                ADMIN_TOPIC_FLOW_KEY: True,
            })
            await state.set_state(NewTopicStates.waiting_topic_name)
            await message.answer("Введите название темы", reply_markup=ReplyKeyboardRemove())
            return

        # 💬 если обязательных данных нет — возвращаемся в стандартный старт /addtopic
        await start_adding_topic(message, state)
        return

    if text == "↩️ Назад":
        # 💬 возвращаемся в меню фазы
        await send_post_menu(message, state)
        return

    data = await state.get_data()
    category_now = ((data.get("topic") or {}).get("category") or "").strip().lower()
    if category_now.startswith("gram"):
        await message.answer(
            "⚠️ ALL IN доступен только для «📚 Лексика».\n"
            "Для грамматики используй «📥 Пулквизы».",  # 💬 защита от ALL IN в грамматике
            reply_markup=ReplyKeyboardRemove()
        )
        return await send_post_menu(message, state)

    if data.get("allin_force_new_phase"):
        await state.update_data(allin_force_new_phase=False)  # 💬 сбрасываем флаг, чтобы не создавать фазы повторно
        await _create_vocab_phase_auto(state)  # 💬 каждый ALL IN = новая фаза (пак)
        data = await state.get_data()  # 💬 обновляем topic/current_phase_id после автосоздания фазы


    topic_data = data["topic"]
    topic_path = data["topic_path"]
    cp = data.get("current_phase_id")

    phrases_objs, errors, meta = _parse_allin_block(text)

    # 💬 мягкая валидация: показываем ошибки, но всё равно сохраняем то, что корректно
    warn_lines: list[str] = []
    if errors:
        warn_lines.append("⚠️ Ошибки (первые 10):")
        warn_lines.extend(errors[:10])

    truncated_at = (meta or {}).get("truncated_at")
    if truncated_at:
        warn_lines.append(
            f"⚠️ Похоже сообщение оборвалось на PHRASE #{truncated_at.get('block')}"
        )
        es_prev = truncated_at.get("es_preview") or ""
        if es_prev:
            warn_lines.append(f"⚠️ ES: {es_prev}")

    phases = topic_data.get("vocab", [])
    phase = next((p for p in phases if p.get("phase_id") == cp), None)
    if not phase:
        await message.answer("❌ Фаза не найдена. Выберите фазу заново.")
        await state.set_state(NewTopicStates.waiting_phase_choice)
        return

    before_cnt = len(phase.get("phrases", []) or [])
    phase.setdefault("phrases", []).extend(phrases_objs)
    added_cnt = len(phase.get("phrases", []) or []) - before_cnt

    # 💬 сохраняем сразу в /data/topics (Railway Volume) атомарно, без риска частичной записи
    ok = atomic_save_json(topic_path, topic_data)
    if not ok:
        await message.answer("❌ Не смог сохранить в topics. Проверь Railway Volume и права записи.")
        return


    await state.update_data(topic=topic_data)

    # 💬 если ALL IN добавляли из режима редактирования = возвращаемся в edit-меню лексики
    if data.get("edit_mode"):
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
                [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
                [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
                [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
                [KeyboardButton(text="↩️ Вернуться в Главное меню")],
            ],
            resize_keyboard=True,
        )
        await message.answer("✅ ALL IN добавлен. Возвращаю в режим редактирования.", reply_markup=kb)
        await state.set_state(EditTopicStates.choose_action)
        return


    found = (meta or {}).get("found", 0)
    saved = (meta or {}).get("saved", 0)
    invalid = (meta or {}).get("invalid", 0)
    truncated = (meta or {}).get("truncated", 0)

    # 💬 если сообщение НЕ обрезано, то следующий ALL IN должен идти в новую фазу
    # 💬 (если обрезано = пользователь пришлёт продолжение и оно должно попасть в ТУ ЖЕ фазу)
    if (not truncated) and added_cnt > 0:
        await state.update_data(allin_force_new_phase=True)


    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="↩️ Назад")],
            [KeyboardButton(text="🆕 Новая тема")],
        ],
        resize_keyboard=True
    )

    msg_lines = [
        "✅ ALL IN сохранено",
        f"📌 Найдено PHRASE: {found}",
        f"✅ Сохранено фраз: {saved}",
        f"✅ Добавлено в фазу: {added_cnt}",
    ]
    if invalid:
        msg_lines.append(f"⚠️ Пропущено из-за ES/RU: {invalid}")
    if truncated:
        msg_lines.append("⚠️ Обрезанный хвост не сохранён, пришли продолжение отдельным сообщением")

    if warn_lines:
        msg_lines.append("")
        msg_lines.extend(warn_lines)

    await message.answer("\n".join(msg_lines), reply_markup=kb)

    # 💬 остаёмся в режиме приёма следующего блока
    await state.set_state(NewTopicStates.waiting_vocab_allin_bulk)



@router.message(NewTopicStates.waiting_vocab_quiz_bulk)
async def import_vocab_quiz_bulk(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    data = await state.get_data()

    category_now = ((data.get("topic") or {}).get("category") or "").strip()  # 💬 lex/gram

    # 💬 этот bulk нужен только для грамматики (теория)
    if category_now != "gram":
        await message.answer(
            "❌ Пулквизы доступны только в разделе Грамматика.",
            reply_markup=ReplyKeyboardRemove()
        )
        await send_post_menu(message, state)
        return

    cp = data.get("current_phase_id")
    topic = data.get("topic") or {}

    if not cp or not isinstance(cp, int) or cp < 1 or cp > len(topic.get("vocab") or []):
        await message.answer("❌ Сначала выбери фазу заново (Теория).", reply_markup=ReplyKeyboardRemove())  # 💬 защита от рассинхрона phase_id
        keyboard = get_main_menu("gram")
        await message.answer("Возвращаемся в Главное меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    lines_in = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    added, skipped, skipped_idx = 0, 0, []

    for i, ln in enumerate(lines_in, start=1):
        parts = [p.strip() for p in ln.split("|")]

        # 💬 строго 4 поля = защищаемся от '|' внутри полей
        if len(parts) != 4 or not parts[0] or not parts[1] or not parts[2] or not parts[3]:
            skipped += 1
            skipped_idx.append(i)
            continue

        q, correct, wrong1, wrong2 = parts[0], parts[1], parts[2], parts[3]

        block = {
            "type": "quiz",  # 💬 POLL-квиз в теории
            "question": q,
            "options": [correct, wrong1, wrong2],  # 💬 правильный всегда первый в options
            "correct_answer": correct
        }

        topic["vocab"][cp - 1].setdefault("vocab", []).append(block)
        added += 1

    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)  # 💬 сохраняем именно JSON грамматической темы

    if skipped:
        await message.answer(
            f"✅ POLL: добавлено {added}.\n⚠️ Пропущено {skipped} (строки: {', '.join(map(str, skipped_idx))}).",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await message.answer(f"✅ POLL: добавлено {added}.", reply_markup=ReplyKeyboardRemove())

    await send_post_menu(message, state)


# ——— FINISH TextQuiz ———




# ——— 📚 словарь ———
# 1) Запрашиваем заголовок словаря
@router.message(NewTopicStates.waiting_vocab_title)
async def get_vocab_title(message: Message, state: FSMContext):
    # Сохраняем title словаря
    vocab_title = message.text.strip()
    await state.update_data(current_vocab_title=vocab_title)
    # Переходим к запросу ссылки/текста словаря
    await message.answer("Введите ССЫЛКУ или ТЕКСТ словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_link)

# 2) Запрашиваем ссылку или текст словаря
@router.message(NewTopicStates.waiting_vocab_link)
async def get_vocab_link(message: Message, state: FSMContext):
    raw_input = message.text.strip()

    # Если в тексте есть <iframe>, то вытягиваем значение src="..."
    if "<iframe" in raw_input:
        src_index = raw_input.find('src="')
        if src_index != -1:
            # начало содержимого ссылки (после src=")
            start = src_index + len('src="')
            end = raw_input.find('"', start)
            if end != -1:
                vocab_link = raw_input[start:end]
            else:
                # Если закрывающая кавычка не найдена, просто сохраняем как есть
                vocab_link = raw_input
        else:
            # Не нашли src, сохраняем как есть
            vocab_link = raw_input
    else:
        vocab_link = raw_input

    data = await state.get_data()
    topic_data = data["topic"]
    topic_path = data["topic_path"]

    # Собираем новый блок словаря
    new_block = {
        "title": data.get("current_vocab_title"),
        "link": vocab_link
    }

    # Обновляем в памяти и в JSON-файле
    # 💬 сохраняем блок в выбранной фазе
    data = await state.get_data()
    cp = data.get("current_phase_id")
    topic_data = data["topic"]

    if cp is None:
        phase_idx = data.get("edit_gram_phase_index")
        if phase_idx is not None:
            try:
                cp = int(phase_idx) + 1
                await state.update_data(current_phase_id=cp)  # 💬 восстанавливаем фазу для вставки в режиме редактирования
            except Exception:
                cp = None

    try:
        cp = int(cp)
    except Exception:
        cp = None

    vocab_phases = topic_data.get("vocab") or []
    if cp is None or cp < 1 or cp > len(vocab_phases):
        await message.answer("⚠️ Не вижу активную фазу теории. Выбери фазу заново.", reply_markup=ReplyKeyboardRemove())
        if data.get("edit_gram_section") == "📖 Теория" or data.get("edit_insert_mode"):
            await state.set_state(EditGrammarStates.waiting_phase)  # 💬 назад к выбору фазы в редактировании
        else:
            await state.set_state(NewTopicStates.waiting_phase_choice)  # 💬 назад к выбору фазы при создании
        return

    insert_index = data.get("edit_insert_index") if data.get("edit_insert_mode") else None  # 💬 индекс вставки (1-based)
    topic_data["vocab"][cp - 1].setdefault("vocab", [])
    _insert_or_append(topic_data["vocab"][cp - 1]["vocab"], new_block, insert_index)  # 💬 вставка по индексу или append





    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

       # … после записи в JSON и очистки current_vocab_title …
    await state.update_data(current_vocab_title=None, last_block="vocab")

    await message.answer("Словарь сохранён.", reply_markup=ReplyKeyboardRemove())
    if data.get("edit_insert_mode"):
        await state.update_data(edit_insert_mode=None, edit_insert_index=None)  # 💬 завершаем режим вставки
        return await _edit_grammar_show_list(message, state)  # 💬 возвращаемся в список редактирования

    await send_post_menu(message, state)



# 3) Пост-блоковое меню для всех блоков (часть 1)
@router.message(NewTopicStates.waiting_post_action)
async def handle_post_action(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    last_block = data.get("last_block")

    # ─── БЛОК «СЛОВАРЬ» ───
    if last_block == "vocab":
        category_now = ((data.get("topic") or {}).get("category") or "").strip().lower()  # 💬 lex/gram в текущей теме
        if category_now.startswith("gram"):
            category_now = "gram"
        elif category_now.startswith("lex"):
            category_now = "lex"

        pressed = (text or "").replace(" ", "")  # 💬 нормализуем кнопку, иногда Телеграм добавляет пробелы

        if category_now == "gram" and pressed == "📘VOC":
            # 💬 защита: VOC не должен жить в грамматике (иначе уводит в круг фаз)
            await message.answer(
                "❌ VOC доступен только в разделе Лексика.\n"
                "Для грамматики используй 📝ТЕКСТ, 🖼FOTO или 📥 Пулквизы.",
                reply_markup=ReplyKeyboardRemove()
            )
            await send_post_menu(message, state)
            return

        if category_now == "gram" and pressed == "🧩ALLIN":
            # 💬 защита: ALL IN только для лексики, в грамматике не даём уходить в этот flow
            await message.answer(
                "❌ ALL IN доступен только в разделе Лексика.\n"
                "Для грамматики используй 📝ТЕКСТ или 🖼FOTO.",
                reply_markup=ReplyKeyboardRemove()
            )
            await send_post_menu(message, state)
            return


        # 💬 для лексики отключаем старые ветки vocab = оставляем только ALL IN (phrases)
        disabled = {
            "🔗 LINK",
            "📥QUIZ",
            "📥TXT_QUIZ",
            "📝ТЕКСТ",
            "🖼FOTO",
            "📝 Текст",
            "🖼 Фото",
            "📥 Пулквизы",
        }
        if category_now != "gram" and text in disabled:
            await message.answer(
                "❌ Эта ветка отключена.\n"
                "Используй 🧩 ALL IN (phrases).",
                reply_markup=ReplyKeyboardRemove()
            )
            await send_post_menu(message, state)
            return

        if text == "🧩 ALL IN":
            await state.update_data(
                allin_force_new_phase=True  # 💬 для ALL IN создаём новую фазу именно на следующей вставке текста
            )

            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="↩️ Назад")]],
                resize_keyboard=True
            )

            await message.answer(
                "Вставь ALL IN блок одним сообщением.\n"
                "Пустые строки игнорируются.\n\n"
                "[PHRASE]\n"
                "ES: pagar con tarjeta\n"
                "RU: платить картой\n"
                "[POLL]\n"
                "...\n"
                "...\n"
                "...\n"
                "...\n"
                "[TEXT]\n"
                "...\n"
                "[/PHRASE]",
                reply_markup=kb
            )  # 💬 подсказка формата для админа
            await state.set_state(NewTopicStates.waiting_vocab_allin_bulk)
            return


        if text == "📘VOC":
            data = await state.get_data()
            topic = data["topic"]
            phases = topic.get("vocab", [])

            # 💬 всегда даём выбор фазы, чтобы можно было перейти на 2-ю, 3-ю и т.д.
            if not phases:
                new_phase = await _create_vocab_phase_auto(state)  # 💬 создаём пак автоматически
                await message.answer(
                    f"Создан: {new_phase['phase_name']}",
                    reply_markup=ReplyKeyboardRemove()
                )  # 💬 пропускаем ввод названия
                await send_post_menu(message, state)  # 💬 сразу показываем кнопки словаря
                return


            buttons = [
                [KeyboardButton(text=f"{p['phase_id']}. {p['phase_name']}")]
                for p in phases
            ]
            buttons.append([KeyboardButton(text="➕ Новая фаза")])
            kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

            await message.answer(
                "Выберите фазу или создайте новую:",
                reply_markup=kb
            )
            await state.set_state(NewTopicStates.waiting_phase_choice)
            return



        # — Добавить ТЕКСТ
        if text == "📝ТЕКСТ":
            await message.answer("📝 Введите произвольный текст-блок для словаря:")
            await state.set_state(NewTopicStates.waiting_vocab_text)
            return
        # ——— Добавить фото словаря ———
        if text == "🖼FOTO" and last_block == "vocab":
            await message.answer("Введите подпись к фото словаря или '-' для пропуска:", reply_markup=ReplyKeyboardRemove())
            await state.set_state(NewTopicStates.waiting_vocab_photo_text)
            return

  
            await state.set_state(NewTopicStates.waiting_ad_source)
            return




    # ─── БЛОК «УПРАЖНЕНИЕ» ───
    if last_block == "exercise":
        if text == "🔄 Создать ещё упражнение":
            await message.answer("Введите НАЗВАНИЕ упражнения:")
            return await state.set_state(NewTopicStates.waiting_ex_title)

        # 💬 в практике больше нет текст/фото кнопок, чтобы не расходиться с GrammarFuture


            return await state.set_state(NewTopicStates.waiting_ex_photo_text)
    # ─── БЛОК «ВИДЕО» ───
    if last_block == "video" and text == "🔄 Создать ещё видео":
        data = await state.get_data()
        topic = data.get("topic") or {}

        # 💬 авто-тайтл по количеству уже добавленных видео
        existing_videos = topic.get("videos") or []
        auto_title = f"Video {len(existing_videos) + 1}"

        await state.update_data(current_video_title=auto_title, last_block="video")

        # 💬 сразу просим ссылку, без шага ввода названия
        await message.answer("Пришли ссылку на видео (или iframe):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(NewTopicStates.waiting_video_link)
        return



    if data.get("edit_insert_mode") and text == "↩️ Назад":
        await state.update_data(edit_insert_mode=None, edit_insert_index=None)  # 💬 выходим из режима вставки
        return await _edit_grammar_show_list(message, state)  # 💬 назад в список редактирования

    # ─── Вернуться в Главное меню ───
    if text == "↩️ Вернуться в Главное меню":
        category_now = ((data.get("topic") or {}).get("category") or "").strip()  # 💬 возвращаемся в правильное меню
        keyboard = get_main_menu(category_now)
        await message.answer("Возвращаемся в Главное меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return


    # ─── Некорректный ввод ───
    if last_block == "vocab":
        category_now = ((data.get("topic") or {}).get("category") or "").strip()  # 💬 показываем актуальные кнопки
        if category_now == "gram":
            await message.answer(
                "❗ Пожалуйста, нажми одну из кнопок: «📝ТЕКСТ», «🖼FOTO» или «↩️ Вернуться в Главное меню»."

            )
        else:
            await message.answer(
                "❗ Пожалуйста, нажми одну из кнопок: «📘VOC», «🧩 ALL IN» или «↩️ Вернуться в Главное меню»."
            )
        return

    await message.answer("❗ Пожалуйста, нажми «↩️ Вернуться в Главное меню».")











# === БЛОК “УПРАЖНЕНИЕ (ОБЩЕЕ)” ===


# 1) Сохраняем название упражнения
@router.message(NewTopicStates.waiting_ex_title)
async def get_ex_title(message: Message, state: FSMContext):
    await state.update_data(current_ex_title=message.text.strip())  # 💬 запоминаем title
    await message.answer("Введите ССЫЛКУ или iframe для упражнения:")  # 💬 без шага инструкции
    await state.set_state(NewTopicStates.waiting_ex_url)

# 2) Совместимость со старым шагом (если кто то уже попал в waiting_ex_instr)
@router.message(NewTopicStates.waiting_ex_instr)
async def get_ex_instr(message: Message, state: FSMContext):
    await state.update_data(current_ex_instr=None)  # 💬 инструкцию больше не используем
    await state.set_state(NewTopicStates.waiting_ex_url)  # 💬 перенаправляем на ввод ссылки
    return await get_ex_link(message, state)

# 3) Сохраняем упражнение (title + link) и возвращаем Главное меню
@router.message(NewTopicStates.waiting_ex_url)
async def get_ex_link(message: Message, state: FSMContext):
    raw = message.text.strip()

    # 💬 вытягиваем src из iframe, если нужно
    if "<iframe" in raw and 'src="' in raw:
        link = raw.split('src="', 1)[1].split('"', 1)[0]
    else:
        link = raw

    data = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]

    new_block = {
        "title": data["current_ex_title"],
        "link":  link
    }
    ex_list = topic.setdefault("exercises", [])
    insert_index = data.get("edit_insert_index") if data.get("edit_insert_mode") else None
    _insert_or_append(ex_list, new_block, insert_index)  # 💬 вставка по индексу или append


    atomic_save_json(topic_path, topic)  # 💬 сохраняем в volume Railway безопасно (atomic)

    # 💬 очищаем временные поля
    await state.update_data(current_ex_title=None, current_ex_instr=None)

    await message.answer("✅ Упражнение сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)







# ——— Добавить текст ———
@router.message(NewTopicStates.waiting_ex_text)
async def save_ex_text(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    topic = data["topic"]
    ex_list = topic.setdefault("exercises", [])
    insert_index = data.get("edit_insert_index") if data.get("edit_insert_mode") else None
    _insert_or_append(ex_list, {"type": "text", "text": text}, insert_index)  # 💬 вставка по индексу или append

    atomic_save_json(data["topic_path"], topic)  # 💬 сохраняем в volume Railway безопасно (atomic)

    await message.answer("Текст упражнения сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)







@router.message(NewTopicStates.waiting_ex_photo_text, F.text)
async def handle_ex_photo_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == '-':
        await state.update_data(ex_photo_caption=None)
    else:
        await state.update_data(ex_photo_caption=text)
    await message.answer("🖼 Пришлите фото, GIF/MP4 или стикер для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_photo)


# ——— Добавить фото/гиф/стикер к упражнению ———
@router.message(NewTopicStates.waiting_ex_photo, F.content_type.in_(["photo", "video", "animation", "sticker", "text"]))
async def save_ex_photo(message: Message, state: FSMContext):
    import time
    from pathlib import Path

    data = await state.get_data()
    topic = data["topic"]
    path = data["topic_path"]

    # создаём папку для медиа
    theme_dir = Path("exercise_images") / topic["title"]
    theme_dir.mkdir(parents=True, exist_ok=True)

    entry = {"type": "photo"}  # общий блок

    # 1) Если это стикер — сохраняем file_id
    if message.sticker:
        entry["media_type"] = "sticker"
        entry["photo"] = message.sticker.file_id

    # 2) Если видео/GIF
    elif message.animation or message.video:
        media = message.animation or message.video
        entry["media_type"] = "animation"
        stamp = int(time.time())
        fname = f"ex_{stamp}_{media.file_id[-5:]}.mp4"
        dest = theme_dir / fname
        file = await message.bot.get_file(media.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 3) Если фото (jpg/png)
    elif message.photo:
        ph = message.photo[-1]
        entry["media_type"] = "photo"
        stamp = int(time.time())
        fname = f"ex_{stamp}_{ph.file_id[-5:]}.jpg"
        dest = theme_dir / fname
        file = await message.bot.get_file(ph.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 4) Если прислан текст (URL или sticker_id)
    else:
        url = message.text.strip()
        lower = url.lower()
        if lower.endswith((".mp4", ".gif")):
            entry["media_type"] = "animation"
        elif lower.endswith((".jpg", ".jpeg", ".png")):
            entry["media_type"] = "photo"
        else:
            entry["media_type"] = "sticker"
        entry["photo"] = url


    # 💬 Сохраняем подпись, если она была добавлена на предыдущем шаге
    if data.get("ex_photo_caption"):
        entry["text"] = data["ex_photo_caption"]
        await state.update_data(ex_photo_caption=None)


    topic.setdefault("exercises", []).append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await message.answer("Медиа упражнения сохранено.", reply_markup=ReplyKeyboardRemove())
    if data.get("edit_insert_mode"):
        await state.update_data(edit_insert_mode=None, edit_insert_index=None)  # 💬 сбрасываем режим вставки
        return await _edit_grammar_show_list(message, state)  # 💬 возвращаемся в список редактирования

    await send_post_menu(message, state)













#------БЛОКИ ДЛЯ "📝 Добавить ТЕКСТ"----------


# 💬 короткие теги для грамматики в Теории (конвертим в Telegram HTML и сохраняем сразу в JSON)
_ALLOWED_GRAM_SHORT_TAGS = {"u", "st", "sp", "q", "b", "i"}  # 💬 b/i на будущее, вложенность всё равно запрещена


def _escape_tg_html(s: str) -> str:
    # 💬 экранируем HTML, чтобы пользовательский ввод не ломал parse_mode="HTML"
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _unescape_allowed_gram_html(s: str) -> str:
    # 💬 разворачиваем только белый список Telegram-HTML тегов, если они пришли экранированными
    out = str(s or "")
    if not out:
        return ""

    for tag in ("u", "s", "b", "i", "blockquote", "tg-spoiler"):
        out = out.replace(f"&lt;{tag}&gt;", f"<{tag}>")
        out = out.replace(f"&lt;/{tag}&gt;", f"</{tag}>")

    # 💬 spoiler через span class для совместимости
    out = out.replace("&lt;span class=&quot;tg-spoiler&quot;&gt;", '<span class="tg-spoiler">')
    out = out.replace("&lt;/span&gt;", "</span>")

    # 💬 переносы
    out = out.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br/>").replace("&lt;br /&gt;", "<br />")

    return out



def _convert_gram_short_tags_to_html(raw: str):
    """
    # 💬 конвертирует [u]/[st]/[sp]/[q] в Telegram HTML
    # 💬 вложенность запрещена, неизвестные теги запрещены
    return: (html_text, error_text)
    """
    s = (raw or "")
    out_parts = []
    plain_buf = []
    open_tag = None
    inner_buf = []

    def _flush_plain():
        if plain_buf:
            out_parts.append(_escape_tg_html("".join(plain_buf)))
            plain_buf.clear()

    def _render_tag(tag: str, inner: str) -> str:
        inner_esc = _escape_tg_html(inner)
        if tag == "u":
            return f"<u>{inner_esc}</u>"
        if tag == "st":
            return f"<s>{inner_esc}</s>"
        if tag == "b":
            return f"<b>{inner_esc}</b>"
        if tag == "i":
            return f"<i>{inner_esc}</i>"
        if tag == "sp":
            # 💬 самый совместимый spoiler для Telegram HTML
            return f'<span class="tg-spoiler">{inner_esc}</span>'
        if tag == "q":
            # 💬 quote только через префикс строк, без <blockquote> (совместимость)
            lines = inner_esc.splitlines()
            prefixed = "\n".join([("› " + ln) if ln.strip() else "" for ln in lines])
            return prefixed

        return inner_esc  # 💬 сюда не должны попасть

    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "[":
            j = s.find("]", i + 1)
            if j != -1:
                token = s[i:j + 1]
                is_close = token.startswith("[/")
                name = token[2:-1] if is_close else token[1:-1]

                if name.isalpha():
                    tag = name.lower()

                    if tag not in _ALLOWED_GRAM_SHORT_TAGS:
                        return None, (
                            "⚠️ Найден неизвестный тег.\n\n"
                            "Разрешено: [u] [st] [sp] [q]\n"
                            "Пример:\n"
                            "[u]underline[/u]\n"
                            "[sp]spoiler[/sp]\n"
                            "[q]quote[/q]\n"
                            "[st]strike[/st]\n\n"
                            "# 💬 вложенность запрещена"
                        )

                    if open_tag is None:
                        if is_close:
                            return None, "⚠️ Найден закрывающий тег без открывающего. Исправь разметку. # 💬 защита"
                        _flush_plain()
                        open_tag = tag
                        inner_buf = []
                    else:
                        # 💬 внутри тега любые другие теги запрещены
                        if (not is_close) or (tag != open_tag):
                            return None, "⚠️ Вложенность или несовпадение тегов запрещены. Исправь разметку. # 💬 защита"
                        # закрываем корректно
                        out_parts.append(_render_tag(open_tag, "".join(inner_buf)))
                        open_tag = None
                        inner_buf = []

                    i = j + 1
                    continue

        # обычный символ
        if open_tag is None:
            plain_buf.append(ch)
        else:
            inner_buf.append(ch)
        i += 1

    if open_tag is not None:
        return None, "⚠️ Тег не закрыт. Добавь закрывающий [/...] и пришли снова. # 💬 защита"

    _flush_plain()
    return "".join(out_parts), None



@router.message(NewTopicStates.waiting_post_action, F.text == "📝ТЕКСТ")
async def ask_vocab_text(message: Message, state: FSMContext):
    await message.answer("📝 Введите произвольный ТЕКСТ-блок для словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_text)



@router.message(NewTopicStates.waiting_vocab_text)
async def save_vocab_text_block(message: Message, state: FSMContext):
    text_raw = (message.text or "").strip()
    data = await state.get_data()
    cp   = data.get("current_phase_id")  # 💬 защита: ключ может отсутствовать при сбитом FSM
    topic = data.get("topic") or {}      # 💬 защита: topic может быть None


    if not text_raw:
        await message.answer("⚠️ Пришли текст. Пустое сообщение не сохраняю. # 💬 защита")
        return

    category_now = ((topic.get("category") or "").strip().lower())

    # 💬 только грамматика, только Теория (в CreateLessonBlock Теория хранится в topic["vocab"][phase]["vocab"])
    if category_now.startswith("gram"):
        html_text, err = _convert_gram_short_tags_to_html(text_raw)
        if err:
            await message.answer(err)  # 💬 остаёмся в этом же state, чтобы ты прислал исправленный текст
            return
            
        html_text = _unescape_allowed_gram_html(html_text)  # 💬 поддержка: Telegram HTML мог быть введён напрямую
        new_block = {"type": "text", "text": html_text, "raw": text_raw}  # 💬 text уже Telegram HTML, raw для редактирования
    else:
        # 💬 лексика и прочее сохраняем как раньше
        new_block = {"type": "text", "text": text_raw}


    if cp is None:
        phase_idx = data.get("edit_gram_phase_index")
        if phase_idx is not None:
            try:
                cp = int(phase_idx) + 1
                await state.update_data(current_phase_id=cp)  # 💬 восстанавливаем фазу для вставки в режиме редактирования
            except Exception:
                cp = None

    try:
        cp = int(cp)
    except Exception:
        cp = None

    vocab_phases = topic.get("vocab") or []
    if cp is None or cp < 1 or cp > len(vocab_phases):
        await message.answer("⚠️ Не вижу активную фазу теории. Выбери фазу заново.", reply_markup=ReplyKeyboardRemove())
        if data.get("edit_gram_section") == "📖 Теория" or data.get("edit_insert_mode"):
            return await state.set_state(EditGrammarStates.waiting_phase)  # 💬 назад к выбору фазы в редактировании
        return await state.set_state(NewTopicStates.waiting_phase_choice)  # 💬 назад к выбору фазы при создании

    # 1) Сохраняем текстовый блок
    # 💬 new_block уже собран выше (gram: Telegram HTML + raw / lex: plain text)
    insert_index = data.get("edit_insert_index") if data.get("edit_insert_mode") else None  # 💬 индекс вставки (1-based)
    topic["vocab"][cp - 1].setdefault("vocab", [])
    _insert_or_append(topic["vocab"][cp - 1]["vocab"], new_block, insert_index)  # 💬 вставка по индексу или append


    # 2) Записываем в файл
    atomic_save_json(data["topic_path"], topic)  # 💬 сохраняем в volume Railway безопасно (atomic)

    # 3) Сразу возвращаемся в пост-меню без квиза
    await message.answer("Текст словаря сохранён.", reply_markup=ReplyKeyboardRemove())
    if data.get("edit_insert_mode"):
        await state.update_data(edit_insert_mode=None, edit_insert_index=None)  # 💬 завершаем режим вставки
        return await _edit_grammar_show_list(message, state)  # 💬 назад в список редактирования

    await send_post_menu(message, state)







# ------ БЛОКИ ДЛЯ "🖼 Добавить ФОТО / PHOTO"----------
@router.message(NewTopicStates.waiting_post_action, F.text=="🖼FOTO")
async def ask_vocab_caption(message: Message, state: FSMContext):
    # 💬 Спросить подпись или '-' для пропуска
    await message.answer(
        "Введите подпись к фото словаря или '-' для пропуска:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(NewTopicStates.waiting_vocab_photo_text)

@router.message(NewTopicStates.waiting_vocab_photo_text)
async def handle_vocab_text(message: Message, state: FSMContext):
    # 💬 в этом state ждём подпись, но пользователь может прислать медиа или URL сразу
    if message.text is None:
        await state.update_data(vocab_caption=None)  # 💬 подписи нет = считаем пропуск

        if message.photo or message.video or message.animation or message.sticker:
            await state.set_state(NewTopicStates.waiting_vocab_photo)  # 💬 переводим на приём медиа
            return await receive_vocab_media(message, state)  # 💬 сохраняем медиа без второго шага

        await message.answer("Введите подпись к фото словаря или '-' для пропуска:")
        return

    raw = message.text.strip()
    if not raw:
        await message.answer("Введите подпись к фото словаря или '-' для пропуска:")
        return

    lower = raw.lower()

    # 💬 если вместо подписи прислали URL медиа = принимаем его сразу как фото/гиф/видео
    if raw.startswith(("http://", "https://", "www.")) and lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".mp4")):
        await state.update_data(vocab_caption=None)  # 💬 подпись пропущена
        await state.set_state(NewTopicStates.waiting_vocab_photo)  # 💬 переводим на приём медиа
        return await receive_vocab_media(message, state)  # 💬 receive_vocab_media сам распознает URL

    # 💬 обычный режим = сохраняем подпись
    if raw == "-":
        await state.update_data(vocab_caption=None)
    else:
        await state.update_data(vocab_caption=raw)

    # 💬 теперь запрашиваем само фото или URL
    await message.answer(
        "🖼 Пришлите фотографию (JPG/PNG) или URL картинки для словаря:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(NewTopicStates.waiting_vocab_photo)



# === БЛОК ДЛЯ "🖼 Добавить ФОТО / PHOTO" — расширенный вариант с GIF и стикерами ===

from pathlib import Path
import time
@router.message(NewTopicStates.waiting_vocab_photo, F.content_type.in_(["photo", "video", "animation", "sticker", "text"]))
async def receive_vocab_media(message: Message, state: FSMContext):
    # 💬 сохраняем фото/медиа как Telegram file_id (или URL) прямо в JSON, без скачивания на диск
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    if not topic_path:
        await message.answer("⚠️ Ошибка: не найден topic_path. Попробуй заново открыть создание темы.")
        return

    entry = {"type": "photo"}  # 💬 единый формат блока фото/медиа

    # 1) Стикер
    if message.sticker:
        entry["media_type"] = "sticker"
        entry["photo"] = message.sticker.file_id

    # 2) GIF/Видео (animation или video)
    elif message.animation or message.video:
        media = message.animation or message.video
        entry["media_type"] = "animation"
        entry["photo"] = media.file_id

    # 3) Фото
    elif message.photo:
        ph = message.photo[-1]
        entry["media_type"] = "photo"
        entry["photo"] = ph.file_id

    # 4) Текст (URL)
    else:
        url = (message.text or "").strip()
        lower = url.lower()

        if lower.endswith((".mp4", ".gif")):
            entry["media_type"] = "animation"
        elif lower.endswith((".jpg", ".jpeg", ".png")):
            entry["media_type"] = "photo"
        else:
            entry["media_type"] = "photo"  # 💬 по умолчанию считаем, что это file_id/URL для фото
        entry["photo"] = url


    # 💬 подпись к фото (опционально): или из FSM, или из message.caption
    caption_state = data.get("vocab_caption")
    caption_inline = (getattr(message, "caption", None) or "").strip()

    caption = None
    if caption_state:
        caption = str(caption_state).strip()
    elif caption_inline:
        caption = caption_inline

    if caption == "-":
        caption = None  # 💬 поддержка пропуска подписи

    await state.update_data(vocab_caption=None)  # 💬 чистим всегда, чтобы подпись не прилипала к следующему фото

    if caption:
        entry["text"] = caption  # 💬 сохраняем подпись (если она есть)


    
    # 💬 сохраняем медиа-блок в выбранной фазе
    cp = data.get("current_phase_id")
    if cp is None:
        phase_idx = data.get("edit_gram_phase_index")
        if phase_idx is not None:
            try:
                cp = int(phase_idx) + 1
                await state.update_data(current_phase_id=cp)  # 💬 восстанавливаем фазу для вставки в режиме редактирования
            except Exception:
                cp = None

    try:
        cp = int(cp)
    except Exception:
        cp = None


    topic.setdefault("vocab", [])
    if cp is None or not (1 <= cp <= len(topic["vocab"])):
        await message.answer("⚠️ Ошибка: фаза не найдена. Выбери фазу заново.")
        if data.get("edit_gram_section") == "📖 Теория" or data.get("edit_insert_mode"):
            await state.set_state(EditGrammarStates.waiting_phase)  # 💬 назад к выбору фазы в редактировании
            return
        await state.set_state(NewTopicStates.waiting_phase_choice)  # 💬 назад к выбору фазы при создании
        return

    topic["vocab"][cp - 1].setdefault("vocab", [])
    insert_index = data.get("edit_insert_index") if data.get("edit_insert_mode") else None  # 💬 индекс вставки (1-based)
    _insert_or_append(topic["vocab"][cp - 1]["vocab"], entry, insert_index)  # 💬 вставка по индексу или append


    import json
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)

    # 💬 подтверждаем и возвращаемся в меню поста
    await message.answer("✅ Фото/медиа сохранено.", reply_markup=ReplyKeyboardRemove())
    if data.get("edit_insert_mode"):
        await state.update_data(edit_insert_mode=None, edit_insert_index=None)  # 💬 завершаем режим вставки
        return await _edit_grammar_show_list(message, state)  # 💬 назад в список редактирования

    await send_post_menu(message, state)








# === БЛОК “ВИДЕО” ===

# 1) Запрашиваем заголовок видео
@router.message(NewTopicStates.waiting_video_title)
async def get_video_title(message: Message, state: FSMContext):
    raw = (message.text or "").strip()

    data = await state.get_data()
    topic = data.get("topic") or {}
    existing_videos = topic.get("videos") or []
    auto_title = f"Video {len(existing_videos) + 1}"

    video_title = auto_title if raw == "-" else raw

    await state.update_data(current_video_title=video_title)
    # 💬 Переходим к запросу ссылки на видео
    await message.answer("Пришли ссылку на видео (или iframe):")
    await state.set_state(NewTopicStates.waiting_video_link)


# 2) Запрашиваем ссылку на видео, сохраняем и пост-меню
@router.message(NewTopicStates.waiting_video_link)
async def get_video_link(message: Message, state: FSMContext):
    raw_input = message.text.strip()

    # Если передан iframe, извлекаем src
    if "<iframe" in raw_input:
        src_index = raw_input.find('src="')
        if src_index != -1:
            start = src_index + len('src="')
            end = raw_input.find('"', start)
            if end != -1:
                video_link = raw_input[start:end]
            else:
                video_link = raw_input
        else:
            video_link = raw_input
    else:
        video_link = raw_input

    data = await state.get_data()
    topic_data = data["topic"]
    topic_path = data["topic_path"]
    # 💬 если title не задан (на всякий случай) = авто-тайтл Video N
    current_title = data.get("current_video_title")
    if not current_title:
        topic_data.setdefault("videos", [])
        current_title = f"Video {len(topic_data.get('videos') or []) + 1}"
        await state.update_data(current_video_title=current_title)


    new_video = {
        "title": data.get("current_video_title"),
        "link": video_link
    }

    # Сохраняем в памяти и сразу в файл
    topic_data.setdefault("videos", [])  # 💬 защита, если ключа нет в старых темах
    topic_data["videos"].append(new_video)
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Удаляем временную переменную + фиксируем обновлённую тему в state
    await state.update_data(topic=topic_data, current_video_title=None, last_block="video")


    # Показываем пост-блоковое меню
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Создать ещё видео"), KeyboardButton(text="↩️ Вернуться в Главное меню")]
        ],
        resize_keyboard=True
    )
    await message.answer("Видео сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)



@router.message(NewTopicStates.waiting_reading_title)
async def get_reading_title(message: Message, state: FSMContext):
    # 💬 создаём новый пакет чтения и сохраняем сразу в JSON, чтобы можно было добавлять частями
    title = ((message.text or "").strip() or "Чтение")

    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    if not topic_path:
        await message.answer("❗ Ошибка: не найден путь темы (topic_path).")
        return

    pack_key = "translate" if (data.get("last_block") == "translate") else "reading"  # 💬 выбираем ключ хранения
    
    if pack_key == "translate" and "translation" in topic and "translate" not in topic:
        pack_key = "translation"  # 💬 сохраняем в существующий ключ, чтобы не дробить структуру
    
    topic.setdefault(pack_key, []).append({
        "title": title,
        "fragments": [],
        "assets": []  # 💬 ассеты внутри конкретного пака
    })
    pack_index = len(topic[pack_key]) - 1  # 💬 индекс именно в выбранном ключе




    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(
        topic=topic,
        current_reading_pack_index=pack_index,
        current_reading_pack_key=pack_key,  # 💬 что делает эта часть: дальше фрагменты/фото сохраняем в правильный раздел
    )


    # ✅ после названия сразу переходим к вводу ассет-блоков
    pack_label = "перевода" if pack_key == "translate" else "чтения"

    if pack_key == "translate":
        await message.answer(
            f"Отправь ассет блоки для {pack_label} парами строк.\n"
            "Пример:\n"
            "Мы уже у кассы, я хочу <b>платить картой</b>\n"
            "[[👩: bueno mira oye <b>pagar con tarjeta</b>, digo no, espera]]\n\n"
            "Да, vale, но сначала я хочу <b>купить хлеб</b>\n"
            "[[🧑: pues venga vale <b>comprar pan</b>, pero oye, rápido]]",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            f"Отправь ассет блоки для {pack_label} текстом.\n"
            "Формат каждой строки: ES | RU | hint (опц.)\n"
            "Минимум 2 поля: ES | RU\n"
            "Символ | внутри полей запрещён\n\n"
            "Пример:\n"
            "Estoy listo. | Я готов. | 💡 listo = готовый\n"
            "¿Qué tal? | Как дела?",
            reply_markup=ReplyKeyboardRemove(),
        )

    return await state.set_state(NewTopicStates.waiting_reading_fragments_text)



@router.message(NewTopicStates.waiting_reading_action)
async def handle_reading_action(message: Message, state: FSMContext):
    # 💬 меню действий внутри одного пакета "Чтение"
    action = (message.text or "").strip()
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")
    pack_key = data.get("current_reading_pack_key") or ("translate" if data.get("last_block") == "translate" else "reading")  # 💬 определяем режим пакета
    pack_label = "перевода" if pack_key == "translate" else "чтения"  # 💬 текст для UI


    category_now = (topic.get("category") or "").strip().lower()
    if category_now.startswith("gram"):
        category_now = "gram"
    else:
        category_now = "lex"

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
            [KeyboardButton(text="🔄 Создать ещё"), KeyboardButton(text="↩️ Назад")],
        ],
        resize_keyboard=True,
    )

    if action == "🧩 Ассет блоки":
        # 💬 режим "перевод" = пары строк: RU-строка + ES-реплика [[...]]
        if pack_key == "translate":
            await message.answer(
                f"Отправь ассет блоки для {pack_label} парами строк.\n"
                "Пример:\n"
                "Мы уже у кассы, я хочу <b>платить картой</b>\n"
                "[[👩: bueno mira oye <b>pagar con tarjeta</b>, digo no, espera]]\n\n"
                "Да, vale, но сначала я хочу <b>купить хлеб</b>\n"
                "[[🧑: pues venga vale <b>comprar pan</b>, pero oye, rápido]]",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer(
                f"Отправь ассет блоки для {pack_label} текстом.\n"
                "Формат каждой строки: ES | RU | hint (опц.)\n"
                "Минимум 2 поля: ES | RU\n"
                "Символ | внутри полей запрещён\n\n"
                "Пример:\n"
                "Estoy listo. | Я готов. | 💡 listo = готовый\n"
                "¿Qué tal? | Как дела?",
                reply_markup=ReplyKeyboardRemove(),
            )

        return await state.set_state(NewTopicStates.waiting_reading_fragments_text)  # 💬 ждём ассет блоки

    if action == "🖼 Фото":
        await message.answer(
            "Напиши подпись к фото одним сообщением.\n"
            "Если подпись не нужна, отправь -",
            reply_markup=ReplyKeyboardRemove(),
        )
        return await state.set_state(NewTopicStates.waiting_reading_photo_text)

    if action in {"🔄 Создать ещё", "↩️ Назад"}:  # 💬 либо создаём следующий пакет, либо выходим назад

        # 💬 если пакет пустой = удаляем его, чтобы не плодить мусор
        try:
            idx = int(data.get("current_reading_pack_index"))
        except Exception:
            idx = None  # 💬 если индекса нет = ничего не удаляем

        if action == "🔄 Создать ещё":
            await state.update_data(
                current_reading_pack_index=None,
                current_reading_pack_key=None,
                reading_photo_caption=None,  # 💬 сбрасываем контекст текущего пакета перед созданием нового
            )
            await message.answer(
                f"✍️ Впишите название фазы {pack_label}:",
                reply_markup=ReplyKeyboardRemove(),  # 💬 снова ждём обычный текст
            )
            return await state.set_state(NewTopicStates.waiting_reading_title)

        packs_list = topic.get(pack_key) if pack_key in {"reading", "translate"} else topic.get("reading")  # 💬 выбираем правильный список пакетов
        if (
            topic_path
            and isinstance(packs_list, list)
            and idx is not None
            and 0 <= idx < len(packs_list)
        ):
            pack = packs_list[idx] or {}
            if not (pack.get("fragments") or pack.get("assets")):
                packs_list.pop(idx)
                try:
                    import json
                    with open(topic_path, "w", encoding="utf-8") as f:
                        json.dump(topic, f, ensure_ascii=False, indent=2)
                    await state.update_data(topic=topic)
                except Exception:
                    pass


        await state.update_data(
            current_reading_pack_index=None,
            current_reading_title=None,
            reading_photo_caption=None,
        )

        # 💬 если это редактирование грамматики = не прыгаем в меню лексики, возвращаемся в список Читать
        if data.get("edit_gram_section") == "📚 Читать":
            await message.answer("↩️ Вернулись к списку чтения.", reply_markup=ReplyKeyboardRemove())  # 💬 кнопки пакета убраны
            return await _edit_grammar_show_list(message, state)


        # 💬 обычный выход назад из пакета = возвращаемся в меню темы
        await message.answer("↩️ Вернулись назад.", reply_markup=get_main_menu(category_now))
        return await state.set_state(NewTopicStates.waiting_first_choice)


    await message.answer("Выбери действие кнопками.", reply_markup=kb)



@router.message(NewTopicStates.waiting_reading_fragments_text)
async def save_reading_fragments(message: Message, state: FSMContext):
    # 💬 сохраняем фрагменты в текущий пак чтения и возвращаемся в меню действий
    raw = (message.text or "").strip()
    if raw.lower() in {"назад", "↩️ назад"}:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
                [KeyboardButton(text="🔄 Создать ещё"), KeyboardButton(text="↩️ Назад")],
            ],
            resize_keyboard=True,
        )
        await message.answer("Ок, выбери действие.", reply_markup=kb)
        return await state.set_state(NewTopicStates.waiting_reading_action)

    lines_in = [line.strip() for line in raw.split("\n") if line.strip()]
    if not lines_in:
        await message.answer(
            "⚠️ Пусто. Пришли ассет блоки текстом.\n"
            "Формат: ES | RU | hint (опц.)\n\n"
            "Пример:\n"
            "Estoy listo. | Я готов. | 💡 listo = готовый\n"
            "¿Qué tal? | Как дела?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return await state.set_state(NewTopicStates.waiting_reading_fragments_text)

    data_pre = await state.get_data()
    pack_key_pre = data_pre.get("current_reading_pack_key") or ("translate" if data_pre.get("last_block") == "translate" else "reading")  # 💬 определяем режим пакета

    parsed: list = []
    bad_idx: list = []

    if pack_key_pre == "translate":
        # 💬 формат "перевод" = пары строк: RU-строка + ES-реплика [[...]]
        if len(lines_in) < 2 or (len(lines_in) % 2) != 0:
            await message.answer(
                "⛔ Формат неверный. Для «перевода» нужны пары строк: RU-строка + ES-строка.\n"
                "Пример:\n"
                "Я хочу <b>платить картой</b>|pagar=платить\n"
                "[[👩: bueno mira <b>pagar con tarjeta</b>, digo no, espera]]",
                reply_markup=ReplyKeyboardRemove(),
            )
            return await state.set_state(NewTopicStates.waiting_reading_fragments_text)

        pair_num = 0
        i = 0
        while i < len(lines_in):
            pair_num += 1
            ru_raw = lines_in[i].strip()
            es_raw = lines_in[i + 1].strip()

            if not ru_raw or not es_raw:
                bad_idx.append(pair_num)
                i += 2
                continue

            # 💬 подсказка только в RU-строке после |
            ru_text = ru_raw
            hint_txt = ""
            if "|" in ru_raw:
                left, right = ru_raw.split("|", 1)
                ru_text = left.strip()
                hint_raw = right.strip()
                if hint_raw and hint_raw != "-":
                    hint_txt = f"💡 {hint_raw}"  # 💬 хинт опционален, поддерживаем key=value

            parsed.append({
                "type": "text",  # 💬 сохраняем совместимость рендера
                "ru": ru_text,
                "es": es_raw,
                "hint": hint_txt,
            })
            i += 2

        if bad_idx and not parsed:
            await message.answer(
                "⛔ Формат неверный. Проверь пары (RU+ES).\n"
                f"Проблемные пары: {', '.join(map(str, bad_idx))}",
                reply_markup=ReplyKeyboardRemove(),
            )
            return await state.set_state(NewTopicStates.waiting_reading_fragments_text)  # 💬 нет валидных пар = остаёмся в вводе

        # 💬 есть валидные пары и ошибки = сохраняем валидные, ошибки посчитаем в итоговой статистике


    else:
        # 💬 формат "чтение" = ES | RU | hint(опц.)
        for i, ln in enumerate(lines_in, start=1):
            parts = [p.strip() for p in ln.split("|")]
            if len(parts) < 2 or len(parts) > 3:
                bad_idx.append(i)
                continue

            es = parts[0]
            ru = parts[1]
            hint = parts[2] if len(parts) == 3 else ""

            if not es or not ru:
                bad_idx.append(i)
                continue

            parsed.append({
                "type": "text",   # 💬 чтобы показывалось как текстовый фрагмент
                "es": es,
                "ru": ru,
                "hint": hint,
            })

        if bad_idx and not parsed:
            await message.answer(
                "⛔ Формат неверный. Исправь и пришли заново.\n"
                f"Проблемные строки: {', '.join(map(str, bad_idx))}\n\n"
                "Формат: ES | RU | hint (опц.)\n"
                "Пример:\n"
                "Estoy listo. | Я готов. | 💡 listo = готовый\n"
                "¿Qué tal? | Как дела?",
                reply_markup=ReplyKeyboardRemove(),
            )
            return await state.set_state(NewTopicStates.waiting_reading_fragments_text)  # 💬 нет валидных строк = остаёмся в вводе

        # 💬 есть валидные строки и ошибки = сохраняем валидные, ошибки посчитаем в итоговой статистике



    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    try:
        pack_index = int(data.get("current_reading_pack_index"))
    except Exception:
        pack_index = -1  # 💬 защита, если индекс не сохранён

    pack_key = data.get("current_reading_pack_key") or ("translate" if data.get("last_block") == "translate" else "reading")  # 💬 что делает эта часть: правильный раздел
    packs = topic.setdefault(pack_key, [])

    if not (topic_path and 0 <= pack_index < len(packs)):
        await message.answer(
            "⚠️ Не найден активный пак чтения. Начни добавление чтения заново.",
            reply_markup=get_main_menu(((topic.get("category") or ""))),  # 💬 правильное меню по категории
        )
        await state.set_state(NewTopicStates.waiting_first_choice)  # 💬 возвращаем в старт выбора
        return

    pack = packs[pack_index]
    pack.setdefault("fragments", [])

    # 💬 считаем статистику строк: добавлено/пропущено/ошибочные
    line_unit = 2 if pack_key_pre == "translate" else 1  # 💬 в «переводе» считаем строками пары
    empty_skipped = sum(1 for ln in (raw.splitlines() if raw else []) if not (ln or "").strip())  # 💬 пустые строки

    def _frag_key(x: dict) -> tuple:
        return (
            (x.get("type") or "").strip(),
            (x.get("es") or "").strip(),
            (x.get("ru") or "").strip(),
            (x.get("hint") or "").strip(),
        )

    existing_keys = {_frag_key(x) for x in (pack.get("fragments") or [])}
    to_add: list = []
    dup_count = 0

    for frag in (parsed or []):
        k = _frag_key(frag)
        if k in existing_keys:
            dup_count += 1
            continue
        existing_keys.add(k)
        to_add.append(frag)

    pack["fragments"].extend(to_add)  # 💬 добавляем только новые фрагменты (без дублей)

    added_lines = len(to_add) * line_unit
    skipped_lines = empty_skipped + (dup_count * line_unit)
    error_lines = len(bad_idx) * line_unit

    import json

    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
            [KeyboardButton(text="🔄 Создать ещё"), KeyboardButton(text="↩️ Назад")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        f"✅ Добавлено строк: {added_lines}\n"
        f"⏭️ Пропущено строк: {skipped_lines}\n"
        f"❗Ошибочные строки: {error_lines}",
        reply_markup=kb,
    )
    return await state.set_state(NewTopicStates.waiting_reading_action)




@router.message(NewTopicStates.waiting_reading_photo_text)
async def handle_reading_photo_text(message: Message, state: FSMContext):
    # 💬 сохраняем подпись к фото и просим прислать фото или файл
    caption = (message.text or "").strip()

    if caption.lower() in {"назад", "↩️ назад"}:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
                [KeyboardButton(text="🔄 Создать ещё"), KeyboardButton(text="↩️ Назад")],
            ],
            resize_keyboard=True,
        )
        await message.answer("Ок, выбери действие.", reply_markup=kb)
        return await state.set_state(NewTopicStates.waiting_reading_action)

    if caption == "-":
        caption = ""

    await state.update_data(reading_photo_caption=caption)
    await message.answer("Теперь пришли фото или файл (документ).", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(NewTopicStates.waiting_reading_photo)



@router.message(NewTopicStates.waiting_reading_photo, F.photo | F.document | F.text)
async def save_reading_photo(message: Message, state: FSMContext):
    # 💬 сохраняем фото или файл в текущий пак чтения и возвращаемся в меню действий
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")
    caption = (data.get("reading_photo_caption") or "").strip()

    try:
        pack_index = int(data.get("current_reading_pack_index"))
    except Exception:
        pack_index = -1

    pack_key = data.get("current_reading_pack_key") or ("translate" if data.get("last_block") == "translate" else "reading")  # 💬 что делает эта часть: правильный раздел
    packs = topic.setdefault(pack_key, [])

    if not (topic_path and 0 <= pack_index < len(packs)):
        await message.answer(
            "⚠️ Не найден активный пак чтения. Начни добавление чтения заново.",
            reply_markup=get_main_menu(),
        )
        return await state.set_state(NewTopicStates.waiting_first_choice)

    file_value = None
    media_type = None

    if message.photo:
        file_value = message.photo[-1].file_id
        media_type = "photo"
    elif message.document:
        file_value = message.document.file_id
        media_type = "document"
    else:
        file_value = (message.text or "").strip()
        media_type = "url"

    entry = {
        "type": "asset",
        "media_type": media_type,
        "file": file_value,
        "text": caption,
    }

    pack = packs[pack_index]
    pack.setdefault("assets", [])
    pack["assets"].append(entry)

    import json

    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic, reading_photo_caption=None)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
            [KeyboardButton(text="🔄 Создать ещё"), KeyboardButton(text="↩️ Назад")],
        ],
        resize_keyboard=True,
    )
    await message.answer("✅ Добавлено. Что ещё добавить?", reply_markup=kb)
    return await state.set_state(NewTopicStates.waiting_reading_action)





async def send_edit_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    selected_id = data.get("selected_topic_id")
    selected_cat = data.get("selected_category")

    topic = load_topic(selected_id, selected_cat)
    if not topic:
        await message.answer("❗ Тема не найдена.")
        return

    make_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Добавить фазу слов"), KeyboardButton(text="🗑 Удалить фазу слов")],
            [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
            [KeyboardButton(text="📚 Добавить чтение"), KeyboardButton(text="🗑 Удалить чтение")],
            [KeyboardButton(text="📊 Статус темы"), KeyboardButton(text="✅ Закончить редактирование")],
            [KeyboardButton(text="⬅️ Вернуться в меню темы")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        f"✏️ Редактирование темы: <b>{topic.get('name', '')}</b>\nВыбери действие",
        reply_markup=make_kb,
    )
@router.message(EditTopicStates.choose_action)
async def handle_edit_action(message: Message, state: FSMContext):
    # 💬 старое reply-меню выключаем, чтобы не было разных меню
    await state.set_state(AdminInlineEditStates.idle)
    await _adm_show_actions_msg(message, state, note_text="ℹ️ Редактирование теперь через inline-кнопки")


# --- Хендлеры удаления фаз и блоков ---

@router.message(EditTopicStates.waiting_vocab_phase_delete_index)
async def edit_delete_vocab_phase(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt == "↩️ Назад":
        await message.answer("Ок.", reply_markup=ReplyKeyboardRemove())
        await message.answer("✏️ Режим редактирования. Что вы хотите сделать?", reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
                [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
                [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
                [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
                [KeyboardButton(text="↩️ Вернуться в Главное меню")],
            ],
            resize_keyboard=True,
        ))
        await state.set_state(EditTopicStates.choose_action)
        return

    m = re.match(r"^\s*(\d+)", txt)
    if not m:
        await message.answer("⚠️ Введите номер фазы.")
        return

    idx = int(m.group(1)) - 1
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    phases = topic.get("vocab") or []
    if not (0 <= idx < len(phases)):
        await message.answer("⚠️ Неверный индекс фазы.")
        return

    removed = phases.pop(idx)

    for i, p in enumerate(phases, 1):
        if isinstance(p, dict):
            p["phase_id"] = i  # 💬 перенумерация после удаления

    topic["vocab"] = phases
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем удаление в Railway

    await state.update_data(topic=topic)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
            [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
            [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
            [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
            [KeyboardButton(text="↩️ Вернуться в Главное меню")],
        ],
        resize_keyboard=True,
    )
    name = removed.get("phase_name") if isinstance(removed, dict) else ""
    await message.answer(f"✅ Фаза удалена: {name}", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)


@router.message(EditTopicStates.waiting_dialog_phase_delete_index)
async def edit_delete_dialog_phase(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt == "↩️ Назад":
        await message.answer("Ок.", reply_markup=ReplyKeyboardRemove())
        await message.answer("✏️ Режим редактирования. Что вы хотите сделать?", reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
                [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
                [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
                [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
                [KeyboardButton(text="↩️ Вернуться в Главное меню")],
            ],
            resize_keyboard=True,
        ))
        await state.set_state(EditTopicStates.choose_action)
        return

    m = re.match(r"^\s*(\d+)", txt)
    if not m:
        await message.answer("⚠️ Введите номер фазы.")
        return

    idx = int(m.group(1)) - 1
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    dialogs = topic.get("dialogs") or []
    if not (0 <= idx < len(dialogs)):
        await message.answer("⚠️ Неверный индекс фазы.")
        return

    removed = dialogs.pop(idx)

    for i, d in enumerate(dialogs, 1):
        if isinstance(d, dict):
            d["phase_id"] = i  # 💬 перенумерация после удаления

    topic["dialogs"] = dialogs
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем удаление в Railway

    await state.update_data(topic=topic)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
            [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
            [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
            [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
            [KeyboardButton(text="↩️ Вернуться в Главное меню")],
        ],
        resize_keyboard=True,
    )
    name = removed.get("phase_name") if isinstance(removed, dict) else ""
    await message.answer(f"✅ Фаза диалогов удалена: {name}", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)


@router.message(EditTopicStates.waiting_video_delete_index)
async def edit_delete_video(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt == "↩️ Назад":
        await message.answer("Ок.", reply_markup=ReplyKeyboardRemove())
        await message.answer("✏️ Режим редактирования. Что вы хотите сделать?", reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
                [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
                [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
                [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
                [KeyboardButton(text="↩️ Вернуться в Главное меню")],
            ],
            resize_keyboard=True,
        ))
        await state.set_state(EditTopicStates.choose_action)
        return

    m = re.match(r"^\s*(\d+)", txt)
    if not m:
        await message.answer("⚠️ Введите номер видео.")
        return

    idx = int(m.group(1)) - 1
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    videos = topic.get("videos") or []
    if not (0 <= idx < len(videos)):
        await message.answer("⚠️ Неверный индекс видео.")
        return

    removed = videos.pop(idx)
    topic["videos"] = videos
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем удаление в Railway

    await state.update_data(topic=topic)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
            [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
            [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
            [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
            [KeyboardButton(text="↩️ Вернуться в Главное меню")],
        ],
        resize_keyboard=True,
    )
    title = removed.get("title") if isinstance(removed, dict) else ""
    await message.answer(f"✅ Видео удалено: {title}", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)


@router.message(EditTopicStates.waiting_reading_delete_index)
async def edit_delete_reading_pack(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt == "↩️ Назад":
        await message.answer("Ок.", reply_markup=ReplyKeyboardRemove())
        await message.answer("✏️ Режим редактирования. Что вы хотите сделать?", reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
                [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
                [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
                [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
                [KeyboardButton(text="↩️ Вернуться в Главное меню")],
            ],
            resize_keyboard=True,
        ))
        await state.set_state(EditTopicStates.choose_action)
        return

    m = re.match(r"^\s*(\d+)", txt)
    if not m:
        await message.answer("⚠️ Введите номер пака.")
        return

    idx = int(m.group(1)) - 1
    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    packs = topic.get("reading") or []
    if not (0 <= idx < len(packs)):
        await message.answer("⚠️ Неверный индекс пака.")
        return

    removed = packs.pop(idx)
    topic["reading"] = packs
    if topic_path:
        atomic_save_json(topic_path, topic)  # 💬 сохраняем удаление в Railway

    await state.update_data(topic=topic)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая фаза словаря"), KeyboardButton(text="🗑 Удалить фазу словаря")],
            [KeyboardButton(text="➕ Новая фаза диалогов"), KeyboardButton(text="🗑 Удалить фазу диалогов")],
            [KeyboardButton(text="➕ Добавить видео"), KeyboardButton(text="🗑 Удалить видео")],
            [KeyboardButton(text="➕ Добавить чтение"), KeyboardButton(text="🗑 Удалить пак чтения")],
            [KeyboardButton(text="↩️ Вернуться в Главное меню")],
        ],
        resize_keyboard=True,
    )
    title = removed.get("title") if isinstance(removed, dict) else ""
    await message.answer(f"✅ Пак чтения удалён: {title}", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)




# — Добавить словарь —
@router.message(EditTopicStates.waiting_vocab_title)
async def edit_vocab_title(message: Message, state: FSMContext):
    await state.update_data(current_vocab_title=message.text.strip())
    await message.answer("🖇️ Введите ссылку или текст словаря:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(EditTopicStates.waiting_vocab_link)

@router.message(EditTopicStates.waiting_vocab_link, F.content_type=="text")
async def edit_vocab_link(message: Message, state: FSMContext):
    data       = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]
    title      = data.get("current_vocab_title")
    raw        = message.text.strip()
    link       = extract_src(raw) if "<iframe" in raw else raw

    add_block_and_save(topic, topic_path, {"title": title, "link": link}, "vocab")
    await state.update_data(current_vocab_title=None)

    await message.answer("✅ Словарь добавлен.", reply_markup=ReplyKeyboardRemove())
    await send_edit_menu(message.chat.id, message.bot, state)







# ——— Новый поток: Добавление рекламы ———
@router.message(StateFilter(NewTopicStates.waiting_ad_action))
async def ad_action_menu(message: Message, state: FSMContext):
    # 💬 меню действий по рекламе после кнопки ADD
    text = (message.text or "").strip()

    if text == "➕ Добавить рекламу":
        await message.answer(
            "📌 Перешли мне ПОСТ из любого канала (forward).\n"
            "✅ Я сохраню его channel_id + message_id в ads_data.json.\n"
            "ℹ️ В показе в боте будет именно FORWARD + одна кнопка OK."
        )
        return await state.set_state(NewTopicStates.waiting_ad_source)

    if text == "🗑 Удалить по индексу":
        ads = load_ads_data()
        if not ads:
            await message.answer("Список рекламы пуст.")
            return await state.set_state(NewTopicStates.waiting_category)

        # 💬 показываем список 1..N без превью
        lines = ["🗑 Выбери индекс для удаления (напиши номер):"]
        for i, ad in enumerate(ads, 1):
            ch = ad.get("channel_id")
            mid = ad.get("message_id")
            lines.append(f"{i}) channel_id={ch} msg_id={mid}")

        await message.answer("\n".join(lines))
        return await state.set_state(NewTopicStates.waiting_ad_delete_index)

    if text == "⬅️ Назад":
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Лексика")],
                [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
                [KeyboardButton(text="✏️ Редактировать темы")],
            ],
            resize_keyboard=True
        )

        await message.answer("📂 Выберите раздел:", reply_markup=keyboard)
        return await state.set_state(NewTopicStates.waiting_category)

    await message.answer("❗ Нажми одну из кнопок.")

# 1) После того, как получили forwarded from_chat + message_id:

@router.message(StateFilter(NewTopicStates.waiting_ad_source), F.forward_from_chat)
async def receive_ad_source(message: Message, state: FSMContext):
    # 💬 сохраняем рекламу сразу из форварда: только channel_id + message_id
    ch = message.forward_from_chat.id
    mid = message.forward_from_message_id

    if not mid:
        # 💬 редкий кейс: если Telegram не дал message_id — просим переслать ещё раз
        await message.answer("❌ Не вижу message_id у форварда. Перешли пост ещё раз.")
        return

    logging.info(f"[receive_ad_source] ad_channel={ch}, ad_message_id={mid}")

    new_ad = {
        "channel_id": ch,
        "message_id": mid
    }

    ads = load_ads_data()
    ads.append(new_ad)
    save_ads_data(ads)

    # 💬 Попытка загрузить обновлённый ads_data.json в GitHub (если настроено)
    try:
        ok, info = github_put_file(ADS_DATA_PATH, "ads_data.json", "Add ad via CreateLessonBlock (forward only)")
        if ok:
            logging.info("[receive_ad_source] Ads uploaded to GitHub")
        else:
            logging.info("[receive_ad_source] GitHub upload skipped/failed: %s", info)
    except Exception as e:
        logging.exception("[receive_ad_source] github_put_file raised: %s", e)

    # 💬 чистим временные поля и возвращаемся в меню категорий
    await state.update_data(
        ad_channel=None,
        ad_message_id=None,
        ad_fwd_chat_id=None,
        ad_fwd_message_id=None
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика")],
            [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
            [KeyboardButton(text="✏️ Редактировать темы")]
        ],
        resize_keyboard=True
    )


    await message.answer("✅ Реклама сохранена (forward → показ в боте с шапкой + кнопка OK).", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_category)






@router.message(NewTopicStates.waiting_ad_buttons)
async def save_ad_block(message: Message, state: FSMContext):
    # 💬 режим вопрос/2 кнопки отключён — реклама добавляется только через форвард
    await message.answer("ℹ️ Вопрос/кнопки отключены. Перешли пост из канала ещё раз (forward).")
    await state.set_state(NewTopicStates.waiting_ad_source)



@router.message(StateFilter(NewTopicStates.waiting_ad_delete_index))
async def delete_ad_by_index(message: Message, state: FSMContext):
    # 💬 удаляем рекламу по индексу (1..N)
    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer("❗ Напиши номер индекса (например: 1).")
        return

    idx = int(text)
    ads = load_ads_data()

    if idx < 1 or idx > len(ads):
        await message.answer(f"❗ Индекс должен быть от 1 до {len(ads)}.")
        return

    deleted = ads.pop(idx - 1)
    save_ads_data(ads)

    # 💬 пытаемся обновить файл в GitHub (если настроено)
    try:
        ok, info = github_put_file(ADS_DATA_PATH, "ads_data.json", f"Delete ad index {idx} via CreateLessonBlock")
        if ok:
            logging.info("[delete_ad_by_index] Ads uploaded to GitHub")
        else:
            logging.info("[delete_ad_by_index] GitHub upload skipped/failed: %s", info)
    except Exception as e:
        logging.exception("[delete_ad_by_index] github_put_file raised: %s", e)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика")],
            [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
            [KeyboardButton(text="✏️ Редактировать темы")]
        ],
        resize_keyboard=True
    )


    await message.answer(
        f"✅ Удалено: channel_id={deleted.get('channel_id')} msg_id={deleted.get('message_id')}",
        reply_markup=keyboard
    )
    await state.set_state(NewTopicStates.waiting_category)















































































































@router.message(StateFilter("*"))
async def _topics_router_debug_seen(message: Message, state: FSMContext):
    """💬 Диагностика: видим все сообщения, дошедшие до topics-router (без ответа в чат)."""
    try:
        data = await state.get_data()
        logging.info(
            "[topics.router.seen] user_id=%s chat_id=%s text=%r state=%s keys=%s",
            getattr(getattr(message, "from_user", None), "id", None),
            getattr(getattr(message, "chat", None), "id", None),
            message.text,
            await state.get_state(),
            sorted(list((data or {}).keys())),
        )
    except Exception as e:
        logging.exception("[topics.router.seen] debug log exception: %s", e)
    return
