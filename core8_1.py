# ProyectoBot/core8_1.py
# файл коры

# ================================================================================
# 🟡 Импорты и константы для core8_1.py
# ================================================================================

# ——— Standard library ——————————————————————————————————————————————
import os                           # Работа с файлами и папками
import json                         # Чтение/запись JSON-топиков
import random                       # Рандомизация (CTA-фразы, сценарии, стикеры)
import asyncio                      # Асинхронные паузы (smart_reply)
import logging                      # Логирование для отладки
import math
import time
import datetime
import sys
import traceback

# ——— Aiogram core ————————————————————————————————————————————————
from aiogram import Bot, Dispatcher, F                   # Bot/DP и фильтр F  
from aiogram.client.default import DefaultBotProperties  # Настройки бота (HTML по умолчанию)
from aiogram.filters import CommandStart, StateFilter
from aiogram.filters import Command # /start
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Chat, User
from aiogram.types import Message
from aiogram.types import (
    Message,                       # 💬 тип сообщения
    CallbackQuery,                 # 💬 для inline-callback
    InlineKeyboardMarkup,          # 💬 для inline-клавиатур
    InlineKeyboardButton,          # 💬 для кнопок в inline
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
    PollAnswer,
    BotCommand
)

# 💬 Уровни и медали для глобального прогресса
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
XP_PER_LEVEL = 3000  # XP, необходимое для перехода на следующий уровень
MEDALS = ["🥉", "🥈", "🥇"]  # бронза, серебро, золото


# 💬 Утилита-хелпер: клавиатура с кнопкой «Проверить подписку»
def check_subscription_kb(topic_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Проверить подписку",
                callback_data=f"check_subscription:{topic_key}"
            )]
        ]
    )



from aiogram.enums import ChatAction                    # Анимация “печатает…”
from aiogram.fsm.state import State, StatesGroup        # FSM: описываем состояния
from aiogram.fsm.context import FSMContext              # FSM: доступ к state.data
from aiogram.fsm.storage.memory import MemoryStorage    # Хранение FSM в памяти

# ——— Роутеры админки ————————————————————————————————————————————
from create_lesson_block import router as create_topic_router  # Роутер админского flow создания тем
from edit_topic_flow     import router as edit_topic_router   # Роутер админского flow редактирования

# ——— Загрузка тем ——————————————————————————————————————————————
from topics.loader import load_topics                    # Функция чтения всех JSON-файлов с уроками
from create_lesson_block import load_ads_data  # 💬 Функция загрузки рекламы из ads_data.json

# ——— Сценарии для учеников ——————————————————————————————————————
from scenarios_estiloso8_1 import (                     # Вся диалоговая логика “сценариев”

    congrats_media,           # Стикеры/гифки-поздравления после окончания урока
    refusal_stickers,         # Стикеры/гифки отказа
    after_text,               # Сценарии “after” для текст-блоков упражнений
    after_photo,              # Сценарии “after” для фото-блоков упражнений
    after_quiz,               # Сценарии “after” для quiz-блоков упражнений
    exercise_start_phrases,   # Вступительные фразы для потока «упражнения»
    motivational_quotes,      # Цитаты для мотивации в главном меню
    link_cta_phrases,         # Варианты призыва к действию (CTA) для link-блоков
    follow_up_phrases,        # Общие follow-up (“Что дальше?”) в админке/учениках
    custom_progress_emojis,   # Набор эмоджи для кастомного прогресса
    vocab_start_phrases,       # Вступительные фразы для потока «Учить слова»
    vocab_return_phrases,      # Фразы возвращения в поток  «Учить слова»
    vocab_quiz_intro_phrases,  #  Фразы для введения в квиз после словаря
    go_next_phrases,
    vocab_quiz_success_phrases
)


from scenario.confirm_done_block import confirm_done
from scenario.feedback_difficulty_block import feedback_difficulty
from scenario.offer_continue_block import offer_continue
from scenario.refusal_block import refusal

# ...другие импорты, если нужны...
from typing import List


scenarios = {
    "confirm_done": confirm_done,
    "feedback_difficulty": feedback_difficulty,
    "offer_continue": offer_continue,
    "refusal": refusal,
    # ... остальные блоки тут ...
}



# ——— Локальные константы ————————————————————————————————————————
EXERCISE_GIF_FOLDER = "gif/dudoso_after_link"   # Папка с MP4 для упражнений
VID_GIF_FOLDER      = "gif/dudoso_after_link"   # То же для видео (пока дублирует)ç
ADS_VIDEO_FOLDER = "ads_videos" # ——— Папка с видеорекламой

# ——— Инициализация бота и FSM ——————————————————————————————————————
BOT_TOKEN = "7267599701:AAEjhQX6xGqZxxnUYeR1L_73ty1JiePiPvQ"  
bot        = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp         = Dispatcher(storage=MemoryStorage())  











# ——— Подключаем админские роутеры ————————————————————————————————
dp.include_router(edit_topic_router)
dp.include_router(create_topic_router)


# ——— Загружаем уроки ——————————————————————————————————————————
topics = load_topics()

from collections import deque
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from functools import wraps
from inspect import signature

# 💬 Декор и очередь для трекинга последних двух хендлеров и сохранения стека
handler_history = deque(maxlen=2)
last_stack      = []

def track_handler(func):
    sig = signature(func)
    @wraps(func)
    async def wrapper(*args, **kwargs):
        global last_stack
        # 💬 сохраняем стек исполнения (кроме текущего кадра)
        last_stack = traceback.extract_stack()[:-1]
        # 💬 сохраняем имя хендлера
        handler_history.append(func.__name__)
        # 💬 убираем лишний аргумент 'dispatcher'
        kwargs.pop('dispatcher', None)
        # 💬 фильтруем kwargs по сигнатуре func
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return await func(*args, **filtered)
    return wrapper

ADMIN_CHAT_ID = 930240763  # ваш Chat ID

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as err:
            # 💬 берём последние два имени из handler_history
            curr = handler_history[-1] if handler_history else "unknown"
            prev = handler_history[-2] if len(handler_history) >= 2 else "none"
            # 💬 отправляем админу только названия хендлеров
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"🔴 Ошибка в `{curr}` (prev: `{prev}`)"
            )
            raise

# 💬 Регистрируем Middleware
dp.update.middleware.register(LoggingMiddleware())




# 💬 Фабрика: возвращает нужный vocab-список (по фазе или всё сразу)
def get_vocab_list(data: dict) -> list:
    topic_key = data.get("selected_topic")
    topic     = topics.get(topic_key, {})
    ph_id     = data.get("selected_phase_id")
    if ph_id is not None:
        # найдём фазу с этим ID
        for ph in topic.get("vocab", []):
            if ph.get("phase_id") == ph_id:
                return ph.get("vocab", [])
        return []
    # если фаза не выбрана — берём весь плоский список (legacy)
    return topic.get("vocab", [])





import os

XP_DATA_PATH = "xp_data.json"

