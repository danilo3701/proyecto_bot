# === КОНСТРУКТОР УРОКОВ: СОХРАНЕНИЕ В STRUCTURE С TYPE ===

import json, random
import os
import uuid  # 💬 Для генерации уникальных имён файлов
import re
import logging  # 💬 для логирования в receive_ad_source

from pathlib import Path

def get_topics_dir() -> Path:
    # 💬 что делает эта часть: выбираем папку topics в Railway Volume (/data/topics); если нельзя = падаем обратно на локальную
    candidates = [Path("/data/topics"), Path(__file__).parent / "topics", Path("topics")]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            # тест записи, чтобы понять что директория реально writable
            test = d / ".write_test"
            test.write_text("ok", encoding="utf-8")
            try:
                test.unlink()
            except Exception:
                pass
            return d
        except Exception:
            continue
    return Path("topics")


from aiogram import Router, Bot
from aiogram import F
from aiogram.filters import StateFilter


from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand

from aiogram.filters.command import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

router = Router()

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
    waiting_post_action     = State()  # 💬 после сохранения словаря/упражнения/видео: создать еще или вернуться

    # ----------- БЛОК “СЛОВАРЬ” -------------
    waiting_phase_choice      = State()  # 💬 выбор существующей фазы или создание новой
    waiting_phase_name        = State()  # 💬 вводим название новой фазы

    waiting_vocab_title     = State()  # 💬 вводим заголовок словаря
    waiting_vocab_link      = State()  # 💬 вводим ссылку или текст словаря



    # ——— BULK-ИМПОРТ ДЛЯ KVIZ ———
    waiting_vocab_textquiz_bulk = State()  # 💬 пакетный ввод: по строкам "вопрос | ответ" для TEXT_QUIZ
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

class EditGrammarStates(StatesGroup):
    waiting_section = State()        # 💬 выбор: теория, практика, видео, читать
    waiting_phase = State()          # 💬 выбор фазы теории
    waiting_delete_index = State()   # 💬 ввод индекса для удаления


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
            [KeyboardButton(text="🎥 Добавить видео"),    KeyboardButton(text="💬 Добавить диалог")],
            [KeyboardButton(text="📖 Добавить чтение")],
            [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")]
        ],
        resize_keyboard=True
    )



def get_edit_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить словарь"), KeyboardButton(text="➕ Добавить упражнение")],
            [KeyboardButton(text="➕ Добавить видео"),    KeyboardButton(text="➕ Добавить диалог")],
            # 💬 Убрана кнопка линейного QUIZ
            [KeyboardButton(text="📝 Добавить ТЕКСТ")],
            [KeyboardButton(text="➖ Удалить блок"),      KeyboardButton(text="🚫 Отмена")]
        ],
        resize_keyboard=True
    )

@router.message(Command("addtopic"))
async def start_adding_topic(message: Message, state: FSMContext):
    await state.clear()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")],
            [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
            [KeyboardButton(text="✏️ Редактировать темы")]  # 💬 переход в EditTopic
        ],
        resize_keyboard=True
    )


    await message.answer("📂 Выбери КАТЕГОРИЮ темы:", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_category)

# === Шаг 1: выбор категории ===

@router.message(NewTopicStates.waiting_category)
async def get_category_or_ads(message: Message, state: FSMContext):
    text = message.text.strip()

    # 💬 Прямая кнопка в режим редактирования тем (аналог /edittopic)
    if text == "✏️ Редактировать темы":
        # очищаем текущий FSM-поток конструктора
        await state.clear()

        from edit_topic_flow import EditTopicStates  # 💬 импортируем только STATES, без router
        topics_dir = get_topics_dir()  # 💬 что делает эта часть: читаем темы из Volume (/data/topics)
        files = [p.stem for p in topics_dir.glob("*.json")]


        if not files:
            await message.answer("⚠️ Нет доступных тем для редактирования.")
            return

        buttons = [[KeyboardButton(text="🚫 Отмена")]] + [
            [KeyboardButton(text=name)] for name in files
        ]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

        await message.answer("✏️ Выберите тему для редактирования:", reply_markup=keyboard)
        await state.set_state(EditTopicStates.choose_topic)
        return

    if text == "ADD":
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
        await message.answer(
            "Введи ссылку (https://t.me/username) или имя канала (@username).\n"
            "Если несколько — раздели через запятую."
        )
        return await state.set_state(NewTopicStates.waiting_channel)

    if text not in ["📚 Лексика", "🧠 Грамматика"]:
        await message.answer("❗ Выбери одну из кнопок.")
        return

    category = "lex" if text == "📚 Лексика" else "gram"
    await state.update_data(topic={"category": category})

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





