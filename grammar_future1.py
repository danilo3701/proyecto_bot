# grammar_future.py
# 🧠 Модуль "Грамматика" для Telegram-бота (aiogram 3.x)
# Архитектура: GrammarFuture v0.3 (Duolingo-style locks, quiz-pool, completion)

from __future__ import annotations
import asyncio
import random
import json
import os
import re
import html
import time
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    PollAnswer,
)
from scenario.grammar_quiz_reactions import (
    grammar_quiz_success_phrases,
    GRAMMAR_CORRECT_EMOJI,
    GRAMMAR_WRONG_EMOJI,
    _maybe_send_grammar_emoji,
)




from aiogram.exceptions import TelegramBadRequest
from aiogram.types.reaction_type_emoji import ReactionTypeEmoji
router = Router()



# ═══════════════════════════════════════════════════════════════════════════
# 🔧 DEPENDENCY INJECTION (из core8_1.py)
# ═══════════════════════════════════════════════════════════════════════════
_load_user_data: Optional[Callable[[], Dict[str, Any]]] = None
_save_user_data: Optional[Callable[[Dict[str, Any]], None]] = None
_ADMIN_CHAT_ID: Optional[int] = None
_bot: Optional[Bot] = None

DATA_DIR = Path("/data")

# 💬 Важно: грамматика хранится отдельно от тем уроков (/data/topics),
# 💬 чтобы legacy-конструктор тем не подхватывал грамматические JSON.
GRAMMAR_TOPICS_DIR = DATA_DIR / "grammar_topics"

XP_DATA_FILE = DATA_DIR / "xp_data.json"


def init_grammar_future(
    *,
    load_user_data: Callable[[], Dict[str, Any]],
    save_user_data: Callable[[Dict[str, Any]], None],
    admin_chat_id: int,
    bot: Bot,
) -> None:
    """
    Инициализация модуля GrammarFuture
    """
    global _load_user_data, _save_user_data, _ADMIN_CHAT_ID, _bot
    _load_user_data = load_user_data
    _save_user_data = save_user_data
    _bot = bot
    try:
        _ADMIN_CHAT_ID = int(admin_chat_id)
    except Exception:
        _ADMIN_CHAT_ID = None

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GRAMMAR_TOPICS_DIR.mkdir(parents=True, exist_ok=True)

    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 📦 CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
TOPICS_PER_SCREEN = 4
DEFAULT_UNLOCKED_SCREENS = 3
STARS_TO_UNLOCK = 3  # нужно завершить 3 из 4 тем на экране
XP_PER_TOPIC_COMPLETION = 150
POLL_TIMEOUT_SEC = 12
PAGE_DELIM = "===PAGE==="
READ_DELAY_S = 1.0  # пауза, чтобы пользователь успел прочитать реакцию/объяснение


# ═══════════════════════════════════════════════════════════════════════════
# 🛠 UTILS (Clean Chat)
# ═══════════════════════════════════════════════════════════════════════════
async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def send_and_auto_delete(
    message: Message,
    text: str,
    delay_sec: int = 1,
    parse_mode: str = "HTML",
) -> None:
    msg = await message.answer(text, parse_mode=parse_mode, disable_web_page_preview=True)
    await asyncio.sleep(delay_sec)
    await safe_delete_message(message.bot, msg.chat.id, msg.message_id)


# ═══════════════════════════════════════════════════════════════════════════
# 📊 DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class GrammarTopic:
    key: str
    title: str
    category: str
    pages: List[str]
    quiz_pool: List[Dict[str, Any]]


@dataclass
class UserGrammarProgress:
    completed_topics: List[str]
    stars_by_screen: Dict[int, int]  # screen_idx -> кол-во звёзд
    unlocked_last_screen: int
    xp_given_topics: List[str]


# ═══════════════════════════════════════════════════════════════════════════
# 💾 STORAGE (Topics + User Progress)
# ═══════════════════════════════════════════════════════════════════════════

def _sanitize_telegram_html_page(s: str) -> str:
    """
    💬 Санитайзер страниц, чтобы Telegram не падал на unsupported HTML.
    Сейчас критично: <br> (и варианты) → '\n'
    """
    t = str(s or "")
    if not t:
        return ""

    # <br> variants (в т.ч. если старые JSON уже сохранены с <br>)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)

    # нормализуем переносы
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    return t


def load_grammar_topics() -> List[GrammarTopic]:
    """
    Загружает все темы грамматики из /data/topics/
    Фильтр: category == "gram" ИЛИ key startswith "gram_"
    """
    topics = []
    if not GRAMMAR_TOPICS_DIR.exists():
        return topics

    for path in GRAMMAR_TOPICS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            key = data.get("key", "")
            category = data.get("category", "")
            
            # Фильтруем только грамматику
            if category != "gram" and not key.startswith("gram_"):
                continue

            topics.append(GrammarTopic(
                key=key,
                title=data.get("title", "Без названия"),
                category=category,
                pages=[_sanitize_telegram_html_page(p) for p in (data.get("pages", []) or [])],
                quiz_pool=data.get("quiz_pool", []),
            ))
        except Exception:
            continue

    # Сортируем по key для стабильного порядка
    topics.sort(key=lambda t: t.key)
    return topics


def save_grammar_topic(topic: GrammarTopic) -> None:
    """
    Сохраняет тему грамматики в /data/topics/<key>.json
    """
    path = GRAMMAR_TOPICS_DIR / f"{topic.key}.json"
    data = {
        "key": topic.key,
        "title": topic.title,
        "category": topic.category,
        "pages": topic.pages,
        "quiz_pool": topic.quiz_pool,
    }
    
    # Atomic save (как в core8_1)
    temp_path = path.with_suffix(".tmp")
    try:
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception as e:
        logging.exception(f"Failed to save grammar topic {topic.key}: {e}")
        if temp_path.exists():
            temp_path.unlink()