def load_xp_data():
    # 💬 Загружает XP-файл, если его нет — создаёт пустой
    if not os.path.exists(XP_DATA_PATH):
        with open(XP_DATA_PATH, "w", encoding="utf-8") as f:
            f.write("{}")
    with open(XP_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def reset_daily_words_if_needed(user_data):
    """
    💬 Если дата не сегодня — сбрасываем счетчик words_learned_today и обновляем дату.
    """
    today = datetime.date.today().isoformat()
    if user_data.get("words_today_date") != today:
        user_data["words_learned_today"] = 0
        user_data["words_today_date"] = today


def save_xp_data(xp_data):
    # 💬 Сохраняет изменения в XP-файл
    with open(XP_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(xp_data, f, ensure_ascii=False, indent=2)




# 💬 USER DATA: сохраняем, какие темы разблокированы, и подписки на каналы
USER_DATA_PATH = "user_data.json"

def load_user_data():
    # Загружает файл user_data.json, если нет — создаёт пустой
    if not os.path.exists(USER_DATA_PATH):
        with open(USER_DATA_PATH, "w", encoding="utf-8") as f:
            f.write("{}")
    with open(USER_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user_data(data):
    # Сохраняет изменения в user_data.json
    with open(USER_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)




# 💬 Возвращает (duration_sec, is_currently_subscribed)
def get_subscription_duration(user_id: str, channel: str):
    data = load_user_data().get(user_id, {})
    ch = data.get("channels", {}).get(channel)
    if not ch:
        return 0, False
    sub = ch.get("subscribed_at", 0)
    unsub = ch.get("unsubscribed_at")
    # если отписался — длительность = unsub - sub
    if unsub:
        return unsub - sub, False
    # иначе — текущее время минус subscribed_at
    return int(time.time()) - sub, True



def get_channel_history(user_id: str, channel: str) -> List[dict]:
    data = load_user_data().get(user_id, {})
    sessions = data.get("channels", {}).get(channel, [])
    return sessions if isinstance(sessions, list) else []




# 💬 Проверяет для user_id и темы topic_key все требуемые каналы;
# фиксирует отписку в user_data.json, если нужно.
async def verify_subscription_for_topic(user_id: int, topic_key: str) -> bool:
    info      = topics.get(topic_key, {})
    required  = info.get("required_channels") or ([info.get("required_channel")] if info.get("required_channel") else [])
    ok = True
    for ch in required:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
        except TelegramBadRequest:
            ok = False; break
        if member.status not in ("member", "administrator", "creator"):
            ok = False
            # 💬 Фиксируем отписку
            data   = load_user_data()
            u      = data.get(str(user_id), {})
            sessions = u.get("channels", {}).get(ch, [])
            if sessions and sessions[-1].get("unsubscribed_at") is None:
                sessions[-1]["unsubscribed_at"] = int(time.time())
                u["channels"][ch] = sessions
                data[str(user_id)] = u
                save_user_data(data)
            break
    return ok





async def register_or_update_user(message: Message):
    # 💬 Добавляет пользователя или обновляет имя, username, дату
    user_id = str(message.from_user.id)
    xp_data = load_xp_data()
    user_data = xp_data.get(user_id, {})
    updated = False

    # Имя из Telegram (или спрашиваем, если пусто)
    name = message.from_user.full_name or ""
    if not user_data.get("name"):
        user_data["name"] = name
        updated = True

    # Username Telegram, если есть
    tg_username = ("@" + message.from_user.username) if message.from_user.username else ""
    if tg_username and user_data.get("tg_username") != tg_username:
        user_data["tg_username"] = tg_username
        updated = True

    # Дата первого входа
    if not user_data.get("first_join"):
        user_data["first_join"] = int(time.time())
        updated = True

    # Дата последнего действия
    user_data["last_active"] = int(time.time())

    # Базовые поля, если нет
    if "total_xp" not in user_data:
        user_data["total_xp"] = 0
        updated = True
    if "by_topic" not in user_data:
        user_data["by_topic"] = {}
        updated = True
    if "stats" not in user_data:
        user_data["stats"] = {"words_learned": 0, "exercises_done": 0}
        updated = True


    # 💬 Инициализация счетчиков недели и месяца для рейтинга

    # Базовые поля, если нет
    if "total_xp" not in user_data:
        user_data["total_xp"] = 0
        updated = True
    if "by_topic" not in user_data:
        user_data["by_topic"] = {}
        updated = True
    if "stats" not in user_data:
        user_data["stats"] = {"words_learned": 0, "exercises_done": 0}
        updated = True

    # 💬 Добавь инициализацию для недельных/месячных печенек:
    if "words_learned_week" not in user_data:
        user_data["words_learned_week"] = 0
        user_data["words_week_number"] = datetime.date.today().isocalendar()[1]
    if "words_learned_month" not in user_data:
        user_data["words_learned_month"] = 0
        user_data["words_month_number"] = datetime.date.today().month





    xp_data[user_id] = user_data
    if updated:
        save_xp_data(xp_data)





async def add_xp(user_id: int, topic: str, amount: int, action: str = None):
    """
    Универсальное начисление XP и обновление статистики по пользователю.
    """
    xp_data = load_xp_data()
    user_id = str(user_id)


    user = xp_data.get(user_id)
    if not user:
        return  # safety, must be зарегистрирован!

    reset_daily_words_if_needed(user)  # 💬 Сбросить/обновить дату, если нужно

    # 1. Общий XP
    user["total_xp"] = user.get("total_xp", 0) + amount



    # 2. По теме
    if "by_topic" not in user:
        user["by_topic"] = {}
    user["by_topic"][topic] = user["by_topic"].get(topic, 0) + amount

    # 3. words_learned сегодня + лимит
    if action == "words_learned":
        limit = user.get("words_daily_limit", 10)
        if user.get("words_learned_today", 0) < limit:
            user["words_learned_today"] = user.get("words_learned_today", 0) + 1

        # 💬 Счётчик за неделю
        week = datetime.date.today().isocalendar()[1]
        month = datetime.date.today().month

        # Сброс если неделя или месяц поменялись
        if user.get("words_week_number") != week:
            user["words_learned_week"] = 0
            user["words_week_number"] = week
        if user.get("words_month_number") != month:
            user["words_learned_month"] = 0
            user["words_month_number"] = month

        user["words_learned_week"] = user.get("words_learned_week", 0) + 1
        user["words_learned_month"] = user.get("words_learned_month", 0) + 1


    # 4. Последняя активность
    user["last_active"] = int(time.time())

    xp_data[user_id] = user
    save_xp_data(xp_data)




# ────────────────────────────────────────────────────────────
# 🕑 Пример «временного» сообщения: отправляем и удаляем через 2 сек
# ────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────────
# 🏷 ФИЛЬТРЫ ПО CURRENT_STAGE (универсальные для всех трёх потоков)
# ────────────────────────────────────────────────────────────────────────────────

async def is_confirm_done_vocab(message: Message, state: FSMContext) -> bool:
    """Поток «Учить слова»: подтвердили выполнение link-блока?"""
    data = await state.get_data()
    return data.get("current_stage") == "confirm_done"

async def is_feedback_difficulty_vocab(message: Message, state: FSMContext) -> bool:
    """Поток «Учить слова»: отвечаем на «Как тебе задание?»"""
    data = await state.get_data()
    return data.get("current_stage") == "feedback_difficulty"

async def is_offer_continue_vocab(message: Message, state: FSMContext) -> bool:
    """Поток «Учить слова»: предложение «Продолжим или Домой?»"""
    data = await state.get_data()
    return data.get("current_stage") == "offer_continue"

async def is_refusal_vocab(message: Message, state: FSMContext) -> bool:
    """Поток «Учить слова»: отказ от link-блока или feedback_difficulty"""
    data = await state.get_data()
    return data.get("current_stage") == "refusal"

async def is_vocab_exercise(message: Message, state: FSMContext) -> bool:
    """Quiz-блок в «Учить слова»: внутри встроенного poll’а"""
    data = await state.get_data()
    return data.get("current_stage") == "vocab_exercise"



# ────────────────────────────────────────────────────────────────────────────────
# 🏷 ФИЛЬТРЫ ПО CURRENT_STAGE для «Делать упражнения»
# ────────────────────────────────────────────────────────────────────────────────

async def is_confirm_done_exercise(message: Message, state: FSMContext) -> bool:
    """Поток «Делать упражнения»: подтвердили выполнение link-блока?"""
    data = await state.get_data()
    return data.get("current_stage") == "confirm_done"

async def is_feedback_difficulty_exercise(message: Message, state: FSMContext) -> bool:
    """Поток «Делать упражнения»: отвечаем на «Как тебе задание?»"""
    data = await state.get_data()
    return data.get("current_stage") == "feedback_difficulty"

async def is_offer_continue_exercise(message: Message, state: FSMContext) -> bool:
    """Поток «Делать упражнения»: предложение «Продолжим или Домой?»"""
    data = await state.get_data()
    return data.get("current_stage") == "offer_continue"

async def is_refusal_exercise(message: Message, state: FSMContext) -> bool:
    """Поток «Делать упражнения»: отказ от link-блока или feedback_difficulty"""
    data = await state.get_data()
    return data.get("current_stage") == "refusal"



# ────────────────────────────────────────────────────────────────────────────────
# 🏷 ФИЛЬТРЫ ПО CURRENT_STAGE для «🎬Смотреть видео»
# ────────────────────────────────────────────────────────────────────────────────

async def is_confirm_done_video(message: Message, state: FSMContext) -> bool:
    """Поток «Смотреть видео»: подтвердили просмотр видео?"""
    data = await state.get_data()
    return data.get("current_stage") == "confirm_done"

async def is_feedback_difficulty_video(message: Message, state: FSMContext) -> bool:
    """Поток «Смотреть видео»: отвечаем на «Как тебе задание?» (видео)"""
    data = await state.get_data()
    return data.get("current_stage") == "feedback_difficulty"

async def is_offer_continue_video(message: Message, state: FSMContext) -> bool:
    """Поток «Смотреть видео»: предложение «Продолжим или Домой?» (видео)"""
    data = await state.get_data()
    return data.get("current_stage") == "offer_continue"

async def is_refusal_video(message: Message, state: FSMContext) -> bool:
    """Поток «Смотреть видео»: отказ от просмотра видео или feedback"""
    data = await state.get_data()
    return data.get("current_stage") == "refusal"



# ────────────────────────────────────────────────────────────────────────────────
# 🏷 ФИЛЬТРЫ ПО CURRENT_STAGE для «🙊Читать диалог»
# ────────────────────────────────────────────────────────────────────────────────

async def is_before_dialog(message: Message, state: FSMContext) -> bool:
    """Поток «Читать диалог»: перед показом диалога (‘before_dialog’)"""
    data = await state.get_data()
    return data.get("current_stage") == "before_dialog"

async def is_complete_after_dialog(message: Message, state: FSMContext) -> bool:
    """Поток «Читать диалог»: после показа диалога (‘complete_after_dialog’)"""
    data = await state.get_data()
    return data.get("current_stage") == "complete_after_dialog"

async def is_feedback_difficulty_dialog(message: Message, state: FSMContext) -> bool:
    """Поток «Читать диалог»: отвечаем на «Как тебе диалог?»"""
    data = await state.get_data()
    return data.get("current_stage") == "feedback_difficulty_dialog"

async def is_dialog_exercise(message: Message, state: FSMContext) -> bool:
    """Поток «Читать диалог»: внутри exercise-блока диалога"""
    data = await state.get_data()
    return data.get("current_stage") == "dialog_exercise"


# ======================================================================
# 🔒 Блок 3: FSM-состояния (StatesGroup)
# ======================================================================



class LessonStates(StatesGroup):
    # 🏁 Начальные шаги: выбор категории и темы
    waiting_subscription = State()  # ожидание проверки подписки на канал(ы)
    choosing_category     = State()  # после /start — ждем «📚 Лексика» или «🧠 Грамматика»
    choosing_level        = State()  # 💬 состояние для выбора уровня после выбора категории
    choosing_topic        = State()  # после выбора категории — ждем тему
    waiting_lesson_action = State()  # главное меню: Учить слова/Делать упражнения/…
    waiting_vocab_phase   = State()   # выбор фазы перед показом словаря


    # 📚 Поток «Учить слова»
    showing_vocab         = State()  # показываем очередной блок (link/text/photo/quiz)
    vocab_exercise        = State()  # ожидаем ответ на встроенный quiz
    vocab_text_continue   = State()  # после текстового блока — «Я прочитал(a) / Пропустить»
    vocab_photo_continue  = State()  # после фото — «Я просмотрел(а) / Пропустить»

    vocab_optional_quiz   = State()  # ожидание ответа на опциональный quiz

        # — Новый блок: текстовый квиз —
    vocab_textquiz = State()   # ожидание ответа на текстовый квиз

    review_failed_vocab = State()      # поток разбора неправильных vocab-quiz
    review_failed_textquiz = State()   # поток разбора неправильных textquiz

    extra_quiz           = State()  # режим показа дополнительных квизов
    extra_quiz_confirm   = State()  # режим «продолжить/вернуться» после extra_quiz

    # 🧩 Поток «Делать упражнения»
    showing_exercise      = State()  # показываем очередной блок упражнений
    exercise_text_continue  = State()# после текстового блока упражнения
    exercise_photo_continue = State()# после фото блока упражнения
    exercise_quiz_continue  = State()# после quiz блока упражнения
    exercise_textquiz = State()  # ожидание ответа на текстовый квиз упражнения

    # 🎬 Поток «Смотреть видео»
    showing_video         = State()  # показываем видео

    # 💬 Поток «Читать диалоги»
    showing_dialog        = State()  # показываем очередной диалог
    complete_after_dialog = State()  # после link/quiz в диалоге
    feedback_difficulty_dialog = State()  # спрашиваем сложность диалога
    dialog_exercise       = State()  # quiz после диалога
    dialog_continue       = State()  # после диалога — кнопка «Продолжить/Домой»








# ─── УТИЛИТЫ XP ───────────────────────────────────────

async def award_xp(amount: int, state: FSMContext):
    """
    Добавляет amount XP (без изменения done_dialog) и обновляет level.
    """
    data = await state.get_data()
    xp = data.get("xp", 0) + amount
    await state.update_data(xp=xp, level=xp // 100)

async def award_dialog(amount: int, state: FSMContext):
    """
    Добавляет amount XP и фиксирует одно пройденное чтение диалога.
    """
    data = await state.get_data()
    xp = data.get("xp", 0) + amount
    done = data.get("done_dialog", 0) + 1
    await state.update_data(xp=xp, done_dialog=done, level=xp // 100)

def render_bar(pct: int, length: int = 10) -> str:
    """
    Рисует прогресс-бар длины length по проценту pct (0–100).
    """
    filled = min(max(int(pct * length / 100), 0), length)
    return "█" * filled + "░" * (length - filled)



@track_handler
async def proceed_to_next(target, state: FSMContext):
    """Перейти к следующему блоку обычным способом."""
    data = await state.get_data()
    new_idx = data.get("vocab_index", 0) + 1
    await state.update_data(vocab_index=new_idx)
    return await send_one_vocab(target, state)

@track_handler
async def send_optional_vocab_quiz(target, state: FSMContext):
    """
    Если у текущего блока есть поле 'quiz', показываем его как обычный poll,
    но без начисления XP.
    """
    data = await state.get_data()
    idx = data.get("vocab_index", 0)
    block = get_vocab_list(data)[idx]
    quiz = block.get("quiz")
    # если квиза нет — сразу следующий
    if not quiz:
        return await proceed_to_next(target, state)

    opts = quiz["options"].copy()
    random.shuffle(opts)
    correct_id = opts.index(quiz["correct_answer"])

    poll = await bot.send_poll(
        chat_id=target.chat.id if hasattr(target, "chat") else target.id,
        question=quiz["question"],
        options=opts,
        type="quiz",
        correct_option_id=correct_id,
        is_anonymous=False
    )
    await state.update_data(
        current_optional_poll_id=poll.poll.id,
        current_optional_message_id=poll.message_id,
        current_optional_correct_id=correct_id
    )
    await state.set_state(LessonStates.vocab_optional_quiz)


# ======================================================
# 🔧  отправка текста в «коричневом» блоке code через HTML <pre>
# ======================================================
async def send_plaintext(target, text: str):
    chat_id = target.chat.id if hasattr(target, "chat") else target.id
    await bot.send_message(chat_id, f"<pre>{text}</pre>", parse_mode="HTML")






# ================================================================================
# 🔧 Утилита: проверка, что пользователь нажал одну из кнопок сцены
# ================================================================================
async def ensure_valid_choice(message: Message, options: List[str]) -> bool:
    """
    Возвращает True, если message.text в списке options;
    иначе шлёт ошибку и клавиатуру с options и возвращает False.
    """
    if message.text not in options:
        buttons = [[KeyboardButton(text=btn)] for btn in options]
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        # 🚫 удаляем старую клавиатуру
        await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
        # ❗ просим выбрать снова
        await smart_reply(message, "Пожалуйста, выбери одну из кнопок.", reply_markup=kb)
        return False
    return True


import unicodedata

# 💬 Нормализация ответа: lower, remove accents/apostrophes, drop article
def normalize_textquiz(text: str) -> str:
    txt = text.lower().strip()
    # разложение акцентов и удаление
    txt = unicodedata.normalize('NFD', txt)
    txt = ''.join(c for c in txt if unicodedata.category(c) != 'Mn')
    # убрать апострофы и обратные кавычки
    txt = txt.replace("'", "").replace("`", "")
    # убрать артикль, если он первый
    # 1) разбиваем по пробелам и убираем отдельный артикль
    parts = txt.split()
    articles = {"el","la","los","las","un","una","unos","unas"}
    if parts and parts[0] in articles:
        parts = parts[1:]
    # 2) объединяем в одну строку (без пробелов)
    combined = "".join(parts)
    # 3) удаляем артикль, если он прописан слитно в начале
    for art in articles:
        if combined.startswith(art):
            combined = combined[len(art):]
            break
    return combined


# ─── ЗАДЕРЖКИ И УДАЛЕНИЯ СТИКЕРОВ И ГИФОК ─────────────────────

# 💬 Отправка стикера с авто-удалением через N секунд
async def send_and_auto_delete_sticker(bot, chat_id, sticker, delay=3):
    msg = await bot.send_sticker(chat_id=chat_id, sticker=sticker)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass



# 💬 Отправка GIF/анимации с авто-удалением через N секунд (по умолчанию 3 сек)
async def send_and_auto_delete_gif(bot, chat_id, gif, delay=3):
    msg = await bot.send_animation(chat_id=chat_id, animation=gif)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass



# ===============================================================================  
# 🔄 Обычный smart_reply с typing + динамической задержкой  
# ===============================================================================  
async def smart_reply(
    target,           # Message или ChatFullInfo
    text: str,
    **kwargs
):
    # Определяем chat_id
    if hasattr(target, "chat"):
        chat_id = target.chat.id
    else:
        chat_id = getattr(target, "id", None)
    # Показываем «typing…»
    await bot.send_chat_action(chat_id, action=ChatAction.TYPING)
    # Задержка: 10 мс на символ, но не больше 3 сек
    await asyncio.sleep(min(len(text) * 0.01, 3.0))
    # Отправляем сообщение
    return await bot.send_message(chat_id, text, **kwargs)




# 👇 ЭТУ функцию поставь ВНЕ всех хендлеров (где-то рядом с другими глобальными функциями)
def render_leaderboard(title, top, emoji):
    medals = ["🥇", "🥈", "🥉"]
    res = [f"<b>{title}</b>"]
    for idx, u in enumerate(top, 1):
        m = medals[idx-1] if idx <= 3 else str(idx)
        res.append(f"{m} {u['name']} {emoji} {u['words_learned']}")
    return "\n".join(res)

# 💬 Отправка текстового сообщения с авто-удалением через N секунд
async def send_and_auto_delete_text(bot, chat_id, text, delay=1.5):
    msg = await bot.send_message(chat_id=chat_id, text=text)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except TelegramBadRequest:
        pass

# ================================================================================
#   🚀 /start — выбор «📚 Лексика / 🧠 Грамматика»
# ================================================================================
# 💬 Команда /start → Показываем категории

@dp.message(CommandStart())
@track_handler
async def start_handler(message: Message, state: FSMContext):
    user_id   = str(message.from_user.id)
    # 💬 Загружаем существующие данные пользователей
    user_data = load_user_data()
    # 💬 Получаем или создаём запись для этого user_id
    u         = user_data.setdefault(user_id, {})

    # 💬 Сохраняем полное имя
    u.setdefault("name", message.from_user.full_name or "")
    # 💬 Сохраняем Telegram-username
    if message.from_user.username:
        u.setdefault("tg_username", "@" + message.from_user.username)

    # 💬 ГАРАНТИРУЕМ поля для тем и подписок
    u.setdefault("unlocked_topics", [])  # ключи открытых тем
    u.setdefault("channels", {})         # история подписок по каналам

    # 💬 Текущее время
    now = int(time.time())
    # — время первого входа
    if "first_join" not in u:
        u["first_join"] = now
    # — время последней активности
    u["last_active"] = now

    # 💬 Сохраняем обновлённые данные в user_data.json
    user_data[user_id] = u
    save_user_data(user_data)

    # — далее остальная логика: приветствие, загрузка тем и установка состояния —
    await state.clear()
    global topics
    topics = load_topics()

    await smart_reply(
        message,
        "Привет! Рад тебя видеть🥰",
        reply_markup=ReplyKeyboardRemove()
    )


    # 💬 Глобальный прогресс пользователя
    xp_data = load_xp_data()
    total_xp = xp_data.get(user_id, {}).get("total_xp", 0)
    # Текущий уровень
    lvl_idx = total_xp // XP_PER_LEVEL
    if lvl_idx >= len(LEVELS):
        lvl_idx = len(LEVELS) - 1
    current_level = LEVELS[lvl_idx]
    # Текущая медаль внутри уровня
    medal_idx = (total_xp % XP_PER_LEVEL) // (XP_PER_LEVEL // 3)
    current_medal = MEDALS[min(medal_idx, 2)]
    # Определяем, что будет следующим
    if medal_idx < 2:
        next_level = current_level
        next_medal = MEDALS[medal_idx + 1]
    else:
        next_level = LEVELS[min(lvl_idx + 1, len(LEVELS) - 1)]
        next_medal = MEDALS[0]
    # Строим прогресс-бар из 10 сегментов
    filled = int((total_xp % XP_PER_LEVEL) / XP_PER_LEVEL * 10)
    bar = "■" * filled + "□" * (10 - filled)
    # Отправляем прогресс
    await message.answer(
        f"📊 Уровень: {current_level}{current_medal}👇   \n"
        f"[{bar}]\n"
        f"{total_xp % XP_PER_LEVEL}/{XP_PER_LEVEL} XP ➡️ {next_level}{next_medal}"
    )



    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")],
            [KeyboardButton(text="Рейтинг🏆"), KeyboardButton(text="⚙️ Настройки")]
        ],
        resize_keyboard=True
    )
    await smart_reply(message, "Что изучаем?⭐", reply_markup=keyboard)

    # 💬 Отправляем «👇» и авто-удаляем через 1.5 сек (НЕ ждем!)
    asyncio.create_task(send_and_auto_delete_text(
        bot,
        message.chat.id,
        "👇",
        delay=1.5
    ))

    await state.set_state(LessonStates.choosing_category)
    # 💬 Теперь пользователь сразу может нажимать на кнопки!




# ================================================================================
#   🟡 1️⃣ Выбор категории (choosing_category)
# ================================================================================
@dp.message(LessonStates.choosing_category, lambda m: not m.text.startswith("/"))
@track_handler
async def category_chosen(message: Message, state: FSMContext):
    await register_or_update_user(message)

    text = message.text.strip()
    if text == "📚 Лексика":
        category = "lex"
    elif text == "🧠 Грамматика":
        category = "gram"
    elif text == "Рейтинг🏆":
        return await show_leaderboard(message, state)
    elif text == "⚙️ Настройки":
        return await settings_menu(message, state)
    else:
        return await smart_reply(message, "🤔 Дружище, выбери что-то из кнопок ниже!")

    await state.update_data(chosen_category=category)

    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😇 A0 (Новичок)", callback_data="level:A0"),
         InlineKeyboardButton(text="🌱 A1 (Легко!)", callback_data="level:A1"),
         InlineKeyboardButton(text="✨ A2 (Средне)", callback_data="level:A2")],
        [InlineKeyboardButton(text="🔥 B1 (Интересно!)", callback_data="level:B1"),
         InlineKeyboardButton(text="🚀 B2 (Продвинуто)", callback_data="level:B2"),
         InlineKeyboardButton(text="🧠 C1 (Профи)", callback_data="level:C1")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="level:back")]
    ])

    await smart_reply(
        message,
        "😜 Отличный выбор! А теперь давай определимся с уровнем сложности:",
        reply_markup=inline_kb
    )

    await state.set_state(LessonStates.choosing_level)

    # 💬 Теперь после выбора Лексика или Грамматика мы спрашиваем уровень (A1, A2 и т.д.).





# 💬 Пользователь выбирает уровень, и показываются темы только из этой категории и уровня.
@dp.callback_query(LessonStates.choosing_level, lambda c: c.data.startswith("level:"))
@track_handler
async def level_chosen(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]

    if choice == "back":
        await callback.message.delete()
        return await start_handler(callback.message, state)

    level = choice
    await state.update_data(chosen_level=level)
    data = await state.get_data()
    category = data.get("chosen_category")

    buttons = [
        InlineKeyboardButton(text=info["visible_title"], callback_data=f"topic:{key}")
        for key, info in topics.items()
        if info.get("category") == category and info.get("level") == level
    ]

    if not buttons:
        await callback.message.edit_text(f"🤷‍♂️ Тем пока нет на уровне {level}. Скоро добавим!")
        return

    inline_keyboard = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    inline_kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

    await callback.message.edit_text(
        f"😎 Уровень <b>{level}</b> выбран! Вот темы специально для тебя:",
        reply_markup=inline_kb,
        parse_mode="HTML"
    )

    await state.set_state(LessonStates.choosing_topic)




