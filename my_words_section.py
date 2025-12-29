# my_words_section.py
# ================================================================================
#   🧩 МОИ СЛОВА (вынесено из core8_1.py)
# ================================================================================
import os
import json
import time
import random
import asyncio
import unicodedata
import datetime

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, PollAnswer,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    Chat, User, ReactionTypeEmoji
)
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from scenario.quiz_reactions import vocab_quiz_success_phrases  # 💬 как в vocab

my_words_router = Router()

# 💬 что делает эта часть = зависимости из Core (мы задаём их через init)
_CONTACT_URL = None
_MATERIALS_POST_URL = None

def init_my_words(contact_url: str, materials_url: str):
    global _CONTACT_URL, _MATERIALS_POST_URL
    _CONTACT_URL = contact_url
    _MATERIALS_POST_URL = materials_url


# ─────────────────────────────────────────────────────────────
# 💾 атомарная запись json (чтобы Railway Volume не ломал файл)
# ─────────────────────────────────────────────────────────────
def _atomic_json_dump(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ─────────────────────────────────────────────────────────────
# ⏱ тайминги (как в core vocab)
# ─────────────────────────────────────────────────────────────
QUIZ_OPEN_PERIOD_S = 12.0
QUIZ_TIMEOUT_TASK_S = 13.0
SLEEP_AFTER_FEEDBACK_S = 0.35


# ─────────────────────────────────────────────────────────────
# 🧠 normalize_textquiz (как в core)
# ─────────────────────────────────────────────────────────────
def normalize_textquiz(text: str) -> str:
    txt = (text or "").lower().strip()
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = txt.replace("'", "").replace("`", "")
    parts = txt.split()
    articles = {"el", "la", "los", "las", "un", "una", "unos", "unas"}
    if parts and parts[0] in articles:
        parts = parts[1:]
    return "".join(parts)


async def send_and_auto_delete_text(bot, chat_id, text, delay=0.35, **kwargs):
    msg = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except TelegramBadRequest:
        pass


async def smart_reply(target: Message, text: str, **kwargs):
    # 💬 что делает эта часть = копия smart_reply, но без зависимости от core
    chat_id = target.chat.id
    bot = target.bot
    try:
        await bot.send_chat_action(chat_id, action=ChatAction.TYPING)
    except Exception:
        pass
    await asyncio.sleep(min(len(text) * 0.01, 3.0))
    return await bot.send_message(chat_id, text, **kwargs)


# ─────────────────────────────────────────────────────────────
# 💬 MY WORDS storage (Railway Volume)
# ─────────────────────────────────────────────────────────────
MY_WORDS_PATH = "/data/my_words.json"
MY_WORDS_BACKUP_PATH = "/data/my_words_backup.json"

def load_my_words_data() -> dict:
    if not os.path.exists(MY_WORDS_PATH):
        data = {"users": {}}
        _atomic_json_dump(MY_WORDS_PATH, data)
        _atomic_json_dump(MY_WORDS_BACKUP_PATH, data)
        return data

    try:
        with open(MY_WORDS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        if os.path.exists(MY_WORDS_BACKUP_PATH):
            try:
                with open(MY_WORDS_BACKUP_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _atomic_json_dump(MY_WORDS_PATH, data)
                return data
            except Exception:
                pass
        data = {"users": {}}
        _atomic_json_dump(MY_WORDS_PATH, data)
        _atomic_json_dump(MY_WORDS_BACKUP_PATH, data)
        return data

def save_my_words_data(data: dict) -> None:
    _atomic_json_dump(MY_WORDS_PATH, data)
    _atomic_json_dump(MY_WORDS_BACKUP_PATH, data)

def ensure_my_words_user(data: dict, user_id: str) -> dict:
    users = data.setdefault("users", {})
    u = users.setdefault(user_id, {})
    u.setdefault("settings", {"session_words": 5})
    u.setdefault("categories", {})
    return u

def parse_es_ru_pair(raw: str):
    if not raw:
        return None, None
    raw = raw.replace("—", "-").replace("–", "-").replace("−", "-")
    if "-" not in raw:
        return None, None
    left, right = raw.split("-", 1)
    es = left.strip()
    ru = right.strip()
    if not es or not ru:
        return None, None
    return es, ru

def gen_my_word_id() -> str:
    return f"{int(time.time()*1000)}_{random.randint(1000, 9999)}"


# ─────────────────────────────────────────────────────────────
# ✅ State strings (ВАЖНО: чтобы не импортировать LessonStates из core)
# ─────────────────────────────────────────────────────────────
ST_MENU = "LessonStates:mywords_menu"
ST_SETTINGS = "LessonStates:mywords_settings_wait"
ST_ADD_CHOOSE = "LessonStates:mywords_add_choose_category"
ST_ADD_NEW_CAT = "LessonStates:mywords_add_new_category"
ST_ADD_PAIR = "LessonStates:mywords_add_input_pair"
ST_ADD_CONFIRM = "LessonStates:mywords_add_confirm"
ST_LEARN_CHOOSE = "LessonStates:mywords_learn_choose_cat"
ST_QUIZ = "LessonStates:mywords_quiz"
ST_TEXT = "LessonStates:mywords_text"
ST_OFFER = "LessonStates:mywords_offer_continue"
ST_EDIT_MENU = "LessonStates:mywords_edit_menu"
ST_EDIT_CHOOSE = "LessonStates:mywords_edit_choose_category"
ST_EDIT_DEL = "LessonStates:mywords_edit_delete_wait"
ST_EDIT_IDX = "LessonStates:mywords_edit_edit_index_wait"
ST_EDIT_PAIR = "LessonStates:mywords_edit_edit_pair_wait"
ST_EDIT_RENAME = "LessonStates:mywords_edit_rename_wait"

ST_CORE_MAIN_MENU = "LessonStates:choosing_category"  # 💬 главное меню core


# ─────────────────────────────────────────────────────────────
#   🧩 UI-клавиатуры
# ─────────────────────────────────────────────────────────────
def build_mywords_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📖 Учить мои слова", callback_data="mywords:learn_new"),
            InlineKeyboardButton(text="🔁 Повторить выученные", callback_data="mywords:learn_repeat")
        ],
        [
            InlineKeyboardButton(text="➕ Добавить слово", callback_data="mywords:add_open"),
            InlineKeyboardButton(text="✏️ Редактировать", callback_data="mywords:edit_open")
        ],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="mywords:settings")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:back_main")]
    ])