def delete_grammar_topic(key: str) -> None:
    """
    Удаляет тему грамматики
    """
    path = GRAMMAR_TOPICS_DIR / f"{key}.json"
    if path.exists():
        path.unlink()


def get_user_grammar_progress(user_id: int) -> UserGrammarProgress:
    """
    Получает прогресс пользователя по грамматике из /data/xp_data.json
    """
    if not _load_user_data:
        return UserGrammarProgress([], {}, DEFAULT_UNLOCKED_SCREENS, [])

    try:
        xp_data = _load_user_data()
        user_data = xp_data.get(str(user_id), {})
        gram_data = user_data.get("grammar_future", {})

        return UserGrammarProgress(
            completed_topics=gram_data.get("completed_topics", []),
            stars_by_screen=gram_data.get("stars_by_screen", {}),
            unlocked_last_screen=gram_data.get("unlocked_last_screen", DEFAULT_UNLOCKED_SCREENS),
            xp_given_topics=gram_data.get("xp_given_topics", []),
        )
    except Exception:
        return UserGrammarProgress([], {}, DEFAULT_UNLOCKED_SCREENS, [])


def save_user_grammar_progress(user_id: int, progress: UserGrammarProgress) -> None:
    """
    Сохраняет прогресс пользователя по грамматике в /data/xp_data.json
    """
    if not _load_user_data or not _save_user_data:
        return

    try:
        xp_data = _load_user_data()
        if str(user_id) not in xp_data:
            xp_data[str(user_id)] = {"xp": 0}

        # Конвертируем ключи stars_by_screen в строки для JSON
        stars_dict = {str(k): v for k, v in progress.stars_by_screen.items()}

        xp_data[str(user_id)]["grammar_future"] = {
            "completed_topics": progress.completed_topics,
            "stars_by_screen": stars_dict,
            "unlocked_last_screen": progress.unlocked_last_screen,
            "xp_given_topics": progress.xp_given_topics,
        }

        _save_user_data(xp_data)
    except Exception as e:
        logging.exception(f"Failed to save grammar progress for user {user_id}: {e}")


def add_xp_to_user(user_id: int, xp_amount: int) -> None:
    """
    Добавляет XP пользователю
    """
    if not _load_user_data or not _save_user_data:
        return

    try:
        xp_data = _load_user_data()
        if str(user_id) not in xp_data:
            xp_data[str(user_id)] = {"xp": 0}

        current_xp = xp_data[str(user_id)].get("xp", 0)
        xp_data[str(user_id)]["xp"] = current_xp + xp_amount

        _save_user_data(xp_data)
    except Exception as e:
        logging.exception(f"Failed to add XP to user {user_id}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ⌨️ KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_topics_list(
    screen_idx: int,
    total_screens: int,
    unlocked_last: int,
    topics_on_screen: List[GrammarTopic],
    completed_topics: List[str],
    stars_current_screen: int,
) -> InlineKeyboardMarkup:
    """
    Клавиатура списка тем (4 темы + пагинация + назад)
    """
    rows = []

    # Кнопки тем
    for topic in topics_on_screen:
        checkmark = "✅ " if topic.key in completed_topics else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{checkmark}{topic.title}",
                callback_data=f"gram:topic:{topic.key}"
            )
        ])

    # Пагинация
    if total_screens > 1:
        prev_cb = "gram:screen_prev" if screen_idx > 0 else "gram:noop"
        
        # Следующий экран: если за лимитом → 🔒
        if screen_idx < total_screens - 1:
            if screen_idx + 1 <= unlocked_last:
                next_cb = "gram:screen_next"
                next_text = "➡️"
            else:
                next_cb = "gram:screen_locked"
                next_text = "➡️🔒"
        else:
            next_cb = "gram:noop"
            next_text = "➡️"

        rows.append([
            InlineKeyboardButton(text="⬅️", callback_data=prev_cb),
            InlineKeyboardButton(text=f"{screen_idx + 1}/{total_screens}", callback_data="gram:noop"),
            InlineKeyboardButton(text=next_text, callback_data=next_cb),
        ])

    # Назад
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_topic_lesson(has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    """
    Клавиатура листалки урока:
    верх: ◀️  🏠  ▶️
    низ:  ПРОВЕРИТЬ СЕБЯ
    """
    prev_cb = "gram:prev" if has_prev else "gram:noop"
    next_cb = "gram:next" if has_next else "gram:noop"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️", callback_data=prev_cb),
            InlineKeyboardButton(text="🏠", callback_data="gram:home"),
            InlineKeyboardButton(text="▶️", callback_data=next_cb),
        ],
        [
            InlineKeyboardButton(text="ПРОВЕРИТЬ СЕБЯ", callback_data="gram:quiz"),
        ]
    ])



def kb_quiz_stop() -> ReplyKeyboardMarkup:
    """
    Reply клавиатура "Стоп" для quiz-flow
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⏹ Стоп")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 🎯 USER FLOW: Вход в грамматику (menu:grammar)
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "menu:grammar")
async def gram_menu_entry(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Вход в модуль грамматики из главного меню
    """
    await cb.answer()  # 💬 сразу закрываем loading, чтобы не зависало при долгом рендере/ошибке edit

    await state.clear()  # Очищаем состояние
    
    user_id = cb.from_user.id
    topics = load_grammar_topics()
    
    if not topics:
        await cb.answer("Темы грамматики пока не добавлены", show_alert=True)
        return

    progress = get_user_grammar_progress(user_id)
    
    # Сохраняем в state для навигации
    await state.update_data(gram_screen_idx=0)
    
    # Рендерим экран
    await _render_topics_screen(cb.message, state, user_id, screen_idx=0, topics=topics, progress=progress)