@dp.message(LessonStates.choosing_category, lambda m: m.text == "⚙️ Настройки")
@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text == "⚙️ Настройки")
@track_handler
async def settings_menu(message: Message, state: FSMContext):
    """
    💬 Меню настроек: выбор лимита слов в день и часа напоминания.
    """
    xp_data = load_xp_data()
    user_id = str(message.chat.id)
    user = xp_data.setdefault(user_id, {})
    reset_daily_words_if_needed(user)
    current_limit = user.get("words_daily_limit", 10)
    reminder_hour = user.get("reminder_hour", 19)
    save_xp_data(xp_data)

    # Кнопки выбора лимита и времени
    buttons = [
        [KeyboardButton(text=f"🔢 Лимит слов: {current_limit}")],
        [KeyboardButton(text=f"⏰ Время уведомления: {reminder_hour}:00")],
        [KeyboardButton(text="⬅️ В меню")]
    ]
    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("⚙️ <b>Настройки:</b>\n\n— Сколько слов в день ты хочешь учить?\n— Время для напоминания:", parse_mode="HTML", reply_markup=kb)
    await state.set_state("settings_menu")



# 💬 Обрабатываем только если текст не пустой и не None
@dp.message(lambda m: m.text is not None and m.text.startswith("🔢 Лимит слов:"))
async def set_limit(message: Message, state: FSMContext):
    # 💬 Здесь пользователь нажал на лимит слов
    await message.answer("Введи новый лимит слов в день (от 1 до 50):")
    await state.set_state("waiting_limit_input")

@dp.message(StateFilter("waiting_limit_input"))
async def process_limit_input(message: Message, state: FSMContext):
    try:
        val = int(message.text)
        if not 1 <= val <= 50:
            raise ValueError
    except:
        return await message.answer("Введи число от 1 до 50.")
    xp_data = load_xp_data()
    user_id = str(message.chat.id)
    user = xp_data.setdefault(user_id, {})
    user["words_daily_limit"] = val
    save_xp_data(xp_data)
    await message.answer(f"✅ Лимит обновлён: {val} слов в день.")
    return await settings_menu(message, state)

@dp.message(lambda m: m.text is not None and m.text.startswith("⏰ Время уведомления:"))
async def set_reminder_time(message: Message, state: FSMContext):
    await message.answer("Введи час (от 1 до 24), когда присылать напоминание:")
    await state.set_state("waiting_reminder_input")

@dp.message(StateFilter("waiting_reminder_input"))
async def process_reminder_input(message: Message, state: FSMContext):
    try:
        hour = int(message.text)
        if not 1 <= hour <= 24:
            raise ValueError
    except:
        return await message.answer("Введи число от 1 до 24.")
    xp_data = load_xp_data()
    user_id = str(message.chat.id)
    user = xp_data.setdefault(user_id, {})
    user["reminder_hour"] = hour
    save_xp_data(xp_data)
    await message.answer(f"✅ Время напоминания обновлено: {hour}:00")
    return await settings_menu(message, state)

@dp.message(lambda m: m.text == "⬅️ В меню")
async def back_to_menu(message: Message, state: FSMContext):
    await start_handler(message, state)






@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text in ["🎲 Упражнения", "🎬 Видео", "🙊 Диалоги"])
@track_handler
async def handle_unavailable_buttons(message: Message, state: FSMContext):
    """
    💬 Если пользователь нажимает на недоступную кнопку,
    отправляем стикер отказа, который удаляется через 1.5 секунды.
    """
    sticker = "CAACAgIAAxkBAAE4YOhogox6Armq-TOX3f5IkYPXCeUwuAACRAMAArVx2gYMtzsTtIZDMDYE"
    await send_and_auto_delete_sticker(bot, message.chat.id, sticker, delay=1.5)




@dp.message(F.text == "Рейтинг🏆")
@track_handler
async def show_leaderboard(message: Message, state: FSMContext):
    xp_data = load_xp_data()
    users = []
    for uid, u in xp_data.items():
        name = u.get("name", "")
        week = u.get("words_learned_week", 0)
        month = u.get("words_learned_month", 0)
        users.append({
            "name": name,
            "words_learned_week": week,
            "words_learned_month": month
        })

    # Топ недели
    top_week = sorted(users, key=lambda u: u["words_learned_week"], reverse=True)[:10]
    top_month = sorted(users, key=lambda u: u["words_learned_month"], reverse=True)[:10]

    def render(title, top, key, emoji):
        medals = ["🥇", "🥈", "🥉"]
        res = [f"<b>{title}</b>"]
        for idx, u in enumerate(top, 1):
            m = medals[idx-1] if idx <= 3 else str(idx)
            res.append(f"{m} {u['name']} {emoji} {u[key]}")
        return "\n".join(res)

    week_text = render("🏆 Рейтинг недели", top_week, "words_learned_week", "🍪")
    month_text = render("🏆 Рейтинг месяца", top_month, "words_learned_month", "🍪")

    menu_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В меню", callback_data="back_to_menu")]
        ]
    )

    await message.answer(f"{week_text}\n\n{month_text}", parse_mode="HTML", reply_markup=menu_kb)



# 🟢 Новый хендлер: Главное меню (/menu)
@dp.message(Command("menu"))
@track_handler
async def menu_handler(message: Message, state: FSMContext):
    # 💬 Возвращает пользователя к выбору категории
    await start_handler(message, state)


@dp.callback_query(lambda c: c.data == "back_to_menu")
async def inline_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()  # Удаляем сообщение с рейтингом (по желанию)
    await start_handler(callback.message, state)
    await callback.answer()  # Убирает "часики"







# ================================================================================
#   🟡 2️⃣ Выбор темы (choosing_topic)
# ================================================================================
@dp.callback_query(
    lambda c: c.data and c.data.startswith("topic:"),
    StateFilter(LessonStates.choosing_topic, LessonStates.waiting_subscription)
)
@track_handler
async def topic_chosen(query: CallbackQuery, state: FSMContext):
    await register_or_update_user(query.message)
    await query.answer()
    # 💬 Удаляем сообщение с кнопками выбора темы
    await query.message.delete()

    topic_key = query.data.split(":", 1)[1]
    await state.update_data(selected_topic=topic_key)

    info     = topics.get(topic_key, {})
    required = info.get("required_channels") or ([info.get("required_channel")] if info.get("required_channel") else [])

    # 1) Тема без каналов → разблокируем сразу
    if not required:
        data = load_user_data()
        u    = data.setdefault(str(query.from_user.id), {})
        unlocked = u.setdefault("unlocked_topics", [])
        if topic_key not in unlocked:
            unlocked.append(topic_key)
            save_user_data(data)
        return await lesson_menu_handler(query.message, state)

    # 2) Тема с каналами → проверяем историю
    data     = load_user_data()
    u        = data.setdefault(str(query.from_user.id), {})
    sessions = u.setdefault("channels", {}).get(required[0], [])

    # 2.1) Первый раз — просим подписаться
    if not sessions:
        channels_str = ", ".join(required)
        await query.message.answer(
            f"🔒 Чтобы получить доступ к этой теме, подпишись на канал(ы): {channels_str}",
            reply_markup=check_subscription_kb(topic_key)
        )
        await state.set_state(LessonStates.waiting_subscription)
        return


    # 2.2) Повторная проверка отписок
    if not await verify_subscription_for_topic(query.from_user.id, topic_key):
        # 💬 Сообщаем, что отписались, и даём кнопку «Проверить подписку» ещё раз
        # 💬 Трёхстрочное уведомление об отписке + кнопка «Проверить подписку»
        channel_names = ", ".join(required)
        await query.message.answer(
            f"❗️ Вы отписались от нужного канала.\n"
            f"{channel_names}\n"
            "Подпишитесь снова и проверь подписку.",
            reply_markup=check_subscription_kb(topic_key)
        )
        # 💬 Котик на 1.5 сек
        await send_and_auto_delete_text(bot, query.message.chat.id, "🙀", delay=1.5)

        # 💬 Переводим FSM в состояние ожидания проверки подписки
        await state.set_state(LessonStates.waiting_subscription)
        return


    # 3) Всё ок — запускаем урок
    return await lesson_menu_handler(query.message, state)









# ================================================================================  
#   🟡 3️⃣ Home (показываем прогресс + 5 кнопок)  
# ================================================================================ 
@track_handler 
async def lesson_menu_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        return await start_handler(message, state)

    # Получаем структуру темы
    import math
    topic = topics.get(topic_key, {})

    xp = data.get("xp", 0)
    # 💬 Расчёт порога XP для разблокировки: 30 XP × кол-во квизов во всех фазах × 0.8
    quizzes = [
        block
        for ph in topic.get("vocab", [])      # 💬 итерируемся по фазам
        for block in ph.get("vocab", [])      # 💬 и по блокам внутри каждой фазы
        if block.get("type") in ("quiz", "textquiz")
    ]
    xp_threshold = math.floor(len(quizzes) * 30 * 0.8 / 10) * 10  # округляем вниз до ближайших 10 XP

    # 💬 Сохраняем порог в state
    await state.update_data(xp_threshold=xp_threshold)
    unlocked = xp >= xp_threshold
    await state.update_data(unlocked=unlocked)

    # 💬 Для отображения округляем вниз до ближайших 10 XP
    display_threshold = (xp_threshold // 10) * 10


    # ─────────────────────────────────────────────────────────────────────────────


    # 📚 Словарь → считаем **фазы**, а значит “done phases / total phases”
    phases = topic.get("vocab", [])
    total_phases = len(phases)
    per_phase    = data.get("vocab_done_per_phase", {})
    # сколько фаз полностью пройдено?
    completed_phases = sum(
        1 for ph in phases
        if per_phase.get(ph["phase_id"], 0)
           >= len([b for b in ph.get("vocab", []) if "link" in b or "url" in b])
    )
    stars = "⭐" * completed_phases + "☆" * (total_phases - completed_phases)



    # Упражнения
    # 🎯 Упражнения (считаем только link-блоки)
    ex_list = topic.get("exercises", [])                      # весь список упражнений
    link_blocks_ex = [b for b in ex_list if "link" in b or "url" in b]  # фильтр link/url
    total_ex_link = len(link_blocks_ex)                        # общее число ссылок
    done_ex_link = data.get("ex_done", 0)                      # сколько уже пройдено
    ex_stars = "⭐" * done_ex_link + "☆" * (total_ex_link - done_ex_link)  # строка звёзд


    # Видео
    total_video = len(topic.get("videos", []))
    dv_idx      = data.get("video_index", 0)
    video_stars = "⭐" * dv_idx + "☆" * (total_video - dv_idx)

    # 4. Диалоги
    total_dlg = len(topic.get("dialogs", []))
    done_dlg  = data.get("done_dialog", 0)
    dlg_stars = "⭐" * done_dlg + "☆" * (total_dlg - done_dlg)

    # Всего выучено слов (legacy + per-phase)
    done_vocab  = data.get("vocab_done", sum(data.get("vocab_done_per_phase", {}).values()))
    # Всего слов во всех фазах
    total_vocab = sum(len(ph.get("vocab", [])) for ph in topic.get("vocab", []))


    # — Общий прогресс —
    total_done = done_vocab + done_ex_link + dv_idx + done_dlg
    total_all  = total_vocab + total_ex_link + total_video + total_dlg
    percent    = (total_done / total_all * 100) if total_all else 0

    # ASCII-бар из 10 сегментов
    bar_len = 10
    filled  = int(percent / 100 * bar_len)
    bar2    = "■" * filled + "□" * (bar_len - filled)

    # Эмоджи-медаль
    if percent >= 90:
        medal = "🥇"
    elif percent >= 60:
        medal = "🥈"
    elif percent >= 30:
        medal = "🥉"
    else: 
        medal = ""


    # — Формируем единый текст меню, сохраняя условие блокировки —
    parts: list[str] = []

    # 1) Общий прогресс
    parts.append(f"📊 <b>Прогресс:</b> [{bar2}] {percent:.0f}% {medal}")

    # — Мотивационная цитата по прогрессу —
    chosen_quotes = None
    for thresh, quotes in sorted(motivational_quotes.items()):
        if percent <= thresh:
            chosen_quotes = quotes
            break
    if not chosen_quotes:
        chosen_quotes = list(motivational_quotes.values())[-1]
    quote = random.choice(chosen_quotes)
    parts.append(f"<tg-spoiler>“{quote}”</tg-spoiler>")



    # ─── ВСТАВКА: Learned Words в виде «печенек» ────────────────────────────
    xp_data = load_xp_data()
    user_id = str(message.chat.id)
    user = xp_data.get(user_id, {})
    reset_daily_words_if_needed(user)
    today = user.get("words_learned_today", 0)
    limit = user.get("words_daily_limit", 10)


    # 4) Подробный прогресс по разделам
    parts.append(
        f"🍪 <b>{today}/{limit}</b>\n"
        f"<b><i>📘 Словарь:</i></b>    {stars}   {completed_phases}/{total_phases}\n"
        f"<b><i>🎲 Упражнения:</i></b> {ex_stars}   {done_ex_link}/{total_ex_link}\n"
        f"<b><i>🎬 Видео:</i></b>      {video_stars}   {dv_idx}/{total_video}\n"
        f"<b><i>🙊 Диалоги:</i></b>    {dlg_stars}   {done_dlg}/{total_dlg}"
    )

    # 3) Если ещё не разблокировано — строка «Набери минимум display_threshold»
    if not unlocked:
        parts.append(
            f"🔒 <b>Набери мин. {display_threshold} XP 🌟</b>"
        )

 
    # ────────────────────────────────────────────────────────────────────────

    # 5) Общее XP
    parts.append(f"🏆 <b>Всего опыта: {xp} XP</b> 🌟")

    # Отправляем всем блоком через bot.send_message, чтобы избежать NotMounted
    menu_text = "\n\n".join(parts)
    await bot.send_message(message.chat.id, menu_text, parse_mode="HTML")

    # — Кнопки меню с блокировкой потоков по флагу unlocked —
    buttons = [[KeyboardButton(text="📘 Учить слова")]]
    if unlocked:
        buttons.append([
            KeyboardButton(text="🎲 Упражнения"),
            KeyboardButton(text="🎬 Видео"),
            KeyboardButton(text="🙊 Диалоги"),
        ])
    else:
        buttons.append([
            KeyboardButton(text="🔒 Упражнения"),
            KeyboardButton(text="🔒 Видео"),
            KeyboardButton(text="🔒 Диалоги"),
        ])
    buttons.append([KeyboardButton(text="🔄 Сменить тему")])
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    # Финальный follow-up
    choice_text = random.choice(follow_up_phrases)
    await smart_reply(
        message,
        f"<b>{choice_text}</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(LessonStates.waiting_lesson_action)



# ─────────────────────────────────────────────────────────
@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text == "🔄 Сменить тему")
@track_handler
async def change_topic(message: Message, state: FSMContext):
    # Сбрасываем все индексы и возвращаемся к выбору категории, но сохраняем done_dialog и xp
    done_dialog = (await state.get_data()).get("done_dialog", 0)
    xp = (await state.get_data()).get("xp", 0)
    await state.clear()
    # восстанавливаем накопленный прогресс по диалогам и xp
    await state.update_data(done_dialog=done_dialog, xp=xp, level=xp//100)
    return await start_handler(message, state)






# 📦 ID стикеров для заблокированных кнопок
LOCKED_STICKERS = [
    "CAACAgIAAxkBAAE2o0poV00UvQJOb5YVn_jgwz-AvPn6aQACKgEAAlKJkSM_2dC0M_P_EjYE", 
    "CAACAgIAAxkBAAE2o05oV03D4cY4PL1miwaTIJkVesewoAACkxEAAvXroUgH6q_y069udjYE",
    "CAACAgIAAxkBAAE2o1BoV03m9PlLTn4Z5mKDqnajd6c1_wACRwMAAm2wQgNSVSv5NcWAgjYE",
    
]

@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text.startswith("🔒"))
@track_handler
async def locked_button_handler(message: Message, state: FSMContext):
    """
    При нажатии на любую «🔒 …» кнопку:
    1) отправляем случайный сти­кер отказа (из refusal_stickers),
       который сам удалится через 3 сек.
    2) ждём 3 сек, а затем возвращаемся в меню урока.
    """
    # 1) выбираем случайный сти­кер из списка отказа
    sticker_id = random.choice(LOCKED_STICKERS)
    # 2) отправляем и авто-удаляем
    await send_and_auto_delete_sticker(bot, message.chat.id, sticker_id)
    # 3) ждём, чтобы не дергать меню раньше удаления
    await asyncio.sleep(3) 





# 💬 Строит зачёркнутый текст через combining overlay
def strike(text: str) -> str:
    return "".join(ch + "\u0336" for ch in text)


# ========= 📘📘📘НАЧАЛО ПОТОКА ПО СЛОВАРЮ или ПО СЛОВАМ 📘📘📘 =============
# ================================================================================  
#   🟡 4️⃣ Поток «Учить слова» (showing_vocab)  
# ================================================================================  
@dp.message(LessonStates.waiting_lesson_action, F.text == "📘 Учить слова")
@track_handler
async def show_phase_menu(message: Message, state: FSMContext):
    data      = await state.get_data()
    topic_key = data.get("selected_topic")
    phases    = topics.get(topic_key, {}).get("vocab", [])

    # ── Скрыть старую Reply-клавиатуру и сразу удалить служебное сообщение ──
    blank = await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
    await blank.delete()


    # … внутри show_phase_menu …
    buttons = []
    for ph in phases:
        blocks     = ph.get("vocab", [])
        # отбираем только link-блоки (те, что имеют ключ "link" или "url")
        link_blocks = [b for b in blocks if "link" in b or "url" in b]
        total       = len(link_blocks)
        passed      = data.get("vocab_done_per_phase", {}).get(ph["phase_id"], 0)
        # порог 80%, округляем вверх (если блоков нет — считаем, что фаза не заполнена)
        threshold   = math.ceil(total * 0.8) if total else 0
        mark = " ✅" if total and passed >= threshold else ""
        if mark:
            # зачёркиваем название фазы и добавляем галочку
            name = strike(ph["phase_name"])
            btn_text = f"{name}{mark}"
        else:
            btn_text = ph["phase_name"]

        buttons.append(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"topic_phase:{ph['phase_id']}"  # 💬 теперь только ID фазы
        )
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn] for btn in buttons])


    await message.answer("Выбери фазу для изучения", reply_markup=kb)
    await state.set_state(LessonStates.waiting_vocab_phase)