@router.message(NewTopicStates.adding_category)
async def get_level_for_topic(message: Message, state: FSMContext):
    raw = (message.text or "").strip()

    # «Назад» — возвращаемся к выбору категории
    if raw == "⬅️ Назад":
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")]],
            resize_keyboard=True
        )
        await message.answer("📂 Выбери КАТЕГОРИЮ темы:", reply_markup=kb)
        return await state.set_state(NewTopicStates.waiting_category)

    # Нормализация: кнопка с эмодзи -> чистое значение уровня
    level = LEVEL_FROM_BUTTON.get(raw, raw)

    if level not in ALLOWED_LEVELS:
        await message.answer("❗ Выбери корректный уровень из кнопок ниже.")
        return

    await state.update_data(topic_level=level)
    # 💬 что делает эта часть: сохраняем 'A0' / 'A1-A2' / 'B1-B2' / 'C1' в state, без эмодзи

    await message.answer("Уровень выбран. Теперь введи НАЗВАНИЕ новой темы:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(NewTopicStates.waiting_topic_name)
    # 💬 После выбора уровня переходим к вводу названия темы.



# === Шаг 2: название темы ===

@router.message(NewTopicStates.waiting_topic_name)
async def get_topic_name(message: Message, state: FSMContext):
    import os, re, json

    raw = message.text.strip()
    clean = re.sub(r"[^\w\s]", "", raw).lower().replace(" ", "_")
    
    topics_dir = get_topics_dir()
    filename = str(topics_dir / f"{clean}.json")  # 💬 что делает эта часть: сохраняем путь темы в Volume (/data/topics)
    
    # 💬 Собираем базовую структуру темы
    data = await state.get_data()
    category = data["topic"]["category"]
    topic = {
        "title": clean,
        "visible_title": raw,
        "category": category,
        "level": data.get("topic_level"),  # 💬 добавляем выбранный уровень
        "vocab": [],
        "exercises": [],
        "videos": [],
        "dialogs": [],
        "reading": []  # 💬 что делает эта часть: хранит пакеты чтения (фрагменты как в подкастах)

    }
    
    # 💾 Сохраняем в файл (уже в Volume)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    
    # 💬 Обновляем состояние
    await state.update_data(topic=topic, topic_path=filename)


    # 💬 Запрос описания темы
    await message.answer("Теперь введи ОПИСАНИЕ темы:", reply_markup=ReplyKeyboardRemove())
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

    }

    # 💾 Сохраняем в файл
    filename = data.get("topic_path")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(new_topic, f, ensure_ascii=False, indent=2)
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
    tp = data.get("topic")
    path = data.get("topic_path")

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


    # ----------------------- Добавить словарь -----------------------
    if text == "📚 словарь":
        await state.update_data(last_block="vocab")
        data   = await state.get_data()
        phases = data["topic"]["vocab"]  # список фаз
        if not phases:
            # нет фаз — сразу создаём
            await message.answer("Введите НАЗВАНИЕ новой ФАЗЫ:")
            await state.set_state(NewTopicStates.waiting_phase_name)
        else:
            # строим кнопки из KeyboardButton
            buttons = [
                [KeyboardButton(text=f"{p['phase_id']}. {p['phase_name']}")]
                for p in phases
            ]
            buttons.append([KeyboardButton(text="➕ Новая фаза")])
            kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
            await message.answer("Выберите фазу или создайте новую:", reply_markup=kb)
            await state.set_state(NewTopicStates.waiting_phase_choice)
        return



    # ----------------------- Добавить упражнение -----------------------
    if text == "✏️ Добавить упражнение":
        # 💬 Последний блок – «exercise» (общие упражнения)
        await state.update_data(last_block="exercise")
        # Просим ввести название упражнения
        await message.answer("Введите НАЗВАНИЕ упражнения:")
        # Переходим в состояние, где ждём title упражнения
        await state.set_state(NewTopicStates.waiting_ex_title)
        return

    # ----------------------- Добавить видео -----------------------
    if text == "🎥 Добавить видео":
        # 💬 Последний блок – «video»
        await state.update_data(last_block="video")
        # Просим ввести заголовок видео
        await message.answer("Введите ЗАГОЛОВОК видео:")
        # Переходим в состояние, где ждём title видео
        await state.set_state(NewTopicStates.waiting_video_title)
        return

    # ----------------------- Добавить диалог -----------------------
    if text == "💬 Добавить диалог":
        await state.update_data(last_block="dialog")
        await message.answer(
            "💬 Введите НАЗВАНИЕ ФАЗЫ диалогов:\n"
            "Например: «Fase 1 — ir al médico (pack 1)».",
            reply_markup=ReplyKeyboardRemove()
        )
        return await state.set_state(NewDialogStates.waiting_dialog_phase_name)

    # ----------------------- Добавить чтение -----------------------
    if text == "📖 Добавить чтение":
        await state.update_data(last_block="reading")  # 💬 что делает эта часть: помечаем текущий раздел
        await message.answer("Введите ЗАГОЛОВОК чтения:", reply_markup=ReplyKeyboardRemove())
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
                    items = ph.get("vocab") or []
                    lines.append(f"  {p_idx}) <b>{_preview_text(ph_name, 40)}</b> (элементов: {len(items)})")
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
                    lines.append(f"  {r_idx}) 📖 <b>{_preview_text(ttl, 40)}</b> (fr={len(fr)}, assets={len(assets)})")
                    if first:
                        lines.append(f"      ↳ {first}")
                if len(reading_list) > 15:
                    lines.append("  …")
            lines.append("")

        else:
            # 💬 fallback для лексики оставляем как было, но без падений
            lines.append("ℹ️ Это не грамматика. Для лексики оставляем старый просмотр.")

        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

        keyboard = get_main_menu(category_now)
        await message.answer("С чего начнём?", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return



    # ----------------------- Редактировать тему -----------------------
    if text == "✏️ Редактировать":
        data = await state.get_data()
        topic = data.get("topic")
        path  = data.get("topic_path")
        category_now = (topic or {}).get("category")
        if category_now == "gram":
            # 💬 отдельное редактирование для грамматики
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📖 Теория"), KeyboardButton(text="📝 Практика")],
                    [KeyboardButton(text="🎥 Видео"), KeyboardButton(text="📚 Читать")],
                    [KeyboardButton(text="🚫 Отмена")],
                ],
                resize_keyboard=True,
            )
            await message.answer("✏️ Редактирование грамматики. Выберите раздел:", reply_markup=kb)
            await state.set_state(EditGrammarStates.waiting_section)
            return

        if not topic or not path:
            await message.answer("❗ Ошибка: тема не загружена. Пожалуйста, создайте или откройте тему заново.")
            return

        # — 1) Выбор раздела для редактирования —
        buttons = [
            [KeyboardButton(text="📚 Словарь"),  KeyboardButton(text="🎲 Упражнения")],
            [KeyboardButton(text="🎬 Видео"),      KeyboardButton(text="💬 Диалоги")],
            [KeyboardButton(text="🚫 Отмена")]
        ]
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer("✏️ Режим редактирования. Выберите раздел:", reply_markup=kb)

        from edit_topic_flow import EditTopicStates
        await state.set_state(EditTopicStates.waiting_section)
        return



    # ----------------------- Обработка ввода не из списка -----------------------
    # Если сообщение не соответствует ни одной кнопке, просим выбрать ещё раз
    await message.answer("❗ Выберите, пожалуйста, одну из кнопок Главного меню.")




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
            lines.append(f"{i}) 📖 {_preview_text(ttl, 40)} (fr={len(fr)}, assets={len(assets)})")
        else:
            lines.append(f"{i}) {_preview_item(it)}")

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗑 Удалить по индексу")],
            [KeyboardButton(text="↩️ Назад"), KeyboardButton(text="🚫 Отмена")],
        ],
        resize_keyboard=True,
    )
    await message.answer("\n".join(lines), reply_markup=kb, disable_web_page_preview=True)
    await state.set_state(EditGrammarStates.waiting_delete_index)