async def _render_topics_screen(
    message: Message,
    state: FSMContext,
    user_id: int,
    screen_idx: int,
    topics: List[GrammarTopic],
    progress: UserGrammarProgress,
) -> None:
    """
    Рендерит экран списка тем
    """
    total_topics = len(topics)
    total_screens = (total_topics + TOPICS_PER_SCREEN - 1) // TOPICS_PER_SCREEN
    
    # Темы на текущем экране
    start_idx = screen_idx * TOPICS_PER_SCREEN
    end_idx = min(start_idx + TOPICS_PER_SCREEN, total_topics)
    topics_on_screen = topics[start_idx:end_idx]
    
    # Конвертируем ключи в int для stars_by_screen
    stars_by_screen_int = {}
    for k, v in progress.stars_by_screen.items():
        try:
            stars_by_screen_int[int(k)] = v
        except (ValueError, TypeError):
            pass
    
    # Звёзды на текущем экране
    stars_current = stars_by_screen_int.get(screen_idx, 0)
    stars_needed = STARS_TO_UNLOCK
    
    # Текст экрана
    text_parts = [
        "🧠 <b>Грамматика</b>",
        f"Экран {screen_idx + 1}/{total_screens}",
        f"⭐ {stars_current}/{stars_needed} до открытия следующего",
        "",
    ]
    
    for i, topic in enumerate(topics_on_screen, start=1):
        checkmark = "✅ " if topic.key in progress.completed_topics else ""
        text_parts.append(f"{start_idx + i}) {checkmark}{topic.title}")
    
    text = "\n".join(text_parts)
    
    # Клавиатура
    kb = kb_topics_list(
        screen_idx=screen_idx,
        total_screens=total_screens,
        unlocked_last=progress.unlocked_last_screen,
        topics_on_screen=topics_on_screen,
        completed_topics=progress.completed_topics,
        stars_current_screen=stars_current,
    )
    
    # Edit or send
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════════════
# 🎯 USER FLOW: Навигация по экранам тем
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "gram:screen_prev")
async def gram_screen_prev(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Предыдущий экран тем
    """
    data = await state.get_data()
    current_screen = data.get("gram_screen_idx", 0)
    
    if current_screen > 0:
        new_screen = current_screen - 1
        await state.update_data(gram_screen_idx=new_screen)
        
        user_id = cb.from_user.id
        topics = load_grammar_topics()
        progress = get_user_grammar_progress(user_id)
        
        await _render_topics_screen(cb.message, state, user_id, new_screen, topics, progress)
    
    await cb.answer()


@router.callback_query(F.data == "gram:screen_next")
async def gram_screen_next(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Следующий экран тем
    """
    data = await state.get_data()
    current_screen = data.get("gram_screen_idx", 0)
    
    topics = load_grammar_topics()
    total_screens = (len(topics) + TOPICS_PER_SCREEN - 1) // TOPICS_PER_SCREEN
    
    if current_screen < total_screens - 1:
        new_screen = current_screen + 1
        await state.update_data(gram_screen_idx=new_screen)
        
        user_id = cb.from_user.id
        progress = get_user_grammar_progress(user_id)
        
        await _render_topics_screen(cb.message, state, user_id, new_screen, topics, progress)
    
    await cb.answer()


@router.callback_query(F.data == "gram:screen_locked")
async def gram_screen_locked(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Попытка перейти на заблокированный экран
    """
    data = await state.get_data()
    current_screen = data.get("gram_screen_idx", 0)
    target_screen = current_screen + 1
    
    user_id = cb.from_user.id
    progress = get_user_grammar_progress(user_id)
    
    unlock_screen = target_screen - 3
    if unlock_screen < 0:
        unlock_screen = 0
    
    await cb.answer(
        f"🔒 Экран {target_screen + 1} пока закрыт.\n"
        f"Набери ⭐ {STARS_TO_UNLOCK}/{TOPICS_PER_SCREEN} на экране {unlock_screen + 1}, чтобы открыть его.",
        show_alert=True
    )


# ═══════════════════════════════════════════════════════════════════════════
# 🎯 USER FLOW: Открытие темы (листалка)
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("gram:topic:"))
async def gram_open_topic(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает тему (листалка страниц)
    """
    topic_key = cb.data.split(":")[-1]
    topics = load_grammar_topics()
    
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await cb.answer("Тема не найдена", show_alert=True)
        return
    
    # Сохраняем в state
    await state.update_data(
        gram_current_topic=topic_key,
        gram_current_page=0,
    )
    
    # Рендерим первую страницу
    await _render_topic_page(cb.message, state, topic, page_idx=0)
    await cb.answer()


async def _render_topic_page(
    message: Message,
    state: FSMContext,
    topic: GrammarTopic,
    page_idx: int,
) -> None:
    """
    Рендерит страницу темы
    """
    total_pages = len(topic.pages)
    
    if page_idx < 0:
        page_idx = 0
    if page_idx >= total_pages:
        page_idx = total_pages - 1
    
    # Текст страницы
    page_text = _sanitize_telegram_html_page(topic.pages[page_idx]) if topic.pages else "Страницы не добавлены"

    
    text = (
        f"🧠 <b>{topic.title}</b>\n\n"
        f"Стр. {page_idx + 1}/{total_pages}\n\n"
        f"{page_text}"
    )
    
    # Клавиатура
    kb = kb_topic_lesson(
        has_prev=page_idx > 0,
        has_next=page_idx < total_pages - 1,
    )
    
    # Edit
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "gram:prev")
async def gram_prev_page(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Предыдущая страница темы
    """
    data = await state.get_data()
    topic_key = data.get("gram_current_topic")
    current_page = data.get("gram_current_page", 0)
    
    if not topic_key:
        await cb.answer()
        return
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await cb.answer()
        return
    
    new_page = max(0, current_page - 1)
    await state.update_data(gram_current_page=new_page)
    await _render_topic_page(cb.message, state, topic, new_page)
    await cb.answer()


@router.callback_query(F.data == "gram:next")
async def gram_next_page(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Следующая страница темы
    """
    data = await state.get_data()
    topic_key = data.get("gram_current_topic")
    current_page = data.get("gram_current_page", 0)
    
    if not topic_key:
        await cb.answer()
        return
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await cb.answer()
        return
    
    new_page = min(len(topic.pages) - 1, current_page + 1)
    await state.update_data(gram_current_page=new_page)
    await _render_topic_page(cb.message, state, topic, new_page)
    await cb.answer()


@router.callback_query(F.data == "gram:home")
async def gram_home(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Возврат к списку тем
    """
    data = await state.get_data()
    screen_idx = data.get("gram_screen_idx", 0)
    
    user_id = cb.from_user.id
    topics = load_grammar_topics()
    progress = get_user_grammar_progress(user_id)
    
    await _render_topics_screen(cb.message, state, user_id, screen_idx, topics, progress)
    await cb.answer()


# ═══════════════════════════════════════════════════════════════════════════
# 🎯 USER FLOW: Quiz Flow
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "gram:quiz")
async def gram_start_quiz(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Запуск quiz-flow
    """
    data = await state.get_data()
    
    # Guard: не запускаем quiz, если уже запущен
    if data.get("gram_in_quiz"):
        await cb.answer("⚠️ Квиз уже запущен", show_alert=True)
        return
    
    topic_key = data.get("gram_current_topic")
    
    if not topic_key:
        await cb.answer("Ошибка: тема не выбрана", show_alert=True)
        return
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await cb.answer("Тема не найдена", show_alert=True)
        return
    
    if not topic.quiz_pool:
        await cb.answer("⚠️ Квизы ещё не добавлены", show_alert=True)
        return
    
    await cb.answer()
    
    # Запускаем quiz-flow и сохраняем task reference
    task = asyncio.create_task(_run_quiz_flow(cb.message, state, topic, cb.from_user.id))
    await state.update_data(gram_quiz_task=id(task))  # Сохраняем ID для отладки


async def _run_quiz_flow(
    message: Message,
    state: FSMContext,
    topic: GrammarTopic,
    user_id: int,
) -> None:
    """
    Основной цикл quiz-flow
    """
    bot = message.bot
    chat_id = message.chat.id
    
    # Показываем reply keyboard "Стоп"
    stop_kb = kb_quiz_stop()
    stop_msg = await message.answer("⏹ Нажми «Стоп», чтобы выйти", reply_markup=stop_kb)
    
    quiz_queue = topic.quiz_pool[:]
    poll_msg_ids = []
    
    # Помечаем, что мы в quiz-flow
    await state.update_data(gram_in_quiz=True, gram_quiz_stop=False)
    
    try:
        while quiz_queue:
            # Проверяем, не нажали ли Стоп
            data = await state.get_data()
            if data.get("gram_quiz_stop"):
                break
            
            quiz = quiz_queue.pop(0)

            # 💬 Перемешиваем варианты на показе (в storage правильный всегда первым)
            options = list(quiz.get("options", []) or [])
            correct_idx = int(quiz.get("correct_index", 0))

            if options and 0 <= correct_idx < len(options):
                correct_answer = options[correct_idx]
                random.shuffle(options)
                correct_idx = options.index(correct_answer)
            else:
                # 💬 если квиз битый = безопасно не падаем
                correct_idx = 0

            
            # Отправляем poll
            try:
                poll_msg = await message.answer_poll(
                    question=quiz.get("question", ""),
                    options=options,
                    type="quiz",
                    correct_option_id=correct_idx,
                    is_anonymous=False,
                    open_period=POLL_TIMEOUT_SEC,
                )

                poll_msg_ids.append(poll_msg.message_id)
            except Exception as e:
                logging.exception(f"Failed to send poll for user {user_id}, topic {topic.key}: {e}")
                continue
            
            # Ждём ответа пользователя или timeout
            poll_id = poll_msg.poll.id if getattr(poll_msg, "poll", None) else None
            if not poll_id:
                # 💬 Без poll.id мы не сможем сопоставить ответ PollAnswer → не зависаем и не "флэш-удаляем"
                logging.warning(
                    f"[gram quiz] poll.id is None (user={user_id}, topic={topic.key}), skip poll message_id={poll_msg.message_id}"
                )
                await safe_delete_message(bot, chat_id, poll_msg.message_id)
                continue

            timeout = POLL_TIMEOUT_SEC
            start_time = time.time()
            is_correct = False

            while time.time() - start_time < timeout:
                data = await state.get_data()

                # Проверка флага stop
                if data.get("gram_quiz_stop"):
                    break

                # Проверка ответа пользователя (guard: poll_id не None)
                if poll_id and data.get("last_poll_id") == poll_id:
                    option_ids = data.get("last_option_ids", [])
                    is_correct = correct_idx in option_ids if option_ids else False

                    # Очищаем результат из state
                    await state.update_data(last_poll_id=None, last_option_ids=None)
                    break

                await asyncio.sleep(0.3)  # Проверяем каждые 300ms

            
            # 💬 если нажали Stop — выходим без complete-логики (дальше обработаем после цикла)
            data = await state.get_data()
            if data.get("gram_quiz_stop"):
                try:
                    await bot.stop_poll(chat_id, poll_msg.message_id)
                except Exception:
                    pass
                await safe_delete_message(bot, chat_id, poll_msg.message_id)
                break

            # ─────────────────────────────────────────────
            # ✅ Реакции (изолированы для грамматики)
            # ─────────────────────────────────────────────
            reaction_msg_id: int | None = None

            # ✅ 1) Показали реакцию/объяснение
            if is_correct:
                text = random.choice(grammar_quiz_success_phrases) if grammar_quiz_success_phrases else "✅"
                reaction_msg = await message.answer(text)
                reaction_msg_id = reaction_msg.message_id

                asyncio.create_task(_maybe_send_grammar_emoji(bot, chat_id, GRAMMAR_CORRECT_EMOJI))

            else:
                explanation = quiz.get("explanation_wrong", "")
                if explanation:
                    reaction_msg = await message.answer(f"❌ {explanation}")
                    reaction_msg_id = reaction_msg.message_id

                asyncio.create_task(_maybe_send_grammar_emoji(bot, chat_id, GRAMMAR_WRONG_EMOJI))

            # ✅ 2) Пауза на прочтение
            await asyncio.sleep(READ_DELAY_S)

            # ✅ 3) stop_poll
            try:
                await bot.stop_poll(chat_id, poll_msg.message_id)
            except Exception:
                pass

            # ✅ 4) удалить poll
            await safe_delete_message(bot, chat_id, poll_msg.message_id)

            # ✅ 5) удалить реакцию/объяснение (если было)
            if reaction_msg_id is not None:
                await safe_delete_message(bot, chat_id, reaction_msg_id)

            # WRONG → в конец очереди (поведение очереди не меняем)
            if not is_correct:
                quiz_queue.append(quiz)




        
        # Если вышли по Stop — НЕ complete, просто вернуться в список тем на тот же экран
        data = await state.get_data()
        if data.get("gram_quiz_stop"):
            screen_idx = data.get("gram_screen_idx", 0)
            topics = load_grammar_topics()
            progress = get_user_grammar_progress(user_id)
            await _render_topics_screen(message, state, user_id, screen_idx, topics, progress)
            return


        # Все квизы пройдены - completion
        await _complete_topic(message, state, topic, user_id)


    finally:
        # Очистка
        await safe_delete_message(bot, chat_id, stop_msg.message_id)
        
        for msg_id in poll_msg_ids:
            await safe_delete_message(bot, chat_id, msg_id)
        
        # Убираем reply keyboard (без мусора в чате)
        rm_msg = await message.answer("✅", reply_markup=ReplyKeyboardRemove())
        await safe_delete_message(bot, chat_id, rm_msg.message_id)
        
        await state.update_data(gram_in_quiz=False)


async def _complete_topic(
    message: Message,
    state: FSMContext,
    topic: GrammarTopic,
    user_id: int,
) -> None:
    """
    Завершение темы (все квизы пройдены)
    """
    progress = get_user_grammar_progress(user_id)
    
    # Проверяем, не завершена ли уже
    if topic.key in progress.completed_topics:
        first_time = False
    else:
        first_time = True
        progress.completed_topics.append(topic.key)
    
    # Обновляем звёзды на экране
    data = await state.get_data()
    screen_idx = data.get("gram_screen_idx", 0)
    
    # Конвертируем ключи в int
    stars_by_screen_int = {}
    for k, v in progress.stars_by_screen.items():
        try:
            stars_by_screen_int[int(k)] = v
        except (ValueError, TypeError):
            pass
    
    current_stars = stars_by_screen_int.get(screen_idx, 0)
    if first_time:
        stars_by_screen_int[screen_idx] = current_stars + 1
    
    progress.stars_by_screen = stars_by_screen_int
    
    # Проверяем unlock нового экрана
    new_stars = stars_by_screen_int.get(screen_idx, 0)
    if new_stars >= STARS_TO_UNLOCK:
        new_unlock = max(progress.unlocked_last_screen, screen_idx + 3)
        if new_unlock > progress.unlocked_last_screen:
            progress.unlocked_last_screen = new_unlock
            # Показываем уведомление об открытии
            await send_and_auto_delete(
                message,
                f"🔓 Открыт экран {new_unlock + 1}!",
                delay_sec=1
            )
    
    # Начисляем XP (только первый раз)
    if first_time and topic.key not in progress.xp_given_topics:
        add_xp_to_user(user_id, XP_PER_TOPIC_COMPLETION)
        progress.xp_given_topics.append(topic.key)
    
    # Сохраняем прогресс
    save_user_grammar_progress(user_id, progress)
    
    # Показываем победные сообщения
    if first_time:
        await send_and_auto_delete(message, "✅ Тема пройдена! +150 XP", delay_sec=1)
        await send_and_auto_delete(message, "🎉✨⭐", delay_sec=1)
    
    # Возвращаем к списку тем
    topics = load_grammar_topics()
    await _render_topics_screen(message, state, user_id, screen_idx, topics, progress)



@router.message(F.text == "⏹ Стоп", StateFilter("*"))  # ← добавить StateFilter("*")
async def gram_quiz_stop(message: Message, state: FSMContext) -> None:
    """
    Остановка quiz-flow
    """
    data = await state.get_data()
    if not data.get("gram_in_quiz"):
        return
    
    await state.update_data(gram_quiz_stop=True)
    await safe_delete_message(message.bot, message.chat.id, message.message_id)



# ═══════════════════════════════════════════════════════════════════════════
# 🎯 POLL ANSWER HANDLER (для quiz)
# ═══════════════════════════════════════════════════════════════════════════
from aiogram.types import PollAnswer

@router.poll_answer()
async def handle_quiz_poll_answer(poll_answer: PollAnswer, state: FSMContext) -> None:
    """
    Обработка ответов на quiz polls
    """
    data = await state.get_data()
    
    # Игнорируем если не в quiz mode
    if not data.get("gram_in_quiz"):
        return
    
    # Сохраняем результат в state для _run_quiz_flow
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    option_ids = poll_answer.option_ids
    
    # Сохраняем результат (будет прочитан в _run_quiz_flow)
    await state.update_data(
        last_poll_id=poll_id,
        last_option_ids=option_ids,
    )
# ═══════════════════════════════════════════════════════════════════════════
# 🎯 NOOP (заглушка)
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "gram:noop")
async def gram_noop(cb: CallbackQuery) -> None:
    await cb.answer()


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: FSM States
# ═══════════════════════════════════════════════════════════════════════════
class GrammarAdminStates(StatesGroup):
    waiting_topic_key = State()
    waiting_topic_title = State()
    
    waiting_pages_insert_index = State()
    waiting_pages_bulk_text = State()
    
    waiting_pages_delete_index = State()
    
    waiting_quiz_bulk_text = State()


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Keyboards
# ═══════════════════════════════════════════════════════════════════════════
def kb_admin_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить тему", callback_data="gramadm:add_topic")],
        [InlineKeyboardButton(text="✏️ Темы", callback_data="gramadm:topics_list")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="gramadm:exit")],
    ])