# ─────────────────────────────────────────────────────────
# 4️⃣ Поток «Учить слова» (start_vocab)

@track_handler  # 💬 теперь это просто обёртка для логирования
async def start_vocab(message: Message, state: FSMContext):
    # 1) Регистрируем пользователя (имя, время и т.п.)
    await register_or_update_user(message)
    # 2) Дайс-анимация
    dice_msg = await message.answer_dice('🎲', reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    try: await dice_msg.delete()
    except: pass

    data = await state.get_data()
    # 3) Если фаза уже выбрана — get_vocab_list вернёт только словарь по фазе
    #    иначе — весь список (legacy)
    vocab_list = get_vocab_list(data)

    # 4) Инициализация указателя и “failed_vocab” при первом заходе
    if "vocab_index" not in data:
        await state.update_data(vocab_index=0,
                                failed_vocab=[],
                                vocab_done=0)
    idx = data.get("vocab_index", 0)

    # 5) Если всё пройдено → предлагать “ещё XP / в меню”
    if idx >= len(vocab_list):
        buttons = [
            [KeyboardButton(text="🎯 Получить ещё XP")],
            [KeyboardButton(text="Нет, вернуться в меню")]
        ]
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        return await smart_reply(
            message,
            "🛑 Эй! Ты уже все сделал.\nХочешь получить больше XP?😏",
            reply_markup=kb
        )

    # 6) Сохраняем в state stats по текст-квизам (печеньки)
    max_cookies = sum(1 for b in vocab_list if b.get("type") == "textquiz")
    xp_all = load_xp_data().get(str(message.chat.id), {})
    initial_cookies = xp_all.get("stats", {}).get("words_learned", 0)
    await state.update_data(max_cookies=max_cookies,
                            initial_cookies=initial_cookies)

    # 7) Вступительная фраза
    if idx == 0:
        phrase = random.choice(vocab_start_phrases)
    else:
        phrase = random.choice(vocab_return_phrases)
    await smart_reply(message, phrase, reply_markup=ReplyKeyboardRemove())

    # 8) Переходим в showing_vocab и идём в send_one_vocab
    await state.set_state(LessonStates.showing_vocab)
    return await send_one_vocab(message, state)


'''
@dp.message(LessonStates.waiting_lesson_action, F.text == "📘 Учить слова")
@track_handler
async def start_vocab(message: Message, state: FSMContext):

    await register_or_update_user(message)   # 💬 фиксирует имя/username/время


    # 🟢 Анимированный кубик (dice) с задержкой
    dice_msg = await message.answer_dice(
        '🎲',                          # эмодзи первым позиционно
        reply_markup=ReplyKeyboardRemove()
    )

    # Ждём 1 секунду, пока идёт анимация
    await asyncio.sleep(1)
    # Опционально удаляем само сообщение с кубиком (игнорируем ошибки)
    try:
        await dice_msg.delete()
    except TelegramBadRequest:
        pass






    data        = await state.get_data()
    vocab_list  = topics.get(data.get("selected_topic"), {}).get("vocab", [])
    current_idx = data.get("vocab_index", 0)
    # 💬 при повторном входе пропускаем уже показанный блок
    if current_idx > 0 and current_idx < len(vocab_list):
        current_idx += 1
        await state.update_data(vocab_index=current_idx)
    idx   = current_idx
    total = len(vocab_list)


    # 🚩 Если весь словарь уже пройден
    if vocab_list and idx >= len(vocab_list):
        buttons = [
            [KeyboardButton(text="🎯 Получить ещё XP")],
            [KeyboardButton(text="Нет, вернуться в меню")]
        ]
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        return await smart_reply(
            message,
            "🛑 Эй! Ты уже все сделал.\nХочешь получить больше XP?😏",
            reply_markup=kb
        )


    # 🚀 Инициализация счётчиков только при первом заходе
    if "vocab_index" not in data:
        await state.update_data(vocab_index=0, vocab_done=0)

    # 📌 Шаг 4.1: обнуляем список невыученных слов
    await state.update_data(failed_vocab=[])



    # 💬 Сколько текст-квизов в этой теме?
    vocab_list = topics.get(data.get("selected_topic"), {}).get("vocab", [])
    max_cookies = sum(1 for b in vocab_list if b.get("type") == "textquiz")
    # 💬 Сколько уже было «печенек» до этого урока?
    xp_all = load_xp_data().get(str(message.chat.id), {})
    initial_cookies = xp_all.get("stats", {}).get("words_learned", 0)
    # 💾 Сохраняем в state для проверки лимита
    await state.update_data(
        max_cookies=max_cookies,
        initial_cookies=initial_cookies
    )


    # 💬 Вступительная фраза для словаря
    idx = data.get("vocab_index", 0)
    if idx == 0:
        # первый раз — стандартные стартер-фразы
        phrase = random.choice(vocab_start_phrases)
    else:
        # при возврате — фразы «С возвращением»
        phrase = random.choice(vocab_return_phrases)

    await smart_reply(message, phrase, reply_markup=ReplyKeyboardRemove())


    # 🔄 Переходим к показу текущего слова
    await state.set_state(LessonStates.showing_vocab)
    return await send_one_vocab(message, state)
'''





@dp.callback_query(
    lambda c: c.data and c.data.startswith("topic_phase:"),
    StateFilter(LessonStates.waiting_vocab_phase)
)
@track_handler
async def topic_phase_chosen(cb: CallbackQuery, state: FSMContext):
    _, ph_str = cb.data.split(":", 1)
    phase_id = int(ph_str)                      # 💬 получаем только ID фазы
    data      = await state.get_data()
    topic_key = data.get("selected_topic")       # 💬 берём topic_key из state

    data  = await state.get_data()
    topic = topics.get(topic_key, {})
    # найдём нужную фазу
    phase = next((ph for ph in topic.get("vocab", []) if ph["phase_id"] == phase_id), None)
    blocks      = phase.get("vocab", []) if phase else []
    link_blocks = [b for b in blocks if "link" in b or "url" in b]
    total       = len(link_blocks)
    passed      = data.get("vocab_done_per_phase", {}).get(phase_id, 0)
    threshold   = math.ceil(total * 0.8) if total else 0

    # 1) фаза уже пройдена?
    if total and passed >= threshold:
        # просто отвечаем и возвращаем меню выбора фазы (исчезнут «часики»)
        await cb.answer("🎉 Фаза уже пройдена, ты красавчик!", show_alert=True)
        # обновим inline-клавиатуру (зачёркнутые + ✅ остались)
        return

    # 2) иначе — удаляем prompt и стартуем/возобновляем словарь
    await cb.message.delete()
    await cb.answer()
    data = await state.get_data()
    prev_phase = data.get("selected_phase_id")
    # Если переключаемся на новую фазу — инициализируем счётчики
    if prev_phase != phase_id:
        await state.update_data(
            selected_phase_id   = phase_id,
            vocab_index         = 0,
            failed_vocab        = [],
            # (если используете per-phase счётчики, их тоже можно сбросить здесь:)
            # vocab_done_per_phase = {}
        )
    else:
        # если возвращаемся в ту же фазу — просто обновляем ID фазы, остальные данные сохраняем
        await state.update_data(selected_phase_id=phase_id)
    return await start_vocab(cb.message, state)


# ─────────────────────────────────────────────────────────



#.............Поток по extra_quiz...........................................

# ───────────────────────────────────────────────────────────────
# 2) Хендлер старта потока extra_quiz по кнопке 🎯 Получить ещё XP
# ───────────────────────────────────────────────────────────────
@dp.message(LessonStates.waiting_lesson_action, F.text=="🎯 Получить ещё XP")
@track_handler
async def start_extra_vocab_quiz(message: Message, state: FSMContext):
    """
    Запускаем дополнительные Quiz’ы, чтобы набрать больше XP.
    """
    data = await state.get_data()
    # 💬 если пользователь уже прошёл extra_quiz, блокируем повтор
    if data.get("extra_quiz_done"):
        await message.answer("🛑 Вы уже прошли все дополнительные квизы.")
        return await lesson_menu_handler(message, state)
    extra_quizzes = topics[data["selected_topic"]].get("extra_quiz", [])  # :contentReference[oaicite:0]{index=0}

    # Если доп. квизов нет — сразу в меню
    if not extra_quizzes:
        await message.answer("🗃️ Дополнительных квизов пока нет. Возвращаемся в меню.")
        return await lesson_menu_handler(message, state)

    await state.update_data(extra_quiz_index=0)
    await state.set_state(LessonStates.extra_quiz)
    await send_one_extra_vocab_quiz(message, state)


# ───────────────────────────────────────────────────────────────
# 3) Хендлер возврата в меню по кнопке «Нет, вернуться в меню»
# ───────────────────────────────────────────────────────────────
@dp.message(LessonStates.waiting_lesson_action, F.text=="Нет, вернуться в меню")
@track_handler
async def return_to_lesson_menu(message: Message, state: FSMContext):
    await register_or_update_user(message)
    """
    Пользователь отказался от доп. квизов — возвращаем в меню темы.
    """
    return await lesson_menu_handler(message, state)


# ───────────────────────────────────────────────────────────────
# 4) Функция отправки одного extra_quiz
# ───────────────────────────────────────────────────────────────
@track_handler
async def send_one_extra_vocab_quiz(message: Message, state: FSMContext):
    """
    Берём из state индекс extra_quiz и отправляем следующий опрос.
    """
    data = await state.get_data()
    idx  = data.get("extra_quiz_index", 0)
    extra_quizzes = topics[data["selected_topic"]].get("extra_quiz", [])

    if idx >= len(extra_quizzes):
        # 💬 помечаем, что все extra_quiz пройдены
        await state.update_data(extra_quiz_done=True)
        await message.answer("Это были все дополнительные квизы. Возвращаемся в меню.")  # :contentReference[oaicite:1]{index=1}
        await state.set_state(LessonStates.waiting_lesson_action)
        return await lesson_menu_handler(message, state)


    quiz = extra_quizzes[idx]
    opts = quiz["options"].copy()
    random.shuffle(opts)
    correct_id = opts.index(quiz["correct_answer"])

    # Отправляем встроенный опрос
    poll_message = await message.answer_poll(
        question=quiz["question"],
        options=opts,
        type="quiz",
        correct_option_id=correct_id,
        explanation=quiz.get("explanation_correct", ""),
        is_anonymous=False
    )

    await state.update_data(
        current_poll_id=poll_message.poll.id,
        current_correct_option_id=correct_id
    )



# ───────────────────────────────────────────────────────────────
# 5) Обработка ответа на extra_quiz (только в состоянии extra_quiz)
# ───────────────────────────────────────────────────────────────
@dp.poll_answer(StateFilter(LessonStates.extra_quiz))
@track_handler
async def handle_extra_vocab_quiz_answer(poll_answer: PollAnswer, state: FSMContext):
    """
    После выбора варианта в доп. квизе:
    — начисляем XP (10–15 за правильный ответ),
    — сбрасываем poll_id,
    — предлагаем продолжить или вернуться в меню.
    """
    data = await state.get_data()
    if poll_answer.poll_id != data.get("current_poll_id"):
        return

    selected = poll_answer.option_ids[0] if poll_answer.option_ids else None
    correct = data["current_correct_option_id"]
    is_correct = (selected == correct)

    # Начисляем XP: 10–15 за верно, иначе 0
    delta = random.randint(10, 15) if is_correct else 0
    await award_xp(delta, state)

    # 🔥 ДОБАВЛЕНО: Запись XP в рейтинг
    user_id = poll_answer.user.id
    topic = data.get("selected_topic", "unknown")
    await add_xp(user_id, topic, delta)

    new_data = await state.get_data()
    xp = new_data.get("xp", 0)

    # Сообщаем о результате
    await bot.send_message(
        poll_answer.user.id,
        f"{'🎯 +'+str(delta)+' XP' if delta > 0 else '❌ 0 XP'}\nВсего XP: {xp}"
    )

    # Сбрасываем общий poll_id, чтобы основной хендлер quiz не срабатывал
    await state.update_data(current_poll_id=None)

    buttons = [
        [KeyboardButton(text="🎯 Получить ещё XP")],
        [KeyboardButton(text="Нет, вернуться в меню")]
    ]
    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    await bot.send_message(poll_answer.user.id, "Продолжим получать XP?", reply_markup=kb)

    await state.set_state(LessonStates.extra_quiz_confirm)


# ───────────────────────────────────────────────────────────────
# 6) Обработка выбора после extra_quiz_confirm
# ───────────────────────────────────────────────────────────────
@dp.message(LessonStates.extra_quiz_confirm)
@track_handler
async def confirm_extra_quiz_continue(message: Message, state: FSMContext):
    """
    Если пользователь нажал:
    🎯 — отправляем следующий extra_quiz,
    иначе — возвращаем в меню темы.
    """
    data = await state.get_data()
    if message.text == "🎯 Получить ещё XP":
        await state.update_data(extra_quiz_index=data.get("extra_quiz_index", 0) + 1)
        await state.set_state(LessonStates.extra_quiz)   # <== ВАЖНО!
        return await send_one_extra_vocab_quiz(message, state)
    # «Нет, вернуться в меню»
    await message.answer("Возвращаемся в меню.")
    await state.set_state(LessonStates.waiting_lesson_action)  # <== ВАЖНО!
    return await lesson_menu_handler(message, state)


#............Конец Потока по extra_quiz............................................
# ─────────────────────────────────────────────────────────
@track_handler
async def send_one_vocab(message: Message, state: FSMContext):
    data      = await state.get_data()
    # защита от отсутствия выбранной темы (во избежание KeyError)
    topic_key = data.get("selected_topic")
    if not topic_key:
        # вернём пользователя в главное меню урока
        return await lesson_menu_handler(message, state)

    idx       = data.get("vocab_index", 0)
    vocab_list= get_vocab_list(data)






   
    # 🚩 ДОБАВЛЕННАЯ ПРОВЕРКА, чтобы не вызывать лишние блоки
    if idx >= len(vocab_list):
        data = await state.get_data()
        failed = data.get("failed_vocab", [])
        if failed:
            # 📌 Шаг 5.1: переход в состояние review_failed_vocab
            await state.set_state(LessonStates.review_failed_vocab)
            # 💬 передаём chat_id вместо объекта Message
            chat_id = message.chat.id if hasattr(message, "chat") else message.id
            return await send_failed_vocab(chat_id, state)


        if not data.get("vocab_finished_once"):
            chat_id = message.chat.id if hasattr(message, "chat") else message.id
            await bot.send_message(chat_id, "🎉 Ты красавчик, все задания пройдены!")
            await state.update_data(vocab_finished_once=True)
            return await lesson_menu_handler(message, state)



        # возвращаем меню «ещё XP / вернуться»
        await bot.send_message(
            message.chat.id,
            "🔄 Ты уже прошёл все задания! Хочешь набрать ещё XP?",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🎯 Получить ещё XP")],
                    [KeyboardButton(text="Нет, вернуться в меню")]
                ],
                resize_keyboard=True
            )
        )
        await state.set_state(LessonStates.waiting_lesson_action)
        return

    
    # 📦 Берём текущий блок – сразу, один раз
    block = vocab_list[idx]
    btype = block.get("type", "link")


    # ——— Фото-блок ———
    if btype == "photo":
        return await send_one_vocab_photo(message, state)

    # ——— Quiz-блок ———
    if btype == "quiz":
        return await send_one_vocab_quiz(message, state)

    # — TextQuiz —
    if btype == "textquiz":
        msg = await smart_reply(message, block["question"], reply_markup=ReplyKeyboardRemove())
        await state.update_data(last_prompt_id=msg.message_id)
        
        # 💬 Показываем смайлик ✍️ на 1 секунду, авто-удаляем (НЕ ждем)
        import asyncio
        asyncio.create_task(send_and_auto_delete_text(
            bot,
            message.chat.id,
            "✍️",
            delay=1
        ))

        return await state.set_state(LessonStates.vocab_textquiz)
        # 💬 Теперь после вопроса появляется ✍️ на 1 сек.


    # ——— Text-блок ———
    if btype == "text":
        return await send_one_vocab_text(message, state)

    '''
Как всё работает ПОШАГОВО (логика потока):
    Пользователь идёт по словарю (showing_vocab).
    Каждый раз, когда показывается link, увеличивается счётчик links_shown (FSM).
    Каждый третий link:
    Сохраняется pending_link_index и вызывается send_ad_block.
    Показывается реклама из ads_data.json (пост из канала, вопрос, кнопки).
    Пользователь жмёт на кнопку →
    Получает реакцию.
    Через 1.5 сек удаляется рекламный пост, вопрос, кнопки, реакция.
    Возвращается к link, который должен был быть показан (по pending_link_index).
    Далее продолжается поток по стандартной логике (confirm_done, feedback_difficulty и т.д.)
    '''
    # ——— Link-блок с показом рекламы каждый третий линк ———

    # Получаем флаг, нужно ли возвращаться к link после рекламы
    data = await state.get_data()
    if data.get("show_ad_after_link"):
        # Только что вернулись с рекламы — не увеличиваем счетчик!
        await state.update_data(show_ad_after_link=False, pending_link_index=None)
    else:
        # Обычный переход: инкрементируем
        links_shown = data.get("links_shown", 0) + 1
        # Каждый 3-й link — реклама
        if links_shown % 3 == 0:
            await state.update_data(
                show_ad_after_link=True,
                pending_link_index=idx,
                links_shown=links_shown
            )
            return await send_ad_block(message, state)
        await state.update_data(links_shown=links_shown)


    # 3. Обновляем счетчик links_shown
    await state.update_data(links_shown=links_shown)

    # ——— Дальше обычный link-блок (без изменений) ———

  


    # иначе — это link-блок
    # ——— Link-блок ———
    title = block.get("title", "Без названия")
    link = block.get("link", "")

 
    # 💬 Отправляем слово + рандомный призыв к действию
    cta = random.choice(link_cta_phrases)
    await smart_reply(
        message,
        f' <b>{title}</b>\n👉 <a href="{link}"><b>{cta}</b></a>',
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    # 💬 Удаляем клавиатуру
    # 1) удаляем клавиатуру
    chat_id = message.chat.id if hasattr(message, 'chat') else message.id
    blank = await bot.send_message(chat_id, '\u00AD', reply_markup=ReplyKeyboardRemove())

    # 2) сразу же удаляем само «пустое» сообщение
    await blank.delete()

    '''

     # 💬 40% шанс отправить стикер или MP4 после ссылки упражнения
    if random.random() < 0.4:
        from scenarios_estiloso8_1 import exercise_stickers

        # 1) Стикеры из scenarios
        stickers = exercise_stickers
        # 2) MP4 из папки
        mp4s = [f for f in os.listdir(EXERCISE_GIF_FOLDER) if f.lower().endswith(".mp4")]

        # 3) Собираем общий список
        choices = [("sticker", s) for s in stickers] + \
                  [("animation", os.path.join(EXERCISE_GIF_FOLDER, m)) for m in mp4s]

        # 4) Выбираем и отправляем
        kind, val = random.choice(choices)
        if kind == "sticker":
            await send_and_auto_delete_sticker(bot, message.chat.id, val)

        else:
            await message.answer_animation(FSInputFile(val))
    # И после этого продолжаем дальше, спрашивая “Ты выполнил?”
    '''
   

    # 💬 Inline Confirm Done
    scene = random.choice(scenarios["confirm_done"])
    await state.update_data(current_stage="confirm_done", current_scene=scene)
    await state.set_state(LessonStates.showing_vocab)
    # 💬 Inline-кнопки “Подтвердить выполнение” в одну строку
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=btn, callback_data=f"confirm_done:{btn}")
            for btn in scene["buttons"]
        ]]
    )
    chat_id = message.chat.id if hasattr(message, 'chat') else (await state.get_data())["last_chat_id"]
    return await bot.send_message(chat_id, scene["text"], reply_markup=inline_kb)