@router.message(EditGrammarStates.waiting_delete_index)
async def edit_grammar_delete_index(message: Message, state: FSMContext):
    # 💬 удаляем элемент по индексу и сохраняем JSON
    text = (message.text or "").strip()

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

    keyboard = get_main_menu()
    await message.answer(
        f"✅ Диалоговая фаза сохранена.\nБлоков: {len(blocks)}.",
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
            [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")],
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
        category = (data.get("topic") or {}).get("category")

        if category == "gram":
            # 💬 что делает эта часть: меню Теории = только текст/фото/пулквизы/назад
            rows = [
                [KeyboardButton(text="📝 Текст"), KeyboardButton(text="🖼 Фото")],
                [KeyboardButton(text="📥 Пулквизы")],
            ]
        else:
            # 💬 лексика: старое меню словаря
            rows = [
                [KeyboardButton(text="📘VOC")],
                [KeyboardButton(text="📝ТЕКСТ"),    KeyboardButton(text="🖼FOTO")],
                [KeyboardButton(text="📥TXT_QUIZ"), KeyboardButton(text="📥QUIZ")],
            ]



    elif last == "exercise":
        rows = [
            # 💬 только создание новых упражнений и их текст/фото — без обычных QUIZ и TXT_QUIZ
            [KeyboardButton(text="🔄 Создать ещё упражнение")],
            [KeyboardButton(text="📝ТЕКСТ"),
             KeyboardButton(text="🖼 Добавить фото")],
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









# === БЛОК “СЛОВАРЬ” ===
# Создание Потока "Учить слова"


@router.message(NewTopicStates.waiting_phase_name)
async def create_phase(message: Message, state: FSMContext):
    # 💬 сохраняем новую фазу
    data = await state.get_data()
    phases = data["topic"]["vocab"]
    phase_name = message.text.strip()
    new_phase = {
        "phase_id": len(phases) + 1,
        "phase_name": phase_name,
        "vocab": []
    }
    phases.append(new_phase)
    await state.update_data(topic=data["topic"], current_phase_id=new_phase["phase_id"])
    await message.answer(f"Фаза «{phase_name}» создана.")
    # Далее просим заголовок словаря в этой фазе
    # 💬 После создания фазы — показываем меню действий
    await send_post_menu(message, state)


@router.message(NewTopicStates.waiting_phase_choice)
async def choose_phase(message: Message, state: FSMContext):
    text = message.text.strip()
    # — Создать новую фазу
    if text == "➕ Новая фаза":
        # 💬 убрать старую клавиатуру и спросить имя фазы
        await message.answer("Введите НАЗВАНИЕ новой ФАЗЫ:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(NewTopicStates.waiting_phase_name)

    # — Выбрать существующую фазу по номеру
    #    ожидаем формат "1. Фразовые глаголы"
    phase_id = int(text.split(".", 1)[0].strip())
    await state.update_data(current_phase_id=phase_id)

    # 💬 подтвердить выбор и убрать клавиатуру
    await message.answer(f"Фаза выбрана: {text}", reply_markup=ReplyKeyboardRemove())

    data = await state.get_data()
    topic = data.get("topic") or {}
    if topic.get("category") == "gram":
        # 💬 что делает эта часть: для грамматики сразу показываем меню Теории (текст/фото/пулквизы)
        await state.update_data(last_block="vocab")
        await send_post_menu(message, state)
        return

    # 💬 для лексики оставляем старое поведение (заголовок + link)
    await message.answer("Введите ЗАГОЛОВОК словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_title)








@router.message(NewTopicStates.waiting_vocab_textquiz_bulk)
async def import_vocab_textquiz_bulk(message: Message, state: FSMContext):
    # 💬 парсим многострочный список TEXT_QUIZ: "вопрос | ответ"
    raw = message.text or ""
    lines_in = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    added, skipped, skipped_idx = 0, 0, []
    data = await state.get_data()
    cp = data["current_phase_id"]
    topic = data["topic"]
    phase = topic["vocab"][cp-1]
    # 💬 гарантируем наличие пула для распределения
    if "textquiz_pool" not in phase:
        phase["textquiz_pool"] = []

    for i, ln in enumerate(lines_in, start=1):
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            skipped += 1
            skipped_idx.append(i)
            continue
        q, a = parts[0], parts[1]
        block = {
            "type": "textquiz",             # 💬 тип квиза
            "question": q,
            "correct_answer": a
        }
        phase["textquiz_pool"].append(block)
        added += 1

    # 💾 сохраняем файл
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # 🧾 отчёт
    if skipped:
        await message.answer(f"✅ Импорт TEXT_QUIZ: добавлено {added}.\n⚠️ Пропущено: {skipped} (строки: {', '.join(map(str, skipped_idx))}).", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(f"✅ Импорт TEXT_QUIZ: добавлено {added}.", reply_markup=ReplyKeyboardRemove())

    await send_post_menu(message, state)


@router.message(NewTopicStates.waiting_vocab_quiz_bulk)
async def import_vocab_quiz_bulk(message: Message, state: FSMContext):
    # 💬 парсим многострочный список QUIZ: "вопрос | правильный | неверный1 | неверный2 | объяснение(опц.)"
    raw = message.text or ""
    lines_in = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    added, skipped, skipped_idx = 0, 0, []
    data = await state.get_data()
    cp = data["current_phase_id"]
    topic = data["topic"]
    phase = topic["vocab"][cp-1]
    # 💬 гарантируем наличие пула для распределения
    if "quiz_pool" not in phase:
        phase["quiz_pool"] = []

    for i, ln in enumerate(lines_in, start=1):
        parts = [p.strip() for p in ln.split("|")]
        # нужно минимум 4 поля: вопрос, правильный, неверный1, неверный2
        if len(parts) < 4 or not parts[0] or not parts[1] or not parts[2] or not parts[3]:
            skipped += 1
            skipped_idx.append(i)
            continue

        q, correct, wrong1, wrong2 = parts[0], parts[1], parts[2], parts[3]
        # объяснение неправильного (опционально)
        expl_wrong = parts[4] if len(parts) >= 5 else ""
        # 💬 дефолтное объяснение, если пусто или '-'
        if not expl_wrong or expl_wrong == "-":
            expl_wrong = f"Неверно. Правильно: {correct}."

        block = {
            "type": "quiz",                  # 💬 обычный quiz
            "question": q,
            "options": [correct, wrong1, wrong2],
            "correct_answer": correct,
            "explanation_wrong": expl_wrong
        }
        phase["quiz_pool"].append(block)
        added += 1

    # 💾 сохраняем файл
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # 🧾 отчёт
    if skipped:
        await message.answer(f"✅ Импорт QUIZ: добавлено {added}.\n⚠️ Пропущено: {skipped} (строки: {', '.join(map(str, skipped_idx))}).", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(f"✅ Импорт QUIZ: добавлено {added}.", reply_markup=ReplyKeyboardRemove())

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
    data            = await state.get_data()
    cp              = data["current_phase_id"]
    topic_data      = data["topic"]
    topic_data["vocab"][cp-1]["vocab"].append(new_block)



    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

       # … после записи в JSON и очистки current_vocab_title …
    await state.update_data(current_vocab_title=None, last_block="vocab")

    await message.answer("Словарь сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)



# 3) Пост-блоковое меню для всех блоков (часть 1)
@router.message(NewTopicStates.waiting_post_action)
async def handle_post_action(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    last_block = data.get("last_block")

    # ─── БЛОК «СЛОВАРЬ» ───
    if last_block == "vocab":
        # 💬 что делает эта часть: алиасы кнопок Теории (gram) на существующие ветки
        if text == "📝 Текст":
            text = "📝ТЕКСТ"
        elif text == "🖼 Фото":
            text = "🖼FOTO"
        elif text == "📥 Пулквизы":
            text = "📥QUIZ"

        if text == "📘VOC":
            data   = await state.get_data()
            topic  = data["topic"]
            phases = topic.get("vocab", [])

            # 1) Фаз вообще нет → сначала создаём первую фазу
            if not phases:
                await message.answer(
                    "Введите НАЗВАНИЕ новой ФАЗЫ:",
                    reply_markup=ReplyKeyboardRemove()
                )
                await state.set_state(NewTopicStates.waiting_phase_name)
                return

            # 2) Фазы уже есть → ВСЕГДА даём выбор фазы (как в редактировании)
            # 💬 всегда спрашиваем фазу, чтобы можно было перейти на 2-ю, 3-ю и т.д.
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





        if text == "📥TXT_QUIZ":
            # 💬 просим многострочный список: каждая строка "ВОПРОС | ПРАВИЛЬНЫЙ"
            await message.answer("📥 Отправь список TEXT_QUIZ:\nкаждая строка: ВОПРОС | ПРАВИЛЬНЫЙ\n(пустые строки игнорируются)")
            return await state.set_state(NewTopicStates.waiting_vocab_textquiz_bulk)

        if text == "📥QUIZ":
            # 💬 просим многострочный список: "вопрос | правильный | неверный1 | неверный2 | объяснение(опц.)"
            await message.answer("📥 Отправь список QUIZ:\nкаждая строка: ВОПРОС | ПРАВИЛЬНЫЙ | НЕВЕРНЫЙ1 | НЕВЕРНЫЙ2 | ОБЪЯСНЕНИЕ(опционально)\n(пустые строки игнорируются)")
            return await state.set_state(NewTopicStates.waiting_vocab_quiz_bulk)

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
        if text == "📝 Добавить ТЕКСТ":
            await message.answer("📝 Введите текст для упражнения:")
            return await state.set_state(NewTopicStates.waiting_ex_text)
        if text == "🖼 Добавить фото":
            await message.answer("Введите подпись к фото упражнения или '-' для пропуска:")
            return await state.set_state(NewTopicStates.waiting_ex_photo_text)

            return await state.set_state(NewTopicStates.waiting_ex_photo_text)
    # ─── БЛОК «ВИДЕО» ───
    if last_block == "video" and text == "🔄 Создать ещё видео":
        await message.answer("Введите ЗАГОЛОВОК видео:")
        await state.set_state(NewTopicStates.waiting_video_title)
        return

    # ─── Вернуться в Главное меню ───
    if text == "↩️ Вернуться в Главное меню":
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
                [KeyboardButton(text="🎥 Добавить видео"),     KeyboardButton(text="💬 Добавить диалог")],
                [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")]
            ],
            resize_keyboard=True
        )
        await message.answer("Возвращаемся в Главное меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    # ─── Некорректный ввод ───
    await message.answer(
        "❗ Пожалуйста, нажми одну из кнопок: «📘VOC», «📝ТЕКСТ», «🖼FOTO», «📥TXT_QUIZ», «📥QUIZ» или «↩️ Вернуться в Главное меню»."
    )










# === БЛОК “УПРАЖНЕНИЕ (ОБЩЕЕ)” ===


# 1) Сохраняем название упражнения
@router.message(NewTopicStates.waiting_ex_title)
async def get_ex_title(message: Message, state: FSMContext):
    await state.update_data(current_ex_title=message.text.strip())
    await message.answer("Введите ИНСТРУКЦИЮ для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_instr)

# 2) Запрашиваем инструкцию к упражнению
@router.message(NewTopicStates.waiting_ex_instr)
async def get_ex_instr(message: Message, state: FSMContext):
    instr = message.text.strip()
    await state.update_data(current_ex_instr=instr)
    # 💬 Как в словаре: сразу просим ссылку или iframe
    await message.answer("Введите ССЫЛКУ или iframe для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_url)



# 3) Сохраняем упражнение (title + instr + link) и возвращаем Главное меню
@router.message(NewTopicStates.waiting_ex_url)
async def get_ex_link(message: Message, state: FSMContext):
    raw = message.text.strip()
    # — вытягиваем src из iframe, если нужно
    if "<iframe" in raw and 'src="' in raw:
        link = raw.split('src="',1)[1].split('"',1)[0]
    else:
        link = raw

    data = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]

    # — прямо как в словаре, но добавляем инструкцию
    new_block = {
        "title":       data["current_ex_title"],
        "instruction": data["current_ex_instr"],
        "link":        link
    }
    topic.setdefault("exercises", []).append(new_block)
    # 🔄 Перезаписываем JSON
    import json
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # очищаем временные поля
    await state.update_data(current_ex_title=None, current_ex_instr=None)

    # — подтвердим и вернём Главное меню темы
    await message.answer("✅ Упражнение сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)







# ——— Добавить текст ———
@router.message(NewTopicStates.waiting_ex_text)
async def save_ex_text(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    topic = data["topic"]
    topic.setdefault("exercises", []).append({"type": "text", "text": text})
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
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
    await send_post_menu(message, state)













#------БЛОКИ ДЛЯ "📝 Добавить ТЕКСТ"----------


@router.message(NewTopicStates.waiting_post_action, F.text == "📝ТЕКСТ")
async def ask_vocab_text(message: Message, state: FSMContext):
    await message.answer("📝 Введите произвольный ТЕКСТ-блок для словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_text)



@router.message(NewTopicStates.waiting_vocab_text)
async def save_vocab_text_block(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    cp   = data["current_phase_id"]
    topic = data["topic"]
    # 1) Сохраняем текстовый блок
    new_block = {"type": "text", "text": text}
    topic["vocab"][cp-1]["vocab"].append(new_block)
    # 2) Записываем в файл
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    # 3) Сразу возвращаемся в пост-меню без квиза
    await message.answer("Текст словаря сохранён.", reply_markup=ReplyKeyboardRemove())
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
    text = message.text.strip()
    # 💬 Сохраняем подпись или None
    if text == '-':
        await state.update_data(vocab_caption=None)
    else:
        await state.update_data(vocab_caption=text)

    # 💬 Теперь запрашиваем само фото или URL
    await message.answer(
        "🖼 Пришлите фотографию (JPG/PNG) или URL картинки для словаря:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(NewTopicStates.waiting_vocab_photo)



# === БЛОК ДЛЯ "🖼 Добавить ФОТО / PHOTO" — расширенный вариант с GIF и стикерами ===

from pathlib import Path
import time

@router.message(NewTopicStates.waiting_vocab_photo, F.content_type.in_(["photo","video","animation","sticker","text"]))
async def receive_vocab_media(message: Message, state: FSMContext):
    """
    Сохраняем в тему либо:
      • JPG/PNG → media_type="photo"
      • MP4/GIF → media_type="animation"
      • Стикер → media_type="sticker"
      • URL (текст) — по расширению решаем, что это за медиа
    """
    data       = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]

    # создаём папку темы внутри vocab_images:
    theme_dir = Path("vocab_images") / topic["title"]
    theme_dir.mkdir(parents=True, exist_ok=True)

    entry = {"type": "photo"}  # общий «photo»-блок, но с уточнением media_type

    # 1) Если это стикер — просто сохраняем file_id
    if message.sticker:
        entry["media_type"] = "sticker"
        entry["photo"]      = message.sticker.file_id

    # 2) Если видео/GIF (Telegram animation или video)
    elif message.animation or message.video:
        media = message.animation or message.video
        entry["media_type"] = "animation"
        stamp = int(time.time())
        fname = f"vocab_{stamp}_{media.file_id[-5:]}.mp4"
        dest  = theme_dir / fname
        file  = await message.bot.get_file(media.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 3) Если фото — сохраняем JPG
    elif message.photo:
        ph    = message.photo[-1]
        entry["media_type"] = "photo"
        stamp = int(time.time())
        fname = f"vocab_{stamp}_{ph.file_id[-5:]}.jpg"
        dest  = theme_dir / fname
        file  = await message.bot.get_file(ph.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 4) Если пользователь прислал текст — считаем URL или sticker_id
    else:
        url = message.text.strip()
        # очень простой детектор: mp4 → animation, .jpg/.png → photo, иначе sticker
        lower = url.lower()
        if lower.endswith((".mp4", ".gif")):
            entry["media_type"] = "animation"
        elif lower.endswith((".jpg", ".jpeg", ".png")):
            entry["media_type"] = "photo"
        else:
            entry["media_type"] = "sticker"
        entry["photo"] = url

    # если была подпись, сохраняем её
    if data.get("vocab_caption"):
        entry["text"] = data["vocab_caption"]
        # очистим её, чтобы не дублировать
        await state.update_data(vocab_caption=None)

    # добавляем в JSON-тему и сохраняем
    # 💬 сохраняем медиа-блок в выбранной фазе
    data       = await state.get_data()
    cp         = data["current_phase_id"]
    topic      = data["topic"]
    topic["vocab"][cp-1]["vocab"].append(entry)


    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # 💬 Подтверждаем и сразу возвращаемся в пост-меню — без квиза к фото
    await message.answer("Фото/медиа сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)








# === БЛОК “ВИДЕО” ===

# 1) Запрашиваем заголовок видео
@router.message(NewTopicStates.waiting_video_title)
async def get_video_title(message: Message, state: FSMContext):
    video_title = message.text.strip()
    await state.update_data(current_video_title=video_title)
    # Переходим к запросу ссылки на видео
    await message.answer("Введите ССЫЛКУ на видео:")
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

    new_video = {
        "title": data.get("current_video_title"),
        "link": video_link
    }

    # Сохраняем в памяти и сразу в файл
    topic_data["videos"].append(new_video)
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Удаляем временную переменную
    await state.update_data(current_video_title=None)

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

    topic.setdefault("reading", []).append({
        "title": title,
        "fragments": [],
        "assets": []  # 💬 сюда кладём фото/стикеры/гифки для чтения
    })
    pack_index = len(topic["reading"]) - 1

    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic, current_reading_pack_index=pack_index)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
            [KeyboardButton(text="✅ Готово"), KeyboardButton(text="↩️ Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("Что добавляем в чтение?", reply_markup=kb)
    return await state.set_state(NewTopicStates.waiting_reading_action)

@router.message(NewTopicStates.waiting_reading_action)
async def handle_reading_action(message: Message, state: FSMContext):
    # 💬 меню действий внутри одного пакета "Чтение"
    action = (message.text or "").strip()

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
            [KeyboardButton(text="✅ Готово"), KeyboardButton(text="↩️ Назад")],
        ],
        resize_keyboard=True,
    )

    if action == "🧩 Ассет блоки":
        await message.answer(
            "Отправь ассет блоки текстом.\n"
            "Каждый фрагмент с новой строки.\n"
            "Пустые строки игнорируются.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return await state.set_state(NewTopicStates.waiting_reading_fragments_text)

    if action == "🖼 Фото":
        await message.answer(
            "Напиши подпись к фото одним сообщением.\n"
            "Если подпись не нужна, отправь -",
            reply_markup=ReplyKeyboardRemove(),
        )
        return await state.set_state(NewTopicStates.waiting_reading_photo_text)

    if action == "✅ Готово":
        # 💬 завершаем добавление пакета чтения
        await state.update_data(
            current_reading_pack_index=None,
            current_reading_title=None,
            reading_photo_caption=None,
        )
        await message.answer("✅ Пакет чтения сохранён.", reply_markup=get_main_menu())
        return await state.set_state(NewTopicStates.waiting_first_choice)

    if action == "↩️ Назад":
        # 💬 отмена: если пакет пустой, удаляем его, чтобы не плодить мусор
        data = await state.get_data()
        topic = data.get("topic") or {}
        topic_path = data.get("topic_path")

        try:
            idx = int(data.get("current_reading_pack_index"))
        except Exception:
            idx = -1

        if (
            topic_path
            and isinstance(topic.get("reading"), list)
            and 0 <= idx < len(topic["reading"])
        ):
            pack = topic["reading"][idx] or {}
            if not (pack.get("fragments") or pack.get("assets")):
                topic["reading"].pop(idx)
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
        await message.answer("↩️ Вернулись назад.", reply_markup=get_main_menu())
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
                [KeyboardButton(text="✅ Готово"), KeyboardButton(text="↩️ Назад")],
            ],
            resize_keyboard=True,
        )
        await message.answer("Ок, выбери действие.", reply_markup=kb)
        return await state.set_state(NewTopicStates.waiting_reading_action)

    fragments = [line.strip() for line in raw.split("\n") if line.strip()]
    if not fragments:
        await message.answer(
            "⚠️ Пусто. Пришли ассет блоки текстом.\n"
            "Каждый фрагмент с новой строки.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return await state.set_state(NewTopicStates.waiting_reading_fragments_text)

    data = await state.get_data()
    topic = data.get("topic") or {}
    topic_path = data.get("topic_path")

    try:
        pack_index = int(data.get("current_reading_pack_index"))
    except Exception:
        pack_index = -1

    packs = topic.setdefault("reading", [])
    if not (topic_path and 0 <= pack_index < len(packs)):
        await message.answer(
            "⚠️ Не найден активный пак чтения. Начни добавление чтения заново.",
            reply_markup=get_main_menu(),
        )
        return await state.set_state(NewTopicStates.waiting_first_choice)

    pack = packs[pack_index]
    pack.setdefault("fragments", [])
    pack["fragments"].extend(fragments)

    import json

    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
            [KeyboardButton(text="✅ Готово"), KeyboardButton(text="↩️ Назад")],
        ],
        resize_keyboard=True,
    )
    await message.answer("✅ Фрагменты добавлены. Что ещё добавить?", reply_markup=kb)
    return await state.set_state(NewTopicStates.waiting_reading_action)



@router.message(NewTopicStates.waiting_reading_photo_text)
async def handle_reading_photo_text(message: Message, state: FSMContext):
    # 💬 сохраняем подпись к фото и просим прислать фото или файл
    caption = (message.text or "").strip()

    if caption.lower() in {"назад", "↩️ назад"}:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🧩 Ассет блоки"), KeyboardButton(text="🖼 Фото")],
                [KeyboardButton(text="✅ Готово"), KeyboardButton(text="↩️ Назад")],
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

    packs = topic.setdefault("reading", [])
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
            [KeyboardButton(text="✅ Готово"), KeyboardButton(text="↩️ Назад")],
        ],
        resize_keyboard=True,
    )
    await message.answer("✅ Добавлено. Что ещё добавить?", reply_markup=kb)
    return await state.set_state(NewTopicStates.waiting_reading_action)






# 🎨 Утилита: меню действий в режиме редактирования
async def send_edit_menu(chat_id: int, bot: Bot, state: FSMContext):
    kb = make_kb([
        ["➕ Добавить словарь",    "➕ Добавить упражнение"],
        ["➕ Добавить видео",      "➕ Добавить диалог"],
        ["➕ Добавить QUIZ",       "📝 Добавить ТЕКСТ"],
        ["↩️ Вернуться в Главное меню"]
    ])
    await bot.send_message(chat_id, "✏️ Режим редактирования. Что вы хотите сделать?", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)

# 🎨 Хендлер: выбор действия в режиме редактирования
@router.message(EditTopicStates.choose_action)
async def handle_edit_action(message: Message, state: FSMContext):
    text = message.text.strip()
    # Каждая кнопка переводит в своё состояние и просит данные
    if text == "➕ Добавить словарь":
        await message.answer("Введите ЗАГОЛОВОК словаря:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_vocab_title)
    if text == "➕ Добавить упражнение":
        await message.answer("Введите НАЗВАНИЕ упражнения:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_ex_title)
    if text == "➕ Добавить видео":
        await message.answer("Введите ЗАГОЛОВОК видео:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_video_title)
    if text == "➕ Добавить диалог":
        await message.answer("Введите ЗАГОЛОВОК диалога:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_dialog_title)
    if text == "➕ Добавить QUIZ":
        await message.answer(
            "📝 Пришлите quiz в формате:\n"
            "Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного",
            reply_markup=ReplyKeyboardRemove()
        )
        return await state.set_state(EditTopicStates.waiting_quiz_block)
    if text == "📝 Добавить ТЕКСТ":
        await message.answer("📝 Введите произвольный текст:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_text_block)
    if text.startswith("↩️"):
        # Возврат в основное меню создания/просмотра
        await send_post_menu(message.chat.id, message.bot)
        return
    await message.answer("❗ Пожалуйста, выберите один из пунктов меню.")



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
                [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")],
                [KeyboardButton(text="ADD"), KeyboardButton(text="CHANALS")],
                [KeyboardButton(text="✏️ Редактировать темы")]
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
            [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")],
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
            [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")],
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

