def build_stop_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏹ Стоп")]], resize_keyboard=True)

def build_offer_continue_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Продолжить", callback_data="mywords:continue"),
            InlineKeyboardButton(text="🏠 Домой", callback_data="mywords:home")
        ]
    ])

def mywords_build_categories_kb(categories: list, cb_prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=name, callback_data=f"{cb_prefix}:{i}")] for i, name in enumerate(categories)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─────────────────────────────────────────────────────────────
# 📦 helpers
# ─────────────────────────────────────────────────────────────
def mywords_get_user_block(user_id: str):
    store = load_my_words_data()
    u = ensure_my_words_user(store, user_id)
    return store, u

def mywords_get_categories(user_id: str) -> list:
    _, u = mywords_get_user_block(user_id)
    return list((u.get("categories") or {}).keys())

def mywords_get_session_words(user_id: str) -> int:
    _, u = mywords_get_user_block(user_id)
    n = int(u.get("settings", {}).get("session_words", 5) or 5)
    return max(1, min(n, 30))

def mywords_words_for_mode(u: dict, category: str, mode: str) -> list:
    words = (u.get("categories") or {}).get(category, [])
    if mode == "new":
        return [w for w in words if not w.get("learned")]
    return [w for w in words if w.get("learned")]

def mywords_all_es_in_category(u: dict, category: str) -> list:
    words = (u.get("categories") or {}).get(category, [])
    return [w.get("es","") for w in words if w.get("es")]

def mywords_build_quiz_options(correct_es: str, all_es: list):
    opts = [correct_es]
    pool = [x for x in all_es if x and x != correct_es]
    random.shuffle(pool)
    for x in pool[:3]:
        opts.append(x)
    random.shuffle(opts)
    return opts, opts.index(correct_es)


# ─────────────────────────────────────────────────────────────
# ✅ ВХОД ИЗ ГЛАВНОГО МЕНЮ CORE (menu:mywords)
# ─────────────────────────────────────────────────────────────
@my_words_router.callback_query(F.data == "menu:mywords")
async def open_mywords_from_core_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    return await mywords_menu(callback.message, state)


# ─────────────────────────────────────────────────────────────
# 🧩 меню «Мои слова»
# ─────────────────────────────────────────────────────────────
async def mywords_show_main_menu(message: Message, state: FSMContext):
    # 💬 возвращаемся в главное меню core (кнопки menu:...)
    inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],
        [
            InlineKeyboardButton(text="📎 Материалы", url=_MATERIALS_POST_URL or "https://t.me/"),
            InlineKeyboardButton(text="💬 Связь", url=_CONTACT_URL or "https://t.me/")
        ],
        [
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),
            InlineKeyboardButton(text="🧩 Мои слова", callback_data="menu:mywords")
        ],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
    ])

    try:
        await message.edit_text("Главное меню:", reply_markup=inline_kb_main)
    except Exception:
        await smart_reply(message, "Главное меню:", reply_markup=inline_kb_main)

    await state.set_state(ST_CORE_MAIN_MENU)  # 💬 важно = чтобы core-хендлеры menu: работали

async def mywords_menu(message: Message, state: FSMContext):
    user_id = str(message.chat.id)
    store, _ = mywords_get_user_block(user_id)
    save_my_words_data(store)

    txt = "🧩 *Мои слова*\n\nВыбирай действие:"
    kb = build_mywords_menu_kb()
    try:
        await message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await smart_reply(message, txt, reply_markup=kb, parse_mode="Markdown")

    await state.set_state(ST_MENU)


# ================================================================================
# 🚨 ДАЛЬШЕ = ты переносишь оставшийся блок «🧩 МОИ СЛОВА» из core8_1.py
# ВАЖНО:
# 1) заменяешь @dp. -> @my_words_router.
# 2) заменяешь LessonStates.mywords_... -> строки ST_...
#
# Чтобы не перегружать ответ на 1000+ строк, я дам тебе это следующим сообщением
# цельным блоком (там много).
# ================================================================================