@track_handler
# 💬 Показывает рекламный блок, сохраняет message_id для удаления
async def send_ad_block(message: Message, state: FSMContext):
    ads = load_ads_data()
    ad_index = (await state.get_data()).get("ad_index", 0)
    if ad_index >= len(ads):
        await message.answer("Все рекламные публикации показаны.")
        return
    ad = ads[ad_index]
    # Отправляем пост из канала
    from aiogram.exceptions import TelegramBadRequest
    import logging

    # Приводим channel_id к строке и оборачиваем в try/except
    channel = str(ad["channel_id"])
    try:
        ad_msg = await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=channel,
            message_id=ad["message_id"]
        )
    except TelegramBadRequest as e:
        logging.error(f"Ошибка копирования рекламы: {e}")
        # 💬 Если реклама не найдена или удалена, просто пропускаем её
        await state.update_data(show_ad_after_link=False, pending_link_index=None)
        await send_one_vocab(message, state)
        return


    btns = [
        [InlineKeyboardButton(text=btn["text"], callback_data=f'ad_answer:{ad_index}:{i}')]
        for i, btn in enumerate(ad["btns"])
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=btns)
    q_msg = await message.answer(ad["question"], reply_markup=kb)
    await state.update_data(
        current_ad_msg_id=ad_msg.message_id,
        current_ad_question_id=q_msg.message_id,
        ad_index=ad_index+1
    )



@track_handler
# Обработчик callback после рекламы
@dp.callback_query(lambda c: c.data and c.data.startswith("ad_answer:"))
async def ad_reaction_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    ad_index = int(parts[1])
    btn_index = int(parts[2])
    ads = load_ads_data()
    reaction = ads[ad_index]["btns"][btn_index]["reaction"]
    reaction_msg = await callback.message.answer(reaction)
    await callback.answer()
    await asyncio.sleep(1.5)
    data = await state.get_data()
    try: await bot.delete_message(callback.message.chat.id, data.get("current_ad_msg_id"))
    except: pass
    try: await bot.delete_message(callback.message.chat.id, data.get("current_ad_question_id"))
    except: pass
    try: await bot.delete_message(callback.message.chat.id, reaction_msg.message_id)
    except: pass
    try: await callback.message.delete()
    except: pass
    # Показываем link, который должен был идти после рекламы
    pending_idx = data.get("pending_link_index")
    if pending_idx is not None:
        await state.update_data(vocab_index=pending_idx)
        await state.update_data(show_ad_after_link=False, pending_link_index=None)
        await send_one_vocab(callback.message, state)






@track_handler
async def send_failed_vocab(chat_id: int, state: FSMContext):
    data       = await state.get_data()
    topic_key  = data["selected_topic"]
    vocab_list = get_vocab_list(data)
    failed     = data.get("failed_vocab", [])
    idx        = failed[0]
    block      = vocab_list[idx]



    # ——— Повтор текст-квиза и запоминаем ID сообщения для удаления
    if block.get("type") == "textquiz":
        # 1) отправляем вопрос
        sent = await bot.send_message(chat_id, block["question"])
        # 2) сохраняем его message_id, чтобы потом удалить вместе с фидбэком
        await state.update_data(last_failed_textquiz_message_id=sent.message_id)
        # 3) переводим FSM в ревью-состояние
        await state.set_state(LessonStates.review_failed_textquiz)
        return


    # ——— Повтор встроенного quiz и запоминаем message_id для удаления
    if block.get("type") == "quiz":
        opts = block["options"].copy()
        random.shuffle(opts)
        correct_id = opts.index(block["correct_answer"])
        poll_msg = await bot.send_poll(
            chat_id=chat_id,
            question=block["question"],
            options=opts,
            type="quiz",
            correct_option_id=correct_id,
            is_anonymous=False
        )
        # 💾 сохраняем poll.id и message_id, чтобы потом удалить и отследить ответ
        await state.update_data(
            current_poll_id=poll_msg.poll.id,
            current_poll_message_id=poll_msg.message_id,
            current_correct_option_id=correct_id
        )
        # 🔄 переключаем FSM в разбор ошибок quiz
        await state.set_state(LessonStates.review_failed_vocab)
        return


    # создаём «фейковый» Message с нужным chat.id
    fake_chat = Chat(id=chat_id, type="private")
    fake_user = User(id=poll_answer.user.id, is_bot=False, first_name=poll_answer.user.first_name or "")
    fake_msg  = Message(
        message_id=0,
        date=datetime.datetime.now(),
        chat=fake_chat,
        from_user=fake_user,
        text=""
    )
    return await lesson_menu_handler(fake_msg, state)







# ------------------------------  
#   ПОТОК по показу type: quiz по VOCAB 📘📘📘
# ------------------------------
@track_handler
async def send_one_vocab_quiz(message: Message, state: FSMContext):
    data      = await state.get_data()
    topic_key = data["selected_topic"]
    vocab_list = get_vocab_list(data)
    idx       = data.get("vocab_index", 0)

    # 1) Если вышли за пределы — сначала ревью ошибок, потом меню
    if idx >= len(vocab_list):
        failed = data.get("failed_vocab", [])
        if failed:
            await state.set_state(LessonStates.review_failed_vocab)
            # 💬 передаём chat_id вместо объекта Message
            return await send_failed_vocab(message.chat.id, state)
        return await lesson_menu_handler(message, state)


    # 2) Берём текущий блок – гарантированно в диапазоне
    block = vocab_list[idx]

        # Если это не Quiz-блок — перенаправляем в общий отправщик
    if block.get("type") != "quiz":
        return await send_one_vocab(message, state)


    # 3) Если перед квизом есть текст — отправляем
    if block.get("text"):
        chat_id = message.chat.id if hasattr(message, "chat") else (await state.get_data())["last_chat_id"]
        await bot.send_message(chat_id, block["text"])


    # 4) Собираем и отправляем Quiz
    opts = block["options"].copy()
    random.shuffle(opts)
    correct_id = opts.index(block["correct_answer"])
# — Отправляем Quiz через bot, чтобы не вызывать методы у ChatFullInfo —
    chat_id = message.chat.id if hasattr(message, "chat") else message.id
    poll_message = await bot.send_poll(
        chat_id=chat_id,
        question=block["question"],
        options=opts,
        type="quiz",
        correct_option_id=correct_id,
        open_period=20,
        explanation=block.get("explanation_correct",""),
        explanation_parse_mode="HTML",
        is_anonymous=False
    )
    # 💾 сохраняем poll и message_id
    await state.update_data(
        current_poll_id=poll_message.poll.id,
        current_poll_message_id=poll_message.message_id,
        current_correct_option_id=correct_id
    )
    # 🚨 запускаем таймаут на ответ
    asyncio.create_task(_vocab_quiz_timeout_handler(
        poll_message.poll.id, chat_id, state, delay=20
    ))
    await state.set_state(LessonStates.vocab_exercise)




@dp.poll_answer(StateFilter(LessonStates.review_failed_vocab))
@track_handler
async def handle_review_failed_vocab(poll_answer: PollAnswer, state: FSMContext):
    data = await state.get_data()
    # 1) Отфильтровываем чужие poll’ы
    if poll_answer.poll_id != data.get("current_poll_id"):
        return
    # 2) Сразу сбрасываем текущий poll_id, чтобы таймаут не сел
    await state.update_data(current_poll_id=None)

    # 3) Достаём индекс и блок
    idx = data.get("failed_vocab", [])[0]
    vocab_list = get_vocab_list(data)
    block      = vocab_list[idx]

    # 4) Проверяем, правильно ли ответили
    selected = poll_answer.option_ids[0] if poll_answer.option_ids else None
    correct = data["current_correct_option_id"]
    is_correct = (selected == correct)

    # 5) Начисляем XP по старой логике
    delta = random.randint(25, 35) if is_correct else -10
    await award_xp(delta, state)
    user_id = poll_answer.user.id
    topic_key = data["selected_topic"]

    xp_before = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    await add_xp(user_id, topic_key, delta)
    xp_after = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    if xp_after // XP_PER_LEVEL > xp_before // XP_PER_LEVEL:
        lvl_idx = min(xp_after // XP_PER_LEVEL, len(LEVELS)-1)
        medal_idx = min((xp_after % XP_PER_LEVEL) // (XP_PER_LEVEL // 3), 2)
        await bot.send_message(
            poll_answer.user.id,
            f"🎉 Поздравляем! Ты достиг уровня {LEVELS[lvl_idx]}{MEDALS[medal_idx]}!"
        )

    # 6) Сообщаем об изменении XP
    xp = (await state.get_data())["xp"]


    # 💬 Новый: показываем правильный ответ или фразу похвалы перед XP
    if is_correct:
        await send_and_auto_delete_text(bot, user_id,
                                       random.choice(vocab_quiz_success_phrases),
                                       delay=1)
    else:
        await send_and_auto_delete_text(bot, user_id,
                                       f"✅ {block['correct_answer']}",
                                       delay=1)
    await asyncio.sleep(1)


    xp_fb = await bot.send_message(
        user_id,
        f"{'🎉 +' + str(delta) + ' XP' if delta > 0 else '⚠️ ' + str(delta) + ' XP'}\nВсего XP: {xp}"
    )

    # 7) Подождать 1.5 с, чтобы успели прочесть
    await asyncio.sleep(1.5)

    # 8) Удаляем сообщение-poll и XP-фидбэк
    chat_id = poll_answer.user.id
    to_del = [
        data.get("current_poll_message_id"),
        xp_fb.message_id
    ]
    for mid in to_del:
        if mid:
            try: await bot.delete_message(chat_id, mid)
            except: pass

    # 9) Обновляем очередь ошибок:
    failed = data.get("failed_vocab", [])
    if is_correct:
        failed.pop(0)
    else:
        failed.append(failed.pop(0))
    await state.update_data(failed_vocab=failed)

    # 🔄 Если остались ошибки — снова повторяем
    if failed:
        return await send_failed_vocab(chat_id, state)

    # ✅ Иначе — возвращаемся в главное меню темы
    chat = await bot.get_chat(chat_id)
    fake_message = Message(
        message_id=0,
        date=datetime.datetime.now(),
        chat=chat,
        from_user=poll_answer.user,
        text=""
    )
    return await lesson_menu_handler(fake_message, state)


import types


@track_handler
async def _vocab_quiz_timeout_handler(poll_id: str, chat_id: int, state: FSMContext, delay: int = 20):
    await asyncio.sleep(delay)
    data = await state.get_data()
    if data.get("current_poll_id") != poll_id:
        return

    # сброс poll_id
    await state.update_data(current_poll_id=None)

    # ── Время вышло! ──
    await bot.send_message(chat_id, "⏱ Время вышло!")

    data = await state.get_data()
    idx  = data.get("vocab_index", 0)
    block = get_vocab_list(data)[idx]
    await send_and_auto_delete_text(bot, chat_id,
                                   f"✅ {block['correct_answer']}",
                                   delay=1)            # показываем и удаляем через 1 с
    await asyncio.sleep(1)
    # ── Далее оригинальный код: снимаем XP, показываем штраф, удаляем, переход к следующему

    # ── Снимаем 20 XP ──
    await award_xp(-20, state)
    xp = (await state.get_data()).get("xp", 0)
    fb = await bot.send_message(chat_id, f"⚠️ -20 XP\nВсего XP: {xp}")

    # ── Сохраняем этот индекс в failed_vocab ──
    idx    = data.get("vocab_index", 0)
    failed = data.get("failed_vocab", [])
    if idx not in failed:
        failed.append(idx)
        await state.update_data(failed_vocab=failed)

    # ── Ждём и удаляем опрос + фидбек ──
    await asyncio.sleep(1.5)
    try: await bot.delete_message(chat_id, data.get("current_poll_message_id"))
    except: pass
    try: await bot.delete_message(chat_id, fb.message_id)
    except: pass

    # ── Инкремент и следующий квиз ──
    await state.update_data(vocab_index=idx+1, current_poll_id=None)

  
    # вместо ChatFullInfo передаём объект с chat.id
    fake_msg = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id)
    )
    return await send_one_vocab_quiz(fake_msg, state)