def kb_admin_topic_menu(topic_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Страницы урока", callback_data=f"gramadm:pages:{topic_key}")],
        [InlineKeyboardButton(text="📥 QUIZ bulk", callback_data=f"gramadm:quiz_bulk:{topic_key}")],
        [InlineKeyboardButton(text="🧹 Очистить QUIZ", callback_data=f"gramadm:quiz_clear:{topic_key}")],
        [InlineKeyboardButton(text="🗑 Удалить тему", callback_data=f"gramadm:delete:{topic_key}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="gramadm:topics_list")],
    ])


def kb_admin_pages_menu(topic_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить по индексу", callback_data=f"gramadm:pages_insert:{topic_key}")],
        [InlineKeyboardButton(text="🗑 Удалить по индексу", callback_data=f"gramadm:pages_delete:{topic_key}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gramadm:topic:{topic_key}")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Entry Point
# ═══════════════════════════════════════════════════════════════════════════

@router.message(Command("grammar_admin"))
async def admin_entry(message: Message, state: FSMContext) -> None:


    await state.clear()

    await message.answer(
        "🔧 GRAMMAR ADMIN\n\nВыбери действие:",
        reply_markup=kb_admin_main(),
    )

@router.callback_query(F.data == "gramadm:exit")
async def admin_exit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()

    try:
        await cb.message.delete()
    except TelegramBadRequest:
        # 💬 если сообщение уже удалено/нельзя удалить = не падаем
        pass



# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Добавление темы
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "gramadm:add_topic")
async def admin_add_topic_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GrammarAdminStates.waiting_topic_key)
    await state.update_data(gram_admin_active=True, gram_admin_step="topic_key")  # 💬 маркер, что мы в админ-флоу

    await cb.message.answer("Введи ключ темы (латиница, цифры, _).\nПример: gram_ser_estar")
    await cb.answer()


@router.message(GrammarAdminStates.waiting_topic_key)
async def admin_add_topic_key(message: Message, state: FSMContext) -> None:
    try:
        key = (message.text or "").strip()

        if not key:
            await message.answer("❌ Отправь ключ темы текстом (латиница, цифры, _).")
            return

        # 💬 Валидация ключа
        if not re.match(r"^[a-z0-9_]+$", key):
            await message.answer("❌ Ключ должен содержать только латиницу, цифры и _")
            return

        # 💬 Проверяем, не существует ли уже
        path = GRAMMAR_TOPICS_DIR / f"{key}.json"
        if path.exists():
            await message.answer("❌ Тема с таким ключом уже существует")
            return

        await state.update_data(adm_topic_key=key)
        await state.set_state(GrammarAdminStates.waiting_topic_title)

        await message.answer("Теперь введи название темы (на русском)")


    except Exception:
        # 💬 если где-то упали (любой баг/путь/права/IO) = не молчим, сбрасываем шаг
        logging.exception("admin_add_topic_key failed")
        await state.clear()
        await message.answer("❌ Ошибка при вводе ключа. Попробуй снова: /grammar_admin")



@router.message(GrammarAdminStates.waiting_topic_title)
async def admin_add_topic_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    
    if not title:
        await safe_delete_message(message.bot, message.chat.id, message.message_id)
        await message.answer("❌ Название не может быть пустым")
        return
    
    data = await state.get_data()
    key = data.get("adm_topic_key")
    
    if not key:
        await safe_delete_message(message.bot, message.chat.id, message.message_id)
        await message.answer("Ошибка состояния. /grammar_admin")
        await state.clear()
        return
    
    # Создаём тему
    topic = GrammarTopic(
        key=key,
        title=title,
        category="gram",
        pages=[],
        quiz_pool=[],
    )
    
    save_grammar_topic(topic)
    
    await state.clear()
    await message.answer("✅ Тема создана", reply_markup=kb_admin_topic_menu(key))


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Список тем
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "gramadm:topics_list")
async def admin_topics_list(cb: CallbackQuery, state: FSMContext) -> None:
    topics = load_grammar_topics()
    
    if not topics:
        await cb.answer("Темы не добавлены", show_alert=True)
        return
    
    rows = []
    for topic in topics:
        rows.append([
            InlineKeyboardButton(
                text=topic.title,
                callback_data=f"gramadm:topic:{topic.key}"
            )
        ])
    
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="gramadm:main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    
    try:
        await cb.message.edit_text("✏️ Выбери тему:", reply_markup=kb)
    except TelegramBadRequest:
        await cb.message.answer("✏️ Выбери тему:", reply_markup=kb)
    
    await cb.answer()