@dp.poll_answer(StateFilter(LessonStates.vocab_exercise))
@track_handler
async def handle_vocab_poll_answer(poll_answer: PollAnswer, state: FSMContext):
    data = await state.get_data()
    # 💬 Был ли доступ уже открыт ДО начисления XP?
    was_unlocked = data.get("unlocked", False)
    # 1) Фильтруем чужие ответы
    if poll_answer.poll_id != data.get("current_poll_id"):
        return

    # 2) Отменяем таймаут
    await state.update_data(current_poll_id=None)

    # 3) Правильность и начисление XP
    idx = data.get("vocab_index", 0)
    selected = poll_answer.option_ids[0] if poll_answer.option_ids else None
    correct  = data["current_correct_option_id"]
    is_correct = (selected == correct)
    delta = random.randint(28, 37) if is_correct else -10
    await award_xp(delta, state)

    # 🔥 ДОБАВЛЕНО: Запись XP в рейтинг
    user_id = poll_answer.user.id
    topic   = data.get("selected_topic", "unknown")
    await add_xp(user_id, topic, delta)


    # 🔥 Level-Up: сохраняем прошлый глобальный XP
    user_id = poll_answer.user.id
    xp_before = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    topic     = data.get("selected_topic", "unknown")

    # 4) Запись XP в общее накопление
    await add_xp(user_id, topic, delta)

    # 🔥 Проверяем, перешли ли на новый уровень
    xp_after = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    prev_lvl = xp_before // XP_PER_LEVEL
    new_lvl  = xp_after  // XP_PER_LEVEL
    if new_lvl > prev_lvl:
        # 💬 Определяем медаль нового уровня
        medal_idx = min((xp_after % XP_PER_LEVEL) // (XP_PER_LEVEL // 3), 2)
        await bot.send_message(
            user_id,
            f"🎉 Поздравляем! Вы достигли уровня {LEVELS[new_lvl]}{MEDALS[medal_idx]}!"
        )


    # 4) Сохраняем ошибку для ревью
    if not is_correct:
        failed = data.get("failed_vocab", [])
        if idx not in failed:
            failed.append(idx)
            await state.update_data(failed_vocab=failed)

    # 5) Получаем обновлённый XP
    new_data = await state.get_data()
    xp = new_data.get("xp", 0)

    vocab_list= get_vocab_list(data)
    block     = vocab_list[idx]

    # 💬 Новый: показываем правильный ответ или фразу похвалы перед XP
    if is_correct:

        await send_and_auto_delete_text(bot, poll_answer.user.id,
                                       random.choice(vocab_quiz_success_phrases),
                                       delay=1)
    else:
        correct_text = f"✅ {block['correct_answer']}"
        await send_and_auto_delete_text(bot, poll_answer.user.id,
                                       correct_text,
                                       delay=1)
    await asyncio.sleep(1)


    # ─── Рандомное оформление сообщения об изменении XP ─────────────────────────
    xp_variants = [
        lambda d, x: (
            f"🎉🎉 <b>+{d} XP</b> 🎉🎉\n"
            f"🌟 Всего XP: <b>{x}</b> 🌟"
        ) if d>0 else (
            f"😢😢 <b>{d} XP</b> 😢😢\n"
            f"🌟 Всего XP: <b>{x}</b> 🌟"
        ),
        lambda d, x: (
            f"🔥 <b>+{d} XP</b> 🔥\n"
            f"❄️ Всего серии: <b>{x} XP</b> ❄️"
        ) if d>0 else (
            f"❄️ <b>{d} XP</b> ❄️\n"
            f"🔥 Всего серии: <b>{x} XP</b> 🔥"
        ),
        lambda d, x: (
            f"👍 <b>{d:+} XP</b> 👍\n"
            f"🏆 Всего XP: <b>{x}</b>"
        ),
        lambda d, x: (
            f"➕ <b>{d}</b> XP!\n"
            f"• Всего: <b>{x} XP</b>\n"
            "🔔 Продолжай в том же духе!"
        ),
        lambda d, x: (
            f"{'🚀' if d>0 else '🐌'} <b>{d:+} XP</b> {'🚀' if d>0 else '🐌'}\n"
            f"⭐️ Всего XP: <b>{x}</b> ⭐️"
        )
    ]
    text = random.choice(xp_variants)(delta, xp)
    fb = await bot.send_message(poll_answer.user.id, text, parse_mode="HTML")

    # 🔐 Если только что пересекли 80% порога — оповестим
    topic_key = data["selected_topic"]
    topic_data = topics.get(topic_key, {})

    # собираем квизы из всех фаз
    quizzes = [
        block
        for ph in topic_data.get("vocab", [])
        for block in ph.get("vocab", [])
        if block.get("type") in ("quiz", "textquiz")
    ]

    # 💬 Расчёт порога XP для разблокировки: 30 XP × кол-во квизов × 0.8, округляем вниз до 10
    threshold = math.floor(len(quizzes) * 30 * 0.8 / 10) * 10


    # 💬 Обновляем порог в state, чтобы меню зналo про него
    await state.update_data(xp_threshold=threshold)
    if not was_unlocked and xp >= threshold:
        # 1) Просто отправляем эмоджи «🔐»
        await bot.send_message(poll_answer.user.id, "🔐")
        # отмечаем в state, что доступ открыт
        await state.update_data(unlocked=True)
        # 2) Оповещаем о разблокировке
        await bot.send_message(
            poll_answer.user.id,
            "<b>БЛОКИ РАЗБЛОКИРОВАНЫ! 🎉</b>",
            parse_mode="HTML"
        )


    # 6) Ждём и удаляем опрос + feedback
    await asyncio.sleep(1.5)
    chat_id = poll_answer.user.id
    try: await bot.delete_message(chat_id, data.get("current_poll_message_id"))
    except: pass
    try: await bot.delete_message(chat_id, fb.message_id)
    except: pass

    # 7) Инкремент и следующий Quiz
    await state.update_data(vocab_index=idx+1, current_poll_id=None)

    # Создаём «фейковое» сообщение для send_one_vocab без SyntaxError
    fake_chat = Chat(id=chat_id, type="private")
    fake_user = User(id=poll_answer.user.id, is_bot=False, first_name="")
    fake_msg = Message(
        message_id=0,                          # фиктивный message_id
        date=datetime.datetime.now(),          # текущее время
        chat=fake_chat,                        # передаваемый chat
        from_user=fake_user,                   # передаваемый пользователь
        text=""                                # пустой текст у фейкового сообщения
    )
    await state.update_data(last_chat_id=chat_id)  # сохраняем последний chat_id
    return await send_one_vocab(fake_msg, state)   # вызываем отправку следующего элемента











'''
# ─────────────────────────────────────────────────────────
# 📝 Обработка ответа Quiz-словаря (правильно/неправильно)
@dp.poll_answer(StateFilter(LessonStates.vocab_exercise))
async def handle_vocab_poll_answer(poll_answer: PollAnswer, state: FSMContext):
    data = await state.get_data()
    if poll_answer.poll_id != data.get("current_poll_id"):
        return

    # 🛑 Отменяем таймаут, чтобы через 20 сек не сняло ещё −20 XP
    await state.update_data(current_poll_id=None)

    # 🔍 Сохраняем, был ли уже разблокирован доступ
    was_unlocked = data.get("unlocked", False)
    old_xp       = data.get("xp", 0)  # до начисления

    selected  = poll_answer.option_ids[0]
    correct   = data["current_correct_option_id"]
    is_correct= (selected == correct)



    # 🎲 Рандом 28–37 XP за правильный, −10 за неправильный
    delta = random.randint(28, 37) if is_correct else -10
    await award_xp(delta, state)

    # 📌 Шаг 3.1: сохраняем индекс блока в failed_vocab, если ответ неверный
    if not is_correct:
        data = await state.get_data()
        idx = data.get("vocab_index", 0)
        failed = data.get("failed_vocab", [])
        if idx not in failed:
            failed.append(idx)
            await state.update_data(failed_vocab=failed)


    # 🔥 ДОБАВЛЕНО: Запись XP в рейтинг
    user_id = poll_answer.user.id
    topic = data.get("selected_topic", "unknown")
    await add_xp(user_id, topic, delta)




    new_data = await state.get_data()
    xp       = new_data.get("xp", 0)  # после начисления

    # ─── Рандомное оформление сообщения об изменении XP ─────────────────────────
    xp_variants = [
        # Вариант 1: праздник vs грусть
        lambda d, x: (
            f"🎉🎉 <b>+{d} XP</b> 🎉🎉\n"
            f"🌟 Всего XP: <b>{x}</b> 🌟"
        ) if d>0 else (
            f"😢😢 <b>{d} XP</b> 😢😢\n"
            f"🌟 Всего XP: <b>{x}</b> 🌟"
        ),

        # Вариант 2: огонь vs снежинка
        lambda d, x: (
            f"🔥 <b>+{d} XP</b> 🔥\n"
            f"❄️ Всего серии: <b>{x} XP</b> ❄️"
        ) if d>0 else (
            f"❄️ <b>{d} XP</b> ❄️\n"
            f"🔥 Всего серии: <b>{x} XP</b> 🔥"
        ),

        # Вариант 3: 👍 vs 👎 с +/− в центре
        lambda d, x: (
            f"👍 <b>{d:+} XP</b> 👍\n"
            f"🏆 Всего XP: <b>{x}</b>"
        ),

        # Вариант 4: буллеты и колокольчик
        lambda d, x: (
            f"➕ <b>{d}</b> XP!\n"
            f"• Всего: <b>{x} XP</b>\n"
            "🔔 Продолжай в том же духе!"
        ),

        # Вариант 5: ракетка vs улитка
        lambda d, x: (
            f"{'🚀' if d>0 else '🐌'} <b>{d:+} XP</b> {'🚀' if d>0 else '🐌'}\n"
            f"⭐️ Всего XP: <b>{x}</b> ⭐️"
        )
    ]
    # выбираем случайный шаблон и отправляем
    text = random.choice(xp_variants)(delta, xp)
    await bot.send_message(
        poll_answer.user.id,
        text,
        parse_mode="HTML"
    )

    # 🔐 Если только что пересекли 80% порога — оповестим
    #    порог по среднему 30 XP × кол-во квизов × 0.8, округляем вверх
    quizzes   = [b for b in topics[data["selected_topic"]]["vocab"] if b.get("type") in ("quiz","textquiz")]
    threshold = math.ceil(len(quizzes) * 30 * 0.8)
    threshold = data.get("xp_threshold", 0)
    if (not was_unlocked) and xp >= threshold:


        # 1) Просто отправляем эмоджи «замка»
        await bot.send_message(poll_answer.user.id, "🔐")

        # отмечаем в state, что доступ открыт
        await state.update_data(unlocked=True)
        # шлём уведомление
        await bot.send_message(
            poll_answer.user.id,
            "<b>БЛОКИ РАЗБЛОКИРОВАНЫ! 🎉</b>",
            parse_mode="HTML"
        )

    # показываем after_quiz-сценарий
    scene   = random.choice(after_quiz)
    buttons = [[KeyboardButton(text=btn)] for btn in scene["buttons"]]
    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await state.update_data(current_scene=scene, current_poll_id=None)

    # ждём кнопки «Продолжить/Домой»
    await state.set_state(LessonStates.vocab_continue)
    await bot.send_message(poll_answer.user.id, scene["text"], reply_markup=kb)

    '''







# ---------------- КОНЕЦ по показу type: quiz📘📘📘 -----------------






# ---------------- НАЧАЛО по показу type: text_quiz📘📘📘 -----------------
@dp.message(LessonStates.vocab_textquiz)
@track_handler
async def handle_vocab_textquiz_answer(message: Message, state: FSMContext):
    # 💬 Нормализуем ответ пользователя и правильный ответ из JSON
    data = await state.get_data()
    topic_key = data["selected_topic"]
    idx = data.get("vocab_index", 0)
    vocab_list= get_vocab_list(data)
    block     = vocab_list[idx]
    user_norm = normalize_textquiz(message.text)
    correct_norm = normalize_textquiz(block["correct_answer"])
    # 🎲 Решаем, верно ли
    is_correct = (user_norm == correct_norm)

    # 🎉 1) Начисляем XP в сессии
    delta = random.randint(25, 35) if is_correct else -10
    await award_xp(delta, state)

    # 🔥 Level-Up: сохраняем прошлый глобальный XP
    user_id   = message.chat.id
    xp_before = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    topic_key = data["selected_topic"]

    # 📌 2) Запись XP в общий рейтинг
    await add_xp(user_id, topic_key, delta,
                 action="words_learned" if is_correct else None)

    # 🔥 Проверяем, перешли ли на новый уровень
    xp_after = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    prev_lvl = xp_before // XP_PER_LEVEL
    new_lvl  = xp_after  // XP_PER_LEVEL
    if new_lvl > prev_lvl:
        medal_idx = min((xp_after % XP_PER_LEVEL) // (XP_PER_LEVEL // 3), 2)
        await message.answer(
            f"🎉 Поздравляем! Вы достигли уровня {LEVELS[new_lvl]}{MEDALS[medal_idx]}!"
        )

    
    # 💬 3) Показываем XP-фидбэк
    xp_total = (await state.get_data())["xp"]
    xp_fb = await message.answer(
        f"{'🎉 +' if delta>0 else '⚠️ '}{delta} XP\nВсего XP: {xp_total}",
        parse_mode="HTML"
    )

    # 💬 4) Дополнительный фидбэк: печенька или правильный ответ
    # 💬 Сколько уже дали за этот урок?
    data = await state.get_data()
    given = (load_xp_data()
             .get(str(user_id), {})
             .get("stats", {})
             .get("words_learned", 0)
         ) - data.get("initial_cookies", 0)

    if is_correct and given < data.get("max_cookies", 0):
        # 📌 даём +1 печеньку, если не исчерпан лимит
        await add_xp(user_id, topic_key, 0, action="words_learned")
        extra_fb = await message.answer("<b>🍪 +1</b>", parse_mode="HTML")
    elif not is_correct:
        # 📌 показываем правильный ответ заглавными
        extra_fb = await message.answer(f"👉 {block['correct_answer'].upper()}", parse_mode="HTML")
    else:
        # 📌 лимит печенек достигнут — пропускаем
        extra_fb = None


    # 💬 Ждём 1.5 секунды перед удалением всех сообщений
    await asyncio.sleep(1.5)
    # 💬 5) Удаляем всё: вопрос, ответ пользователя, XP-фидбэк и (если есть) extra-фидбэк
    chat_id   = message.chat.id
    prompt_id = (await state.get_data()).get("last_prompt_id")
    # собираем ID
    to_delete = [prompt_id, message.message_id, xp_fb.message_id]
    # extra_fb мог быть None, добавляем только если это Message
    if isinstance(extra_fb, Message):
        to_delete.append(extra_fb.message_id)
    for mid in to_delete:
        if not mid:
            continue
        try:
            await bot.delete_message(chat_id, mid)
        except TelegramBadRequest:
            # например, уже удалили
            pass


    # 💬 6) Убираем этот элемент из очереди ошибок
    failed = data.get("failed_vocab", [])
    if not is_correct and idx not in failed:
        failed.append(idx)
    await state.update_data(failed_vocab=failed)

    # 💬 7) Переходим к следующему слову или в меню
    await state.update_data(vocab_index=idx + 1)
    return await send_one_vocab(message, state)



    data = await state.get_data()
    user_id = message.from_user.id
    topic = data.get("selected_topic", "unknown")
    # 💬 Записываем в XP-файл
    if is_correct:
        await add_xp(user_id, topic, delta, action="words_learned")
    else:
        await add_xp(user_id, topic, delta)


    data2 = await state.get_data()
    if not data2.get("unlocked") and data2["xp"] >= data2["xp_threshold"]:
        await state.update_data(unlocked=True)
        await message.answer("🔐 <b>Блоки разблокированы! 🎉</b>", parse_mode="HTML")

    xp = (await state.get_data()).get("xp", 0)
    # 💬 Сообщаем результат
    # 🎨 Визуализация, как в Poll-Quiz
    xp_variants = [
        lambda d,x: f"🎉🎉 <b>+{d} XP</b> 🎉🎉\n🌟 Всего XP: <b>{x}</b> 🌟" if d>0 else f"😢😢 <b>{d}</b> XP 😢😢\n🌟 Всего XP: <b>{x}</b> 🌟",
        lambda d,x: f"🔥 <b>+{d} XP</b> 🔥\n❄️ Всего серии: <b>{x} XP</b> ❄️" if d>0 else f"❄️ <b>{d}</b> XP ❄️\n🔥 Всего серии: <b>{x} XP</b> 🔥",
        lambda d,x: f"👍 <b>{d:+} XP</b> 👍\n🏆 Всего XP: <b>{x}</b>",
        lambda d,x: f"➕ <b>{d}</b> XP!\n• Всего: <b>{x} XP</b>\n🔔 Продолжай в том же духе!",
        lambda d,x: f"{'🚀' if d>0 else '🐌'} <b>{d:+} XP</b> {'🚀' if d>0 else '🐌'}\n⭐️ Всего XP: <b>{x}</b> ⭐️"
    ]
    text = random.choice(xp_variants)(delta, xp)
    await message.answer(text, parse_mode="HTML")

    # 👉 Переходим к следующему элементу
    await state.update_data(vocab_index=idx + 1)
    return await send_one_vocab(message, state)


# ---------------- КОНЕЦ по показу type: text_quiz📘📘📘 -----------------




# ------------------------------  
#   ПОТОК по показу type: text по VOCAB
# ------------------------------

# 1) Хендлер отправки текстового блока словаря
@track_handler
async def send_one_vocab_text(message: Message, state: FSMContext):
    """
    💬 После текстового блока словаря бот теперь отправляет inline-кнопки.
    """
    data       = await state.get_data()
    topic_key  = data["selected_topic"]
    idx        = data.get("vocab_index", 0)
    vocab_list= get_vocab_list(data)
    block     = vocab_list[idx]

    # Отправляем текст
    await send_plaintext(message, block["text"])

    # Выбираем сцену after_text
    scene = random.choice(after_text)
    await state.update_data(current_stage="after_text", current_scene=scene)

    # Строим InlineKeyboardMarkup
    # 💬 Кнопки “прочитал/пропустить” в одну строку
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=btn,
                callback_data=f"after_text:{btn}"
            ) for btn in scene["buttons"]
        ]]
    )


    chat_id = message.chat.id if hasattr(message, "chat") else (await state.get_data())["last_chat_id"]
    await bot.send_message(chat_id, scene["text"], reply_markup=inline_kb)

    # Переходим в состояние ожидания inline callback
    await state.set_state(LessonStates.vocab_text_continue)

# 💬 Это отправляет текст + inline-кнопки вместо обычных клавиш.


@dp.callback_query(StateFilter(LessonStates.vocab_text_continue), lambda cb: cb.data.startswith("after_text:"))
@track_handler
async def handle_vocab_text_continue_cb(cb: CallbackQuery, state: FSMContext):
    """
    💬 Inline-ответ после текстового блока словаря:
    1) Удаляет текст и кнопки
    2) Если есть реакция — показывает её (всегда отдельным сообщением)
    3) Через паузу отправляет следующий блок (новое слово)
    """
    await cb.answer()
    await cb.message.delete()

    data   = await state.get_data()
    scene  = data["current_scene"]
    choice = cb.data.split(":",1)[1]
    reply_cfg = scene["replies"].get(choice)

    # 1. Показываем реакцию (если не пусто)
    reaction = reply_cfg.get("reaction", "")
    if reaction:
        await cb.message.answer(reaction)
        await asyncio.sleep(1.2)   # короткая пауза, чтобы прочитать реакцию

    # 2. Всегда инкрементируем индекс и отправляем следующий блок
    if reply_cfg.get("next") == "next_item":
        # 1) если у текущего текст-блока есть quiz → показываем его
        block = get_vocab_list(data)[data["vocab_index"]]
        if block.get("quiz"):
            return await send_optional_vocab_quiz(cb.message, state)
        # 2) иначе – просто переходим к следующему
        return await proceed_to_next(cb.message, state)








# ---------------- КОНЕЦ по показу type: text 📘📘📘 -----------------



# ---------------- НАЧАЛО по показу type: photo по VOCAB -----------------



@track_handler
async def send_one_vocab_photo(message, state: FSMContext):
    data      = await state.get_data()
    topic_key = data["selected_topic"]
    idx       = data.get("vocab_index", 0)
    vocab_list= get_vocab_list(data)
    block     = vocab_list[idx]

    # 1) Если есть текст-подпись перед фото, шлём её
    if block.get("text"):
        await smart_reply(message, block["text"])

    # 💬 определяем chat_id для Message или SimpleNamespace
    chat_id = message.chat.id if hasattr(message, "chat") else message.id

    # 2) Отправляем медиа — фото, анимацию или стикер
    mt = block.get("media_type", "photo")
    if mt == "photo":
         chat_id = message.chat.id if hasattr(message, "chat") else message.id
         await bot.send_photo(chat_id, photo=FSInputFile(block["photo"]))
    elif mt == "animation":
        await message.answer_animation(FSInputFile(block["photo"]))
    elif mt == "sticker":
        await bot.send_sticker(chat_id=message.chat.id, sticker=block["photo"])

    # 3) Выбираем сцену «after_photo» и сохраняем в state
    scene = random.choice(after_photo)
    await state.update_data(current_stage="after_photo", current_scene=scene)

    # 4) Строим inline-кнопки на основе scene["buttons"] — бок о бок
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=scene["buttons"][0],
                callback_data=f"after_photo:{scene['buttons'][0]}"
            ),
            InlineKeyboardButton(
                text=scene["buttons"][1],
                callback_data=f"after_photo:{scene['buttons'][1]}"
            )
        ]]
    )

    # 5) Отправляем текст сцены с inline-кнопками
    await bot.send_message(message.chat.id, scene["text"], reply_markup=inline_kb)

    # 6) Переходим в состояние обработки callback
    await state.set_state(LessonStates.vocab_photo_continue)



# ─────────────────────────────────────────────────────────

@dp.callback_query(StateFilter(LessonStates.vocab_photo_continue),
                   lambda cb: cb.data.startswith("after_photo:"))
@track_handler
async def handle_vocab_photo_continue_cb(cb: CallbackQuery, state: FSMContext):
    """
    💬 После фото — показываем реакцию, ждем 1.5 сек и только потом отправляем следующий блок.
    """
    await cb.answer()
    await cb.message.delete()

    data  = await state.get_data()
    scene = data["current_scene"]
    choice = cb.data.split(":",1)[1]

    reply_cfg = scene["replies"].get(choice)

    # 1. Показываем реакцию, если она есть
    reaction = reply_cfg.get("reaction", "")
    if reaction:
        await cb.message.answer(reaction)
        await asyncio.sleep(1.5)  # ⏳ Задержка, чтобы пользователь увидел реакцию

   # 2. Переход к следующему слову (с проверкой на опциональный квиз)
    if reply_cfg.get("next") == "next_item":
       # Если у текущего блока после фото есть свой quiz — показываем его
       block = get_vocab_list(data)[data["vocab_index"]]
       if block.get("quiz"):
           return await send_optional_vocab_quiz(cb.message, state)
       # Иначе просто инкремент и следующий элемент
       return await proceed_to_next(cb.message, state)
# 💬 Теперь бот ждет 1.5 сек после реакции на фото, всё видно как надо!



# ---------------- КОНЕЦ по показу type: photo 📘📘📘 -----------------


@dp.poll_answer(StateFilter(LessonStates.vocab_optional_quiz))
@track_handler
async def handle_optional_vocab_quiz(poll_answer: PollAnswer, state: FSMContext):
    data = await state.get_data()
    # 1) фильтруем чужие опросы
    if poll_answer.poll_id != data.get("current_optional_poll_id"):
        return
    # сразу сбрасываем, чтобы таймауты не мешали
    await state.update_data(current_optional_poll_id=None)

    user_id = poll_answer.user.id
    selected = poll_answer.option_ids[0] if poll_answer.option_ids else None
    correct = data["current_optional_correct_id"]
    is_correct = (selected == correct)

    # 2) фидбэк без XP
    if is_correct:
        await send_and_auto_delete_text(bot, user_id, "🎉 Правильно!", delay=1.5)
    else:
        correct_text = get_vocab_list(data)[data["vocab_index"]]["quiz"]["correct_answer"]
        await send_and_auto_delete_text(bot, user_id, f"✅ {correct_text}", delay=1.5)

    # 3) удаляем сам poll
    await asyncio.sleep(1.5)
    try:
        await bot.delete_message(user_id, data.get("current_optional_message_id"))
    except:
        pass

     # 4) идём к следующему блоку через fake_msg
    import types  # 💬 для создания объекта с chat.id
    fake_msg = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=poll_answer.user.id)
    )
    return await proceed_to_next(fake_msg, state)






@dp.message(LessonStates.showing_vocab, is_confirm_done_vocab)
@track_handler
async def handle_confirm_done_vocab(message: Message, state: FSMContext):
    # 💬 Стираем старую клавиатуру сразу после нажатия
 
  
    await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
    data = await state.get_data()
    scene = data["current_scene"]


    # 🚫 Если ответ не из кнопок — восстанавливаем клавиатуру
    if not await ensure_valid_choice(message, scene["buttons"]):
        return

    params     = scene["replies"][message.text]
    reaction   = params.get("reaction")
    next_stage = params.get("next")
    if reaction:
        await smart_reply(message, reaction, parse_mode="HTML")

    # 🎉 Если подтвердили выполнение блока «Учить слова»
    if next_stage == "feedback_difficulty":
        # 1) Собираем все link-блоки словаря (игнорируем quiz/text/photo)
        topic_key = data["selected_topic"]
        vocab_list     = get_vocab_list(data)
        link_blocks = [b for b in vocab_list if "link" in b]
        total = len(link_blocks)

        # 2) Обновляем общий счётчик link‐блоков (legacy, чтобы старую логику не сломать)
        passed = data.get("vocab_done", 0) + 1
        await state.update_data(vocab_done=passed, refusal_count=0)

        # 💬 А ещё обновляем per‐phase счётчик
        phase_id        = data.get("selected_phase_id")
        per_phase       = data.get("vocab_done_per_phase", {})
        phase_passed    = per_phase.get(phase_id, 0) + 1
        per_phase[phase_id] = phase_passed
        await state.update_data(vocab_done_per_phase=per_phase)



        # 3) Формируем строку звёздочек
        stars = "⭐" * passed + "☆" * (total - passed)





        # 💬 40% шанс отправить случайный стикер или MP4 из папки gif/
        if random.random() < 0.4:

            # 1) Собираем список file_id для стикеров
            stickers = [item["file_id"] for item in congrats_media if item["type"] == "sticker"]
            # 2) Собираем список локальных MP4 из папки gif/
            mp4_files = [f for f in os.listdir("gif") if f.lower().endswith(".mp4")]

            # 3) Объединяем в общий список
            media_choices = []
            media_choices += [("sticker", sid) for sid in stickers]
            media_choices += [("animation", os.path.join("gif", mp4)) for mp4 in mp4_files]

            # 4) Выбираем случайный элемент
            kind, val = random.choice(media_choices)
            
            # 5) Отправляем
            try:
                if kind == "sticker":
                    await send_and_auto_delete_sticker(bot, message.chat.id, val)
                else:
                    await send_and_auto_delete_gif(bot, message.chat.id, val)
            except TelegramBadRequest:
                # Невалидный ID — просто пропускаем
                pass




        await smart_reply(message, f"{stars} {passed}/{total} игр пройдено!")

        # 💬 Подсказка после 3-го слова
        if passed == 3:
            await smart_reply(message, "Если ты чувствуешь, что готов, можешь перейти к упражнениям.")


        # 🎲 Выбираем случайный вариант вопроса о сложности из списка сценариев
        fb_scene = random.choice(scenarios["feedback_difficulty"])
    
        # 🖲 Готовим кнопки: для каждой строки из fb_scene["buttons"] создаём KeyboardButton
        buttons = [[KeyboardButton(text=btn)] for btn in fb_scene["buttons"]]
    
        # 🗂 Собираем клавиатуру с нашими кнопками 
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    
        # 💾 Сохраняем в память FSM, что мы сейчас в этапе feedback_difficulty и какую сцену показали
        await state.update_data(current_stage="feedback_difficulty", current_scene=fb_scene)
    
        # 📤 Отправляем пользователю текст вопроса и прикрепляем нашу клавиатуру
        await smart_reply(
            message,
            fb_scene["text"],
            reply_markup=kb,
            parse_mode="HTML"
        )


    # 🚫 Если отказались — показываем отказную ветку
    if next_stage == "refusal":

        # 💬 40% шанс отправить случайный стикер или MP4 из папки с отказами

        # 1) Стикеры отказа
        stickers = os.path.join("gif", "animanions_refusual")
        # 2) Локальные MP4 из папки animanions_refusual
        mp4_files = [f for f in os.listdir("animanions_refusual") if f.lower().endswith(".mp4")]

        # 3) Объединяем в общий список
        media_choices = [("sticker", sid) for sid in stickers] + \
                        [("animation", os.path.join("animanions_refusual", m)) for m in mp4_files]

        # 4) Выбираем и отправляем
        kind, val = random.choice(media_choices)
        try:
            if kind == "sticker":
                await send_and_auto_delete_sticker(bot, message.chat.id, val)
            else:
                await send_and_auto_delete_gif(bot, message.chat.id, val)
        except TelegramBadRequest:
            # если вдруг невалидный ID — просто пропускаем
            pass


        # 🚫 Если отказались — показываем отказную ветку из сценария
        ref_scene = random.choice(scenarios["refusal"])
        buttons = [[KeyboardButton(text=btn)] for btn in ref_scene["buttons"]]
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await state.update_data(current_stage="refusal", current_scene=ref_scene)
        return await smart_reply(message, ref_scene["text"], reply_markup=kb, parse_mode="HTML")








# ─────────────────────────────────────────────────────────
@dp.message(LessonStates.showing_vocab, is_feedback_difficulty_vocab)
@track_handler

async def handle_feedback_difficulty_vocab(message: Message, state: FSMContext):
    # 💬 Стираем старую клавиатуру сразу после нажатия
    await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
    data = await state.get_data()
    scene = data["current_scene"]

    # 🚫 Неправильный ввод — восстанавливаем клавиатуру
    if not await ensure_valid_choice(message, scene["buttons"]):
        return

    # 1️⃣ Получаем реакцию и следующий этап
    params = scene["replies"][message.text]
    reaction = params.get("reaction")
    next_stage = params.get("next")

    # 2️⃣ Отправляем реакцию из сценария (если есть)
    if reaction:
        await smart_reply(message, reaction, parse_mode="HTML")

    # 3️⃣ Если следующий элемент — quiz, сразу переходим к квиз-блоку
    data = await state.get_data()
    topic_key = data["selected_topic"]
    vocab_list= get_vocab_list(data)
    next_idx = data.get("vocab_index", 0) + 1

    # ➡️ Если следующий — quiz или textquiz, сразу к нему (пропускаем offer_continue)
    if next_idx < len(vocab_list) and vocab_list[next_idx].get("type") in ("quiz", "textquiz"):
        # 💬 рандомный эмоджи перед фразой квиза
        emojis = ["👮‍♂️", "👮‍♀️", "🚓"]
        prefix = random.choice(emojis)
        await smart_reply(message, prefix, reply_markup=ReplyKeyboardRemove())

        # 💬 промежуточная фраза перед квизом
        phrase = random.choice(vocab_quiz_intro_phrases)
        await smart_reply(message, phrase, reply_markup=ReplyKeyboardRemove())

        # 💾 обновляем индекс и прыгаем в send_one_vocab (там уже будет своя логика для quiz/textquiz)
        await state.update_data(vocab_index=next_idx)
        return await send_one_vocab(message, state)



    # 4️⃣ Иначе — стандартное “offer_continue”
    oc_scene = random.choice(scenarios["offer_continue"])
    buttons = [[KeyboardButton(text=btn)] for btn in oc_scene["buttons"]]
    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await state.update_data(current_stage="offer_continue", current_scene=oc_scene)
    return await smart_reply(message, oc_scene["text"], reply_markup=kb, parse_mode="HTML")