@router.callback_query(F.data == "gramadm:main")
async def admin_main(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await cb.message.edit_text("🔧 Админка грамматики", reply_markup=kb_admin_main())
    except TelegramBadRequest:
        await cb.message.answer("🔧 Админка грамматики", reply_markup=kb_admin_main())
    await cb.answer()


@router.callback_query(F.data.startswith("gramadm:topic:"))
async def admin_topic_menu(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    topics = load_grammar_topics()
    
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await cb.answer("Тема не найдена", show_alert=True)
        return
    
    text = (
        f"📝 <b>{topic.title}</b>\n\n"
        f"Ключ: <code>{topic.key}</code>\n"
        f"Страниц: {len(topic.pages)}\n"
        f"Квизов: {len(topic.quiz_pool)}"
    )
    
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb_admin_topic_menu(topic_key))
    except TelegramBadRequest:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb_admin_topic_menu(topic_key))
    
    await cb.answer()


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Страницы (Pages)
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("gramadm:pages:"))
async def admin_pages_menu(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    
    try:
        await cb.message.edit_text("📄 Управление страницами", reply_markup=kb_admin_pages_menu(topic_key))
    except TelegramBadRequest:
        await cb.message.answer("📄 Управление страницами", reply_markup=kb_admin_pages_menu(topic_key))
    
    await cb.answer()


@router.callback_query(F.data.startswith("gramadm:pages_insert:"))
async def admin_pages_insert_start(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    
    await state.update_data(adm_pages_topic_key=topic_key)
    await state.set_state(GrammarAdminStates.waiting_pages_insert_index)
    
    await cb.message.answer(
        "Введи индекс (1-based), куда вставить страницы.\n"
        "Например, 1 = в начало, 2 = после первой страницы и т.д."
    )
    await cb.answer()


@router.message(GrammarAdminStates.waiting_pages_insert_index)
async def admin_pages_insert_index(message: Message, state: FSMContext) -> None:
    try:
        index = int(message.text or "")
        if index < 1:
            raise ValueError()
    except ValueError:
        await safe_delete_message(message.bot, message.chat.id, message.message_id)
        await message.answer("❌ Введи число >= 1")
        return
    
    await state.update_data(adm_pages_insert_index=index)
    await state.set_state(GrammarAdminStates.waiting_pages_bulk_text)
    
    await message.answer(
        "Теперь вставь страницы одним сообщением.\n\n"
        "Формат:\n"
        "**жирный** = <b>жирный</b>\n"
        "_курсив_ = <i>курсив</i>\n"
        "`код` = <code>код</code>\n\n"
        "Разделитель страниц: ===PAGE===\n\n"
        "Пример:\n"
        "Стр. 1 текст **жирный**\n"
        "===PAGE===\n"
        "Стр. 2 текст _курсив_"
    )


def mdish_to_html(s: str) -> str:
    """
    Конвертер markdown-маркеров в HTML (Telegram HTML subset)
    """
    t = html.escape((s or "").strip())

    # code
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    # bold
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    # italic
    t = re.sub(r"_([^_]+)_", r"<i>\1</i>", t)

    # 💬 Telegram НЕ принимает <br> в parse_mode="HTML".
    # 💬 Оставляем обычные переносы строк: '\n' — это валидно.
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    return t

@router.message(GrammarAdminStates.waiting_pages_bulk_text)
async def admin_pages_bulk_insert(message: Message, state: FSMContext) -> None:
    raw_text = message.text or ""
    
    # Парсим страницы
    # Парсим страницы
    pages_raw = [p.strip() for p in raw_text.split(PAGE_DELIM) if p.strip()]
    
    if not pages_raw:
        await safe_delete_message(message.bot, message.chat.id, message.message_id)
        await message.answer("❌ Не нашёл страниц. Проверь формат.")
        return
    # Конвертируем в HTML
    pages_html = [_sanitize_telegram_html_page(mdish_to_html(p)) for p in pages_raw]

    
    # Получаем тему
    data = await state.get_data()
    topic_key = data.get("adm_pages_topic_key")
    insert_index = data.get("adm_pages_insert_index", 1)
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await safe_delete_message(message.bot, message.chat.id, message.message_id)
        await message.answer("Тема не найдена. /grammar_admin")
        await state.clear()
        return
    
    # Вставляем страницы
    # Вставляем страницы
    insert_pos = insert_index - 1  # 1-based -> 0-based
    if insert_pos < 0:
        insert_pos = 0
    if insert_pos > len(topic.pages):
        insert_pos = len(topic.pages)
    
    for i, page in enumerate(pages_html):
        topic.pages.insert(insert_pos + i, page)
    
    save_grammar_topic(topic)
    
    await state.clear()
    await message.answer(
        f"✅ Добавлено страниц: {len(pages_html)}\n"
        f"Всего страниц: {len(topic.pages)}",
        reply_markup=kb_admin_topic_menu(topic_key)
    )


@router.callback_query(F.data.startswith("gramadm:pages_delete:"))
async def admin_pages_delete_start(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic or not topic.pages:
        await cb.answer("Страниц нет", show_alert=True)
        return
    
    # Показываем список страниц
    lines = ["📄 Список страниц:\n"]
    for i, page in enumerate(topic.pages, start=1):
        # Превью (первые 30 символов без HTML)
        preview = re.sub(r"<[^>]+>", "", page)[:30]
        lines.append(f"{i}) {preview}...")
    
    lines.append("\nВведи номер страницы для удаления (1..N):")
    
    await state.update_data(adm_pages_topic_key=topic_key)
    await state.set_state(GrammarAdminStates.waiting_pages_delete_index)
    
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.message(GrammarAdminStates.waiting_pages_delete_index)
async def admin_pages_delete_execute(message: Message, state: FSMContext) -> None:
    try:
        index = int(message.text or "")
        if index < 1:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Введи число >= 1")
        return
    
    data = await state.get_data()
    topic_key = data.get("adm_pages_topic_key")
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await message.answer("Тема не найдена. /grammar_admin")
        await state.clear()
        return
    
    if index > len(topic.pages):
        await message.answer(f"❌ Страницы {index} не существует")
        return
    
    # Удаляем
    del topic.pages[index - 1]
    save_grammar_topic(topic)
    
    # Удаляем сообщение админа (clean chat)
    await safe_delete_message(message.bot, message.chat.id, message.message_id)
    
    await state.clear()
    await message.answer(
        f"✅ Страница {index} удалена\n"
        f"Осталось страниц: {len(topic.pages)}",
        reply_markup=kb_admin_topic_menu(topic_key)
    )


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Quiz Bulk & Clear
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("gramadm:quiz_bulk:"))
async def admin_quiz_bulk_start(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    
    await state.update_data(adm_quiz_topic_key=topic_key)
    await state.set_state(GrammarAdminStates.waiting_quiz_bulk_text)
    
    await cb.message.answer(
        "Вставь квизы одним сообщением.\n\n"
        "Формат (одна строка = один квиз):\n"
        "Вопрос | Правильный | Неверный1 | Неверный2 | Объяснение(опц.)\n\n"
        "Пример:\n"
        "Yo ___ de Rusia | soy | estoy | era | Используй SER для происхождения\n"
        "Yo ___ cansado | estoy | soy | era | Используй ESTAR для состояния"
    )
    await cb.answer()


def parse_quiz_bulk(text: str) -> List[Dict[str, Any]]:
    """
    Парсит квизы из bulk-формата
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    quizzes = []
    
    for ln in lines:
        if "|" not in ln:
            continue
        
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 4:
            continue
        
        question = parts[0]
        correct = parts[1]
        wrong1 = parts[2]
        wrong2 = parts[3]
        explanation = parts[4] if len(parts) > 4 else ""
        
        # Перемешиваем варианты (правильный на первое место)
        options = [correct, wrong1, wrong2]
        
        quizzes.append({
            "question": question,
            "options": options,
            "correct_index": 0,
            "explanation_wrong": explanation,
        })
    
    return quizzes


@router.message(GrammarAdminStates.waiting_quiz_bulk_text)
async def admin_quiz_bulk_execute(message: Message, state: FSMContext) -> None:
    raw_text = message.text or ""
    
    quizzes = parse_quiz_bulk(raw_text)
    
    if not quizzes:
        await message.answer("❌ Не смог распарсить квизы. Проверь формат.")
        return
    
    data = await state.get_data()
    topic_key = data.get("adm_quiz_topic_key")
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await message.answer("Тема не найдена. /grammar_admin")
        await state.clear()
        return
    
    # Добавляем квизы
    topic.quiz_pool.extend(quizzes)
    save_grammar_topic(topic)
    
    await state.clear()
    await message.answer(
        f"✅ Добавлено квизов: {len(quizzes)}\n"
        f"Всего квизов: {len(topic.quiz_pool)}",
        reply_markup=kb_admin_topic_menu(topic_key)
    )


@router.callback_query(F.data.startswith("gramadm:quiz_clear:"))
async def admin_quiz_clear(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    
    topics = load_grammar_topics()
    topic = None
    for t in topics:
        if t.key == topic_key:
            topic = t
            break
    
    if not topic:
        await cb.answer("Тема не найдена", show_alert=True)
        return
    
    topic.quiz_pool = []
    save_grammar_topic(topic)
    
    await cb.answer("✅ Квизы очищены", show_alert=True)
    
    # Обновляем меню
    text = (
        f"📝 <b>{topic.title}</b>\n\n"
        f"Ключ: <code>{topic.key}</code>\n"
        f"Страниц: {len(topic.pages)}\n"
        f"Квизов: {len(topic.quiz_pool)}"
    )
    
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb_admin_topic_menu(topic_key))
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 ADMIN: Удаление темы
# ═══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("gramadm:delete:"))
async def admin_delete_topic(cb: CallbackQuery, state: FSMContext) -> None:
    topic_key = cb.data.split(":")[-1]
    
    delete_grammar_topic(topic_key)
    
    await cb.answer("✅ Тема удалена", show_alert=True)
    await admin_topics_list(cb, state)