# ─────────────────────────────────────────────────────────
@dp.message(LessonStates.showing_vocab, is_offer_continue_vocab)
@track_handler
async def handle_offer_continue_vocab(message: Message, state: FSMContext):
    # 💬 Стираем старую клавиатуру сразу после нажатия
    await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())

    data = await state.get_data()
    scene = data["current_scene"]

    # 🚫 Если ответ не из кнопок — восстанавливаем клавиатуру
    if not await ensure_valid_choice(message, scene["buttons"]):
        return

    params     = scene["replies"][message.text]
    reaction   = params.get("reaction")
    next_stage = params.get("next")

    if reaction:
        await smart_reply(message, reaction, parse_mode="HTML")

    # 💬 Если продолжаем — сначала сдвигаем индекс, потом отправляем следующий блок
    if next_stage == "next_item":

        phrase, sticker_id = random.choice(go_next_phrases)
        await smart_reply(message, phrase)
        await send_and_auto_delete_sticker(bot, message.chat.id, sticker_id, delay=3)

        # ...теперь отправляем следующий элемент
        # 🚀 инкрементируем индекс «учить слова»
        curr = data.get("vocab_index", 0)
        await state.update_data(vocab_index=curr + 1, refusal_count=0)
        # и только потом шлём новый элемент (он уже учтёт квизы из JSON)
        return await send_one_vocab(message, state)

    # 💬 Если «Домой» — возвращаемся в меню урока
    if next_stage == "home":
        return await lesson_menu_handler(message, state)




# ─────────────────────────────────────────────────────────
@dp.message(LessonStates.showing_vocab, is_refusal_vocab)
@track_handler
async def handle_refusal_vocab(message: Message, state: FSMContext):
    await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
    data = await state.get_data()
    scene = data["current_scene"]

    if message.text not in scene["buttons"]:
        return await smart_reply(message, "Пожалуйста, нажми одну из кнопок.")

    params = scene["replies"][message.text]
    reaction = params.get("reaction")
    next_stage = params.get("next")
    if reaction:
        # 💬 Проверяем, есть ли анимированный эмодзи
        if reaction:
            await smart_reply(message, reaction, parse_mode="HTML")


    # 💬 Повтор текущего элемента или домой
    if next_stage == "repeat_current":
        return await send_one_vocab(message, state)
    if next_stage == "home":
        return await lesson_menu_handler(message, state)






# ─────────────────────────────────────────────────────────
@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text == "🏠 Home")
@track_handler
async def go_home(message: Message, state: FSMContext):
    # Просто возвращаемся в меню урока, сохраняя прогресс
    await register_or_update_user(message)
    return await lesson_menu_handler(message, state)


# ─ review quiz ошибок ─────────────────────────────────
@dp.message(LessonStates.review_failed_textquiz)
@track_handler
async def handle_failed_textquiz(message: Message, state: FSMContext):
    # 💬 Получаем данные FSM и индекс текущего вопроса
    data = await state.get_data()
    idx = data.get("failed_vocab", [])[0]
    # Новая логика: берём список блоков конкретной фазы через helper
    vocab_list = get_vocab_list(data)
    block      = vocab_list[idx]


    # 💬 Нормализуем ответ пользователя и верный ответ
    user_ans = normalize_textquiz(message.text)
    correct_ans = normalize_textquiz(block["correct_answer"])
    is_correct = (user_ans == correct_ans)

    # 💬 Начисляем XP в сессии
    delta = random.randint(25, 35) if is_correct else -10
    await award_xp(delta, state)

    # 🔥 Level-Up: предыдущий глобальный XP
    user_id = message.from_user.id
    xp_before = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    topic_key = data.get("selected_topic", "unknown")

    # 💬 Запись XP в общее накопление
    await add_xp(user_id, topic_key, delta,
                 action="words_learned" if is_correct else None)

    # 🔥 Проверка перехода на новый уровень
    xp_after = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    if xp_after // XP_PER_LEVEL > xp_before // XP_PER_LEVEL:
        lvl_idx = min(xp_after // XP_PER_LEVEL, len(LEVELS)-1)
        medal_idx = min((xp_after % XP_PER_LEVEL) // (XP_PER_LEVEL // 3), 2)
        await message.answer(
            f"🎉 Поздравляем! Вы достигли уровня {LEVELS[lvl_idx]}{MEDALS[medal_idx]}!"
        )


    # 💬 Сообщаем XP-фидбэк
    xp_total = (await state.get_data()).get("xp", 0)
    xp_fb = await message.answer(
        f"{'🎉 +'+str(delta)+' XP' if delta>0 else '⚠️ '+str(delta)+' XP'}\n"
        f"Всего XP: {xp_total}",
        parse_mode="HTML"
    )

    # 💬 Дополнительный фидбэк:  
    #   – 🍪 +1 если правильно  
    #   – ❌ ПРАВИЛЬНЫЙ_ОТВЕТ (заглавными) если нет  
    # 💬 Сколько уже дали за этот урок?
    data = await state.get_data()
    given = (load_xp_data()
             .get(str(user_id), {})
             .get("stats", {})
             .get("words_learned", 0)
         ) - data.get("initial_cookies", 0)

    if is_correct and given < data.get("max_cookies", 0):
        # 📌 даём +1 печеньку, если не исчерпан лимит
        await add_xp(user_id, topic_key, 0, action="words_learned")
        extra_fb = await message.answer("🍪 +1", parse_mode="HTML")
    elif not is_correct:
        # 📌 показываем правильный ответ заглавными
        extra_fb = await message.answer(f"👉 {block['correct_answer'].upper()}", parse_mode="HTML")
    else:
        # 📌 лимит печенек достигнут — пропускаем
        extra_fb = None


    # 💬 Ждём 1.5 секунды перед удалением
    await asyncio.sleep(1.5)

    # …после sleep…
    # 💬 Удаляем из чата всё: вопрос, ответ пользователя, оба фидбэка
    chat_id = message.chat.id
    try:
        # вопрос из send_failed_vocab сохранили в state  
        qid = data.get("last_failed_textquiz_message_id")
        if qid:
            await bot.delete_message(chat_id, qid)
        await bot.delete_message(chat_id, message.message_id)      # ответ пользователя
        await bot.delete_message(chat_id, xp_fb.message_id)       # XP-фидбэк
        # вместо cookie_fb используем extra_fb
        if isinstance(extra_fb, Message):
            await bot.delete_message(chat_id, extra_fb.message_id)  # печенька/правильный ответ
    except:
        pass


    # 💬 Обновляем очередь ошибок:
    failed = data.get("failed_vocab", [])
    if is_correct:
        # при правильном ответе убираем текущий индекс
        failed.pop(0)
    else:
        # при неверном — сдвигаем его в конец, чтобы повторять снова
        failed.append(failed.pop(0))
    await state.update_data(failed_vocab=failed)

    # 🔄 Если ещё остались ошибки — повторяем, иначе — возвращаемся в меню
    if failed:
        return await send_failed_vocab(chat_id, state)
    return await lesson_menu_handler(message, state)






# ========= 📘📘📘КОНЕЦ ПОТОКА ПО СЛОВАРЮ или ПО СЛОВАМ 📘📘📘 ====================


# ────────────────────────────────────────────────────────────────────
# 🏠 Хендлер «Домой» для возврата в меню урока
# ────────────────────────────────────────────────────────────────────
@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text == "🏠 Home")
async def go_home(message: Message, state: FSMContext):
    # 💬 Возвращаем в главное меню урока, сохраняя прогресс
    return await lesson_menu_handler(message, state)



# ——————— Конец «🙊Читать диалог» ———————


@dp.callback_query(
    lambda c: c.data and c.data.startswith("check_subscription:"),
    StateFilter(LessonStates.waiting_subscription)
)
async def check_subscription(query: CallbackQuery, state: FSMContext):
    await query.answer()
    topic_key = query.data.split(":", 1)[1]
    info      = topics.get(topic_key, {})
    required  = info.get("required_channels") or ([info.get("required_channel")] if info.get("required_channel") else [])

    import time
    now = int(time.time())
    uid = str(query.from_user.id)

    # 1) Проверяем каждый канал; при ошибке считаем НЕподписанным
    for ch in required:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=query.from_user.id)
            is_member = member.status in ("member", "administrator", "creator")
        except TelegramBadRequest:
            is_member = False

        if not is_member:
            # фиксируем отписку в последней сессии
            data     = load_user_data()
            u        = data.setdefault(uid, {})
            sessions = u.setdefault("channels", {}).setdefault(ch, [])
            if sessions and sessions[-1].get("unsubscribed_at") is None:
                sessions[-1]["unsubscribed_at"] = now
                save_user_data(data)

            # удаляем старое сообщение с кнопкой
            await query.message.delete()

            # показываем список каналов и кнопку
            channels_str = ", ".join(required)
            return await query.message.answer(
                f"❗ Подпишитесь на все указанные каналы:\n{channels_str}\n\n"
                f"Затем нажмите «Проверить подписку».",
                reply_markup=check_subscription_kb(topic_key)
            )



    # 2) Всё ок — удаляем сообщение с кнопкой «Проверить подписку»
    await query.message.delete()
    # 💬 Оповещаем об открытии доступа
    await query.message.answer("✅ Доступ к теме открыт!")
    data    = load_user_data()
    u       = data.setdefault(uid, {})

    # — добавляем тему в unlocked_topics
    unlocked = u.setdefault("unlocked_topics", [])
    if topic_key not in unlocked:
        unlocked.append(topic_key)

    # — добавляем новую сессию подписки
    for ch in required:
        sessions = u.setdefault("channels", {}).setdefault(ch, [])
        if not sessions or sessions[-1].get("unsubscribed_at") is not None:
            sessions.append({"subscribed_at": now, "unsubscribed_at": None})

    save_user_data(data)

    # 3) Возвращаемся в меню урока
    return await lesson_menu_handler(query.message, state)













@dp.callback_query(
    lambda c: c.data and c.data.split(":",1)[0] in 
        ("confirm_done","feedback_difficulty","offer_continue","refusal"),
    StateFilter(LessonStates.showing_vocab)
)
@track_handler
async def cb_scenario_vocab(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    scene = data["current_scene"]
    stage, choice = cb.data.split(":", 1)
    params = scene["replies"][choice]

    # 1) реакция
    if params.get("reaction"):
        await cb.message.edit_text(params["reaction"], parse_mode="HTML")
    # 2) пауза
    await asyncio.sleep(1.5)

    # 3) обработка по веткам — сначала confirm_done
    if stage == "confirm_done":
        next_stage = params["next"]
        if next_stage == "next_item":
            new_idx = data.get("vocab_index", 0) + 1
            await state.update_data(vocab_index=new_idx)
            return await send_one_vocab(cb.message, state)

        if next_stage == "feedback_difficulty":
            # 1) Собираем все link-блоки **текущей фазы**
            link_blocks = [b for b in get_vocab_list(data) if "link" in b or "url" in b]

            # 2) **Legacy-счётчик** (можно оставить, чтобы не сломать прочие места)
            passed = data.get("vocab_done", 0) + 1
            await state.update_data(vocab_done=passed, refusal_count=0)

            # 3) **Per-phase-счётчик**  
            phase_id    = data["selected_phase_id"]
            per_phase   = data.get("vocab_done_per_phase", {})
            phase_done  = per_phase.get(phase_id, 0) + 1
            per_phase[phase_id] = phase_done
            await state.update_data(vocab_done_per_phase=per_phase)

            # 4) Звёздочки по фазе
            stars = "⭐" * phase_done + "☆" * (len(link_blocks) - phase_done)
            await cb.message.edit_text(
                f"{stars} {phase_done}/{len(link_blocks)} выполнено!",
                parse_mode="HTML"
            )
            # — сама кнопка feedback_difficulty
            fb = random.choice(scenarios["feedback_difficulty"])
            await state.update_data(current_stage="feedback_difficulty", current_scene=fb)
            # 💬 Inline-кнопки “Оценка сложности” в одну строку
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text=btn, callback_data=f"feedback_difficulty:{btn}")
                    for btn in fb["buttons"]
                ]]
            )
            await asyncio.sleep(1)
            return await cb.message.edit_text(fb["text"], reply_markup=kb, parse_mode="HTML")

        if next_stage == "refusal":
            rf = random.choice(scenarios["refusal"])
            await state.update_data(current_stage="refusal", current_scene=rf)
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=btn, callback_data=f"refusal:{btn}")]
                    for btn in rf["buttons"]
                ]
            )
            return await cb.message.edit_text(rf["text"], reply_markup=kb, parse_mode="HTML")

    # 4) stage = feedback_difficulty → копируем логику handle_feedback_difficulty_vocab
    elif stage == "feedback_difficulty":
        # снимаем старую клавиатуру уже сделали выше через edit_text
        topic_key = data["selected_topic"]
        vocab_list = get_vocab_list(data)
        next_idx = data.get("vocab_index", 0) + 1

        # ➡️ если следующий блок — quiz или textquiz, пропускаем offer_continue
        if next_idx < len(vocab_list) and vocab_list[next_idx].get("type") in ("quiz","textquiz"):
            # эмоджи полиции + фраза перед квизом
            prefix = random.choice(["👮‍♂️","👮‍♀️","🚓"])
            await cb.message.answer(prefix)
            await asyncio.sleep(0.5)
            phrase = random.choice(vocab_quiz_intro_phrases)
            await cb.message.answer(phrase)
            await state.update_data(vocab_index=next_idx)
            return await send_one_vocab(cb.message, state)

        # иначе — inline-offer_continue
        oc = random.choice(scenarios["offer_continue"])
        await state.update_data(current_stage="offer_continue", current_scene=oc)
        # 💬 Inline-кнопки “Продолжить/Домой” в одну строку
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                for btn in oc["buttons"]
            ]]
        )
        return await cb.message.edit_text(oc["text"], reply_markup=kb, parse_mode="HTML")

    # 5) stage = offer_continue → копируем логику handle_offer_continue_vocab
    elif stage == "offer_continue":
        # Получаем параметры выбора
        params     = scene["replies"][choice]
        next_stage = params.get("next")

        # 1) Показываем реакцию (если есть)
        if params.get("reaction"):
            try:
                await cb.message.edit_text(params["reaction"], parse_mode="HTML")
            except TelegramBadRequest:
                pass

        # 2) Небольшая пауза для чтения реакции
        await asyncio.sleep(1.5)

        # 3) Убираем inline-кнопки
        try:
            await cb.message.edit_reply_markup()
        except TelegramBadRequest:
            pass

        # Переход по результату
        if next_stage == "next_item":
            # Можно добавить перед отправкой следующего элемента мотивирующую фразу/стикер
            new_idx = data.get("vocab_index", 0) + 1
            await state.update_data(vocab_index=new_idx, refusal_count=0)
            return await send_one_vocab(cb.message, state)
        if next_stage == "home":
            return await lesson_menu_handler(cb.message, state)


        # Фолбэк: отрисовать кнопки снова
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")]
                for btn in scene["buttons"]
            ]
        )
        return await cb.message.edit_text(scene["text"], reply_markup=kb, parse_mode="HTML")


    # 6) stage = refusal → копируем логику handle_refusal_vocab
    elif stage == "refusal":
        # 💬 Удаляем сообщение с кнопками, чтобы больше не пытаться редактировать одно и то же
        await cb.message.delete()
        # Небольшая пауза для UX
        await asyncio.sleep(0.5)
        # Повтор текущего элемента или возврат в меню
        if params.get("next") == "repeat_current":
            return await send_one_vocab(cb.message, state)
        if params.get("next") == "home":
            return await lesson_menu_handler(cb.message, state)



    # 7) всё прочее — домой
    return await lesson_menu_handler(cb.message, state)









#================================================================================
#   🚀 Запуск бота
# ================================================================================

if __name__ == '__main__':
    async def main():
        # 💬 Регистрируем команды бота (в меню Telegram: /start, /addtopic, /edittopic, /menu)
        # 💬 Обычному пользователю показываем только эти команды
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="menu",  description="Главное меню")
        ])


        print("🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀 Бот запущен!")
        await dp.start_polling(bot)

    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 💬 последние два хендлера
        curr = handler_history[-1] if handler_history else "unknown"
        prev = handler_history[-2] if len(handler_history) >= 2 else "none"
        # 💬 три последних кадра стека
        snippet = "".join(traceback.format_list(last_stack[-3:]))
        msg = (
            f"⏹️ Остановлено по KeyboardInterrupt\n"
            f"Last handler: {curr}\n"
            f"Previous: {prev}\n"
            f"Stack:\n```{snippet}```"
        )
        logging.info(msg)
        print(msg)
        sys.exit(0)

