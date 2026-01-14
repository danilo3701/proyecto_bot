# ProyectoBot/core8_1.py
# файл коры

# ================================================================================
# 🟡 Импорты и константы для core8_1.py
# ================================================================================

# ——— Standard library ——————————————————————————————————————————————
import os                           # Работа с файлами и папками

# ⛔ Проверка отключения бота через переменную
if (os.getenv("DISABLED") or "").strip().lower() == "true":
    print("🚫 DISABLED=true → бот не запускаем", flush=True)  # 💬 чтобы это точно попало в Railway logs
    raise SystemExit(0)

# 📦 Volume-папка (не даём деплою “упасть молча”)
try:
    os.makedirs("/data", exist_ok=True)  # 💬 создаём папку Volume, если ещё не создана
except Exception as e:
    print(f"⚠️ Не могу создать /data: {e}", flush=True)  # 💬 явный лог причины падения
    raise

from pathlib import Path  # 💬 чтобы строить путь к файлу надёжно

import json                         # Чтение/запись JSON-топиков
import random                       # Рандомизация (CTA-фразы, сценарии, стикеры)
import html                         # 💬 html.escape для безопасного HTML в Telegram
import asyncio                      # Асинхронные паузы (smart_reply)
import logging                      # Логирование для отладки
import math
import time
import datetime
import sys
import traceback
import re  # 💬 нужен для конвертации [[...]] → ||...||

# ——— Aiogram core ————————————————————————————————————————————————
from aiogram import Bot, Dispatcher, F                   # Bot/DP и фильтр F  
from aiogram.client.default import DefaultBotProperties  # Настройки бота (HTML по умолчанию)
from aiogram.filters import CommandStart, StateFilter
from aiogram.filters import Command # /start
from aiogram.types import ReactionTypeEmoji  # 💬 тип реакции-эмоджи для setMessageReaction
from aiogram.exceptions import TelegramBadRequest
from aiogram.exceptions import TelegramNetworkError  # 💬 ловим сетевые таймауты Telegram при отправке репортов
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
    BotCommand,
    ReactionTypeEmoji  # 💬 для реакций «🎉» на сообщение-квиз

)

# 💬 Уровни и медали для глобального прогресса
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
XP_PER_LEVEL = 3000  # XP, необходимое для перехода на следующий уровень
MEDALS = ["🥉", "🥈", "🥇"]  # бронза, серебро, золото


# 💬 Короткий прогресс по уровню для главного меню и Level-Up
def render_short_level_progress(user_id: int) -> str:
    """
    💬 Возвращает строку вида:
        🧭 Explorador A1: 1 de 5 ⭐️
        46% 🟩🟩🟩🟨⬜⬜⬜⬜⬜⬜
    Основано на глобальном total_xp из xp_data.json.
    """
    xp_data = load_xp_data()
    total_xp = xp_data.get(str(user_id), {}).get("total_xp", 0)

    # Текущий уровень по глобальному XP
    lvl_idx = total_xp // XP_PER_LEVEL if XP_PER_LEVEL else 0
    if lvl_idx >= len(LEVELS):
        lvl_idx = len(LEVELS) - 1
    level_code = LEVELS[lvl_idx]

    # Названия уровней (можно будет допилить/переименовать отдельно)
    level_titles = {
        "A1": "🧭 Explorador A1",
        "A2": "🧭 Explorador A2",
        "A0": "🧭 Уровень новичок",  # 💬 вместо A0 показываем новичок
        "B1": "🚀 Pro B1",
        "B2": "🚀 Pro B2",
        "C1": "🎓 Maestro C1",
        "C2": "🎓 Maestro C2",
    }
    title = level_titles.get(level_code, f"🧭 Explorador {level_code}")

    # 5 ступенек внутри одного уровня
    STEPS_PER_LEVEL = 5
    xp_in_level = total_xp % XP_PER_LEVEL if XP_PER_LEVEL else 0

    if XP_PER_LEVEL:
        step_idx = min(
            xp_in_level * STEPS_PER_LEVEL // XP_PER_LEVEL,
            STEPS_PER_LEVEL - 1,
        )
        percent = int(xp_in_level * 100 / XP_PER_LEVEL)
    else:
        step_idx = 0
        percent = 0

    step_num = step_idx + 1  # от 1 до 5
    # 💬 прогресс-бар из 20 сегментов (5% за сегмент) + минимум 1 сегмент по умолчанию
    display_percent = int(percent)
    if display_percent <= 0:
        display_percent = 5  # 💬 по дефолту показываем 1 заполненный сегмент (5%)
    if display_percent > 100:
        display_percent = 100  # 💬 защита от некорректных значений

    bar = render_bar(display_percent, length=20)
    return f"{title}: {step_num} de {STEPS_PER_LEVEL} ⭐️\n{bar} {display_percent}%"




# 💬 минимальная задержка между удалением старого и показом нового квиза
QUIZ_NEXT_DELAY = 0.35  # секунды; можно уменьшать до 0.25, но ниже 0.2 риск флуд-лимитов


def check_subscription_kb(topic_key: str, channels: list[str]) -> InlineKeyboardMarkup:
    """
    💬 Инлайн-клавиатура для блока «Рекламная подписка».
    - по одной URL-кнопке на каждый канал из списка `channels`
    - ниже кнопка «✅ Проверить подписку»
    - ещё ниже кнопка «⬅️ Назад» в меню
    """
    rows: list[list[InlineKeyboardButton]] = []

    # 💬 Кнопки-ссылки на каналы
    for ch in channels:
        if not ch:
            continue
        username = ch.lstrip("@")
        rows.append([
            InlineKeyboardButton(
                text=ch,
                url=f"https://t.me/{username}",  # 💬 переход на канал
            )
        ])

    # 💬 Кнопка проверки подписки
    rows.append([
        InlineKeyboardButton(
            text="✅ Проверить подписку",
            callback_data=f"check_subscription:{topic_key}",
        )
    ])

    # 💬 Кнопка «Назад»
    rows.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_topics",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)




SUBSCRIPTION_CHANNELS_PATH = "subscription_channels.json"

AD_SUBSCRIPTION_DAYS = 3  # 💬 срок действия рекламной подписки (в днях)

# 💬 ссылки для кнопок в главном меню
MATERIALS_POST_URL = "https://t.me/+TOHEAq_otQY5MWE0"  # 💬 ссылка на конкретный пост с материалами
CONTACT_URL = "https://t.me/Drancherrro"            # 💬 ссылка на твой личный контакт


def is_ad_subscription_active(user_id: int) -> bool:
    # 💬 Проверяем, есть ли у пользователя активная рекламная подписка
    data = load_user_data()
    user = data.get(str(user_id), {})
    ad = user.get("ad_subscription") or {}
    now = int(time.time())
    return ad.get("active_until", 0) > now

def load_subscription_channels():
    if not os.path.exists(SUBSCRIPTION_CHANNELS_PATH):
        with open(SUBSCRIPTION_CHANNELS_PATH, "w", encoding="utf-8") as f:
            json.dump({"channels": []}, f, ensure_ascii=False, indent=2)
    with open(SUBSCRIPTION_CHANNELS_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("channels", [])


from aiogram.enums import ChatAction                    # Анимация “печатает…”
from aiogram.fsm.state import State, StatesGroup        # FSM: описываем состояния
from aiogram.fsm.context import FSMContext              # FSM: доступ к state.data
from aiogram.fsm.storage.memory import MemoryStorage    # Хранение FSM в памяти

# ——— Роутеры админки ————————————————————————————————————————————
from create_lesson_block import router as create_topic_router  # 💬 админский flow тем (всё редактирование тут)

# ——— Загрузка тем (ТОЛЬКО Railway Volume: /data/topics) ———————————
from pathlib import Path  # 💬 путь к Volume

def get_topics_dir() -> Path:
    return Path(os.getenv("TOPICS_DIR", "/data/topics"))  # 💬 берём темы из Railway Volume

def load_topics_from_volume() -> dict:
    topics_dir = get_topics_dir()
    topics_dir.mkdir(parents=True, exist_ok=True)  # 💬 гарантируем папку /data/topics
    loaded = {}
    for p in topics_dir.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            continue
        key = data.get("title") or p.stem  # 💬 ключ темы
        loaded[key] = data
    return loaded

def load_topics_from_railway() -> dict:
    return load_topics_from_volume()  # 💬 совместимость со старым названием

def load_topics() -> dict:
    return load_topics_from_volume()  # 💬 совместимость с create_lesson_block (reload)
    
def sync_topics_volume_to_local() -> None:
    return None  # 💬 GitHub/Local sync отключён, чтобы не было NameError


from battle_feature import router as battle_router, set_topics_ref, start_battle_from_lex_menu, set_battle_links, cancel_battle_if_running  # 💬 модуль "Битва"
from bonuses_feature import (
    router as bonuses_router,
    init_bonus_feature,
    bonuses_open,
    bonus_register_referral_from_start,
    bonus_try_qualify_referral,
)  # 💬 модуль «🎁 Бонусы»
from podcasts_feature import router as podcasts_router, init_podcasts_feature, podcasts_open  # 💬 модуль "Подкасты"
from grammar_feature import router as grammar_router, init_grammar_feature, set_topics_ref as set_grammar_topics_ref, open_grammar_topic  # 💬 модуль "Грамматика"


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
    start_stickers,
    menu_study_phrases,
    difficulty_intro_phrases,
    vocab_start_phrases,         # Вступительные фразы для потока «Учить слова»
    vocab_return_phrases,        # Фразы возвращения в поток  «Учить слова»
    vocab_quiz_intro_phrases,    # Фразы для введения в квиз после словаря
    vocab_quiz_progress_phrases, # 💬 фразы для закреплённого прогресса poll-квизов
    go_next_phrases
)

from scenario.quiz_reactions import vocab_quiz_success_phrases  # 💬 централизованные позитивные реакции квиза

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
BOT_TOKEN = "7267599701:AAG4duS6_2R8PFpoUzroIY1M5ib1OWw8o6s"  
bot        = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp         = Dispatcher(storage=MemoryStorage())  


# 💬 фиксим business_connection_id: aiogram ожидает str, иногда прилетает int (chat_id/user_id)
def _coerce_bcid(kwargs: dict) -> None:
    bcid = kwargs.get("business_connection_id")
    if bcid is not None and not isinstance(bcid, str):
        kwargs["business_connection_id"] = str(bcid)  # 💬 приводим к строке, чтобы не падал Pydantic

def _wrap_bot_method(_bot: Bot, method_name: str) -> None:
    orig = getattr(_bot, method_name, None)
    if orig is None:
        return

    async def wrapped(*args, **kwargs):
        _coerce_bcid(kwargs)  # 💬 защищаем любые edit_* от int business_connection_id
        return await orig(*args, **kwargs)

    setattr(_bot, method_name, wrapped)

# 💬 ставим один раз, чтобы не было двойной обёртки при перезагрузках
if not getattr(bot, "_bcid_fix_installed", False):
    for _m in ("edit_message_reply_markup", "edit_message_text", "edit_message_caption", "edit_message_media"):
        _wrap_bot_method(bot, _m)
    bot._bcid_fix_installed = True  # 💬 маркер установки фикса









# ——— Подключаем админские роутеры ————————————————————————————————
dp.include_router(battle_router)  # 💬 подключаем хендлеры "Битвы"
dp.include_router(bonuses_router)  # 💬 подключаем хендлеры «Бонусы»
dp.include_router(podcasts_router)  # 💬 подключаем модуль "Подкасты"
dp.include_router(create_topic_router)
dp.include_router(grammar_router)  # 💬 подключаем грамматику

# ——— Загружаем уроки (ТОЛЬКО /data/topics) ———————————————————————
topics = load_topics_from_volume()  # 💬 стартовая загрузка тем из Railway Volume


def load_topics_from_volume() -> dict:
    # 💬 что делает эта часть: читаем темы только из Railway Volume (/data/topics), без копирования в ./topics и без GitHub
    topics_dir = "/data/topics"
    os.makedirs(topics_dir, exist_ok=True)

    loaded = {}
    for fn in os.listdir(topics_dir):
        if not fn.lower().endswith(".json"):
            continue

        path = os.path.join(topics_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            key = (data or {}).get("title") or os.path.splitext(fn)[0]
            if key:
                loaded[key] = data
        except Exception as e:
            logging.exception("load_topics_from_volume: failed %s: %s", path, e)

    return loaded


topics = topics = load_topics_from_volume()  # 💬 грузим темы только из Railway Volume (/data/topics)

# 💬 что делает эта часть: topics уже взяли из Volume, локальные ./topics и GitHub не используем
set_grammar_topics_ref(topics)  # 💬 передаём topics в модуль грамматики
set_topics_ref(topics)          # 💬 передаём topics в модуль "Битва" без круговых импортов





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
        # 💬 сохраняем имя хендлера (без дубля, если уже записали в middleware)
        added = False
        if not handler_history or handler_history[-1] != func.__name__:
            handler_history.append(func.__name__)
            added = True

        # 💬 аналитика: последний хендлер + (если есть) тема и state из FSM
        try:
            if added:
                # 💬 если middleware уже записал контекст = не дублируем запись
                user_id = None

                # 💬 пытаемся вытащить пользователя из args/kwargs
                for v in list(kwargs.values()) + list(args):
                    if getattr(v, "from_user", None):
                        user_id = str(v.from_user.id)
                        break

                if user_id:
                    st = kwargs.get("state")
                    topic_key = None
                    state_name = None
                    if st:
                        try:
                            st_data = await st.get_data()
                            topic_key = st_data.get("selected_topic")
                            state_name = await st.get_state()
                        except Exception:
                            pass

                    analytics_set_last_context(
                        user_id=user_id,
                        handler_name=func.__name__,
                        topic_key=topic_key,
                        state_name=state_name
                    )  # 💬 пишем last context только один раз
        except Exception:
            logging.exception("track_handler: analytics last context failed")  # 💬 логируем только реальные сбои


        # 💬 убираем лишний аргумент 'dispatcher'
        kwargs.pop('dispatcher', None)
        # 💬 фильтруем kwargs по сигнатуре func
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return await func(*args, **filtered)
    return wrapper

ADMIN_CHAT_ID = 930240763  # ваш Chat ID

class LoggingMiddleware(BaseMiddleware):
    # 💬 Глобальный перехват голосовых + логирование ошибок для всех апдейтов
    async def __call__(self, handler, event, data):


        # 💬 аналитика: фиксируем активность (first/last/clicks) на каждый апдейт
        try:
            if getattr(event, "from_user", None):
                if isinstance(event, CallbackQuery):
                    analytics_touch_daily(event.from_user, "callback")
                elif isinstance(event, Message):
                    analytics_touch_daily(event.from_user, "message")
                else:
                    analytics_touch_daily(event.from_user, event.__class__.__name__)
        except Exception:
            logging.exception("LoggingMiddleware: analytics touch failed")

        # ⚠️ Любой voice/не-текст останавливаем до хендлеров
        if isinstance(event, Message) and getattr(event, "voice", None):
            await event.answer("⚠️ Голосовые сообщения пока не поддерживаются. Пришли текст или нажми кнопку ниже.")
            return
        # 💬 фиксируем текущий хендлер ДО выполнения (работает для роутеров из других файлов тоже)
        try:
            global last_stack
            last_stack = traceback.extract_stack()[:-1]  # 💬 чтобы видеть стек перед падением

            handler_name = getattr(handler, "__name__", handler.__class__.__name__)
            if not handler_history or handler_history[-1] != handler_name:
                handler_history.append(handler_name)  # 💬 сохраняем реальный хендлер (curr/prev)

            if getattr(event, "from_user", None):
                st = data.get("state")
                topic_key = None
                state_name = None

                if st:
                    try:
                        st_data = await st.get_data()
                        topic_key = st_data.get("selected_topic")
                        state_name = await st.get_state()
                    except Exception:
                        pass

                analytics_set_last_context(
                    user_id=str(event.from_user.id),
                    handler_name=handler_name,
                    topic_key=topic_key,
                    state_name=state_name
                )  # 💬 сохраняем last context в xp_data.json
        except Exception:
            logging.exception("LoggingMiddleware: track handler failed")


        try:
            return await handler(event, data)
        except Exception as err:
            # 💬 берём последние два имени из handler_history
            curr = handler_history[-1] if handler_history else "unknown"
            prev = handler_history[-2] if len(handler_history) >= 2 else "none"

            # 💬 тема из FSM (если есть) = но показываем только если реально известна
            topic_key = None
            topic_name = None
            st = data.get("state")
            if st:
                try:
                    st_data = await st.get_data()
                    tk = st_data.get("selected_topic")
                    if tk and tk != "unknown":
                        info = topics.get(tk, {}) if isinstance(topics, dict) else {}
                        tn = info.get("title") or info.get("name") or tk
                        if tn and tn != "unknown":
                            topic_key = tk
                            topic_name = tn
                except Exception:
                    pass

            # 💬 ник админа берём из CONTACT_URL (https://t.me/Drancherrro) = получится @Drancherrro
            admin_nick = "@admin"
            try:
                if isinstance(CONTACT_URL, str) and "t.me/" in CONTACT_URL:
                    admin_nick = "@" + CONTACT_URL.rstrip("/").split("/")[-1]
            except Exception:
                pass

            # 1) 💬 сообщение админу
            admin_lines = [
                "🔴 Ошибка",
                f"Где = `{curr}`",
                f"Пред = `{prev}`",
            ]
            if topic_key and topic_name:
                admin_lines.append(f"Тема = `{topic_name}` ({topic_key})")
            admin_lines.append(f"Тип = `{err.__class__.__name__}`")
            admin_text = "\n".join(admin_lines)

            try:
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    admin_text,
                    request_timeout=120
                )  # 💬 увеличиваем таймаут, чтобы не падать на сетевых лагов Telegram
            except (TelegramBadRequest, TelegramNetworkError, asyncio.TimeoutError):
                pass  # 💬 если Telegram тупит/таймаутит = не роняем бота из-за репорта админу


            # 2) 💬 сообщение пользователю + кнопка связи (и гасим “loading…” у callback)
            try:
                chat_id = None

                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("⚠️ Ошибка. Нажми /start.", show_alert=False)
                    except Exception:
                        pass
                    if event.message:
                        chat_id = event.message.chat.id

                elif isinstance(event, Message):
                    chat_id = event.chat.id

                # fallback на случай других типов event
                if not chat_id and getattr(event, "chat", None):
                    chat_id = getattr(event.chat, "id", None)

                if chat_id:
                    report_lines = [
                        "⚠️ Упс, произошла ошибка",
                        "",
                        "<pre>",
                        f"Где = {curr}",
                        f"Пред = {prev}",
                    ]
                    if topic_key and topic_name:
                        report_lines.append(f"Тема = {topic_name} ({topic_key})")
                    report_lines += [
                        "</pre>",
                        "",
                        "Что делать",
                        "1) Нажми /start",
                        f"2) Если повторится = нажми кнопку ниже и отправь админу блок выше ({admin_nick})",
                    ]

                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="✉️ Сообщить админу", url=CONTACT_URL)]
                        ]
                    )

                    await bot.send_message(chat_id, "\n".join(report_lines), reply_markup=kb)

            except Exception:
                pass

            raise



# 💬 Регистрируем Middleware
dp.update.middleware.register(LoggingMiddleware())


def _get_vocab_phase(topic_key: str, phase_id: str) -> dict:
    topic_data = topics.get(topic_key, {})
    phases = topic_data.get("vocab", [])
    return next((p for p in phases if p.get("phase_id") == phase_id), {}) or {}


def _get_active_phrase_indexes(phrases: list, hidden: set) -> list:
    return [i for i in range(len(phrases)) if i not in hidden]


def get_vocab_list(data: dict) -> list:
    """
    💬 Логика:
      1) Если есть lex_session_vocab_list в state = используем её (ALL IN раунды)
      2) Если фаза содержит phrases = показываем base-блоки фазы + спец-блок phrase_selector
      3) Иначе = старая логика "link → 6 quiz" + потом textquiz_pool
    """
    # 0) ALL IN: если уже собрана сессия раунда = возвращаем её
    lex_session = data.get("lex_session_vocab_list")

    # 💬 что делает эта часть: если режим раунда активирован = отдаём сессию даже если она пустая,
    # чтобы не вернуться обратно к phrase_selector и не зациклиться
    if isinstance(lex_session, list) and (lex_session or data.get("lex_mode_active")):
        return lex_session


    topic_key = data.get("selected_topic")
    topic     = topics.get(topic_key, {})
    ph_id     = data.get("selected_phase_id")

    # legacy: без фазы — как раньше
    if not ph_id:
        return topic.get("vocab", [])

    # берём фазу по её ID (фазы лежат в topic["vocab"] как блоки с phase_id)
    phase = next((ph for ph in topic.get("vocab", []) if ph.get("phase_id") == ph_id), None)
    if not phase:
        return []

    # 1) ALL IN: если в фазе есть phrases = сначала база, потом selector, а квизы соберём после выбора
    if isinstance(phase.get("phrases"), list) and phase.get("phrases"):
        base = list(phase.get("vocab", []))  # 💬 link/text/photo и т п
        base.append({"type": "phrase_selector"})  # 💬 спец-блок: выбор известных фраз
        return base

    # 2) Старый режим quiz_pool/textquiz_pool отключён для VOCAB
    # 💬 что делает эта часть: возвращаем только базовые блоки фазы без автосборки пакетов
    return list(phase.get("vocab", []))


def _lex_get_selected_phase(data: dict) -> dict | None:
    # 💬 что делает эта часть: достаём текущую фазу из topics по selected_topic + selected_phase_id
    topic_key = data.get("selected_topic")
    topic = topics.get(topic_key, {})
    ph_id = data.get("selected_phase_id")
    if not ph_id:
        return None
    return next((ph for ph in topic.get("vocab", []) if ph.get("phase_id") == ph_id), None)


def _lex_render_phrase_list(phrases: list) -> str:
    # 💬 что делает эта часть: рисуем разминку перед квизами = жирный заголовок + жирный italic список + italic подсказки
    lines = ["🧠<b>Разминка перед квизами</b>", ""]  # 💬 пустая строка после заголовка

    if not phrases:
        lines.append("<i>Фраз не осталось</i>")
        return "\n".join(lines)

    for i, ph in enumerate(phrases, start=1):
        es = (ph.get("es") or "").strip()
        ru = (ph.get("ru") or "").strip()
        if not es and not ru:
            continue
        lines.append(f"<b><i>{i}. {es} = {ru}</i></b>")

    lines.append("")  # 💬 пустая строка перед инструкцией
    lines.append("<i>✍🏽 Пришли в чат номер тех фраз, которые тебе скучны</i>")
    lines.append("<i>🗑 Они удалятся автоматически</i>")
    return "\n".join(lines)



def _lex_pick_round_item(seq, round_idx: int):
    # 💬 что делает эта часть: безопасно берём элемент раунда (list или dict ключи 1..4)
    if isinstance(seq, list):
        return seq[round_idx] if 0 <= round_idx < len(seq) else None
    if isinstance(seq, dict):
        return seq.get(str(round_idx + 1)) or seq.get(round_idx) or None
    return None


def _lex_get_poll_round(phrase: dict, round_idx: int) -> dict | None:
    # 💬 что делает эта часть: достаём poll-quiz текущего раунда из phrase
    polls = (
        phrase.get("polls")
        or phrase.get("pulls")
        or phrase.get("pullquiz")
        or phrase.get("pull_quizzes")
        or phrase.get("poll_quiz")
        or phrase.get("poll_quizzes")
        or phrase.get("quiz_rounds")
        or []
    )  # 💬 поддерживаем старые ключи, чтобы старые темы тоже показывали квизы

    item = _lex_pick_round_item(polls, round_idx)
    if isinstance(item, dict):
        out = dict(item)
        out["type"] = "quiz"
        return out
    return None


def _lex_get_textquiz_first(phrase: dict) -> dict | None:
    # 💬 что делает эта часть: забираем 1-й textquiz из фразы и нормализуем ключ correct_answer
    tqs = phrase.get("textquizzes") or phrase.get("textquiz") or phrase.get("text_quiz") or []
    out = None

    if isinstance(tqs, list) and tqs and isinstance(tqs[0], dict):
        out = dict(tqs[0])
    elif isinstance(tqs, dict):
        out = dict(tqs)

    if not out:
        return None

    out["type"] = "textquiz"

    # 💬 совместимость с ALL IN: answer -> correct_answer (handle_vocab_textquiz_answer читает correct_answer/correct_answers)
    if "correct_answer" not in out and "answer" in out:
        out["correct_answer"] = out.get("answer") or ""

    return out



def _lex_detect_total_rounds(phrases: list, default_total: int = 4) -> int:
    # 💬 что делает эта часть: определяем сколько раундов реально есть (если где то меньше 4)
    mx = 0
    for ph in phrases:
        polls = ph.get("polls") or ph.get("pulls") or ph.get("pull_quizzes") or ph.get("poll_quizzes") or ph.get("quiz_rounds")
        if isinstance(polls, list):
            mx = max(mx, len(polls))
        elif isinstance(polls, dict):
            mx = max(mx, len(polls.keys()))
    return mx if mx > 0 else default_total


async def _lex_prepare_round_session(state: FSMContext, round_idx: int):
    # 💬 что делает эта часть: собираем lex_session_vocab_list = N poll-quiz (по фразам) + 1 textquiz (по очереди)
    data = await state.get_data()
    phrases = data.get("lex_active_phrases") or []
    if not isinstance(phrases, list):
        phrases = []

    total_rounds = data.get("lex_round_total") or _lex_detect_total_rounds(phrases, default_total=4)
    cursor = data.get("lex_textquiz_phrase_cursor", 0)

    session = []
    for ph in phrases:
        poll_block = _lex_get_poll_round(ph, round_idx)
        if poll_block:
            session.append(poll_block)

    # 1 textquiz после сета (по очереди по фразам)
    if 0 <= cursor < len(phrases):
        tq = _lex_get_textquiz_first(phrases[cursor])
        if tq:
            session.append(tq)
        cursor += 1

    quiz_count = sum(1 for b in session if b.get("type") == "quiz")

    await state.update_data(
        lex_mode_active=True,
        lex_round=round_idx,
        lex_round_total=total_rounds,
        lex_textquiz_phrase_cursor=cursor,
        lex_session_vocab_list=session,
        lex_round_block_size=quiz_count,

        # сброс сетовой механики под новый раунд
        vocab_index=0,
        redo_stack=[],
        redo_active=False,
        refusal_count=0,
        pending_textquiz=[],
        lex_textquiz_done_round=False,
        last_main_quiz_index=-1,
        vocab_set_anchor=0,
        current_poll_id=None,
        current_poll_correct=None,
        failed_vocab=[],
        failed_textquiz=[]
    )



import os

XP_DATA_PATH = "/data/xp_data.json"

XP_DATA_PATH = "/data/xp_data.json"
XP_DATA_BACKUP_PATH = "/data/xp_data_backup.json"  # 💬 резерв: спасает рейтинг, если основной файл сломался

def _atomic_json_dump(path: str, data: dict):
    # 💬 атомарная запись: сначала temp, потом replace (не будет "битого" JSON)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

def load_xp_data():
    # 💬 грузим XP; если файл пропал/битый — восстанавливаем из backup, чтобы рейтинг не "обнулялся"
    if not os.path.exists(XP_DATA_PATH):
        # если основного нет, но есть backup — восстановим
        if os.path.exists(XP_DATA_BACKUP_PATH):
            try:
                with open(XP_DATA_BACKUP_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _atomic_json_dump(XP_DATA_PATH, data)
                return data
            except Exception:
                logging.exception("load_xp_data: backup restore failed")
        _atomic_json_dump(XP_DATA_PATH, {})
        return {}

    try:
        with open(XP_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # если JSON сломался — пробуем поднять из backup
        try:
            if os.path.exists(XP_DATA_BACKUP_PATH):
                with open(XP_DATA_BACKUP_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _atomic_json_dump(XP_DATA_PATH, data)
                return data
        except Exception:
            logging.exception("load_xp_data: failed to restore from backup")
        return {}

def save_xp_data(xp_data):
    # 💬 сохраняем атомарно + пишем backup (чтобы redeploy/сбой не "стёр" рейтинг)
    _atomic_json_dump(XP_DATA_PATH, xp_data)
    _atomic_json_dump(XP_DATA_BACKUP_PATH, xp_data)





def reset_daily_words_if_needed(user_data):
    """
    💬 Если дата не сегодня — сбрасываем счетчик words_learned_today и обновляем дату.
    """
    today = datetime.date.today().isoformat()
    if user_data.get("words_today_date") != today:
        user_data["words_learned_today"] = 0
        user_data["words_today_date"] = today


def migrate_runtime_files_to_volume():
    # 💬 переносим данные из контейнера в Volume (один раз) + синхронизируем topics
    try:
        if not os.path.exists(XP_DATA_PATH) and os.path.exists("xp_data.json"):
            with open("xp_data.json", "rb") as src, open(XP_DATA_PATH, "wb") as dst:
                dst.write(src.read())

        if not os.path.exists(USER_DATA_PATH) and os.path.exists("user_data.json"):
            with open("user_data.json", "rb") as src, open(USER_DATA_PATH, "wb") as dst:
                dst.write(src.read())

        # 💬 гарантируем наличие папки тем в Railway Volume; GitHub ./topics не трогаем
        os.makedirs("/data/topics", exist_ok=True)

        # 💬 синхронизируем темы строго из Railway Volume в локальную ./topics, чтобы load_topics() их видел
        volume_topics_dir = "/data/topics"
        local_topics_dir = "topics"

        os.makedirs(volume_topics_dir, exist_ok=True)
        os.makedirs(local_topics_dir, exist_ok=True)

        # 💬 безопасно: если в Volume пока пусто, не трогаем локальные темы
        volume_files = [f for f in os.listdir(volume_topics_dir) if f.endswith(".json")]
        if volume_files:
            # 💬 убираем локальные json которых нет в Volume, чтобы не подмешивались GitHub темы
            try:
                local_files = [f for f in os.listdir(local_topics_dir) if f.endswith(".json")]
                volume_set = set(volume_files)
                for fname in local_files:
                    if fname not in volume_set:
                        try:
                            os.remove(os.path.join(local_topics_dir, fname))
                        except OSError:
                            pass
            except Exception:
                logging.exception("migrate_runtime_files_to_volume: local topics cleanup failed")

            # 💬 копируем из Volume в локал, обновляем если в Volume версия новее
            for fname in volume_files:
                src = os.path.join(volume_topics_dir, fname)
                dst = os.path.join(local_topics_dir, fname)

                need_copy = not os.path.exists(dst)
                if not need_copy:
                    try:
                        need_copy = os.path.getmtime(src) > os.path.getmtime(dst)
                    except OSError:
                        need_copy = True

                if need_copy:
                    with open(src, "rb") as s, open(dst, "wb") as d:
                        d.write(s.read())  # 💬 локальный кэш темы становится копией Railway Volume


    except Exception:
        logging.exception("migrate_runtime_files_to_volume failed")



def _analytics_purge_days(days: dict, keep_days: int = 30) -> dict:
    # 💬 оставляем только последние keep_days дат формата YYYY-MM-DD
    if not isinstance(days, dict):
        return {}
    keys = sorted(days.keys())
    if len(keys) <= keep_days:
        return days
    to_drop = keys[:-keep_days]
    for k in to_drop:
        days.pop(k, None)
    return days


def analytics_touch_daily(from_user: User, event_type: str):
    # 💬 фиксируем first/last/clicks за день + обновляем имя/username в xp_data.json
    try:
        uid = str(from_user.id)
        ts = int(time.time())
        today = datetime.date.today().isoformat()

        xp_data = load_xp_data()
        user = xp_data.get(uid, {})

        # базовые поля (на случай если /start не проходили)
        if not user.get("first_join"):
            user["first_join"] = ts
        user["last_active"] = ts

        if not user.get("name"):
            user["name"] = from_user.full_name or ""

        tg_username = ("@" + from_user.username) if getattr(from_user, "username", None) else ""
        if tg_username and user.get("tg_username") != tg_username:
            user["tg_username"] = tg_username

        analytics = user.get("analytics", {})
        days = analytics.get("days", {})

        dayrec = days.get(today, {})
        if "first_ts" not in dayrec:
            dayrec["first_ts"] = ts
        dayrec["last_ts"] = ts
        dayrec["clicks"] = dayrec.get("clicks", 0) + 1
        dayrec["last_event_type"] = event_type

        days[today] = dayrec
        analytics["days"] = _analytics_purge_days(days, keep_days=30)
        user["analytics"] = analytics

        xp_data[uid] = user
        save_xp_data(xp_data)

    except Exception:
        logging.exception("analytics_touch_daily: failed")


def analytics_set_last_context(user_id: str, handler_name: str, topic_key: str = None, state_name: str = None):
    # 💬 сохраняем где пользователь был последний раз (хендлер/тема/state)
    try:
        ts = int(time.time())
        xp_data = load_xp_data()
        user = xp_data.get(user_id, {})
        analytics = user.get("analytics", {})
        last = analytics.get("last", {})

        last["ts"] = ts
        last["handler"] = handler_name
        if topic_key:
            last["topic_key"] = topic_key
        if state_name:
            last["state"] = state_name

        analytics["last"] = last
        user["analytics"] = analytics
        xp_data[user_id] = user
        save_xp_data(xp_data)

    except Exception:
        logging.exception("analytics_set_last_context: failed")



# 💬 USER DATA: сохраняем, какие темы разблокированы, и подписки на каналы
USER_DATA_PATH = "/data/user_data.json"  # 💬 данные хранятся в Railway Volume и не теряются при redeploy
USER_DATA_BACKUP_PATH = "/data/user_data_backup.json"  # 💬 резерв, чтобы настройки не "слетали"


# 💬 MY WORDS: пользовательские слова и категории (Railway Volume)
MY_WORDS_PATH = "/data/my_words.json"  # 💬 файл пользовательских слов
MY_WORDS_BACKUP_PATH = "/data/my_words_backup.json"  # 💬 резерв, чтобы не потерять слова

def load_my_words_data() -> dict:
    # 💬 грузим my_words; если файла нет или он битый = создаём пустой или восстанавливаем из backup
    if not os.path.exists(MY_WORDS_PATH):
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

    try:
        with open(MY_WORDS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 💬 если основной файл битый = пробуем восстановить из backup
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
    # 💬 сохраняем атомарно + backup
    _atomic_json_dump(MY_WORDS_PATH, data)
    _atomic_json_dump(MY_WORDS_BACKUP_PATH, data)

def ensure_my_words_user(data: dict, user_id: str) -> dict:
    # 💬 создаём структуру пользователя, если её ещё нет
    users = data.setdefault("users", {})
    u = users.setdefault(user_id, {})
    u.setdefault("settings", {"session_words": 5})
    u.setdefault("categories", {})
    return u

def parse_es_ru_pair(raw: str):
    # 💬 парсим строку формата ES - RU (делим по первому дефису, принимаем разные тире)
    if not raw:
        return None, None

    raw = raw.replace("—", "-").replace("–", "-").replace("−", "-")  # 💬 нормализуем тире
    if "-" not in raw:
        return None, None

    left, right = raw.split("-", 1)  # 💬 делим по первому "-"
    es = left.strip()
    ru = right.strip()
    if not es or not ru:
        return None, None
    return es, ru


def gen_my_word_id() -> str:
    # 💬 простой уникальный id для слов (нужен при дубликатах ES)
    return f"{int(time.time()*1000)}_{random.randint(1000, 9999)}"

def load_user_data():
    # 💬 грузим user_data; если файл пропал/битый — восстанавливаем из backup
    if not os.path.exists(USER_DATA_PATH):
        if os.path.exists(USER_DATA_BACKUP_PATH):
            try:
                with open(USER_DATA_BACKUP_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _atomic_json_dump(USER_DATA_PATH, data)
                return data
            except Exception:
                logging.exception("load_user_data: backup restore failed")
        _atomic_json_dump(USER_DATA_PATH, {})
        return {}

    try:
        with open(USER_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            if os.path.exists(USER_DATA_BACKUP_PATH):
                with open(USER_DATA_BACKUP_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _atomic_json_dump(USER_DATA_PATH, data)
                return data
        except Exception:
            logging.exception("load_user_data: failed to restore from backup")
        return {}

def save_user_data(data):
    # 💬 сохраняем атомарно + backup
    _atomic_json_dump(USER_DATA_PATH, data)
    _atomic_json_dump(USER_DATA_BACKUP_PATH, data)




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
        # 💬 Авто-инициализация пользователя, если его ещё нет в xp_data.json
        user = {
            "total_xp": 0,
            "by_topic": {},
            "stats": {"words_learned": 0, "exercises_done": 0},
            "first_join": int(time.time()),
        }

    reset_daily_words_if_needed(user)  # 💬 Сбросить/обновить дату, если нужно

    # 1. Общий XP
    if amount > 0:
        user["total_xp"] = user.get("total_xp", 0) + amount  # 💬 total_xp никогда не уменьшаем
    else:
        user["total_xp"] = user.get("total_xp", 0)  # 💬 минусы не трогают общий XP

    # 2. По теме
    if "by_topic" not in user:
        user["by_topic"] = {}

    cur_topic_xp = user["by_topic"].get(topic, 0)
    user["by_topic"][topic] = max(0, cur_topic_xp + amount)  # 💬 штрафы режут только topic_xp, но не ниже 0


    # 3. words_learned сегодня + лимит
    if action == "words_learned":
        # 💬 daily-limit учитываем только в xp_data, вывод в меню делается отдельно
        limit = user.get("words_daily_limit", 10)

        if user.get("words_learned_today", 0) < limit:
            user["words_learned_today"] = user.get("words_learned_today", 0) + 1  # 💬 +1 сегодня (если не превышен лимит)

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

        # 💬 Глобальная статистика: общий счётчик выученных слов (для отчётов/лимитов в сессии)
        if "stats" not in user:
            user["stats"] = {"words_learned": 0, "exercises_done": 0}
        user["stats"]["words_learned"] = user["stats"].get("words_learned", 0) + 1  # 🍪 +1

        # 💬 аналитика: слова по темам (чтобы понимать, какие темы реально учат)
        analytics = user.get("analytics", {})
        topics_words = analytics.get("topics_words", {})
        if isinstance(topics_words, dict):
            topics_words[topic] = topics_words.get(topic, 0) + 1
        analytics["topics_words"] = topics_words
        user["analytics"] = analytics




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



# ======================================================================
# 🔒 Блок 3: FSM-состояния (StatesGroup)
# ======================================================================



class LessonStates(StatesGroup):
    # 🏁 Начальные шаги: выбор категории и темы
    waiting_subscription = State()  # ожидание проверки подписки на канал(ы)
    choosing_category     = State()  # после /start — ждем «📚 Лексика» или «🧠 Грамматика»
    choosing_level        = State()  # 💬 состояние для выбора уровня после выбора категории
    choosing_subcategory  = State()  # 💬 выбор «Лексика / Грамматика» внутри уровня
    choosing_topic        = State()  # после выбора категории — ждем тему
    waiting_lesson_action = State()  # главное меню: Учить слова/Делать упражнения/…
    waiting_vocab_phase   = State()   # выбор фазы перед показом словаря
    # 🧩 Мои слова (пользовательские категории)
    mywords_menu                 = State()  # меню «Мои слова»
    mywords_settings_wait        = State()  # ввод числа session_words

    mywords_add_choose_category  = State()  # выбор категории для добавления
    mywords_add_new_category     = State()  # ввод названия новой категории
    mywords_add_input_pair       = State()  # ввод ES - RU
    mywords_add_confirm          = State()  # подтверждение сохранения пары

    mywords_edit_choose_category = State()  # выбор категории для редактирования
    mywords_edit_menu            = State()  # меню редактирования выбранной категории
    mywords_edit_delete_wait     = State()  # ввод индекса для удаления
    mywords_edit_edit_index_wait = State()  # ввод индекса для изменения
    mywords_edit_edit_pair_wait  = State()  # ввод новой пары ES - RU
    mywords_edit_rename_wait     = State()  # ввод нового названия категории

    mywords_learn_choose_cat     = State()  # выбор категории для обучения/повтора
    mywords_quiz                 = State()  # стадия quiz RU=>ES (poll)
    mywords_text                 = State()  # стадия text RU=>ES (ввод текста)
    mywords_offer_continue       = State()  # пауза: продолжить или домой



    # 📚 Поток «Учить слова»
    showing_vocab         = State()  # показываем очередной блок (link/text/photo/quiz)
    vocab_phrase_select  = State()  # 💬 выбор известных фраз по индексам перед раундами (ALL IN)

    vocab_exercise        = State()  # ожидаем ответ на встроенный quiz
    vocab_text_continue   = State()  # после текстового блока — «Я прочитал(a) / Пропустить»
    vocab_photo_continue  = State()  # после фото — «Я просмотрел(а) / Пропустить»

    vocab_optional_quiz   = State()  # ожидание ответа на опциональный quiz

        # — Новый блок: текстовый квиз —
    vocab_textquiz = State()   # ожидание ответа на текстовый квиз

    review_failed_vocab = State()      # поток разбора неправильных vocab-quiz
    review_failed_textquiz = State()   # поток разбора неправильных textquiz


    # 🙊 Поток «Читать диалоги» — новая логика
    waiting_dialog_phase  = State()    # выбор фазы перед чтением диалогов
    showing_dialog        = State()    # показываем блок диалога (4 строки) с самопроверкой



    # 🎬 Поток «Смотреть видео»
    showing_video         = State()  # показываем видео  # 💬 состояние показа видео-блока

   




# 💬 инициализация модуля «🎁 Бонусы» (рефералка + заявки)
init_bonus_feature(
    load_user_data=load_user_data,
    save_user_data=save_user_data,
    load_subscription_channels=load_subscription_channels,
    LessonStates=LessonStates,
    materials_url=MATERIALS_POST_URL,
    contact_url=CONTACT_URL,
    admin_chat_id=ADMIN_CHAT_ID,
)

init_podcasts_feature(
    load_user_data=load_user_data,
    save_user_data=save_user_data,
    load_subscription_channels=load_subscription_channels,
    LessonStates=LessonStates,
    admin_chat_id=ADMIN_CHAT_ID,
    bot=bot,
)  # 💬 пробрасываем зависимости в модуль "Подкасты"

init_grammar_feature(
    load_user_data=load_user_data,
    save_user_data=save_user_data,
    show_topics_for_category_level=(lambda *args, **kwargs: globals()["show_topics_for_category_level"](*args, **kwargs)),  # 💬 прокси чтобы избежать NameError при импорте
    start_handler=(lambda *args, **kwargs: globals()["start_handler"](*args, **kwargs)),  # 💬 прокси чтобы избежать NameError при импорте
    admin_chat_id=ADMIN_CHAT_ID,
    bot=bot,
)  # 💬 пробрасываем зависимости в модуль грамматики



# ─── УТИЛИТЫ XP ───────────────────────────────────────

async def award_xp(amount: int, state: FSMContext):
    """
    Добавляет amount XP (без изменения done_dialog) и обновляет level.
    """
    data = await state.get_data()
    xp = data.get("xp", 0) + amount
    if xp < 0:
        xp = 0  # 💬 session_xp не уходит в минус

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


# 💬 есть ли ещё обычные квизы дальше от текущего индекса
def _has_quiz_ahead(vocab_list: list, start_idx: int) -> bool:
    for b in vocab_list[start_idx:]:
        if b.get("type") == "quiz":
            return True
    return False


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


# 💬 helper: отправка текста в виде Telegram Quote (HTML <blockquote>)
async def send_quotedtext(target, text: str, expandable: bool = False):
    chat_id = target.chat.id if hasattr(target, "chat") else target.id
    # 💬 если нужен expandable — ставим атрибут, иначе обычный блок
    tag_open = "<blockquote expandable>" if expandable else "<blockquote>"
    await bot.send_message(chat_id, f"{tag_open}{text}</blockquote>", parse_mode="HTML")







# ================================================================================
# 🔧 Утилита: проверка, что пользователь нажал одну из кнопок сцены
# ================================================================================
async def ensure_valid_choice(message: Message, options: List[str]) -> bool:
    """
    Возвращает True, если message.text в списке options;
    иначе шлёт ошибку и клавиатуру с options и возвращает False.
    + Обрабатывает голосовые/не-текстовые (message.text is None/empty).
    """
    txt = (message.text or "").strip()
    if not txt:
        # 💬 сюда попадут voice, фото без подписи и пустые тексты
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=btn)] for btn in options],
            resize_keyboard=True
        )
        await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())  # 💬 скрыть старую
        await smart_reply(message, "⚠️ Голосовые и не-текстовые сообщения не поддерживаются. Выбери одну из кнопок ниже.", reply_markup=kb)
        return False

    if txt not in options:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=btn)] for btn in options],
            resize_keyboard=True
        )
        await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
        await smart_reply(message, "Пожалуйста, выбери одну из кнопок.", reply_markup=kb)
        return False

    return True



import unicodedata

import unicodedata

# 💬 Нормализация ответа TEXTQUIZ: lower + без акцентов и артиклей
def normalize_textquiz(text: str) -> str:
    txt = text.lower().strip()
    # 1) убираем акценты
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    # 2) убираем апострофы
    txt = txt.replace("'", "").replace("`", "")

    # 3) выкидываем артикль, если стоит отдельно
    parts = txt.split()
    articles = {"el", "la", "los", "las", "un", "una", "unos", "unas"}
    if parts and parts[0] in articles:
        parts = parts[1:]

    # 4) объединяем в одну «слепленную» строку
    combined = "".join(parts)

    # 5) режем артикль, если он был слитно (elcuaderno → cuaderno)
    for art in articles:
        if combined.startswith(art):
            combined = combined[len(art):]
            break

    return combined




# ─────────────────────────────────────────────────────────────
# ⏱ ЕДИНЫЕ ТАЙМИНГИ ДЛЯ КВИЗОВ/ФИДБЭКА/УДАЛЕНИЙ
# 💬 все «sleep/delay» собраны в одном месте для удобной настройки
# ─────────────────────────────────────────────────────────────
QUIZ_OPEN_PERIOD_S       = 12.0   # ⏳ сколько открыт опрос (poll) у Telegram Quiz
QUIZ_TIMEOUT_TASK_S      = 13.0   # 🕒 дублёр-таймаут: через сколько сработает наш фоновый watchdog

SLEEP_BEFORE_FEEDBACK_S  = 0.35   # ⏸ пауза между показом «правильного/похвалы» и XP
SLEEP_AFTER_FEEDBACK_S   = 0.35    # 📖 даём дочитать XP/фидбек перед удалением

AUTO_DELETE_TEXT_DELAY_S = 0.35   # 🧹 авто-удаление сервисных сообщений («Время вышло!», «✅ …»)
AUTO_DELETE_GIF_DELAY_S  = 3.0    # 🧹 авто-удаление MP4/стикеров после ссылки-упражнения

AUTO_DELETE_STICKER_DELAY_S = 2.3   # 🧹 авто-удаление стикеров по умолчанию
LONG_STICKER_DELETE_S       = 10.0  # 🧹 редкий длинный показ стикера (подписка/баннер)
# 💬 если не нужен длинный кейс — можно обеих местами использовать AUTO_DELETE_STICKER_DELAY_S

def _normalize_nl(text: str) -> str:
    # 💬 нормализуем переносы строк из ALL IN и убираем лишние слэши
    if not isinstance(text, str):
        return ""

    if not text:
        return text

    s = text.replace("\r\n", "\n").replace("\r", "\n")

    # 💬 кейс со скрина: "слэш + реальный перенос" = превращаем в чистый перенос
    s = s.replace("\\\n", "\n")


    # 💬 кейс из ALL IN: приходит как \\n или \\\\n
    s = s.replace("\\\\n", "\n")  # 💬 двойной слэш + n
    s = s.replace("\\n", "\n")    # 💬 одиночный слэш + n
    s = re.sub(r"\\\s*\n", "\n", s)  # 💬 убираем одиночный "\" перед реальным переносом строки


    return s



# ─── Негативный фидбек при ошибке (квиз) ───────────────────────
NEGATIVE_STICKERS = [
      "CAACAgIAAxkBAAIRIGlE3W3MzKs6hfGC6PBO1kNZnIkdAAKhMgACnIfBSFQYZ8fI6S5UNgQ.",  # 💬 
      "CAACAgIAAxkBAAIQtGlExnTmmic3O0KvpIIspVsWb7JzAAKvEAACH1yYSbY5sQMKIUkvNgQ",  # 💬 №2
      "CAACAgIAAxkBAAIQwGlEyGHOeggqkrRWCRSJ8wk16SlYAAKGAAPBnGAM5riI3F3JHAQ2BA",  # 💬 №3
      "CAACAgIAAxkBAAIRJmlE3iEgwjBN2ZJagKtYmbauKs-kAALVCgAC16xhS8dwLdmVKEAtNgQ",  # 💬 №4
      "CAACAgIAAxkBAAIRMGlE3pe_U8eaS2iRnDKdmV1Vb1m-AAIVMAACvxdJSHkF7H2f3kAaNgQ",  # 💬 №5
      "CAACAgIAAxkBAAIRNGlE3q8aCIWKQZTrDaPe_iTl4l8AA-svAAJLt1FJWR9bn1FKlyY2BA",  # 💬
      "CAACAgIAAxkBAAIROmlE3vTINWHAQRbefMkaaQgQ0FjWAAIrEAACIfiYSfeadbBgPmtmNgQ",  # 💬 №2
      "CAACAgIAAxkBAAIRPmlE30Jnig-Oi5-n16Uuyi3FeJ_sAAIzAQACUomRI9GLrMjcGVmbNgQ",  # 💬 №3
      "CAACAgIAAxkBAAIRQmlE31ct037BwKN26N_p-8L765eNAAImAQACUomRI3VoLZaREiseNgQ",  # 💬 №4
      "CAACAgIAAxkBAAIRRmlE33yP9FpaV1RLhgIjG8cXperuAAJJAQACUomRI4JZzSRvd3QzNgQ",  # 💬 №5
      "CAACAgIAAxkBAAIRSmlE36yXFEuP_JdjsrUIIb0mLPrlAAJMAQACUomRIyzkKh0sMQYCNgQ",  # 💬 №5
      "CAACAgIAAxkBAAIRTmlE39AM4lV1UOtN8k4Je_Tcj9BfAALOAAP3AsgPXJhH4Myrboo2BA",  # 💬 №5
      "CAACAgIAAxkBAAIRUmlE4AUDdKUh0k6c08vvP6OVpkBGAAIzAQAC9wLIDzvK4ZTu2U7NNgQ",  # 💬 №5
      "CAACAgIAAxkBAAIRWGlE4EfuynZEoFaKP-PDGmYh9_i7AAK5AAP3AsgPkCGq-Dl3Rtg2BA",  # 💬 №5
]

NEGATIVE_STICKER_PROB   = 0.30  # 💬 шанс показать «негативный» стикер при ошибке
WRONG_FB_TEXT_TOTAL_S   = 2.0   # 💬 сколько держим сообщение с правильным ответом (всего)
WRONG_STICKER_DELAY_S   = 0.5   # 💬 через сколько после ответа показать стикер
WRONG_STICKER_SHOW_S    = 1.0   # 💬 сколько показываем стикер (потом удаляем)


AD_REACTION_DELETE_S     = 2.0    # 🎯 пауза перед зачисткой рекламного блока после клика

# 💬 единые паузы чтения/ожидания для реакций и сервисных анимаций
DICE_DELETE_DELAY_S              = 1.0   # 💬 задержка до удаления 🎲
LINK_HINT_DELETE_S               = 3.0   # 💬 подсказка перед ссылкой (аним. текст)
REPLY_REACTION_READ_DELAY_S      = 1.0   # 💬 пауза, чтобы прочитать реакцию (текст)
REPLY_REACTION_READ_DELAY_PHOTO_S= 1.0   # 💬 пауза, чтобы прочитать реакцию (фото)

# ─────────────────────────────────────────────────────────────
# 💬 что делает эта часть: все задержки сведены в константы, чтобы менять
# поведение бота без копания в десятках «sleep/delay» по коду.


# ─── ЗАДЕРЖКИ И УДАЛЕНИЯ СТИКЕРОВ И ГИФОК ─────────────────────

# 💬 Отправка стикера с авто-удалением через N секунд
async def send_and_auto_delete_sticker(bot, chat_id, sticker, delay=AUTO_DELETE_STICKER_DELAY_S):  # 💬 единый дефолт для стикеров

    msg = await bot.send_sticker(chat_id=chat_id, sticker=sticker)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass



# 💬 Отправка GIF/анимации с авто-удалением через N секунд (по умолчанию 3 сек)
async def send_and_auto_delete_gif(bot, chat_id, gif, delay=AUTO_DELETE_GIF_DELAY_S):  # 💬 единый дефолт для GIF/видео

    msg = await bot.send_animation(chat_id=chat_id, animation=gif)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass



async def _maybe_send_negative_sticker(bot, chat_id: int):  # 💬 1 из NEGATIVE_STICKERS при ошибке
    if not NEGATIVE_STICKERS:
        return
    if random.random() >= NEGATIVE_STICKER_PROB:
        return

    await asyncio.sleep(WRONG_STICKER_DELAY_S)  # 💬 даём увидеть правильный ответ
    await send_and_auto_delete_sticker(
        bot,
        chat_id,
        random.choice(NEGATIVE_STICKERS),
        delay=WRONG_STICKER_SHOW_S  # 💬 показываем 1 секунду
    )



# 💬 Делает текст жирным, безопасно для HTML (не ломает уже размеченный текст)
def _boldify_html(text: str) -> str:
    import html  # 💬 экранируем спецсимволы только для “обычного” текста
    if text is None:
        return ""

    t = str(text)
    s = t.strip()

    # 💬 если уже обёрнуто — не трогаем
    if s.startswith("<b>") and s.endswith("</b>"):
        return t

    low = s.lower()

    # 💬 code/pre лучше НЕ оборачивать в <b>, чтобы не ломать форматирование
    if "<pre>" in low or "</pre>" in low or "<code>" in low or "</code>" in low:
        return t

    # 💬 если в тексте нет HTML-тегов — экранируем
    has_html = any(tag in low for tag in (
        "<b>", "</b>", "<i>", "</i>", "<u>", "</u>", "<s>", "</s>",
        "<a ", "</a>", "<tg-spoiler>", "</tg-spoiler>"
    ))
    if not has_html:
        t = html.escape(t)

    return f"<b>{t}</b>"

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
    safe_text = "" if text is None else str(text)
    await asyncio.sleep(min(len(safe_text) * 0.01, 3.0))

    # 💬 если HTML (или не задан) — оборачиваем в жирный
    pm = kwargs.get("parse_mode")
    if pm is None or pm == "HTML":
        kwargs["parse_mode"] = "HTML"
        send_text = _boldify_html(safe_text)
    else:
        send_text = safe_text

    # Отправляем сообщение
    return await bot.send_message(chat_id, send_text, **kwargs)




# 👇 ЭТУ функцию поставь ВНЕ всех хендлеров (где-то рядом с другими глобальными функциями)
def render_leaderboard(title, top, emoji):
    medals = ["🥇", "🥈", "🥉"]
    res = [f"<b>{title}</b>"]
    for idx, u in enumerate(top, 1):
        m = medals[idx-1] if idx <= 3 else str(idx)
        res.append(f"{m} {u['name']} {emoji} {u['words_learned']}")
    return "\n".join(res)

# 💬 Отправка текстового сообщения с авто-удалением через N секунд
async def send_and_auto_delete_text(bot, chat_id, text, delay=AUTO_DELETE_TEXT_DELAY_S, **kwargs):  # 💬 единый дефолт

    # 💬 отправляем текст и удаляем через delay секунд
    msg = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except TelegramBadRequest:
        pass

async def _safe_delete_message(chat_id: int, message_id: int | None):
    # 💬 безопасно удаляем сообщение, чтобы поток не падал
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def _lex_cleanup_last_bot_message(chat_id: int, state: FSMContext):
    # 💬 держим чат чистым: удаляем прошлое сообщение бота в потоке «Учить слова»
    data = await state.get_data()
    last_id = data.get("lex_last_bot_msg_id")
    if last_id:
        await _safe_delete_message(chat_id, last_id)
        await state.update_data(lex_last_bot_msg_id=None)


# 💬 Набор ТЕКСТОВЫХ подсказок перед link (без эмодзи)
LINK_HINT_TEXTS = (
    "Готовим ссылку…",
    "Секунду, открываю материал…",
    "Сейчас пришлю ссылку",
    "🏆",
    "🎰",
    "☕️",
    "🎉",
    "🚀",
    "Дальше будет ссылка",
)

# 💬 Отправка СЛУЧАЙНОГО текста с авто-удалением, не блокируя поток
async def send_and_auto_delete_random_text(bot, chat_id, texts=LINK_HINT_TEXTS, delay: float = 3.0):
    try:
        txt = random.choice(texts)
    except Exception:
        return  # 💬 если список пуст/ошибка — тихо выходим
    await send_and_auto_delete_text(bot, chat_id, txt, delay=delay)  # 💬 используем существующую функцию



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

    # 💬 фиксируем рефералку из /start ref_<id>
    payload = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            payload = parts[1].strip()
    bonus_register_referral_from_start(user_id, payload)  # 💬 сохраняем, кто пригласил пользователя


    # 💬 ГАРАНТИРУЕМ поля для тем и подписок
    u.setdefault("unlocked_topics", [])  # ключи открытых тем
    u.setdefault("channels", {})         # история подписок по каналам
    u.setdefault("last_subscription_channel_index", -1)  # 💬 для ротации каналов


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

    # 💬 Обновляем XP-профиль: имя / username / базовые поля в xp_data.json
    await register_or_update_user(message)


        # — далее остальная логика: приветствие, загрузка тем и установка состояния —
    await cancel_battle_if_running(bot, message.chat.id, message.from_user.id)  # 💬 если шла битва = останавливаем её на /start

    await state.clear()
    
    global topics
    topics = load_topics_from_railway()  # 💬 перезагружаем темы ТОЛЬКО из /data/topics
    set_topics_ref(topics)               # 💬 обновляем topics для "Битвы"
    set_grammar_topics_ref(topics)       # 💬 обновляем topics для "Грамматики"



    # 💬 Убираем старую Reply-клавиатуру и отправляем нормальное приветствие
    hello_msg = await smart_reply(
        message,
        "Holaaa...",
        reply_markup=ReplyKeyboardRemove()
    )  # 💬 приветствие, которое удалим позже

    async def _delete_hello_later(chat_id: int, msg_id: int, delay: float = 30.0):
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    if hello_msg:
        asyncio.create_task(
            _delete_hello_later(hello_msg.chat.id, hello_msg.message_id)
        )  # 💬 авто-удаление приветствия через 30 секунд




    # 💬 Отправляем рандомный стартовый стикер и авто-удаляем через 3 секунды
    sticker_id = random.choice(start_stickers)  # список импортируется из scenarios_estiloso8_1
    sticker_msg = await message.answer_sticker(sticker_id)

    async def _auto_delete_start_sticker(msg):
        await asyncio.sleep(3)
        try:
            await msg.delete()
        except TelegramBadRequest:
            # 💬 если сообщение уже удалено/недоступно — тихо игнорируем
            pass

    asyncio.create_task(_auto_delete_start_sticker(sticker_msg))

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

    '''
    # Отправляем прогресс
    await message.answer(
        f"📊 Уровень: {current_level}{current_medal}👇   \n"
        f"[{bar}]\n"
        f"{total_xp % XP_PER_LEVEL}/{XP_PER_LEVEL} XP ➡️ {next_level}{next_medal}"
    )
    '''

    # 💬 Инициализация показа рекламы в «Учить слова»
    await state.update_data(phase_entry_count=0, pending_phase=False)


        # 💬 Главное меню теперь ИНЛАЙН — без ReplyKeyboard (ничего не «висит» внизу)
    inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],
    
        [
            InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL),
            InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords"),
        ],
        
        [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts")],
    
        [
            InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle"),
            InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses"),
        ],
    
        [
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),
            InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings"),
        ],
    ])




    menu_text = random.choice(menu_study_phrases) if menu_study_phrases else "Выбирай"  # 💬 рандомная фраза главного меню


    menu_msg = await smart_reply(
        message,
        menu_text,
        reply_markup=inline_kb_main,
        parse_mode="HTML"
    )  # 💬 показываем меню и получаем message для сохранения id

    await state.update_data(last_menu_msg_id=menu_msg.message_id)  # 💬 запоминаем id для последующего удаления
    await state.update_data(menu_hidden=False)  # 💬 меню на экране
    await state.set_state(LessonStates.choosing_category)  # 💬 ждём выбор кнопок меню




# ================================================================================
#   🟡 1️⃣ Выбор категории (choosing_category)
# ================================================================================


@dp.callback_query(LessonStates.choosing_category, F.data.startswith("menu:"))
@track_handler
async def category_chosen_cb(callback: CallbackQuery, state: FSMContext):
    # 💬 регистрируем активность пользователя (как и раньше)
    await register_or_update_user(callback.message)

    action = callback.data.split(":", 1)[1]
    # 💬 совместимость: если где-то остались старые кнопки с lex_menu:read (старый «Переводить»)
    if action == "read_legacy":
        action = "translate"



    # 🏆/⚙️ — сразу открываем соответствующие разделы
    if action == "rating":
        await callback.answer()
    
        # 💬 сохраняем “кто нажал рейтинг”, потому что callback.message.from_user = бот
        await state.update_data(
            leaderboard_actor_uid=str(callback.from_user.id),
            leaderboard_actor_name=((callback.from_user.full_name or callback.from_user.username) or "").strip()
        )
    
        return await show_leaderboard(callback.message, state)


    if action == "settings":
        await callback.answer()
        return await settings_menu(callback.message, state)
        
    # ⚔️ Битва
    if action == "battle":
        await callback.answer()
        try:
            await callback.message.delete()  # 💬 чистим главное меню чтобы не копилось
        except TelegramBadRequest:
            pass
        return await start_battle_from_lex_menu(callback.message, state)  # 💬 показываем темы битвы


    if action == "mywords":
        await callback.answer()
        return await mywords_menu(callback.message, state)  # 💬 открываем «Мои слова»

    if action == "bonuses":
        await callback.answer()
        return await bonuses_open(callback.message, state)  # 💬 открываем «Бонусы»

    if action == "podcasts":
        await callback.answer()  # 💬 обязательно отвечаем на callback, чтобы не было Telegram timeout
        await podcasts_open(callback.message, state)  # 💬 открываем подкасты (авторы -> эпизоды)
        return




    # 📚 УЧИТЬСЯ — показываем выбор уровня (категорию выберем позже внутри уровня)
    if action == "learn":
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🐥 Новичок",     callback_data="level:A0"),
             InlineKeyboardButton(text="😤 Начальный",    callback_data="level:A1-A2")],
            [InlineKeyboardButton(text="😼 Средний",      callback_data="level:B1-B2"),
             InlineKeyboardButton(text="🤓 Продвинутый",  callback_data="level:C1")],
            [InlineKeyboardButton(text="⬅️ Назад",        callback_data="level:back")]
        ])  # 💬 человеко-читаемые названия уровней без A1/B2


        # 💬 вместо новой реплай-клавы — редактируем то же сообщение с инлайном
        # 💬 фраза про уровень берётся рандомно из набора
        intro_text = random.choice(difficulty_intro_phrases) if difficulty_intro_phrases else \
            "😜 Отличный выбор! А теперь давай определимся с уровнем сложности:"

        await callback.message.edit_text(
            intro_text,
            reply_markup=inline_kb
        )
        await state.set_state(LessonStates.choosing_level)
        await callback.answer()
        return

    # 📚/🧠 из старого меню — сохраняем категорию и спрашиваем уровень (старый сценарий)
    if action in ("lex", "gram"):
        category = "lex" if action == "lex" else "gram"
        await state.update_data(chosen_category=category)

        if category == "gram":
            inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🍺 Начальный",    callback_data="level:A1-A2"),
                 InlineKeyboardButton(text="🌻 Средний",      callback_data="level:B1-B2")],
                [InlineKeyboardButton(text="🧠 Продвинутый",  callback_data="level:C1")],
                [InlineKeyboardButton(text="⬅️ Назад",        callback_data="level:back")]
            ])  # 💬 грамматика без A0
        else:
            inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🐥 Новичок",     callback_data="level:A0"),
                 InlineKeyboardButton(text="😤 Начальный",    callback_data="level:A1-A2")],
                [InlineKeyboardButton(text="😼 Средний",      callback_data="level:B1-B2"),
                 InlineKeyboardButton(text="🤓 Продвинутый",  callback_data="level:C1")],
                [InlineKeyboardButton(text="⬅️ Назад",        callback_data="level:back")]
            ])  # 💬 человеко-читаемые названия уровней без A1/B2


        # 💬 вместо новой реплай-клавы — редактируем то же сообщение с инлайном
        # 💬 фраза про уровень берётся рандомно из набора
        intro_text = random.choice(difficulty_intro_phrases) if difficulty_intro_phrases else \
            "😜 Отличный выбор! А теперь давай определимся с уровнем сложности:"

        await callback.message.edit_text(
            intro_text,
            reply_markup=inline_kb
        )
        await state.set_state(LessonStates.choosing_level)
        await callback.answer()
        return


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
    _LEVEL_LABELS = {
        "A0": "Новичок",
        "A1-A2": "Начальный",
        "B1-B2": "Средний",
        "C1": "Продвинутый",
    }  # 💬 отображаемые названия уровней
    level_show = _LEVEL_LABELS.get(str(level).upper(), str(level))


    await state.update_data(chosen_level=level)

    # 💬 После выбора уровня показываем выбор «Лексика / Грамматика» внутри этого уровня
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📚 ЛЕКСИКА",    callback_data="subcat:lex"),
            InlineKeyboardButton(text="🧠 ГРАММАТИКА", callback_data="subcat:gram"),
        ],
        [
            InlineKeyboardButton(text="👈 НАЗАД",      callback_data="subcat:back"),
        ],
    ])

    text = (
        f"Уровень <b>{level_show}</b> выбран!\n"  # 💬 выводим новичок вместо A0

        f"Что будем учить на этом уровне?"
    )

    await callback.message.edit_text(
        text,
        reply_markup=inline_kb,
        parse_mode="HTML"
    )

    await state.set_state(LessonStates.choosing_subcategory)
    await callback.answer()



async def show_topics_for_category_level(callback: CallbackQuery, state: FSMContext, category: str, level: str):
    """
    💬 Показываем список тем для выбранной категории и уровня + прогресс-бар
    """
    message = callback.message  # 💬 работаем через message, чтобы не плодить NameError

    buttons = [
        InlineKeyboardButton(text=info["visible_title"], callback_data=f"topic:{key}")
        for key, info in topics.items()
        if info.get("category") == category and info.get("level") == level
    ]

    if not buttons:
        await message.edit_text("🤷‍♂️ Тем пока нет на уровне. Скоро добавим!")
        # 💬 Если тем нет — возвращаем пользователя в стартовое меню
        return await start_handler(message, state)

    # 💬 По одной теме в строке
    inline_keyboard = [[btn] for btn in buttons]

    # 💬 Добавляем кнопку «НАЗАД» в конец списка тем
    inline_keyboard.append(
        [InlineKeyboardButton(text="👈 НАЗАД", callback_data="topic_back")]
    )

    inline_kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

    # 💬 Глобальный прогресс пользователя — короткий формат
    try:
        progress_text = render_short_level_progress(message.from_user.id)
    except Exception:
        # 💬 если вдруг что-то пошло не так с чтением xp_data — не ломаем поток
        progress_text = ""

    # 💬 Подпись экрана уровня + категория, чтобы не путать пользователя
    if category == "lex":
        cat_title = "📚 <b>ЛЕКСИКА</b>"
    elif category == "gram":
        cat_title = "🧠 <b>ГРАММАТИКА</b>"
    else:
        cat_title = "📘 <b>Категория</b>"

    level_show = "новичок" if str(level).upper() == "A0" else level  # 💬 A0 показываем как новичок

    # 💬 Прогресс: 20 ячеек (5% за ячейку) + ✅ в начале + смайлик после процентов
    import re  # 💬 локальный импорт, чтобы не зависеть от верхних импортов

    pct = 0
    try:
        m = re.search(r"(\d{1,3})\s*%", str(progress_text or ""))
        if m:
            pct = int(m.group(1))
    except Exception:
        pct = 0
    pct = max(0, min(int(pct), 100))  # 💬 защита от мусорных значений

    mood_steps = [
        "🗿", "💩", "🐥", "🐒", "🔥",
        "🦥", "🐝", "🌝", "🍷", "🐙",
        "🐘", "🦦", "🍻", "🌞", "🧘🏻‍♂️",
        "🔱", "🎗", "🎖", "🏆", "🏆",
    ]  # 💬 20 смайликов на шаги 0–95% (по 5%)

    mood_idx = min(int(pct // 5), len(mood_steps) - 1)
    mood_emoji = mood_steps[mood_idx]

    filled = max(1, min(int(pct * 20 / 100), 20))  # 💬 всегда минимум 1 “закрашенный” квадратик
    bar = ("█" * filled) + ("░" * (20 - filled))
    bar_line = f"✅{bar} {pct}% {mood_emoji}"

    # 💬 Итоговый текст экрана: 1) уровень 2) прогресс 3) призыв выбрать тему
    level_screen_text = (
        f"🧭 Уровень <b>{level_show}</b> · {cat_title}\n"
        f"{bar_line}\n\n"
        f"Выбери тему для этого уровня:"
    )



    # 💬 Отправляем уровень со списком тем этого уровня (прогресс уже перед словом «Уровень»)
    await message.edit_text(
        level_screen_text,
        reply_markup=inline_kb,
        parse_mode="HTML"
    )

    await state.set_state(LessonStates.choosing_topic)  # 💬 дальше ждём выбор конкретной темы




@dp.callback_query(LessonStates.choosing_subcategory, F.data.startswith("subcat:"))
@track_handler
async def subcategory_chosen(callback: CallbackQuery, state: FSMContext):
    """
    💬 Внутри выбранного уровня пользователь выбирает: Лексика / Грамматика / Назад
    """
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    level = data.get("chosen_level")

    # Если по какой-то причине уровень не сохранён — возвращаемся к выбору уровня
    if not level:
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🐥 Новичок",      callback_data="level:A0"),
             InlineKeyboardButton(text="😤 Начальный",    callback_data="level:A1-A2")],
            [InlineKeyboardButton(text="😼 Средний",      callback_data="level:B1-B2"),
             InlineKeyboardButton(text="🤓 Продвинутый",  callback_data="level:C1")],
            [InlineKeyboardButton(text="⬅️ Назад",        callback_data="level:back")]
        ])  # 💬 человеко-читаемые уровни, лексика

        intro_text = random.choice(difficulty_intro_phrases) if difficulty_intro_phrases else \
            "😜 Отличный выбор! А теперь давай определимся с уровнем сложности:"

        await callback.message.edit_text(
            intro_text,
            reply_markup=inline_kb,
        )
        await state.set_state(LessonStates.choosing_level)
        await callback.answer()
        return

    # 🔙 Назад → возвращаемся к выбору уровня
    if action == "back":
        data = await state.get_data()
        category = data.get("chosen_category")  # 💬 грамматика не показывает "Новичок"

        if category == "gram":
            inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🍺 Начальный",   callback_data="level:A1-A2"),
                 InlineKeyboardButton(text="🌻 Средний",     callback_data="level:B1-B2")],
                [InlineKeyboardButton(text="🧠 Продвинутый", callback_data="level:C1")],
                [InlineKeyboardButton(text="⬅️ Назад",       callback_data="level:back")]
            ])  # 💬 выбор уровня для грамматики без буквенных уровней
        else:
            inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🐥 Новичок",     callback_data="level:A0"),
                 InlineKeyboardButton(text="😤 Начальный",   callback_data="level:A1-A2")],
                [InlineKeyboardButton(text="😼 Средний",     callback_data="level:B1-B2"),
                 InlineKeyboardButton(text="🤓 Продвинутый", callback_data="level:C1")],
                [InlineKeyboardButton(text="⬅️ Назад",       callback_data="level:back")]
            ])  # 💬 выбор уровня для лексики без буквенных уровней

        intro_text = random.choice(difficulty_intro_phrases) if difficulty_intro_phrases else \
            "😜 Отличный выбор! А теперь давай определимся с уровнем сложности:"

        await callback.message.edit_text(
            intro_text,
            reply_markup=inline_kb,
        )
        await state.set_state(LessonStates.choosing_level)
        await callback.answer()
        return



    if action == "lex":
        # 💬 Сохраняем выбранную категорию и показываем темы для этого уровня
        await state.update_data(chosen_category="lex")
        await show_topics_for_category_level(callback, state, category="lex", level=level)
        await callback.answer()
        return
        
    elif action == "gram":
        await state.update_data(chosen_category="gram")  # 💬 фиксируем категорию грамматики
        if str(level).upper() == "A0":
            level = "A1-A2"  # 💬 грамматика начинается с начального, A0 пропускаем
            await state.update_data(chosen_level=level)  # 💬 чтобы темы/назад работали без рассинхрона

        await show_topics_for_category_level(callback, state, category="gram", level=level)  # 💬 показываем темы грамматики
        await callback.answer()  # 💬 закрываем loading
        return




@dp.message(LessonStates.choosing_category, lambda m: m.text == "Настройки ⚙️")

@track_handler
async def settings_menu(message: Message, state: FSMContext):
    user_data = load_user_data()
    user_id = str(message.from_user.id)
    settings = user_data.get(user_id, {}).get("settings", {})

    daily_limit_words = settings.get("daily_limit_words", 20)  # 💬 дефолт если нет
    notify_time = settings.get("notify_time", "09:00")  # 💬 дефолт если нет

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Связь 💬", url=CONTACT_URL),
            InlineKeyboardButton(text="Лимит слов", callback_data="settings:limit"),
        ],
        [
            InlineKeyboardButton(text="Время уведомления", callback_data="settings:notify"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back"),
        ],
    ])  # 💬 меню настроек (инлайн 4 кнопки)


    txt = (
        "⚙️ <b>Настройки</b>\n\n"
        f"📌 Лимит слов в день = <b>{daily_limit_words}</b>\n"
        f"⏰ Время уведомления = <b>{notify_time}</b>\n\n"
        "Выбери действие:"
    )  # 💬 показываем текущие значения настроек

    try:
        await message.edit_text(txt, reply_markup=kb)  # 💬 не плодим новые сообщения
    except Exception:
        await message.answer(txt, reply_markup=kb)  # 💬 fallback если edit_text нельзя



@dp.callback_query(F.data == "settings:back")
async def settings_back_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    await state.update_data(
        _settings_wait=None,
        _settings_prev_state=None,
        _settings_chat_id=None,
        _settings_msg_id=None,
    )  # 💬 чистим режим ввода настроек

    inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],

        [
            InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL),
            InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords"),
        ],

        [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts")],  # 💬 возвращаем кнопку подкастов

        [
            InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle"),
            InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses"),
        ],

        [
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),
            InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings"),
        ],
    ])  # 💬 главное меню в актуальной раскладке

    menu_text = random.choice(menu_study_phrases) if menu_study_phrases else "Выбирай"  # 💬 рандомная фраза главного меню

    menu_msg_id = None
    try:
        await callback.message.edit_text(menu_text, reply_markup=inline_kb_main, parse_mode="HTML")
        menu_msg_id = callback.message.message_id  # 💬 это же сообщение стало главным меню
    except Exception:
        menu_msg = await smart_reply(callback.message, menu_text, reply_markup=inline_kb_main, parse_mode="HTML")
        menu_msg_id = menu_msg.message_id  # 💬 fallback если edit_text нельзя

    if menu_msg_id:
        await state.update_data(last_menu_msg_id=menu_msg_id, menu_hidden=False)  # 💬 синхронизируем id главного меню

    await state.set_state(LessonStates.choosing_category)



@dp.callback_query(F.data == "settings:limit")
async def settings_limit_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    # 💬 просим число, дальше обработает отдельный input-хендлер
    prev_state = await state.get_state()  # 💬 запоминаем состояние, чтобы вернуть после ввода
    await state.update_data(
        _settings_chat_id=callback.message.chat.id,   # 💬 чтобы вернуть экран настроек без новых сообщений
        _settings_msg_id=callback.message.message_id  # 💬 чтобы вернуть экран настроек без новых сообщений
    )

    await state.update_data(_settings_wait="limit", _settings_prev_state=prev_state)  # 💬 ждём ввод лимита
    await state.set_state("settings_inline_input")  # 💬 включаем режим ввода из настроек

    await callback.message.edit_text(
        "🔢 Введи лимит слов в день (число):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")]
        ])
    )


@dp.callback_query(F.data == "settings:notify")
async def settings_notify_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    prev_state = await state.get_state()  # 💬 запоминаем состояние, чтобы вернуть после ввода
    await state.update_data(
        _settings_wait="notify",                      # 💬 ждём ввод времени
        _settings_prev_state=prev_state,              # 💬 куда вернуть FSM после ввода
        _settings_chat_id=callback.message.chat.id,   # 💬 чтобы вернуть экран настроек без новых сообщений
        _settings_msg_id=callback.message.message_id  # 💬 чтобы вернуть экран настроек без новых сообщений
    )
    await state.set_state("settings_inline_input")  # 💬 включаем режим ввода из настроек

    await callback.message.edit_text(
        "⏰ Введи час уведомления числом 1–24 (время Мадрида)\n24 = 00:00",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")]
        ])
    )


@dp.message(StateFilter("settings_inline_input"), F.text, ~F.text.startswith("/"))
async def settings_inline_input_router(message: Message, state: FSMContext):
    data = await state.get_data()
    wait = data.get("_settings_wait")
    prev_state = data.get("_settings_prev_state")

    if wait not in ("limit", "notify"):
        return  # 💬 не наше состояние ввода

    user_data = load_user_data()
    user_id = str(message.from_user.id)
    user_data.setdefault(user_id, {}).setdefault("settings", {})

    chat_id = data.get("_settings_chat_id") or message.chat.id  # 💬 берём сохранённый chat_id экрана настроек
    msg_id  = data.get("_settings_msg_id")  # 💬 берём сохранённый message_id, чтобы обновлять настройки без “зависаний”

    # 💬 пытаемся удалить ввод пользователя (цифру), чтобы чат не засорялся
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass


    # ─────────────────────────────────────────────────────────────
    # LIMIT WORDS
    # ─────────────────────────────────────────────────────────────
    if wait == "limit":
        try:
            val = int((message.text or "").strip())
            if val < 1 or val > 500:
                raise ValueError
        except Exception:
            asyncio.create_task(
                send_and_auto_delete_text(bot, chat_id, "⚠️ Введи число от 3 до 30", delay=1.0)
            )  # 💬 короткое предупреждение без мусора в чате
            return


        user_data[user_id]["settings"]["daily_limit_words"] = val  # 💬 реально сохраняем лимит (раньше этого не было)
        save_user_data(user_data)

        # 💬 синхронизируем лимит со старой логикой (xp_data), чтобы он реально влиял на обучение
        xp_data = load_xp_data()
        xp_user_id = str(message.chat.id)
        xp_data.setdefault(xp_user_id, {})["words_daily_limit"] = val
        save_xp_data(xp_data)


        # 💬 обновляем меню настроек (редактируем исходное сообщение)
        settings = user_data[user_id]["settings"]
        daily_limit_words = settings.get("daily_limit_words", 20)
        notify_time = settings.get("notify_time", "09:00")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Связь 💬", url=CONTACT_URL),
                InlineKeyboardButton(text="Лимит слов", callback_data="settings:limit"),
            ],
            [
                InlineKeyboardButton(text="Время уведомления", callback_data="settings:notify"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back"),
            ],
        ])  # 💬 меню настроек (инлайн 4 кнопки)

        txt = (
            "⚙️ <b>Настройки</b>\n\n"
            f"📌 Лимит слов в день = <b>{daily_limit_words}</b>\n"
            f"⏰ Время уведомления = <b>{notify_time}</b>\n\n"
            "Выбери действие:"
        )  # 💬 показываем текущие значения настроек


        if msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=txt,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception:
                pass  # 💬 если исходное сообщение уже удалено/не редактируется

        await state.update_data(
            _settings_wait=None,
            _settings_prev_state=None,
            _settings_chat_id=None,
            _settings_msg_id=None,
        )  # 💬 полностью выходим из режима ввода

        await state.set_state(prev_state if prev_state else LessonStates.choosing_category)
        return

    # ─────────────────────────────────────────────────────────────
    # NOTIFY TIME (1–24 Madrid)
    # ─────────────────────────────────────────────────────────────
    if wait == "notify":
        try:
            hour = int((message.text or "").strip())
            if hour < 1 or hour > 24:
                raise ValueError
        except Exception:
            asyncio.create_task(
                send_and_auto_delete_text(bot, chat_id, "⚠️ Введи час числом от 1 до 24\n23 = 23:00", delay=1.0)
            )  # 💬 короткое предупреждение без мусора в чате
            return


        hour_norm = 0 if hour == 24 else hour
        notify_time = f"{hour_norm:02d}:00"  # 💬 храним как HH:00, ввод всегда по Мадриду

        user_data[user_id]["settings"]["notify_time"] = notify_time  # 💬 сохраняем время уведомления
        save_user_data(user_data)

        # 💬 синхронизируем час со старой логикой (xp_data), чтобы напоминания брали новое время
        xp_data = load_xp_data()
        xp_user_id = str(message.chat.id)
        xp_data.setdefault(xp_user_id, {})["reminder_hour"] = hour_norm
        save_xp_data(xp_data)



        # 💬 обновляем меню настроек
        settings = user_data[user_id]["settings"]
        daily_limit_words = settings.get("daily_limit_words", 20)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Связь 💬", url=CONTACT_URL),
                InlineKeyboardButton(text="Лимит слов", callback_data="settings:limit"),
            ],
            [
                InlineKeyboardButton(text="Время уведомления", callback_data="settings:notify"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back"),
            ],
        ])  # 💬 меню настроек (инлайн 4 кнопки)

        txt = (
            "⚙️ <b>Настройки</b>\n\n"
            f"📌 Лимит слов в день = <b>{daily_limit_words}</b>\n"
            f"⏰ Время уведомления = <b>{notify_time}</b>\n\n"
            "Выбери действие:"
        )  # 💬 показываем текущие значения настроек


        if msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=txt,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception:
                pass  # 💬 если исходное сообщение уже удалено/не редактируется

        await state.update_data(
            _settings_wait=None,
            _settings_prev_state=None,
            _settings_chat_id=None,
            _settings_msg_id=None,
        )  # 💬 полностью выходим из режима ввода

        await state.set_state(prev_state if prev_state else LessonStates.choosing_category)
        return


        save_user_data(user_data)
        
        # 💬 возвращаем экран настроек (без “зависаний”)
        data = await state.get_data()
        chat_id = data.get("_settings_chat_id") or message.chat.id
        msg_id = data.get("_settings_msg_id")
        
        settings = user_data.get(user_id, {}).get("settings", {})
        daily_limit_words = settings.get("daily_limit_words", 20)
        notify_time = settings.get("notify_time", "09:00")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Связь 💬", url=CONTACT_URL),
                InlineKeyboardButton(text="Лимит слов", callback_data="settings:limit"),
            ],
            [
                InlineKeyboardButton(text="Время уведомления", callback_data="settings:notify"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back"),
            ],
        ])  # 💬 меню настроек (инлайн 4 кнопки)
        
        txt = (
            "⚙️ <b>Настройки</b>\n\n"
            f"📌 Лимит слов в день = <b>{daily_limit_words}</b>\n"
            f"⏰ Время уведомления = <b>{notify_time}</b>\n\n"
            "Выбери действие:"
        )  # 💬 показываем текущие значения настроек
        
        if msg_id:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=txt, reply_markup=kb)  # 💬 не плодим новые сообщения
            except Exception:
                await message.answer(txt, reply_markup=kb)  # 💬 fallback если edit_message_text нельзя
        else:
            await message.answer(txt, reply_markup=kb)  # 💬 fallback если нет msg_id
        
        await state.update_data(_settings_wait=None, _settings_prev_state=None, _settings_chat_id=None, _settings_msg_id=None)  # 💬 чистим флаги ожидания
        await state.set_state(prev_state if prev_state else LessonStates.choosing_category)  # 💬 возвращаем состояние
        




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



# 🎲 Стикеры для заблокированных кнопок (🔒 Читать / 🔒 Видео и т.д.)
UNAVAILABLE_STICKERS = [
    "CAACAgIAAxkBAAIQtGlExnTmmic3O0KvpIIspVsWb7JzAAKvEAACH1yYSbY5sQMKIUkvNgQ",  # 💬 вставь ID стикера
    "CAACAgIAAxkBAAIQtmlExoF2ySyJV2ZfWGmjvZTkm6gtAALDEAACyy6YSWRm4_6tdy94NgQ",  # 💬 вставь ID стикера
    "CAACAgIAAxkBAAIQuGlExpaDen0-RArL7Y1B0_X-gleoAAL2DgACMowBSlhbMUADkul4NgQ",  # 💬 вставь ID стикера
    "CAACAgIAAxkBAAIQvmlEyFItz7xyloNqTjJ8CJkDUNd8AAJzAAPBnGAMCyMQkP6llyc2BA",  # 💬 вставь ID стикера
    "CAACAgIAAxkBAAIQwGlEyGHOeggqkrRWCRSJ8wk16SlYAAKGAAPBnGAM5riI3F3JHAQ2BA",
    "CAACAgIAAxkBAAIQwmlEyI0iFrq1o3yDm7WSpILFS9bkAAIqAQACUomRIz_Z0LQz8_8SNgQ",
]



@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text in ["🎲 Упражнения", "🎬 Видео", "🙊 Диалоги"])
@track_handler
async def handle_unavailable_buttons(message: Message, state: FSMContext):
    """
    💬 Если пользователь нажимает на недоступную кнопку,
    отправляем стикер отказа, который удаляется через 1.5 секунды.
    """
    # 🎲 выбираем один случайный стикер из списка
    sticker_id = random.choice(UNAVAILABLE_STICKERS) if UNAVAILABLE_STICKERS else "CAACAgIAAxkBAAE4YOhogox6Armq-TOX3f5IkYPXCeUwuAACRAMAArVx2gYMtzsTtIZDMDYE"  # 💬 fallback если список пустой
    await send_and_auto_delete_sticker(bot, message.chat.id, sticker_id, delay=1.5)  # 💬 показали и удалили





@dp.message(F.text == "Рейтинг🏆")
@track_handler
async def show_leaderboard(message: Message, state: FSMContext):
    xp_data = load_xp_data()
    users = []
    for uid, u in xp_data.items():
        name = (u.get("name", "") or "").strip()
        week = int(u.get("words_learned_week", 0) or 0)
        month = int(u.get("words_learned_month", 0) or 0)

        users.append({
            "uid": str(uid),
            "name": name or f"User {uid}",
            "words_learned_week": week,
            "words_learned_month": month
        })

    current_uid = str(message.from_user.id)
    data = await state.get_data()  # 💬 берём FSM-data один раз, чтобы render_block мог читать actor_uid/actor_name и last_menu_msg_id


    def render_block(title: str, key: str, emoji: str) -> str:
        place_icons = {  # 💬 эмодзи мест как на скриншоте
            1: "👑",
            2: "🥈",
            3: "🥉",
            4: "🎓",
            5: "🍀",
        }
        nbsp = " "               # 💬 обычный пробел = будет ровно работать внутри <pre> (моноширинный блок)
        indent = ""              # 💬 убрали стартовые пробелы, чтобы на телефоне не переносило

        NAME_COL = 16            # 💬 минус 2 пробела между именем и 🍪, чтобы всё влезало

        RANK_COL = 2             # 💬 ширина колонки ранга (1) / 10) / 223)

        def _name_cell(raw: str) -> str:
            # 💬 делает ячейку имени фикс длины, убирая эмодзи (иначе в <pre> всё съезжает)
            raw = (raw or "").strip()

            cleaned = []
            for ch in raw:
                o = ord(ch)
                if ch in ("\uFE0F", "\u200D"):
                    continue  # 💬 вариации эмодзи и joiner ломают ширину
                if (0x1F300 <= o <= 0x1FAFF) or (0x2600 <= o <= 0x27BF):
                    continue  # 💬 убираем эмодзи из имени только для рейтинга
                cleaned.append(ch)

            raw = "".join(cleaned).strip()

            if len(raw) > NAME_COL:
                raw = raw[:max(0, NAME_COL - 3)] + "..."  # 💬 длинное имя = обрезаем
            pad = nbsp * max(0, NAME_COL - len(raw))
            return f"{raw}{pad}"  # 💬 добивка до фикс ширины


        def _mark_cell(is_me: bool) -> str:
            # 💬 маркер для строки пользователя без лишних пробелов (телефонная версия не ломается)
            return "> " if is_me else ""


        def _rank_cell(pos: int) -> str:
            # 💬 фикс-ячейка ранга без лишнего пробела в конце
            base = f"{pos})"
            pad = nbsp * max(0, RANK_COL - len(base))
            return f"{base}{pad}"


        def _under_name(text: str) -> str:
            # 💬 строка под колонкой имени с меньшими отступами
            # формат строки теперь = "{rank} {icon} {name} {emoji} {val}"
            name_pad = nbsp * (RANK_COL + 3)
            return f"{name_pad}{text}"


        def _line(pos: int, name: str, val: int, is_me: bool = False) -> str:
            # 💬 компактная строка, чтобы не переносило на телефоне
            icon = "🤓" if is_me else (place_icons.get(pos) or nbsp)
            name_cell = _name_cell(name)
            return f"{_mark_cell(is_me)}{_rank_cell(pos)} {icon} {name_cell} {emoji} {val}"


    
        sorted_all = sorted(
            users,
            key=lambda u: (int(u.get(key, 0) or 0), u.get("name", "")),
            reverse=True
        )
    
        res = [f"<b>{title}</b>", "<pre>"]  # 💬 <pre> = моноширинный шрифт, колонки реально выравниваются

        # 💬 “реальные + 30 фейковых” (без вывода строки “участников”)
        FAKE_ADD = 30
        real_count = len(sorted_all)
        total_count = real_count + FAKE_ADD
    

        actor_uid = (data.get("leaderboard_actor_uid") or "").strip()
        actor_name = (data.get("leaderboard_actor_name") or "").strip()
    
        current_uid = actor_uid or str(message.from_user.id)
        my_name = actor_name or (message.from_user.first_name or "Пользователь")  # 💬 имя вместо слова Ты

    
    
        if not sorted_all:
            # 💬 даже если данных нет = не падаем и показываем формат с моноширинным выравниванием
            res.append("Пока пусто")
            res.append(_under_name(f"↳{total_count}"))  # 💬 общее число участников
            me_line = _line(1, my_name, 0, is_me=True)  # 💬 строка пользователя отдельно (для выделения)

            res.append(me_line)  # 💬 строка пользователя внутри списка (не вылезает из <pre>)
            res.append("</pre>")  # 💬 закрываем моноширинный блок
            return "\n".join(res)

    
        # 💬 ищем позицию “тебя”
        my_rank = None
        my_val = 0
        for idx, u in enumerate(sorted_all, 1):
            if str(u.get("uid", "")) == str(current_uid):
                my_rank = idx
                my_val = int(u.get(key, 0) or 0)
                if not my_name or my_name == "Ты":
                    my_name = u.get("name", my_name)
                break
    
        if my_rank is None:
            # 💬 если вдруг юзера нет в xp_data — ставим его “после реальных”
            my_rank = min(real_count + 1, total_count)
            my_val = 0
    
        # 💬 топ-5
        top5 = sorted_all[:5]
        for idx, u in enumerate(top5, 1):
            val = int(u.get(key, 0) or 0)
            res.append(_line(idx, u.get("name", ""), val))  # 💬 выравнивание колонок как на скриншоте
        
        # 💬 сколько всего пользователей (пишем ровно под колонкой имени)
        if total_count > len(top5):
            res.append(_under_name(f"↳{total_count}"))  # 💬 общее число участников

        
        me_line = _line(my_rank, my_name, my_val, is_me=True) if my_rank > len(top5) else None  # 💬 строка пользователя отдельно (для выделения)

        if me_line:
            res.append(me_line)  # 💬 показываем пользователя внутри <pre> на новой строке после ↳

        res.append("</pre>")  # 💬 закрываем моноширинный блок
        return "\n".join(res)



    week_text = render_block("🏆 Рейтинг недели", "words_learned_week", "🍪")
    month_text = render_block("🏆 Рейтинг месяца", "words_learned_month", "🍪")


    last_menu_msg_id = data.get("last_menu_msg_id")
    if last_menu_msg_id:
        try:
            await bot.delete_message(message.chat.id, last_menu_msg_id)
        except Exception:
            pass

    # 💬 убираем ReplyKeyboard (старые кнопки меню), и даём интро перед рейтингом
    intro_msg = await message.answer("А теперь посмотрим, где ты среди толпы... 👀")  # 💬 интро рейтинга отдельным сообщением
    await state.update_data(
        leaderboard_intro_msg_id=intro_msg.message_id,
        leaderboard_intro_chat_id=intro_msg.chat.id,
    )  # 💬 сохраняем id, чтобы удалить при выходе из рейтинга



    menu_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В меню", callback_data="back_to_menu")]
        ]
    )

    legend = "🍪 = слов выучено"  # 💬 легенда для рейтинга


    await message.answer(f"{legend}\n\n{week_text}\n\n{month_text}", parse_mode="HTML", reply_markup=menu_kb)  # 💬 легенда перед блоками


# 🟢 Новый хендлер: Главное меню (/menu)
@dp.message(Command("menu"))
@track_handler
async def menu_handler(message: Message, state: FSMContext):
    # 💬 Возвращает пользователя к выбору категории
    await start_handler(message, state)



@dp.message(Command("stats"))
@track_handler
async def stats_handler(message: Message, state: FSMContext):
    # 💬 статистика только для админа
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    xp_data = load_xp_data()
    total_users = len(xp_data)

    now_ts = int(time.time())
    today = datetime.date.today().isoformat()
    since_24h = now_ts - 86400

    new_24h = 0
    words_total = 0
    words_today = 0

    from collections import Counter
    topics_words_total = Counter()

    # 💬 собираем по каждому пользователю: клики сегодня + слова по темам
    per_user_rows = []

    for uid, u in xp_data.items():
        if not isinstance(u, dict):
            continue

        if u.get("first_join", 0) >= since_24h:
            new_24h += 1

        stats = u.get("stats", {})
        words_total += int(stats.get("words_learned", 0) or 0)
        words_today += int(u.get("words_learned_today", 0) or 0)

        analytics = u.get("analytics", {})
        days = analytics.get("days", {})
        dayrec = days.get(today) if isinstance(days, dict) else None
        clicks_today = int(dayrec.get("clicks", 0) or 0) if isinstance(dayrec, dict) else 0

        tw = analytics.get("topics_words", {})
        user_topics = {}
        if isinstance(tw, dict):
            for tk, cnt in tw.items():
                try:
                    c_int = int(cnt or 0)
                except Exception:
                    continue
                if c_int > 0:
                    user_topics[tk] = c_int
                    topics_words_total[tk] += c_int

        per_user_rows.append({
            "uid": uid,
            "name": (u.get("name") or "").strip() or "Без имени",
            "tg_username": (u.get("tg_username") or "").strip(),
            "clicks_today": clicks_today,
            "topics": user_topics
        })

    def title_for_topic(key: str) -> str:
        # 💬 показываем название темы в статистике
        info = topics.get(key, {}) if isinstance(topics, dict) else {}
        t = (info.get("title") or info.get("name") or key)
        return t

    top_topics_words = topics_words_total.most_common(7)

    lines = []
    lines.append("<b>📊 Статистика бота</b>")
    lines.append(f"👥 Всего пользователей = <b>{total_users}</b>")
    lines.append(f"🆕 Новые за 24ч = <b>{new_24h}</b>")
    lines.append(f"🍪 Слов выучено всего = <b>{words_total}</b>")
    lines.append(f"🍪 Слов сегодня = <b>{words_today}</b>")

    lines.append("")
    lines.append("<b>👤 По пользователям</b>")
    lines.append("🖱 клики сегодня + 🍪 слова по темам")

    if per_user_rows:
        # 💬 выводим всех, сортировка по кликам сегодня (desc)
        per_user_rows.sort(key=lambda r: (r.get("clicks_today", 0), r.get("uid", "")), reverse=True)

        for r in per_user_rows:
            uname = f" {r['tg_username']}" if r.get("tg_username") else ""
            lines.append(f"• <b>{r['name']}</b>{uname} <code>{r['uid']}</code> = 🖱 <b>{r['clicks_today']}</b>")

            tdict = r.get("topics", {}) or {}
            if tdict:
                for tk, cnt in sorted(tdict.items(), key=lambda x: int(x[1] or 0), reverse=True):
                    lines.append(f"↳ {title_for_topic(tk)} = <b>{cnt}</b> 🍪")
            else:
                lines.append("↳ тем пока нет")

    else:
        lines.append("— пользователей нет —")

    lines.append("")
    lines.append("<b>🔝 Темы по словам (всего)</b>")
    if top_topics_words:
        for i, (tk, c) in enumerate(top_topics_words, 1):
            lines.append(f"{i}) {title_for_topic(tk)} = <b>{c}</b> 🍪")
    else:
        lines.append("— пока нет данных —")

    # 💬 режем на несколько сообщений, если слишком длинно
    chunk = ""
    for line in lines:
        add = line + "\n"
        if len(chunk) + len(add) > 3800:
            await message.answer(chunk, parse_mode="HTML")
            chunk = ""
        chunk += add

    if chunk.strip():
        await message.answer(chunk, parse_mode="HTML")

@dp.message(Command("stats_export"))
@track_handler
async def stats_export_handler(message: Message, state: FSMContext):
    # 💬 экспорт статистики файлом, только для админа
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    xp_data = load_xp_data()
    user_data = load_user_data()

    now_ts = int(time.time())
    today = datetime.date.today().isoformat()
    since_24h = now_ts - 86400

    total_users = len(xp_data)
    new_24h = 0
    words_total = 0
    words_today = 0

    from collections import Counter
    topics_words_total = Counter()
    users_out = []

    # 💬 готовим данные по каждому юзеру
    for uid, u in xp_data.items():
        if not isinstance(u, dict):
            continue

        if u.get("first_join", 0) >= since_24h:
            new_24h += 1

        stats = u.get("stats", {})
        words_total += int(stats.get("words_learned", 0) or 0)
        words_today += int(u.get("words_learned_today", 0) or 0)

        analytics = u.get("analytics", {})
        days = analytics.get("days", {})
        dayrec = days.get(today) if isinstance(days, dict) else None
        clicks_today = int(dayrec.get("clicks", 0) or 0) if isinstance(dayrec, dict) else 0

        tw = analytics.get("topics_words", {})
        topics_map = {}
        if isinstance(tw, dict):
            for tk, cnt in tw.items():
                try:
                    c_int = int(cnt or 0)
                except Exception:
                    continue
                if c_int > 0:
                    topics_map[tk] = c_int
                    topics_words_total[tk] += c_int

        users_out.append({
            "uid": uid,
            "name": (u.get("name") or "").strip() or "Без имени",
            "tg_username": (u.get("tg_username") or "").strip(),
            "first_join": int(u.get("first_join", 0) or 0),
            "clicks_today": clicks_today,
            "words_learned_total": int(stats.get("words_learned", 0) or 0),
            "words_learned_today": int(u.get("words_learned_today", 0) or 0),
            "topics_words": topics_map
        })

    export_payload = {
        "generated_at_ts": now_ts,
        "generated_at_date": today,
        "summary": {
            "total_users": total_users,
            "new_24h": new_24h,
            "words_total": words_total,
            "words_today": words_today
        },
        "topics_words_total": dict(topics_words_total),
        "users": users_out,

        # 💬 полный дамп, чтобы ты видел вообще всё
        "raw": {
            "xp_data": xp_data,
            "user_data": user_data
        }
    }

    export_path = f"/tmp/stats_export_{today}_{now_ts}.json"

    # 💬 пишем файл на диск и отправляем документом
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(export_payload, f, ensure_ascii=False, indent=2)

    try:
        await message.answer_document(
            document=FSInputFile(export_path),
            caption=f"📎 stats_export = {today} = users {total_users}"
        )
    finally:
        # 💬 чистим временный файл, чтобы не копился
        try:
            os.remove(export_path)
        except Exception:
            pass


@dp.callback_query(lambda c: c.data == "back_to_menu")
async def inline_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()  # 💬 убираем "часики" сразу, даже если дальше будет delete/edit

    data = await state.get_data()

    intro_id = data.get("leaderboard_intro_msg_id")
    intro_chat_id = data.get("leaderboard_intro_chat_id")
    if intro_id and intro_chat_id:
        try:
            await callback.bot.delete_message(chat_id=intro_chat_id, message_id=intro_id)
        except Exception:
            pass
        await state.update_data(
            leaderboard_intro_msg_id=None,
            leaderboard_intro_chat_id=None,
        )  # 💬 чистим сохранённое интро рейтинга при выходе в меню

    # 💬 TelegramBadRequest тут обычно из-за delete: message can't be deleted / message to delete not found
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        # 💬 если удалить нельзя = просто снимаем кнопки, чтобы не жать повторно и не ловить ошибку
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    return await start_handler(callback.message, state)  # 💬 возвращаем в выбор категории/тем без падений




async def safe_open_grammar_topic(message: Message, state: FSMContext):
    # 💬 безопасно открываем меню грамматики даже если текущее сообщение нельзя редактировать
    try:
        # 💬 снимаем кнопки с текущего экрана, чтобы не спамили кликами
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

        return await open_grammar_topic(message, state)

    except TelegramBadRequest:
        # 💬 fallback: создаём текстовое "хост-сообщение", которое точно можно редактировать
        host = None
        try:
            host = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        except Exception:
            host = message

        try:
            return await open_grammar_topic(host, state)
        except TelegramBadRequest:
            # 💬 последний fallback: хотя бы не падаем и возвращаем стандартное меню урока
            return await lesson_menu_handler(host, state)





    #   🟡 2️⃣ Выбор темы (choosing_topic)
# ================================================================================
@dp.callback_query(
    lambda c: c.data and c.data.startswith("topic:"),
    StateFilter(LessonStates.choosing_topic, LessonStates.waiting_subscription)
)
@track_handler
async def topic_chosen(query: CallbackQuery, state: FSMContext):
    await register_or_update_user(query.message)

    # 💬 Попробуем показать pop-up с коротким описанием темы
    topic_key = query.data.split(":", 1)[1]
    desc = topics.get(topic_key, {}).get("description", "")
    if desc:
        MAX_ALERT = 200
        alert_text = desc if len(desc) <= MAX_ALERT else desc[:MAX_ALERT - 3].rstrip() + "..."
        await query.answer(text=alert_text, show_alert=True)
    else:
        await query.answer()

    # 💬 В грамматике обычно редактируем это же сообщение (edit_text) = не удаляем его заранее
    is_gram = topics.get(topic_key, {}).get("category") == "gram"

    # 💬 Удаляем экран со списком тем сразу после выбора (и для грамматики тоже)
    try:
        await query.message.delete()
    except TelegramBadRequest:
        if menu_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=int(menu_msg_id))
            except (TelegramBadRequest, ValueError, TypeError):
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=message.chat.id,
                        message_id=int(menu_msg_id),
                        reply_markup=None
                    )  # 💬 fallback: снять inline-кнопки, если удалить нельзя
                except (TelegramBadRequest, ValueError, TypeError):
                    pass  # 💬 если id битый/сообщение уже исчезло = просто игнорируем


    old_topic = (await state.get_data()).get("selected_topic")
    if old_topic and old_topic != topic_key:
        await state.update_data(
            completed_phases=0,
            total_phases=0,
            current_stage=None,
            vocab_index=0,
            ex_index=0,
            video_index=0,
            vocab_done=0,
            vocab_done_per_phase={},          # 💬 ключевое: сброс прогресса по фазам, иначе 100% наследуется
            ex_done=0,
            done_dialog=0,
            redo_stack=[],
            redo_stack_text=[],               # 💬 сброс очереди повторов textquiz
            pending_textquiz=[],              # 💬 всегда список, чтобы логика очередей не путалась
            textquiz_seen=[],                 # 💬 чтобы новый топик не считал textquiz “уже показанным”
            last_prompt_id=None,              # 💬 чистим id последнего вопроса
            vocab_textquiz_prompt_id=None,    # 💬 чистим id textquiz вопроса
            last_oc_msg_id=None,              # 💬 на всякий случай, чтобы не удалить чужое
            offer_continue_target_idx=None,   # 💬 сброс точки прыжка
            unlocked=False,                   # 💬 новый топик стартует закрытым до 70%
            lex_mode_active=False,
        )  # 💬 сбрасываем прогресс, чтобы новый топик не наследовал 100%


    # 💬 Сохраняем выбранную тему в FSM
    await state.update_data(selected_topic=topic_key)

    user_id_str = str(query.from_user.id)

    # 0) Проверяем рекламную подписку:
    #    a) ещё не истекла по времени
    #    b) пользователь ВСЁ ЕЩЁ подписан на каналы из набора
    data = load_user_data()
    u = data.setdefault(user_id_str, {})
    ad = u.get("ad_subscription") or {}
    now = int(time.time())
    active = False  # 💬 отключаем проверку по времени = всегда показываем окно подписки


    if active and ad.get("channels"):
        all_ok = True
        for ch in ad["channels"]:
            try:
                member = await bot.get_chat_member(chat_id=ch, user_id=query.from_user.id)
                is_member = member.status in ("member", "administrator", "creator")
            except TelegramBadRequest:
                is_member = False

            if not is_member:
                all_ok = False
                # 💬 фиксируем момент отписки от канала и сбрасываем рекламную подписку
                sessions = u.setdefault("channels", {}).setdefault(ch, [])
                if sessions and sessions[-1].get("unsubscribed_at") is None:
                    sessions[-1]["unsubscribed_at"] = now
                u.pop("ad_subscription", None)
                save_user_data(data)
                break

        if all_ok:
            # 💬 подписка по времени активна и пользователь подписан на все каналы — пускаем в урок
            unlocked = u.setdefault("unlocked_topics", [])
            if topic_key not in unlocked:
                unlocked.append(topic_key)
                save_user_data(data)
            topic = topics.get(topic_key, {})  # 💬 достаём тему, чтобы понять category
            
            if topics.get(topic_key, {}).get("category") == "gram":
                return await safe_open_grammar_topic(query.message, state)  # 💬 грамматика: отдельное меню без TelegramBadRequest


            return await lesson_menu_handler(query.message, state)  # 💬 query = текущий CallbackQuery


    elif active:
        # 💬 есть active_until, но нет списка каналов — считаем подписку невалидной и сбрасываем
        u.pop("ad_subscription", None)
        save_user_data(data)


    # 1) Формируем пакет каналов для подписки из глобального списка
    channels_list = load_subscription_channels()
    all_user_data = load_user_data()
    u = all_user_data.setdefault(user_id_str, {})
    last_idx = u.get("last_subscription_channel_index", -1)

    required: list[str] = []

    if channels_list:
        # 💬 всегда показываем только 1 канал = первый в subscription_channels.json
        required = [channels_list[0]]
        u["last_subscription_channel_index"] = 0
    else:
        # 💬 Каналов нет = индекс не двигаем
        u["last_subscription_channel_index"] = last_idx


    save_user_data(all_user_data)

    # 💬 Сохраняем список каналов в state (для check_subscription и подсказок)
    await state.update_data(
        required_channel=required[0] if required else None,  # на всякий случай
        required_channels=required,
    )

    # 2) Если каналов нет — открываем тему без проверки
    if not required:
        data = load_user_data()
        u = data.setdefault(user_id_str, {})
        unlocked = u.setdefault("unlocked_topics", [])
        if topic_key not in unlocked:
            unlocked.append(topic_key)
            save_user_data(data)
        if topics.get(topic_key, {}).get("category") == "gram":
            return await safe_open_grammar_topic(query.message, state)  # 💬 грамматика: отдельное меню без TelegramBadRequest



        return await lesson_menu_handler(query.message, state)

    # 💬 Если юзер уже подписан на обязательный канал — не показываем окно подписки
    try:
        member = await bot.get_chat_member(chat_id=required[0], user_id=query.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except TelegramBadRequest:
        is_member = False

    if is_member:
        data = load_user_data()
        u = data.setdefault(user_id_str, {})

        unlocked = u.setdefault("unlocked_topics", [])
        if topic_key not in unlocked:
            unlocked.append(topic_key)

        # 💬 фиксируем сессию подписки (чтобы stats/история не были пустыми)
        ch = required[0]
        sessions = u.setdefault("channels", {}).setdefault(ch, [])
        if not sessions or sessions[-1].get("unsubscribed_at") is not None:
            sessions.append({"subscribed_at": now, "unsubscribed_at": None})

        # 💬 отключаем таймерный доступ = подписку проверяем каждый раз при входе в тему
        u.pop("ad_subscription", None)

        save_user_data(data)
        if topics.get(topic_key, {}).get("category") == "gram":
            return await safe_open_grammar_topic(query.message, state)  # 💬 грамматика: отдельное меню без TelegramBadRequest


        return await lesson_menu_handler(query.message, state)


    # 3) Каналы есть — показываем окно подписки с inline-кнопками
    channels_str = ", ".join(required)

    # 💬 Убираем старую reply-клавиатуру (лексика/грамматика)
    blank = await query.message.answer("\u00AD", reply_markup=ReplyKeyboardRemove())
    await blank.delete()

    await query.message.answer(
        "🔒 Для бесплатного доступа\n"
        "👇🏼 Подпишись на спонсорские каналы:",  # 💬 оффер 3-дневного доступа
        reply_markup=check_subscription_kb(topic_key, required),
    )


    # 💬 Переводим FSM в состояние ожидания проверки подписки
    await state.set_state(LessonStates.waiting_subscription)



@dp.callback_query(
    lambda c: c.data == "back_to_topics",
    StateFilter(LessonStates.waiting_subscription, LessonStates.choosing_topic)
)
@track_handler
async def cb_back_to_topics(callback: CallbackQuery, state: FSMContext):
    """
    💬 Инлайн-кнопка «⬅️ Назад» из окна подписки:
    возвращаем пользователя в главное меню выбора уровня/тем.
    """
    await callback.answer()
    # 💬 Удаляем сообщение с блоком подписки
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    # 💬 Возвращаемся в стартовый поток (главное меню)
    await start_handler(callback.message, state)


@dp.callback_query(StateFilter(LessonStates.choosing_topic), F.data == "topic_back")
@track_handler
async def topic_back_to_level(callback: CallbackQuery, state: FSMContext):
    """
    💬 Кнопка «👈 НАЗАД» в списке тем — возвращаемся к выбору уровня.
    """
    # 💬 Собираем клавиатуру уровней так же, как при выборе категории
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐥 Новичок",      callback_data="level:A0"),
         InlineKeyboardButton(text="😤 Начальный",    callback_data="level:A1-A2")],
        [InlineKeyboardButton(text="😼 Средний",      callback_data="level:B1-B2"),
         InlineKeyboardButton(text="🤓 Продвинутый",  callback_data="level:C1")],
        [InlineKeyboardButton(text="⬅️ Назад",        callback_data="level:back")]
    ])  # 💬 возврат к выбору уровня


    # 💬 Тот же текст, что и при первом показе уровней
    intro_text = random.choice(difficulty_intro_phrases) if difficulty_intro_phrases else \
        "😜 Отличный выбор! А теперь давай определимся с уровнем сложности:"

    # 💬 Показываем выбор уровней вместо списка тем
    await callback.message.edit_text(
        intro_text,
        reply_markup=inline_kb,
    )
    await state.set_state(LessonStates.choosing_level)
    await callback.answer()




@dp.callback_query(
    lambda c: c.data == "back_to_topics",
    StateFilter(LessonStates.waiting_subscription, LessonStates.choosing_topic)
)
@track_handler
async def cb_back_to_topics(callback: CallbackQuery, state: FSMContext):
    """
    💬 Кнопка «⬅️ Назад» из окна подписки:
    возвращаем пользователя в главное меню / выбор темы.
    """
    await callback.answer()
    # 💬 Убираем сообщение с каналами
    await callback.message.delete()
    # 💬 Минимально безопасно: возвращаемся в стартовый хендлер
    await start_handler(callback.message, state)




# ================================================================================
#   🧩 МОИ СЛОВА (my_words.json)
# ================================================================================

def build_mywords_menu_kb() -> InlineKeyboardMarkup:
    # 💬 главное меню «Мои слова»
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📖 Учить мои слова", callback_data="mywords:learn_new"),
            InlineKeyboardButton(text="🔁 Повторить выученные", callback_data="mywords:learn_repeat")
        ],
        [
            InlineKeyboardButton(text="➕ Добавить слово", callback_data="mywords:add_open"),
            InlineKeyboardButton(text="✏️ Редактировать", callback_data="mywords:edit_open")
        ],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="mywords:settings"),
         InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:back_main")],
    ])

def build_stop_kb() -> ReplyKeyboardMarkup:
    # 💬 кнопка выхода во время обучения
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏹ Стоп")]], resize_keyboard=True)

def build_offer_continue_kb() -> InlineKeyboardMarkup:
    # 💬 offer_continue как в vocab: продолжить или домой
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Продолжить", callback_data="mywords:continue"),
            InlineKeyboardButton(text="🏠 Домой", callback_data="mywords:home")
        ]
    ])

def mywords_build_categories_kb(categories: list, cb_prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    # 💬 список категорий инлайном (cb_prefix = действие)
    rows = [[InlineKeyboardButton(text=name, callback_data=f"{cb_prefix}:{i}")] for i, name in enumerate(categories)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def mywords_get_user_block(user_id: str) -> tuple[dict, dict]:
    # 💬 загружаем хранилище и блок пользователя
    store = load_my_words_data()
    u = ensure_my_words_user(store, user_id)
    return store, u

def mywords_get_categories(user_id: str) -> list:
    # 💬 список категорий в стабильном порядке
    _, u = mywords_get_user_block(user_id)
    cats = list(u.get("categories", {}).keys())
    cats.sort(key=lambda x: x.lower())
    return cats

def mywords_get_session_words(user_id: str) -> int:
    # 💬 читаем session_words из настроек
    _, u = mywords_get_user_block(user_id)
    n = int(u.get("settings", {}).get("session_words", 5) or 5)
    return max(1, min(n, 30))

def mywords_words_for_mode(u: dict, category: str, mode: str) -> list:
    # 💬 new = learned False, repeat = learned True
    words = list(u.get("categories", {}).get(category, []))
    if mode == "new":
        return [w for w in words if not w.get("learned")]
    return [w for w in words if w.get("learned")]

def mywords_all_es_in_category(u: dict, category: str) -> list:
    # 💬 все ES в категории (для вариантов quiz)
    words = list(u.get("categories", {}).get(category, []))
    return [w.get("es", "") for w in words if w.get("es")]

def mywords_build_quiz_options(correct_es: str, all_es: list) -> tuple[list, int]:
    # 💬 варианты для poll quiz (Telegram требует минимум 2 варианта)
    distractors = [x for x in all_es if x and x != correct_es]
    random.shuffle(distractors)

    options = [correct_es]
    while len(options) < 4 and distractors:
        options.append(distractors.pop())

    if len(options) < 2:
        options.append("не знаю")  # 💬 запасной вариант, чтобы poll не упал

    random.shuffle(options)
    return options, options.index(correct_es)

async def mywords_show_main_menu(message: Message, state: FSMContext):
    # 💬 возвращаемся в главное инлайн-меню без /start
    inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],
    
        [
            InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL),
            InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords"),
        ],

        [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts")],  # 💬 единое главное меню с подкастами

    
        [
            InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle"),
            InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses"),
        ],
    
        [
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),
            InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings"),
        ],
    ])  # 💬 выровненное главное меню


    menu_text = random.choice(menu_study_phrases) if menu_study_phrases else "Выбирай"  # 💬 рандомная фраза главного меню

    try:
        await message.edit_text(menu_text, reply_markup=inline_kb_main)
    except Exception:
        await smart_reply(message, menu_text, reply_markup=inline_kb_main)

    await state.set_state(LessonStates.choosing_category)

async def mywords_menu(message: Message, state: FSMContext):
    # 💬 показываем меню «Мои слова»
    user_id = str(message.chat.id)
    store, _ = mywords_get_user_block(user_id)
    save_my_words_data(store)  # 💬 гарантируем файл в Volume

    txt = "🧩 *Мои слова*\n\nВыбирай действие:"
    kb = build_mywords_menu_kb()

    try:
        await message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await smart_reply(message, txt, reply_markup=kb, parse_mode="Markdown")

    await state.set_state(LessonStates.mywords_menu)

async def mywords_show_categories(message: Message, state: FSMContext, mode: str):
    # 💬 список категорий для режима обучения
    user_id = str(message.chat.id)
    categories = mywords_get_categories(user_id)

    await state.update_data(mywords_mode=mode, mywords_categories=categories)

    if mode == "new":
        title = "📖 *Учить мои слова*\n\nВыбери категорию:"
        prefix = "mywords:learncat"
    else:
        title = "🔁 *Повторить выученные слова*\n\nВыбери категорию:"
        prefix = "mywords:repcat"

    if not categories:
        title += "\n\nПока нет категорий. Добавь слово."

    kb = mywords_build_categories_kb(categories, cb_prefix=prefix, back_cb="mywords:menu")

    try:
        await message.edit_text(title, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await smart_reply(message, title, reply_markup=kb, parse_mode="Markdown")

    await state.set_state(LessonStates.mywords_learn_choose_cat)

async def mywords_mark_learned(user_id: str, category: str, word_id: str):
    # 💬 отмечаем слово как выученное (learned=true)
    store, u = mywords_get_user_block(user_id)
    words = u.get("categories", {}).get(category, [])
    for w in words:
        if w.get("id") == word_id:
            w["learned"] = True
            break
    save_my_words_data(store)

async def mywords_send_next_quiz(message: Message, state: FSMContext):
    # 💬 следующий quiz RU=>ES, пока очередь не опустеет
    data = await state.get_data()
    queue = list(data.get("mywords_quiz_queue", []))
    pool = list(data.get("mywords_pool", []))

    if not queue:
        return await mywords_start_text_stage(message, state)  # 💬 все quiz закрыты

    word_id = queue.pop(0)
    word = next((w for w in pool if w.get("id") == word_id), None)
    if not word:
        await state.update_data(mywords_quiz_queue=queue)
        asyncio.create_task(_mywords_quiz_timeout_handler(
            poll_msg.poll.id, message.chat.id, state, delay=int(QUIZ_TIMEOUT_TASK_S)
        ))  # 💬 watchdog таймаут как в vocab, но без XP

        return await mywords_send_next_quiz(message, state)

    user_id = str(message.chat.id)
    _, u = mywords_get_user_block(user_id)
    category = data.get("mywords_category", "")
    all_es = mywords_all_es_in_category(u, category)

    options, correct_id = mywords_build_quiz_options(word.get("es", ""), all_es)
    question = f"Как по-испански: {word.get('ru','')}?"

    poll_msg = await bot.send_poll(
        chat_id=message.chat.id,
        question=question,
        options=options,
        type="quiz",
        correct_option_id=correct_id,
        open_period=QUIZ_OPEN_PERIOD_S,  # 💬 квиз живёт 12 сек как в vocab
        is_anonymous=False               # 💬 чтобы поведение было как в vocab
    )


    await state.update_data(
        mywords_quiz_queue=queue,
        mywords_current_word_id=word_id,
        mywords_current_correct_id=correct_id,
        mywords_current_poll_id=poll_msg.poll.id,
        mywords_current_poll_msg_id=poll_msg.message_id
    )
    await state.set_state(LessonStates.mywords_quiz)

async def _mywords_quiz_timeout_handler(poll_id: str, chat_id: int, state: FSMContext, delay: int):
    await asyncio.sleep(delay)

    # 💬 если уже не в mywords_quiz, то таймаут не срабатывает
    if await state.get_state() != LessonStates.mywords_quiz:
        return

    data = await state.get_data()
    if data.get("mywords_current_poll_id") != poll_id:
        return  # 💬 poll уже обработан ответом

    poll_msg_id = data.get("mywords_current_poll_msg_id")
    word_id = data.get("mywords_current_word_id")
    queue = list(data.get("mywords_quiz_queue", []))

    # 💬 таймаут = считаем как ошибку и возвращаем слово в конец
    if word_id:
        queue.append(word_id)

    await state.update_data(
        mywords_quiz_queue=queue,
        mywords_current_word_id=None,
        mywords_current_poll_id=None,
        mywords_current_correct_id=None,
        mywords_current_poll_msg_id=None
    )

    # 💬 останавливаем poll и чистим сообщение как в vocab
    try:
        if poll_msg_id:
            await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)
    except Exception:
        pass

    fb = None
    try:
        fb = await bot.send_message(chat_id, "⏱ Время вышло!")
    except Exception:
        pass

    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 пауза и удаляем poll + фидбек

    try:
        if poll_msg_id:
            await bot.delete_message(chat_id, poll_msg_id)
    except Exception:
        pass

    try:
        if isinstance(fb, Message):
            await bot.delete_message(chat_id, fb.message_id)
    except Exception:
        pass

    # 💬 fake message, чтобы переиспользовать mywords_send_next_quiz
    fc = Chat(id=chat_id, type="private")
    fu = User(id=chat_id, is_bot=False, first_name="")
    fake = Message(message_id=0, date=datetime.datetime.now(), chat=fc, from_user=fu, text="")

    return await mywords_send_next_quiz(fake, state)

async def mywords_start_text_stage(message: Message, state: FSMContext):
    # 💬 старт text стадии RU=>ES
    data = await state.get_data()
    pool = list(data.get("mywords_pool", []))
    queue = [w.get("id") for w in pool if w.get("id")]
    random.shuffle(queue)

    await state.update_data(mywords_text_queue=queue, mywords_current_word_id=None)
    return await mywords_send_next_text(message, state)

async def mywords_send_next_text(message: Message, state: FSMContext):
    # 💬 следующий text RU=>ES (ввод текста)
    data = await state.get_data()
    queue = list(data.get("mywords_text_queue", []))
    pool = list(data.get("mywords_pool", []))

    if not queue:
        mode = data.get("mywords_mode", "new")
        await smart_reply(message, "🎉 Готово! Возвращаю в список категорий.", reply_markup=ReplyKeyboardRemove())
        return await mywords_show_categories(message, state, mode)

    word_id = queue.pop(0)
    word = next((w for w in pool if w.get("id") == word_id), None)
    if not word:
        await state.update_data(mywords_text_queue=queue)
        return await mywords_send_next_text(message, state)

    prompt = f"Напиши по-испански: {word.get('ru','')}"
    msg = await smart_reply(message, prompt, reply_markup=build_stop_kb())  # 💬 сохраняем id вопроса как в vocab
    await state.update_data(
        mywords_text_queue=queue,
        mywords_current_word_id=word_id,
        mywords_last_prompt_id=msg.message_id  # 💬 чтобы удалить вопрос после ответа
    )
    
    # ✍️ маркер "пора писать" как в vocab
    asyncio.create_task(send_and_auto_delete_text(bot, message.chat.id, "✍️", delay=1))  # 💬 мини-подсказка

    await state.set_state(LessonStates.mywords_text)

# ─────────────────────────────────────────────────────────────
#   📌 Callback: навигация «Мои слова»
# ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "mywords:menu")
@track_handler
async def mywords_menu_any_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    return await mywords_menu(callback.message, state)  # 💬 открыть меню «Мои слова»

@dp.callback_query(F.data == "mywords:back_main")
@track_handler
async def mywords_back_main_any_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    return await mywords_show_main_menu(callback.message, state)  # 💬 назад в главное меню

@dp.callback_query(F.data == "mywords:learn_new")
@track_handler
async def mywords_learn_new_any_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    return await mywords_show_categories(callback.message, state, mode="new")  # 💬 учить новые

@dp.callback_query(F.data == "mywords:learn_repeat")
@track_handler
async def mywords_learn_repeat_any_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    return await mywords_show_categories(callback.message, state, mode="repeat")  # 💬 повтор

@dp.callback_query(F.data == "mywords:settings")
@track_handler
async def mywords_settings_any_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    txt = "⚙️ Настройки\n\nСколько слов учим за раз?\nНапиши число."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:menu")]])
    try:
        await callback.message.edit_text(txt, reply_markup=kb)
    except Exception:
        await smart_reply(callback.message, txt, reply_markup=kb)
    await state.set_state(LessonStates.mywords_settings_wait)

@dp.message(StateFilter(LessonStates.mywords_settings_wait))
@track_handler
async def mywords_settings_wait_number(message: Message, state: FSMContext):
    user_id = str(message.chat.id)
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await smart_reply(message, "Напиши число, например 5.")  # 💬 валидация числа

    n = max(1, min(int(raw), 30))
    store, u = mywords_get_user_block(user_id)
    u.setdefault("settings", {})["session_words"] = n
    save_my_words_data(store)

    await smart_reply(message, f"✅ Сохранено = {n}", reply_markup=ReplyKeyboardRemove())
    return await mywords_menu(message, state)

# ─────────────────────────────────────────────────────────────
#   ➕ Добавить слово
# ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "mywords:add_open")
@track_handler
async def mywords_add_open_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = str(callback.message.chat.id)
    categories = mywords_get_categories(user_id)
    await state.update_data(mywords_categories=categories)

    kb_rows = [[InlineKeyboardButton(text=name, callback_data=f"mywords:addcat:{i}")] for i, name in enumerate(categories)]
    kb_rows.append([InlineKeyboardButton(text="➕ Новая категория", callback_data="mywords:add_newcat")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    txt = "➕ Добавить слово\n\nВыбери категорию:"
    try:
        await callback.message.edit_text(txt, reply_markup=kb)
    except Exception:
        await smart_reply(callback.message, txt, reply_markup=kb)

    await state.set_state(LessonStates.mywords_add_choose_category)

@dp.callback_query(StateFilter(LessonStates.mywords_add_choose_category), F.data.startswith("mywords:addcat:"))
@track_handler
async def mywords_add_choose_cat_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    categories = data.get("mywords_categories", [])
    idx = int(callback.data.split(":")[-1])

    if idx < 0 or idx >= len(categories):
        return await mywords_menu(callback.message, state)

    category = categories[idx]
    await state.update_data(mywords_category=category)

    txt = (
        f"➕ Добавить слово\n\n"
        f"Категория: *{category}*\n\n"
        f"Отправь вот так: ES - RU\n"
        f"Пример: *Comer - Кушать*"
    )  # 💬 показываем пример формата ввода

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:add_open")]])
    try:
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await smart_reply(callback.message, txt, reply_markup=kb, parse_mode="Markdown")

    await state.set_state(LessonStates.mywords_add_input_pair)

@dp.callback_query(StateFilter(LessonStates.mywords_add_choose_category), F.data == "mywords:add_newcat")
@track_handler
async def mywords_add_newcat_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    txt = "➕ Новая категория\n\nНапиши название категории."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:add_open")]])
    try:
        await callback.message.edit_text(txt, reply_markup=kb)
    except Exception:
        await smart_reply(callback.message, txt, reply_markup=kb)
    await state.set_state(LessonStates.mywords_add_new_category)

@dp.message(StateFilter(LessonStates.mywords_add_new_category))
@track_handler
async def mywords_add_newcat_name(message: Message, state: FSMContext):
    user_id = str(message.chat.id)
    name = (message.text or "").strip()
    if not name:
        return await smart_reply(message, "Напиши название категории.")  # 💬 валидация

    store, u = mywords_get_user_block(user_id)
    cats = u.setdefault("categories", {})
    cats.setdefault(name, [])
    save_my_words_data(store)

    await state.update_data(mywords_category=name)
    await smart_reply(message, f"Категория выбрана: {name}\n\nОтправь строкой: ES - RU", reply_markup=ReplyKeyboardRemove())
    await state.set_state(LessonStates.mywords_add_input_pair)

@dp.message(StateFilter(LessonStates.mywords_add_input_pair))
@track_handler
async def mywords_add_input_pair(message: Message, state: FSMContext):
    es, ru = parse_es_ru_pair(message.text or "")
    if not es or not ru:
        return await smart_reply(message, "Формат такой: ES - RU")  # 💬 валидация формата

    await state.update_data(mywords_pending_pair={"es": es, "ru": ru})

    txt = f"Проверь:\n\nES: *{es}*\nRU: *{ru}*\n\nСохранить?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="mywords:add_save")],
        [InlineKeyboardButton(text="🗑 Отмена", callback_data="mywords:menu")]
    ])
    await smart_reply(message, txt, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(LessonStates.mywords_add_confirm)

@dp.callback_query(StateFilter(LessonStates.mywords_add_confirm), F.data == "mywords:add_save")
@track_handler
async def mywords_add_save_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = str(callback.message.chat.id)
    data = await state.get_data()
    category = data.get("mywords_category", "")
    pair = data.get("mywords_pending_pair") or {}

    store, u = mywords_get_user_block(user_id)
    cats = u.setdefault("categories", {})
    words = cats.setdefault(category, [])

    if len(words) >= 30:
        await smart_reply(callback.message, "В категории уже 30 слов. Создай новую категорию.")
        return await mywords_menu(callback.message, state)

    words.append({
        "id": gen_my_word_id(),
        "es": pair.get("es", ""),
        "ru": pair.get("ru", ""),
        "learned": False
    })
    save_my_words_data(store)

    await smart_reply(callback.message, "✅ Сохранено!")
    return await mywords_menu(callback.message, state)

# ─────────────────────────────────────────────────────────────
#   📖 Учить / 🔁 Повторить: выбор категории
# ─────────────────────────────────────────────────────────────

@dp.callback_query(StateFilter(LessonStates.mywords_learn_choose_cat), F.data.startswith("mywords:learncat:"))
@track_handler
async def mywords_choose_cat_new_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    categories = data.get("mywords_categories", [])
    idx = int(callback.data.split(":")[-1])
    if idx < 0 or idx >= len(categories):
        return await mywords_menu(callback.message, state)

    category = categories[idx]
    user_id = str(callback.message.chat.id)

    store, u = mywords_get_user_block(user_id)
    pool_words = mywords_words_for_mode(u, category, mode="new")
    if not pool_words:
        await smart_reply(callback.message, "В этой категории нет новых слов. Возвращаю к категориям.")
        return await mywords_show_categories(callback.message, state, mode="new")

    pool = []
    for w in pool_words:
        if not w.get("id"):
            w["id"] = gen_my_word_id()  # 💬 id нужен при дубликатах ES
        pool.append({"id": w["id"], "es": w.get("es",""), "ru": w.get("ru","")})
    save_my_words_data(store)

    quiz_queue = [w["id"] for w in pool]
    random.shuffle(quiz_queue)

    await state.update_data(
        mywords_category=category,
        mywords_mode="new",
        mywords_pool=pool,
        mywords_quiz_queue=quiz_queue,
        mywords_passed_in_session=0
    )

    await smart_reply(callback.message, f"📖 Категория: {category}\n\nСтадия 1 = quiz.", reply_markup=build_stop_kb())
    return await mywords_send_next_quiz(callback.message, state)

@dp.callback_query(StateFilter(LessonStates.mywords_learn_choose_cat), F.data.startswith("mywords:repcat:"))
@track_handler
async def mywords_choose_cat_repeat_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    categories = data.get("mywords_categories", [])
    idx = int(callback.data.split(":")[-1])
    if idx < 0 or idx >= len(categories):
        return await mywords_menu(callback.message, state)

    category = categories[idx]
    user_id = str(callback.message.chat.id)

    store, u = mywords_get_user_block(user_id)
    pool_words = mywords_words_for_mode(u, category, mode="repeat")
    if not pool_words:
        await smart_reply(callback.message, "В этой категории нет выученных слов. Возвращаю к категориям.")
        return await mywords_show_categories(callback.message, state, mode="repeat")

    pool = []
    for w in pool_words:
        if not w.get("id"):
            w["id"] = gen_my_word_id()
        pool.append({"id": w["id"], "es": w.get("es",""), "ru": w.get("ru","")})
    save_my_words_data(store)

    await state.update_data(
        mywords_category=category,
        mywords_mode="repeat",
        mywords_pool=pool,
        mywords_passed_in_session=0
    )

    await smart_reply(callback.message, f"🔁 Категория: {category}\n\nПовтор = только text.", reply_markup=build_stop_kb())
    return await mywords_start_text_stage(callback.message, state)

# ─────────────────────────────────────────────────────────────
#   ⏹ Стоп во время обучения (quiz/text)
# ─────────────────────────────────────────────────────────────

@dp.message(StateFilter(LessonStates.mywords_quiz, LessonStates.mywords_text), F.text == "⏹ Стоп")
@track_handler
async def mywords_stop_any(message: Message, state: FSMContext):
    await smart_reply(message, "Ок, стоп.", reply_markup=ReplyKeyboardRemove())  # 💬 выход в меню
    return await mywords_menu(message, state)

# ─────────────────────────────────────────────────────────────
#   Quiz стадия: poll_answer
# ─────────────────────────────────────────────────────────────
@dp.poll_answer(StateFilter(LessonStates.mywords_quiz))
@track_handler
async def mywords_poll_answer(poll_answer: PollAnswer, state: FSMContext):
    data = await state.get_data()
    if poll_answer.poll_id != data.get("mywords_current_poll_id"):
        return  # 💬 это не наш poll

    # 💬 отменяем watchdog таймаут
    await state.update_data(mywords_current_poll_id=None)

    selected = poll_answer.option_ids[0] if poll_answer.option_ids else None
    correct = data.get("mywords_current_correct_id")
    is_correct = (selected == correct)

    chat_id = poll_answer.user.id
    poll_msg_id = data.get("mywords_current_poll_msg_id")
    word_id = data.get("mywords_current_word_id")
    queue = list(data.get("mywords_quiz_queue", []))

    # 💬 закрываем poll
    try:
        if poll_msg_id:
            await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)
    except Exception:
        pass

    # 💬 реакция как в vocab
    if is_correct:
        try:
            if poll_msg_id:
                await bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=poll_msg_id,
                    reaction=[ReactionTypeEmoji(emoji="🎉")],
                    is_big=True
                )
        except Exception:
            pass

    # 💬 неверно = возвращаем слово в конец
    if not is_correct and word_id:
        queue.append(word_id)

    # 💬 чистим текущие маркеры poll
    await state.update_data(
        mywords_quiz_queue=queue,
        mywords_current_word_id=None,
        mywords_current_correct_id=None,
        mywords_current_poll_msg_id=None
    )

    # 💬 feedback как в vocab, но без XP
    fb = None
    try:
        if is_correct:
            fb = await bot.send_message(
                chat_id,
                random.choice(vocab_quiz_success_phrases) if vocab_quiz_success_phrases else "✅"
            )
        else:
            fb = await bot.send_message(chat_id, "❌ Ошибка. Вернёмся к этому слову ещё раз.")
    except Exception:
        pass

    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 пауза и удаляем poll + фидбек

    try:
        if poll_msg_id:
            await bot.delete_message(chat_id, poll_msg_id)
    except Exception:
        pass

    try:
        if isinstance(fb, Message):
            await bot.delete_message(chat_id, fb.message_id)
    except Exception:
        pass

    # 💬 fake message как в vocab, чтобы переиспользовать send_next_quiz
    fc = Chat(id=chat_id, type="private")
    fu = User(id=chat_id, is_bot=False, first_name="")
    fake = Message(message_id=0, date=datetime.datetime.now(), chat=fc, from_user=fu, text="")

    return await mywords_send_next_quiz(fake, state)


# ─────────────────────────────────────────────────────────────
#   Text стадия: ответ пользователя
# ─────────────────────────────────────────────────────────────

@dp.message(StateFilter(LessonStates.mywords_text))
@track_handler
async def mywords_text_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    prompt_id = data.get("mywords_last_prompt_id")  # 💬 id вопроса, чтобы удалить как в vocab
    pool = list(data.get("mywords_pool", []))
    word_id = data.get("mywords_current_word_id")
    word = next((w for w in pool if w.get("id") == word_id), None)
    if not word:
        return await mywords_send_next_text(message, state)

    user_answer = normalize_textquiz(message.text or "")
    correct = normalize_textquiz(word.get("es", ""))

    queue = list(data.get("mywords_text_queue", []))
    passed = int(data.get("mywords_passed_in_session", 0) or 0)
    mode = data.get("mywords_mode", "new")
    category = data.get("mywords_category", "")
    user_id = str(message.chat.id)

    if user_answer == correct:
        passed += 1  # 💬 считаем только правильно закрытые text
        await state.update_data(mywords_passed_in_session=passed)

        if mode == "new":
            await mywords_mark_learned(user_id, category, word_id)  # 💬 learned=true

        fb = await smart_reply(
            message,
            random.choice(vocab_quiz_success_phrases) if vocab_quiz_success_phrases else "✅"
        )  # 💬 фидбек как в vocab, но без XP

        await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 пауза перед зачисткой как в vocab

        to_delete = [prompt_id, message.message_id]  # 💬 вопрос + ответ пользователя
        if isinstance(fb, Message):
            to_delete.append(fb.message_id)          # 💬 удаляем фидбек

        for mid in to_delete:
            if not mid:
                continue
            try:
                await bot.delete_message(message.chat.id, mid)
            except TelegramBadRequest:
                pass  # 💬 если уже удалено/нельзя удалить

        session_words = mywords_get_session_words(user_id)
        if passed >= session_words and queue:
            await state.update_data(mywords_text_queue=queue, mywords_current_word_id=None)
            await smart_reply(message, "Продолжим или домой?", reply_markup=ReplyKeyboardRemove())
            await smart_reply(message, "Выбирай:", reply_markup=build_offer_continue_kb())
            return await state.set_state(LessonStates.mywords_offer_continue)

        await state.update_data(mywords_text_queue=queue, mywords_current_word_id=None)
        return await mywords_send_next_text(message, state)


    # 💬 неверно = возвращаем слово в конец очереди, learned не меняем
    queue.append(word_id)
    fb = await smart_reply(message, "❌ Ошибка. Попробуем ещё раз.")  # 💬 фидбек без XP

    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 пауза перед зачисткой как в vocab

    to_delete = [prompt_id, message.message_id]  # 💬 вопрос + ответ пользователя
    if isinstance(fb, Message):
        to_delete.append(fb.message_id)          # 💬 удаляем фидбек

    for mid in to_delete:
        if not mid:
            continue
        try:
            await bot.delete_message(message.chat.id, mid)
        except TelegramBadRequest:
            pass  # 💬 если уже удалено/нельзя удалить


    await state.update_data(mywords_text_queue=queue, mywords_current_word_id=None)
    return await mywords_send_next_text(message, state)





# ─────────────────────────────────────────────────────────────
#   offer_continue: продолжить или домой
# ─────────────────────────────────────────────────────────────

@dp.callback_query(StateFilter(LessonStates.mywords_offer_continue), F.data == "mywords:continue")
@track_handler
async def mywords_continue_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(mywords_passed_in_session=0)  # 💬 новый блок из N слов
    await smart_reply(callback.message, random.choice(vocab_quiz_success_phrases) if vocab_quiz_success_phrases else "✅")  # 💬 берём фразы как в vocab
    return await mywords_send_next_text(callback.message, state)

@dp.callback_query(StateFilter(LessonStates.mywords_offer_continue), F.data == "mywords:home")
@track_handler
async def mywords_home_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    mode = data.get("mywords_mode", "new")
    await state.update_data(mywords_passed_in_session=0)
    await smart_reply(callback.message, "Ок, домой.", reply_markup=ReplyKeyboardRemove())
    return await mywords_show_categories(callback.message, state, mode)

# ─────────────────────────────────────────────────────────────
#   ✏️ Редактирование (MVP) = удалить / изменить / переименовать
# ─────────────────────────────────────────────────────────────

def mywords_words_nav_kb(page: int, total_words: int, back_cb: str) -> InlineKeyboardMarkup:
    # 💬 навигация по страницам (10 слов)
    per_page = 10
    total_pages = (max(total_words, 1) - 1) // per_page + 1

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Пред", callback_data="mywords:page_prev"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️ След", callback_data="mywords:page_next"))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def mywords_render_words_page(user_id: str, category: str, page: int) -> tuple[str, int]:
    # 💬 возвращает текст страницы и общее кол-во слов
    _, u = mywords_get_user_block(user_id)
    words = list(u.get("categories", {}).get(category, []))
    total = len(words)

    if not words:
        return "Список пуст.", 0

    per_page = 10
    start = page * per_page
    end = start + per_page
    chunk = words[start:end]

    total_pages = (total - 1) // per_page + 1
    lines = [f"{i}) {w.get('es','')} = {w.get('ru','')}" for i, w in enumerate(chunk, start=start+1)]
    return f"Слова (страница {page+1}/{total_pages})\n" + "\n".join(lines), total

async def mywords_open_edit_category_menu(message: Message, state: FSMContext, category: str):
    # 💬 меню действий внутри выбранной категории
    await state.update_data(mywords_category=category, mywords_edit_page=0)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить слово", callback_data="mywords:edit_delete")],
        [InlineKeyboardButton(text="✏️ Изменить слово", callback_data="mywords:edit_change")],
        [InlineKeyboardButton(text="🗂 Переименовать категорию", callback_data="mywords:edit_rename")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="mywords:edit_open")]
    ])
    txt = f"✏️ Категория: *{category}*\n\nВыбери действие:"
    try:
        await message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await smart_reply(message, txt, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(LessonStates.mywords_edit_menu)

@dp.callback_query(F.data == "mywords:edit_open")
@track_handler
async def mywords_edit_open_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = str(callback.message.chat.id)
    categories = mywords_get_categories(user_id)
    await state.update_data(mywords_categories=categories)

    kb = mywords_build_categories_kb(categories, cb_prefix="mywords:editcat", back_cb="mywords:menu")
    txt = "✏️ Редактировать\n\nВыбери категорию:"
    try:
        await callback.message.edit_text(txt, reply_markup=kb)
    except Exception:
        await smart_reply(callback.message, txt, reply_markup=kb)

    await state.set_state(LessonStates.mywords_edit_choose_category)

@dp.callback_query(StateFilter(LessonStates.mywords_edit_choose_category), F.data.startswith("mywords:editcat:"))
@track_handler
async def mywords_edit_choose_cat_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    categories = data.get("mywords_categories", [])
    idx = int(callback.data.split(":")[-1])
    if idx < 0 or idx >= len(categories):
        return await mywords_menu(callback.message, state)

    return await mywords_open_edit_category_menu(callback.message, state, categories[idx])

@dp.callback_query(StateFilter(LessonStates.mywords_edit_menu), F.data == "mywords:edit_delete")
@track_handler
async def mywords_edit_delete_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    category = data.get("mywords_category", "")
    page = int(data.get("mywords_edit_page", 0) or 0)
    user_id = str(callback.message.chat.id)

    txt, total = await mywords_render_words_page(user_id, category, page)
    kb = mywords_words_nav_kb(page, total, back_cb="mywords:edit_open")

    await smart_reply(callback.message, txt + "\n\nНапиши номер строки для удаления.", reply_markup=kb)
    await state.set_state(LessonStates.mywords_edit_delete_wait)

@dp.callback_query(StateFilter(LessonStates.mywords_edit_delete_wait), F.data.in_({"mywords:page_prev", "mywords:page_next"}))
@track_handler
async def mywords_delete_nav_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    category = data.get("mywords_category", "")
    page = int(data.get("mywords_edit_page", 0) or 0)
    user_id = str(callback.message.chat.id)

    _, total = await mywords_render_words_page(user_id, category, page)
    max_page = max(0, (max(total, 1) - 1) // 10)

    if callback.data == "mywords:page_prev":
        page = max(0, page - 1)
    else:
        page = min(max_page, page + 1)

    await state.update_data(mywords_edit_page=page)
    txt, total = await mywords_render_words_page(user_id, category, page)
    kb = mywords_words_nav_kb(page, total, back_cb="mywords:edit_open")
    await smart_reply(callback.message, txt + "\n\nНапиши номер строки для удаления.", reply_markup=kb)

@dp.message(StateFilter(LessonStates.mywords_edit_delete_wait))
@track_handler
async def mywords_delete_wait_index(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await smart_reply(message, "Напиши номер строки числом.")  # 💬 валидация индекса

    idx = int(raw)
    data = await state.get_data()
    category = data.get("mywords_category", "")
    user_id = str(message.chat.id)

    _, u = mywords_get_user_block(user_id)
    words = list(u.get("categories", {}).get(category, []))
    if idx < 1 or idx > len(words):
        return await smart_reply(message, "Такого номера нет.")

    w = words[idx - 1]
    await state.update_data(mywords_pending_index=idx)

    txt = f"Удалить?\n\n{idx}) {w.get('es','')} = {w.get('ru','')}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Удалить", callback_data="mywords:delete_confirm")],
        [InlineKeyboardButton(text="🗑 Отмена", callback_data="mywords:edit_open")]
    ])
    await smart_reply(message, txt, reply_markup=kb)

@dp.callback_query(StateFilter(LessonStates.mywords_edit_delete_wait), F.data == "mywords:delete_confirm")
@track_handler
async def mywords_delete_confirm_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    idx = int(data.get("mywords_pending_index", 0) or 0)
    category = data.get("mywords_category", "")
    user_id = str(callback.message.chat.id)

    store, u = mywords_get_user_block(user_id)
    words = u.get("categories", {}).get(category, [])
    if 1 <= idx <= len(words):
        words.pop(idx - 1)
        save_my_words_data(store)

    await smart_reply(callback.message, "✅ Удалено!")
    return await mywords_open_edit_category_menu(callback.message, state, category)

@dp.callback_query(StateFilter(LessonStates.mywords_edit_menu), F.data == "mywords:edit_change")
@track_handler
async def mywords_edit_change_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    category = data.get("mywords_category", "")
    user_id = str(callback.message.chat.id)

    txt, total = await mywords_render_words_page(user_id, category, page=0)
    kb = mywords_words_nav_kb(0, total, back_cb="mywords:edit_open")
    await state.update_data(mywords_edit_page=0)

    await smart_reply(callback.message, txt + "\n\nНапиши номер строки для изменения.", reply_markup=kb)
    await state.set_state(LessonStates.mywords_edit_edit_index_wait)

@dp.message(StateFilter(LessonStates.mywords_edit_edit_index_wait))
@track_handler
async def mywords_edit_wait_index(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await smart_reply(message, "Напиши номер строки числом.")

    idx = int(raw)
    data = await state.get_data()
    category = data.get("mywords_category", "")
    user_id = str(message.chat.id)

    _, u = mywords_get_user_block(user_id)
    words = list(u.get("categories", {}).get(category, []))
    if idx < 1 or idx > len(words):
        return await smart_reply(message, "Такого номера нет.")

    w = words[idx - 1]
    await state.update_data(mywords_pending_index=idx)
    await smart_reply(message, f"Текущее:\n{idx}) {w.get('es','')} = {w.get('ru','')}\n\nОтправь новое: ES - RU")
    await state.set_state(LessonStates.mywords_edit_edit_pair_wait)

@dp.message(StateFilter(LessonStates.mywords_edit_edit_pair_wait))
@track_handler
async def mywords_edit_wait_pair(message: Message, state: FSMContext):
    es, ru = parse_es_ru_pair(message.text or "")
    if not es or not ru:
        return await smart_reply(message, "Формат такой: ES - RU")

    await state.update_data(mywords_pending_pair={"es": es, "ru": ru})
    data = await state.get_data()
    idx = int(data.get("mywords_pending_index", 0) or 0)

    txt = f"Сохранить изменения?\n\n{idx}) {es} = {ru}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="mywords:edit_save")],
        [InlineKeyboardButton(text="🗑 Отмена", callback_data="mywords:edit_open")]
    ])
    await smart_reply(message, txt, reply_markup=kb)

@dp.callback_query(StateFilter(LessonStates.mywords_edit_edit_pair_wait), F.data == "mywords:edit_save")
@track_handler
async def mywords_edit_save_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = str(callback.message.chat.id)
    data = await state.get_data()
    category = data.get("mywords_category", "")
    idx = int(data.get("mywords_pending_index", 0) or 0)
    pair = data.get("mywords_pending_pair") or {}

    store, u = mywords_get_user_block(user_id)
    words = u.get("categories", {}).get(category, [])
    if 1 <= idx <= len(words):
        words[idx - 1]["es"] = pair.get("es", "")
        words[idx - 1]["ru"] = pair.get("ru", "")
        save_my_words_data(store)

    await smart_reply(callback.message, "✅ Изменено!")
    return await mywords_open_edit_category_menu(callback.message, state, category)

@dp.callback_query(StateFilter(LessonStates.mywords_edit_menu), F.data == "mywords:edit_rename")
@track_handler
async def mywords_edit_rename_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    category = data.get("mywords_category", "")
    await smart_reply(callback.message, f"🗂 Переименовать\n\nТекущее: {category}\nНапиши новое название.")
    await state.set_state(LessonStates.mywords_edit_rename_wait)

@dp.message(StateFilter(LessonStates.mywords_edit_rename_wait))
@track_handler
async def mywords_rename_wait(message: Message, state: FSMContext):
    user_id = str(message.chat.id)
    new_name = (message.text or "").strip()
    if not new_name:
        return await smart_reply(message, "Напиши новое название.")  # 💬 валидация

    data = await state.get_data()
    old_name = data.get("mywords_category", "")

    store, u = mywords_get_user_block(user_id)
    cats = u.get("categories", {})
    if new_name in cats:
        return await smart_reply(message, "Такая категория уже есть.")

    cats[new_name] = cats.pop(old_name, [])
    save_my_words_data(store)

    await smart_reply(message, "✅ Переименовано!")
    return await mywords_menu(message, state)




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


    # 💬 Глобальный XP пользователя по теме (по всем фазам словаря)
    xp_json   = load_xp_data()
    total_usr = xp_json.get(str(message.chat.id), {})
    topic_xp  = total_usr.get("by_topic", {}).get(topic_key, 0)

    # 💬 Считаем ВСЕ квизы по теме:
    #    • top-level в фазах,
    #    • inline у text/photo (block.get("quiz")),
    #    • пулы bulk: quiz_pool / textquiz_pool
    base_quiz = sum(
        1 for ph in topic.get("vocab", [])
          for b in ph.get("vocab", [])
          if b.get("type") in ("quiz", "textquiz")
    )
    inline_quiz = sum(
        1 for ph in topic.get("vocab", [])
          for b in ph.get("vocab", [])
          if b.get("quiz")
    )
    pool_quiz = sum(
        len(ph.get("quiz_pool", [])) + len(ph.get("textquiz_pool", []))
        for ph in topic.get("vocab", [])
    )
    total_quizzes = base_quiz + inline_quiz + pool_quiz

    # 💬 Порог: 30 XP × кол-во квизов × 0.8 (округление вниз десятками)
    xp_threshold = math.floor(total_quizzes * 30 * 0.8 / 10) * 10
    await state.update_data(
        xp_threshold=xp_threshold,
        total_quizzes=total_quizzes,  # 💬 сохраняем для прогресса по квизам
    )

    # 💬 Разблокирование считаем ниже по прогрессу «Учить слова» (фазы)
    unlocked = data.get("unlocked", False)


    # 💬 Для отображения
    display_threshold = (xp_threshold // 10) * 10



    # ─────────────────────────────────────────────────────────────────────────────


    # 📚 Словарь → считаем **фазы**, а значит “done phases / total phases”
    phases = topic.get("vocab", [])
    total_phases = len(phases)
    per_phase    = data.get("vocab_done_per_phase", {})
    # сколько фаз полностью пройдено?
    completed_phases = 0
    total_phases_for_unlock = 0

    for ph in phases:
        link_cnt = len([b for b in ph.get("vocab", []) if "link" in b or "url" in b])
        if link_cnt <= 0:
            continue  # 💬 пустая/без ссылок фаза не считается пройденной и не участвует в %
        total_phases_for_unlock += 1

        if per_phase.get(ph.get("phase_id"), 0) >= link_cnt:
            completed_phases += 1  # 💬 фаза пройдена по ссылочным блокам

    # 💬 70% фаз словаря пройдено = разблокируем остальные разделы
    vocab_unlock_percent = (completed_phases / total_phases_for_unlock * 100) if total_phases_for_unlock else 0  # 💬 нет фаз = 0%
    unlocked = vocab_unlock_percent >= 70
    await state.update_data(unlocked=unlocked)

    stars = "⭐" * completed_phases + "☆" * (total_phases_for_unlock - completed_phases)




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

    # — Общий прогресс теперь по КВИЗАМ —
    total_quizzes = data.get("total_quizzes", 0)

    # 💬 что делает эта часть: считаем прогресс по уникально закрытым poll (poll_done_ids) + правильным textquiz
    poll_done_ids = data.get("poll_done_ids") or []
    quiz_correct_poll = max(data.get("quiz_correct_total", 0), len(poll_done_ids))
    quiz_correct_total = quiz_correct_poll + data.get("textquiz_correct", 0)

    if total_quizzes:
        # 💬 режем сверху, чтобы из-за пересдач не было > 100%
        capped_correct = min(total_quizzes, quiz_correct_total)
        percent = capped_correct / total_quizzes * 100

    else:
        # 💬 fallback: старая логика по словарю + упражнениям/видео/диалогам
        total_done = done_vocab + done_ex_link + dv_idx + done_dlg
        total_all  = total_vocab + total_ex_link + total_video + total_dlg
        percent    = (total_done / total_all * 100) if total_all else 0


    # 💬 Эмоджи-бар прогресса из 10 сегментов
    bar_len = 10

    # 💬 Всегда показываем хотя бы один зелёный сегмент (минимальный прогресс в меню)
    filled = int(percent / 100 * bar_len)
    if filled == 0:
        filled = 1
    if filled > bar_len:
        filled = bar_len

    empty = bar_len - filled
    bar2  = "🟩" * filled + "⬜️" * empty



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
    # 💬 Сначала текст с процентом, ниже — визуальный бар


    # — Мотивационная цитата по прогрессу —
    chosen_quotes = None
    for thresh, quotes in sorted(motivational_quotes.items()):
        if percent <= thresh:
            chosen_quotes = quotes
            break
    if not chosen_quotes:
        chosen_quotes = list(motivational_quotes.values())[-1]
    quote = random.choice(chosen_quotes)
    # 💬 Цитата в спойлере теперь и жирная, и наклонная
    parts.append(f"<tg-spoiler><b><i>“{quote}”</i></b></tg-spoiler>")



    # ─── ВСТАВКА: Learned Words в виде «печенек» ────────────────────────────
    xp_data = load_xp_data()
    user_id = str(message.chat.id)
    user = xp_data.get(user_id, {})
    reset_daily_words_if_needed(user)
    today = user.get("words_learned_today", 0)
    limit = user.get("words_daily_limit", 10)


    
    # 💬 звёзды по фазам = done True только по ➡️ на последнем фрагменте
    reading_packs = topic.get("reading", []) or []
    translate_packs = topic.get("translate", []) or []
    
    rd_all = data.get("lex_read_progress") or {}
    rd_topic = rd_all.get(topic_key, {}) if isinstance(rd_all, dict) else {}
    if not isinstance(rd_topic, dict):
        rd_topic = {}
    
    tr_all = data.get("lex_translate_progress") or {}
    tr_topic = tr_all.get(topic_key, {}) if isinstance(tr_all, dict) else {}
    if not isinstance(tr_topic, dict):
        tr_topic = {}
    
    done_read = sum(1 for i in range(len(reading_packs)) if isinstance(rd_topic.get(str(i)), dict) and rd_topic.get(str(i), {}).get("done"))
    done_translate = sum(1 for i in range(len(translate_packs)) if isinstance(tr_topic.get(str(i)), dict) and tr_topic.get(str(i), {}).get("done"))
    
    

    # 4) Подробный прогресс по разделам
    # 💬 Строим прогресс по разделам. Строку «Видео» показываем только,
    #     если в теме реально есть хотя бы одно видео.
    # 💬 прогресс бар как в грамматике: иконка + бар + проценты + ✅ на 100%
    def _bar(pct: float, width: int = 10) -> str:
        if pct < 0:
            pct = 0
        if pct > 1:
            pct = 1
        filled = int(round(pct * width))
        if filled <= 0:
            filled = 1  # 💬 минимум 1 сегмент
        if filled > width:
            filled = width
        return "█" * filled + "░" * (width - filled)

    def _line(icon: str, pct: float) -> str:
        p = int(pct * 100)
        if p > 100:
            p = 100
        tick = " ✅" if p >= 100 else ""
        return f"<b>{icon}  {_bar(pct, width=10)}  {p}%{tick}</b>"  # 💬 жирным вся строка прогресса (и цифры тоже)


    vocab_pct = (completed_phases / total_phases) if total_phases else 0.0
    tr_total = len(translate_packs)
    rd_total = len(reading_packs)
    tr_pct = (done_translate / tr_total) if tr_total else 0.0
    rd_pct = (done_read / rd_total) if rd_total else 0.0
    vid_pct = (dv_idx / total_video) if total_video else 0.0

    lines_pb = [
        _line("📖", vocab_pct),   # 💬 учить слова
        _line("📝", tr_pct),      # 💬 переводить
        _line("🙊", rd_pct),      # 💬 читать
    ]
    if total_video > 0:
        lines_pb.insert(2, _line("🎬", vid_pct))  # 💬 видео между переводом и чтением

    parts.append("<blockquote>" + "\n".join(lines_pb) + "</blockquote>")  # 💬 общий блок прогресса

    blocks_done = 0
    if total_phases and vocab_pct >= 0.999999:
        blocks_done += 1  # 💬 словарь закрыт на 100%
    if tr_total and done_translate >= tr_total:
        blocks_done += 1  # 💬 перевод закрыт на 100%
    if rd_total and done_read >= rd_total:
        blocks_done += 1  # 💬 читать закрыто на 100%
    if total_video and vid_pct >= 0.999999:
        blocks_done += 1  # 💬 видео закрыто на 100%


    parts.append(f"💯 <b>Блоков пройдено:</b> +{blocks_done}⭐")  # 💬 итог звёзд за 100% блоки

    # 💬 Если видео нет (total_video == 0), строка «🎬 Видео» вообще не попадёт в текст
    
    # 💬 показываем общий счётчик выученных слов (stats.words_learned) всегда
    learned = int((user.get("stats", {}) or {}).get("words_learned", 0) or 0)  # 💬 всего выучено слов
    parts.append(f"🍪 Слов выучено: {learned}")  # 💬 без плюса, всегда строкой




    # 3) Если ещё не разблокировано — строка «Набери минимум display_threshold»
    if not unlocked:
        parts.append(
            "🔒 <b>Набери минимум 70% 📖</b>\n"
        )

  
    # ────────────────────────────────────────────────────────────────────────

    # 5) XP по текущей теме
    # 💬 показываем именно XP по выбранной теме (by_topic), а не общий total_xp
    parts.append(f"🏆 <b>Опыт по теме: +{topic_xp} XP</b>")






    # Отправляем всем блоком через bot.send_message, чтобы избежать NotMounted
    menu_text = "\n\n".join(parts)

    progress_msg = await bot.send_message(message.chat.id, menu_text, parse_mode="HTML")
    await state.update_data(last_progress_msg_id=progress_msg.message_id)  # 💬 запоминаем id прогресс-блока для удаления при смене темы



    # — Кнопки меню с блокировкой потоков по флагу unlocked —
    category = data.get("chosen_category")

    # 💬 Раздел «Лексика»: убираем «Упражнения» и показываем инлайн-кнопки
    if category == "lex":
        # ...
        # 💬 Показываем кнопку «Видео» только если есть хотя бы одно видео в теме
        has_videos = total_video > 0
        has_translate = len(topic.get("translate", []) or []) > 0  # 💬 если нет раздела «Переводить» = кнопку не показываем

        if unlocked:
            # 💬 Строим ряды так, чтобы КАЖДАЯ кнопка была на своей строке (полная ширина)
            rows = [
                [InlineKeyboardButton(text="📖 Учить слова", callback_data="lex_menu:learn")],
            ]

            if has_translate:
                rows.append(
                    [InlineKeyboardButton(text="📝 Переводить", callback_data="lex_menu:translate")]
                )  # 💬 показываем только когда есть translate-паки

            rows.append(
                [InlineKeyboardButton(text="📖 Читать", callback_data="lex_menu:read")]
            )  # 💬 поток «Читать» всегда (если он у тебя есть по JSON)

            if has_videos:
                rows.append(
                    [InlineKeyboardButton(text="🎬 Видео", callback_data="lex_menu:video")]
                )
            rows.append(
                [InlineKeyboardButton(text="🔄 Сменить тему", callback_data="lex_menu:change_topic")]
            )

            inline_kb = InlineKeyboardMarkup(inline_keyboard=rows)
        else:
            # 💬 Заблокированный вариант — тоже одна кнопка в строке
            rows = [
                [InlineKeyboardButton(text="📖 Учить слова", callback_data="lex_menu:learn")],
            ]

            if has_translate:
                rows.append(
                    [InlineKeyboardButton(text="🔒 Переводить", callback_data="lex_menu:locked_translate")]
                )  # 💬 блокируемый «Переводить» тоже скрываем, если раздела нет

            rows.append(
                [InlineKeyboardButton(text="🔒 Читать", callback_data="lex_menu:locked_read")]
            )  # 💬 заблокирован «Читать»

            if has_videos:
                rows.append(
                    [InlineKeyboardButton(text="🔒 Видео", callback_data="lex_menu:locked_video")]
                )
            rows.append(
                [InlineKeyboardButton(text="🔄 Сменить тему", callback_data="lex_menu:change_topic")]
            )

            inline_kb = InlineKeyboardMarkup(inline_keyboard=rows)

        # 💬 В результате, если translate/videos пустые, соответствующие кнопки не показываем

        # 💬 В результате, если videos пустой, в меню останутся только:
        #     «Учить слова», «Читать» и «Сменить тему»

        # Финальный follow-up
        choice_text = random.choice(follow_up_phrases)

        # 🤖 показываем IT-стикер перед меню (не блокируем поток)
        try:
            sticker_id = random.choice(IT_MENU_STICKERS)  # 💬 1 из 5
            asyncio.create_task(
                send_and_auto_delete_sticker(bot, message.chat.id, sticker_id, delay=1.7)
            )  # 💬 task: показать и удалить через 1 сек без await
        except Exception:
            pass


        # 💬 отправляем меню урока и запоминаем его message_id для последующего удаления
        menu_msg = await smart_reply(
            message,
            f"<b>{choice_text}</b>",
            reply_markup=inline_kb,
            parse_mode="HTML"
        )
        await state.update_data(last_menu_msg_id=menu_msg.message_id)
        # 💬 меню на экране, значит считаем его НЕ скрытым
        await state.update_data(menu_hidden=False)

        await state.set_state(LessonStates.waiting_lesson_action)
        return

    # 💬 Все остальные категории (в т.ч. «Грамматика») оставляем на ReplyKeyboard
    buttons = [[KeyboardButton(text="📖 Учить слова")]]
    if unlocked:
        buttons.append([
            KeyboardButton(text="🎲 Упражнения"),
            KeyboardButton(text="🎬 Видео"),
            KeyboardButton(text="🙊 Читать"),
        ])
    else:
        buttons.append([
            KeyboardButton(text="🔒 Упражнения"),
            KeyboardButton(text="🔒 Видео"),
            KeyboardButton(text="🔒 Читать"),
        ])
    buttons.append([KeyboardButton(text="🔄 Сменить тему")])
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    # Финальный follow-up
    choice_text = random.choice(follow_up_phrases)
    # 🤖 показываем IT-стикер перед меню (не блокируем поток)
    try:
        sticker_id = random.choice(IT_MENU_STICKERS)  # 💬 1 из 5
        asyncio.create_task(
            send_and_auto_delete_sticker(bot, message.chat.id, sticker_id, delay=1.7)
        )  # 💬 task: показать и удалить через 1 сек без await
    except Exception:
        pass


    # 💬 отправляем меню урока и запоминаем его message_id для последующего удаления
    menu_msg = await smart_reply(
        message,
        f"<b>{choice_text}</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.update_data(last_menu_msg_id=menu_msg.message_id)
    await state.update_data(menu_hidden=False)  # 💬 флаг для защиты от двойного удаления

    await state.set_state(LessonStates.waiting_lesson_action)
    return





# ─────────────────────────────────────────────────────────
@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text == "🔄 Сменить тему")
@track_handler
async def change_topic(message: Message, state: FSMContext):
    # Сбрасываем все индексы и возвращаемся к выбору категории, но сохраняем done_dialog и xp
    done_dialog = (await state.get_data()).get("done_dialog", 0)
    xp = (await state.get_data()).get("xp", 0)
    data = await state.get_data()
    lex_translate_progress = data.get("lex_translate_progress") or {}  # 💬 сохраняем прогресс "Переводить" при смене темы
    progress_msg_id = data.get("last_progress_msg_id")
    menu_msg_id = data.get("last_menu_msg_id")

    # 💬 удаляем прогресс-блок и меню «Что делаем дальше?», чтобы не оставались старые кнопки/текст
    if progress_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=progress_msg_id)  # 💬 kwargs, чтобы не путать параметры
        except TelegramBadRequest:
            pass

    if menu_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=menu_msg_id)  # 💬 kwargs, чтобы не путать параметры
        except TelegramBadRequest:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=message.chat.id,
                    message_id=menu_msg_id,
                    reply_markup=None,
                )  # 💬 fallback: снять кнопки (kwargs, чтобы не уехать в business_connection_id)

            except TelegramBadRequest:
                pass

    await state.clear()
    # восстанавливаем накопленный прогресс по диалогам и xp
    await state.update_data(
        done_dialog=done_dialog,
        xp=xp,
        level=xp//100,
        lex_translate_progress=lex_translate_progress,  # 💬 восстанавливаем прогресс "Переводить"
    )

    return await start_handler(message, state)

@dp.callback_query(LessonStates.waiting_lesson_action, F.data.startswith("lex_menu:"))
@track_handler
async def lex_lesson_menu_router(callback: CallbackQuery, state: FSMContext):
    # 💬 маршрутизатор инлайн-кнопок меню «Лексика» (Учить слова / Читать / Видео / Сменить тему)
    return await lex_lesson_menu_inline(callback, state)


async def lex_lesson_menu_inline(callback: CallbackQuery, state: FSMContext):
    """
    💬 Инлайн-меню для раздела «Лексика»:
        • lex_menu:learn        → поток «Учить слова»
        • lex_menu:translate    → поток «Переводить» (твой текущий reading-пак)
        • lex_menu:read         → поток «Читать» (отдельно от «Переводить»)
        • lex_menu:video        → поток «Смотреть видео»
        • lex_menu:change_topic → вернуться к выбору темы
        • lex_menu:locked_*     → заблокированные кнопки (отказной стикер)
    """

    action = callback.data.split(":", 1)[1]

    # 🔒 Заблокированные кнопки «Читать» / «Видео» из инлайн-меню
    if action.startswith("locked_"):
        await callback.answer()
        # 💬 используем общий хендлер недоступных потоков (стикер + автоудаление)
        return await handle_unavailable_buttons(callback.message, state)


    # 📖 Учить слова — переиспользуем существующий хендлер
    if action == "learn":
        await callback.answer()
        return await show_phase_menu(callback.message, state)

    # 🔄 Сменить тему — тот же хендлер, что и у ReplyKeyboard
    if action == "change_topic":
        await callback.answer()

        # 💬 удаляем текущее меню целиком (текст + кнопки), чтобы не оставался "Прогресс" и "Что делаем дальше?"
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            # 💬 если удалить нельзя = максимально "очищаем" сообщение и снимаем кнопки
            try:
                await callback.message.edit_text("⠀", reply_markup=None)  # 💬 визуально пустой текст
            except TelegramBadRequest:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)  # 💬 хотя бы убираем кнопки
                except TelegramBadRequest:
                    pass

        return await change_topic(callback.message, state)


    # 📝 Переводить — стартуем поток translate (topic["translate"])
    if action == "translate":
        await callback.answer()  # 💬 снимаем «часики»

        data = await state.get_data()
        last_menu_msg_id = data.get("last_menu_msg_id")
        last_progress_msg_id = data.get("last_progress_msg_id")

        # 💬 чистим старое меню и прогресс, чтобы сверху не висели старые кнопки
        for mid in (last_menu_msg_id, last_progress_msg_id):
            if mid:
                try:
                    await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=mid)
                except Exception:
                    pass

        return await lex_translate_intro(callback.message, state)  # 💬 показываем фазы «Переводить»

    # 📖 Читать — пока переиспользуем тот же вход, но помечаем режим
    if action == "read":
        # 💬 Читать = сначала чистим старое меню и прогресс, потом показываем reading
        await callback.answer()

        data = await state.get_data()

        # 💬 удаляем старые сообщения меню и прогресса, чтобы не висели сверху
        for key in ("last_menu_msg_id", "last_progress_msg_id"):
            msg_id = data.get(key)
            if msg_id:
                try:
                    await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
                except Exception:
                    pass

        # 💬 на всякий случай удаляем текущее меню-сообщение с кнопками (если оно не совпало с last_menu_msg_id)
        try:
            await callback.message.delete()
        except Exception:
            pass

        await state.update_data(menu_hidden=True)  # 💬 фиксируем, что меню уже спрятали
        return await lex_read_intro(callback.message, state)



    # 🎬 Смотреть видео — показываем ссылку в слове + галочка «готово»
    if action == "video":
        await callback.answer()

        data = await state.get_data()
        topic_key = data.get("selected_topic")
        if not topic_key:
            # 💬 подстраховка: если тема не выбрана, возвращаем в /start-меню
            return await start_handler(callback.message, state)

        topic = topics.get(topic_key, {})
        videos = topic.get("videos", [])

        # 💬 если видео нет, ведём себя как с недоступной кнопкой
        if not videos:
            return await handle_unavailable_buttons(callback.message, state)

        idx = data.get("video_index", 0) or 0
        if idx < 0:
            idx = 0
        if idx >= len(videos):
            idx = len(videos) - 1

        video_item = videos[idx]

        # 💬 поддерживаем и dict, и просто строку-ссылку
        if isinstance(video_item, dict):
            link = video_item.get("link") or video_item.get("url") or ""
            title = video_item.get("title") or f"Видео {idx + 1}"
        else:
            link = str(video_item)
            title = f"Видео {idx + 1}"

        if not link:
            # 💬 если ссылки нет, считаем поток недоступным
            return await handle_unavailable_buttons(callback.message, state)

        # 💬 CTA-фраза, как в link-блоках словаря (типа «Жми сюда»)
        cta = random.choice(link_cta_phrases)

        # 💬 Текст: заголовок + кликабельное слово/фраза вместо голого линка
        text = f"🎬 <b>{title}</b>\n\n👉 <a href=\"{link}\">{cta}</a>"

        # 💬 Под видео: отметить просмотр, перейти к следующему, или вернуться в меню
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Просмотрено", callback_data="video:done")],
                [InlineKeyboardButton(text="➡️ Следующее видео", callback_data="video:next")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="video:menu")],
            ]
        )


        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        # 💬 состояние остаётся LessonStates.waiting_lesson_action,
        # прогресс по видео обновим при нажатии на «✅»
        return

    # Остальное (locked_*) — недоступно, даём тот же отказной стикер
    await callback.answer()
    return await handle_unavailable_buttons(callback.message, state)


# ────────────────────────────────────────────────────────────────────
# 📝 Поток «Переводить» (идентично "📚 Читать" из грамматики, но для лексики)
# ────────────────────────────────────────────────────────────────────

def _lex_translate_packs(topic: dict) -> list:
    # 💬 reading-паки лежат в topic["reading"] (CreateLessonBlock уже пишет туда)
    # 💬 перевод-паки лежат в topic["translate"]
    packs = topic.get("translate") or []  # 💬 что делает эта часть: отдельный ключ под «Переводить»

    return packs if isinstance(packs, list) else []

def _lex_translate_fragments(topic: dict, pack_idx: int) -> list:
    packs = _lex_translate_packs(topic)
    if pack_idx < 0 or pack_idx >= len(packs):
        return []
    frags = packs[pack_idx].get("fragments") or []
    return frags if isinstance(frags, list) else []

def _lex_render_translate_fragment(f) -> str:
    # 💬 «Переводить»: RU видно, ES скрыто в spoiler, hint видно
    if isinstance(f, str):
        s = (f or "").strip()
        return html.escape(s) if s else "Пустой фрагмент"

    if not isinstance(f, dict):
        return "Пустой фрагмент"

    es_txt = html.escape(str(f.get("es") or "").strip())
    ru_txt = html.escape(str(f.get("ru") or "").strip())
    hint_txt = html.escape(str(f.get("hint") or "").strip())

    lines = []
    if ru_txt:
        lines.append(f"<b>🇷🇺 {ru_txt}</b>")
    if es_txt:
        lines.append(f"<i>🇪🇸 <tg-spoiler>{es_txt}</tg-spoiler></i>")
    if hint_txt:
        lines.append(f"<b><i>{hint_txt}</i></b>")

    return "\n".join(lines).strip() or "Пустой фрагмент"


def _lex_kb_translate_packs(topic: dict, st: dict) -> InlineKeyboardMarkup:
    # 💬 интро экран: список фаз (паков) + выход в меню
    packs = _lex_translate_packs(topic)
    prog = st.get("lex_translate_progress") or {}
    rows = []

    for i, p in enumerate(packs):
        title = str(p.get("title") or f"Фаза {i+1}")
        ph = prog.get(str(i)) or {}
        if isinstance(ph, dict) and ph.get("done"):
            title = f"<s>{html.escape(title)}</s>"  # 💬 зачёркиваем при 100%
            btn_text = title
            # InlineKeyboardButton не поддерживает HTML в тексте кнопки, поэтому делаем ✅
            btn_text = f"✅ {str(p.get('title') or f'Фаза {i+1}')}"
        else:
            btn_text = str(p.get("title") or f"Фаза {i+1}")

        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"lex_tr:pack:{i}")])

    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="lex_tr:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _lex_kb_translate_controls() -> InlineKeyboardMarkup:
    # 💬 стрелки + кнопка назад к интро
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data="lex_tr:prev"),
                InlineKeyboardButton(text="➡️", callback_data="lex_tr:next"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="lex_tr:back"),
            ],
        ]
    )

async def _lex_mark_translate_seen(state: FSMContext, pack_idx: int, item_idx: int, total: int) -> None:
    # 💬 отмечаем просмотр фрагмента и готовность пака при 100%
    st = await state.get_data()
    prog = st.get("lex_translate_progress") or {}
    if not isinstance(prog, dict):
        prog = {}

    ph = prog.setdefault(str(pack_idx), {})
    if not isinstance(ph, dict):
        ph = {}
        prog[str(pack_idx)] = ph

    seen = ph.setdefault("seen", [])
    if not isinstance(seen, list):
        seen = []
        ph["seen"] = seen

    if 0 <= int(item_idx) < int(total):
        if int(item_idx) not in seen:
            seen.append(int(item_idx))

    pct = (len(set(seen)) / int(total)) if total else 0.0
    ph["pct"] = pct
    if pct >= 0.999999:
        ph["done"] = True  # 💬 done только при 100%

    await state.update_data(lex_translate_progress=prog)

async def lex_translate_intro(message: Message, state: FSMContext) -> None:
    # 💬 показываем список фаз "Переводить"
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        return await start_handler(message, state)

    topic = topics.get(topic_key, {})
    packs = _lex_translate_packs(topic)
    if not packs:
        await message.answer("📝 Пока нет фаз для «Переводить».")
        return await lesson_menu_handler(message, state)

    st = await state.get_data()
    await state.update_data(lex_section="translate_intro")  # 💬 чтобы навигация не конфликтовала
    await message.answer(
        "📝 Выбери фазу «Переводить»:",
        reply_markup=_lex_kb_translate_packs(topic, st),
    )

@dp.callback_query(LessonStates.waiting_lesson_action, F.data.startswith("lex_tr:pack:"))
@track_handler
async def lex_translate_open_pack(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        return await start_handler(cb.message, state)

    try:
        pack_idx = int(cb.data.split(":")[-1])
    except Exception:
        return

    topic = topics.get(topic_key, {})
    frags = _lex_translate_fragments(topic, pack_idx)
    if not frags:
        return await cb.message.edit_text(
            "📝 В этой фазе нет фрагментов.",
            reply_markup=_lex_kb_translate_packs(topic, st),
        )

    await state.update_data(
        lex_section="translate_view",
        lex_tr_pack_idx=pack_idx,
        lex_tr_item_idx=0,
    )  # 💬 фиксируем выбранный пак и индекс

    text = _lex_render_translate_fragment(frags[0])
    await _lex_mark_translate_seen(state, pack_idx, 0, len(frags))
    await cb.message.edit_text(text, reply_markup=_lex_kb_translate_controls(), parse_mode="HTML")

@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "lex_tr:back")
@track_handler
async def lex_translate_back_to_intro(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        return await start_handler(cb.message, state)

    topic = topics.get(topic_key, {})
    await state.update_data(lex_section="translate_intro")  # 💬 возвращаемся на интро
    await cb.message.edit_text(
        "📝 Выбери фазу «Переводить»:",
        reply_markup=_lex_kb_translate_packs(topic, st),
    )

@dp.callback_query(LessonStates.waiting_lesson_action, F.data.in_(["lex_tr:prev", "lex_tr:next"]))
@track_handler
async def lex_translate_nav(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    st = await state.get_data()
    if st.get("lex_section") != "translate_view":
        return

    topic_key = st.get("selected_topic")
    if not topic_key:
        return await start_handler(cb.message, state)

    topic = topics.get(topic_key, {})
    pack_idx = int(st.get("lex_tr_pack_idx") or 0)
    frags = _lex_translate_fragments(topic, pack_idx)

    if not frags:
        return await lex_translate_back_to_intro(cb, state)

    idx = int(st.get("lex_tr_item_idx") or 0)

    if cb.data.endswith("prev"):
        if idx <= 0:
            await cb.answer("Это начало", show_alert=False)
            return
        idx -= 1
    else:
        # 💬 конец = только сообщение, без смены экрана
        if idx >= len(frags) - 1:
            data = await state.get_data()
            topic_key = data.get("selected_topic")
            if topic_key:
                all_prog = data.get("lex_translate_progress") or {}
                if not isinstance(all_prog, dict):
                    all_prog = {}
                by_topic = all_prog.get(topic_key, {})
                if not isinstance(by_topic, dict):
                    by_topic = {}
                by_topic[str(pack_idx)] = {"done": True}  # 💬 что делает эта часть: 100% только по ➡️ на последнем
                all_prog[topic_key] = by_topic
                await state.update_data(lex_translate_progress=all_prog)
    
            await cb.answer("Это конец")
            return
        idx += 1

    await state.update_data(lex_tr_item_idx=idx)
    await _lex_mark_translate_seen(state, pack_idx, idx, len(frags))
    text = _lex_render_translate_fragment(frags[idx])
    await cb.message.edit_text(text, reply_markup=_lex_kb_translate_controls(), parse_mode="HTML")

@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "lex_tr:menu")
@track_handler
async def lex_translate_to_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    # 💬 убираем кнопки у текущего сообщения, чтобы не залипало
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.update_data(lex_section=None)  # 💬 выходим из потока "Переводить"
    return await lesson_menu_handler(cb.message, state)



# ────────────────────────────────────────────────────────────────────
# 📖 Поток «Читать» (topic["reading"])
# ────────────────────────────────────────────────────────────────────

def _lex_read_packs(topic: dict) -> list:
    # 💬 что делает эта часть: reading-паки лежат в topic["reading"]
    packs = topic.get("reading") or []
    return packs if isinstance(packs, list) else []

def _lex_read_fragments(topic: dict, pack_idx: int) -> list:
    packs = _lex_read_packs(topic)
    if pack_idx < 0 or pack_idx >= len(packs):
        return []
    frags = packs[pack_idx].get("fragments") or []
    return frags if isinstance(frags, list) else []

def _lex_render_read_fragment(f) -> str:
    # 💬 стиль как в подкастах: ES видно, RU спрятано, hint видно (💡 максимум одна)
    if isinstance(f, str):
        ru_txt = html.escape((f or "").strip())
        return (f"<i>🔹 <tg-spoiler>{ru_txt}</tg-spoiler></i>").strip() if ru_txt else "Пустой фрагмент"

    if not isinstance(f, dict):
        return "Пустой фрагмент"  # 💬 защита от мусора

    es_raw = str(f.get("es") or "").strip()
    ru_raw = str(f.get("ru") or "").strip()
    hint_raw = str(f.get("hint") or "").strip()

    bulb_in_text = ("💡" in es_raw) or ("💡" in ru_raw)  # 💬 если лампочка уже в тексте, не дублируем её в hint
    hint_clean = hint_raw.replace("💡", "").strip()      # 💬 убираем лампочку из самого hint-текста

    es_txt = html.escape(es_raw)
    ru_txt = html.escape(ru_raw)
    hint_txt = html.escape(hint_clean)

    lines = []
    if es_txt:
        lines.append(f"<b>🇪🇸 {es_txt}</b>")
    if ru_txt:
        lines.append(f"<i>🔹 <tg-spoiler>{ru_txt}</tg-spoiler></i>")
    if hint_txt:
        if bulb_in_text:
            lines.append(f"<b><i>{hint_txt}</i></b>")
        else:
            lines.append(f"<b><i>💡 {hint_txt}</i></b>")

    return "\n".join(lines).strip() or "Пустой фрагмент"


def _lex_kb_read_packs(topic: dict, st: dict, topic_key: str) -> InlineKeyboardMarkup:
    # 💬 список фаз + меню
    packs = _lex_read_packs(topic)
    all_prog = st.get("lex_read_progress") or {}
    by_topic = all_prog.get(topic_key, {}) if isinstance(all_prog, dict) else {}
    if not isinstance(by_topic, dict):
        by_topic = {}

    rows = []
    for i, p in enumerate(packs):
        if isinstance(by_topic.get(str(i)), dict) and by_topic.get(str(i), {}).get("done"):
            btn_text = f"✅ {str(p.get('title') or f'Фаза {i+1}')}"
        else:
            btn_text = str(p.get("title") or f"Фаза {i+1}")
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"lex_rd:pack:{i}")])

    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="lex_rd:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _lex_kb_read_controls() -> InlineKeyboardMarkup:
    # 💬 стрелки + назад + меню
    return InlineKeyboardMarkup(
        inline_keyboard = [
            [
                InlineKeyboardButton(text="⬅️", callback_data="lex_rd:prev"),
                InlineKeyboardButton(text="➡️", callback_data="lex_rd:next"),
            ],
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="lex_rd:menu")],  # 💬 без "Назад" как в грамматике
        ]
    )

async def lex_read_intro(message: Message, state: FSMContext) -> None:
    # 💬 интро экран фаз «Читать»
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        return await start_handler(message, state)

    topic = topics.get(topic_key, {})
    packs = _lex_read_packs(topic)
    if not packs:
        await message.answer("📖 Пока нет фаз для «Читать».")
        return await lesson_menu_handler(message, state)

    st = await state.get_data()
    await state.update_data(lex_section="read_intro")  # 💬 что делает эта часть: режим чтения
    await message.answer("📖 Выбери фазу «Читать»:", reply_markup=_lex_kb_read_packs(topic, st, topic_key))

@dp.callback_query(LessonStates.waiting_lesson_action, F.data.startswith("lex_rd:pack:"))
@track_handler
async def lex_read_open_pack(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        return await start_handler(cb.message, state)

    try:
        pack_idx = int(cb.data.split(":")[-1])
    except Exception:
        return

    topic = topics.get(topic_key, {})
    frags = _lex_read_fragments(topic, pack_idx)
    if not frags:
        return await cb.message.edit_text("📖 В этой фазе нет фрагментов.", reply_markup=_lex_kb_read_packs(topic, st, topic_key))

    await state.update_data(lex_section="read_view", lex_rd_pack_idx=pack_idx, lex_rd_item_idx=0)  # 💬 фиксируем фазу и индекс
    await cb.message.edit_text(_lex_render_read_fragment(frags[0]), reply_markup=_lex_kb_read_controls(), parse_mode="HTML")

@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "lex_rd:back")
@track_handler
async def lex_read_back_to_intro(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        return await start_handler(cb.message, state)

    topic = topics.get(topic_key, {})
    await state.update_data(lex_section="read_intro")  # 💬 назад на список фаз
    await cb.message.edit_text("📖 Выбери фазу «Читать»:", reply_markup=_lex_kb_read_packs(topic, st, topic_key))

@dp.callback_query(LessonStates.waiting_lesson_action, F.data.in_(["lex_rd:prev", "lex_rd:next"]))
@track_handler
async def lex_read_nav(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    st = await state.get_data()
    if st.get("lex_section") != "read_view":
        return

    topic_key = st.get("selected_topic")
    if not topic_key:
        return await start_handler(cb.message, state)

    topic = topics.get(topic_key, {})
    pack_idx = int(st.get("lex_rd_pack_idx") or 0)
    frags = _lex_read_fragments(topic, pack_idx)
    if not frags:
        await cb.answer("Пусто")
        return

    idx = int(st.get("lex_rd_item_idx") or 0)

    if cb.data.endswith("prev"):
        if idx <= 0:
            await cb.answer("Это начало")
            return
        idx -= 1
    else:
        if idx >= len(frags) - 1:
            all_prog = st.get("lex_read_progress") or {}
            if not isinstance(all_prog, dict):
                all_prog = {}
            by_topic = all_prog.get(topic_key, {})
            if not isinstance(by_topic, dict):
                by_topic = {}
            by_topic[str(pack_idx)] = {"done": True}  # 💬 100% только по ➡️ на последнем
            all_prog[topic_key] = by_topic
            await state.update_data(lex_read_progress=all_prog)

            await cb.answer("Это конец")
            return
        idx += 1

    await state.update_data(lex_rd_item_idx=idx)
    await cb.message.edit_text(_lex_render_read_fragment(frags[idx]), reply_markup=_lex_kb_read_controls(), parse_mode="HTML")

@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "lex_rd:menu")
@track_handler
async def lex_read_to_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    # 💬 удаляем сообщение со строфой/фрагментом, чтобы оно не висело при выходе из «Читать»
    try:
        await cb.message.delete()
    except Exception:
        # 💬 fallback: если удалить нельзя (например, старое сообщение) = хотя бы снимаем кнопки
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    await state.update_data(lex_section=None)  # 💬 выходим из «Читать»
    return await lesson_menu_handler(cb.message, state)


@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "video:done")
@track_handler
async def handle_video_done(callback: CallbackQuery, state: FSMContext):
    """
    💬 Обработчик галочки под видео:
        • инкрементирует video_index в state
        • возвращает пользователя в меню урока с обновлённым прогрессом по видео
    """
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        await callback.answer()
        return await start_handler(callback.message, state)

    topic = topics.get(topic_key, {})
    videos = topic.get("videos", [])
    total_video = len(videos)

    dv_idx = int(data.get("video_index", 0) or 0)

    if total_video:
        # 💬 не выходим за пределы количества видео:
        # dv_idx == total_video → все видео уже просмотрены, звёздочки полные
        new_idx = min(dv_idx + 1, total_video)
        await state.update_data(video_index=new_idx)

    await callback.answer("✅ Видео отмечено как просмотренное")
    # 💬 Возвращаемся в меню урока — там пересчитается строка «🎬 Видео: ...»
    return await lesson_menu_handler(callback.message, state)

@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "video:menu")
@track_handler
async def handle_video_menu(callback: CallbackQuery, state: FSMContext):
    # 💬 Убираем кнопки под видео и возвращаем в меню урока
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    return await lesson_menu_handler(callback.message, state)


@dp.callback_query(LessonStates.waiting_lesson_action, F.data == "video:next")
@track_handler
async def handle_video_next(callback: CallbackQuery, state: FSMContext):
    """
    # 💬 Следующее видео:
    #    1) отмечаем текущее как просмотренное (двигаем video_index)
    #    2) сразу показываем следующее видео, не возвращая в меню
    """
    await callback.answer()

    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        return await start_handler(callback.message, state)

    topic = topics.get(topic_key, {})
    videos = topic.get("videos", [])
    total_video = len(videos)

    if not videos:
        # 💬 если видео пропали = возвращаемся в меню
        return await lesson_menu_handler(callback.message, state)

    dv_idx = int(data.get("video_index", 0) or 0)

    # 💬 сдвигаем прогресс, но не выходим за предел
    new_idx = min(dv_idx + 1, total_video) if total_video else dv_idx
    await state.update_data(video_index=new_idx)

    # 💬 если дошли до конца — показываем кнопку возврата в меню
    if new_idx >= total_video:
        end_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="video:menu")]]
        )
        try:
            await callback.message.edit_text("✅ Все видео по этой теме отмечены как просмотренные", reply_markup=end_kb)
        except Exception:
            await callback.message.answer("✅ Все видео по этой теме отмечены как просмотренные", reply_markup=end_kb)
        return

    # 💬 показываем следующее видео (new_idx) в том же сообщении
    video_item = videos[new_idx]
    if isinstance(video_item, dict):
        link = video_item.get("link") or video_item.get("url") or ""
        title = video_item.get("title") or f"Видео {new_idx + 1}"
    else:
        link = str(video_item)
        title = f"Видео {new_idx + 1}"

    if not link:
        return await lesson_menu_handler(callback.message, state)

    cta = random.choice(link_cta_phrases)
    text = f"🎬 <b>{title}</b>\n\n👉 <a href=\"{link}\">{cta}</a>"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Просмотрено", callback_data="video:done")],
            [InlineKeyboardButton(text="➡️ Следующее видео", callback_data="video:next")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="video:menu")],
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # 💬 fallback: если edit невозможен — отправляем новым сообщением
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(LessonStates.waiting_lesson_action, lambda m: m.text == "🙊 Читать")
@track_handler
async def handle_read_dialogs_button(message: Message, state: FSMContext):
    # 💬 Прячем меню урока и клавиатуру перед запуском потока диалогов
    data = await state.get_data()

    if not data.get("menu_hidden"):
        last_menu_msg_id = data.get("last_menu_msg_id")
        if last_menu_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=last_menu_msg_id)
            except Exception:
                pass
    
        last_progress_msg_id = data.get("last_progress_msg_id")
        if last_progress_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=last_progress_msg_id)
            except Exception:
                pass
    
        await state.update_data(
            menu_hidden=True,
            last_menu_msg_id=None,
            last_progress_msg_id=None,
        )  # 💬 прячем и меню с кнопками, и главный прогресс-блок


    # 💬 Дополнительно убираем ReplyKeyboard и клик пользователя
    try:
        await message.answer("\u00AD", reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass
        
    # 🎲 Рандомный стикер при старте «Читать» (и авто-удаление)
    try:
        sticker_id = random.choice(READ_STICKERS)  # 💬 берём один из списка
        asyncio.create_task(
            send_and_auto_delete_sticker(bot, message.chat.id, sticker_id)
        )  # 💬 отправляем и удаляем стикер фоном, не блокируя выдачу фаз
    except Exception:
        pass


    # 💬 Запускаем поток чтения диалогов
    return await start_dialog_reading(message, state)


# 📦 ID стикеров для заблокированных кнопок
LOCKED_STICKERS = [
    "CAACAgIAAxkBAAE2o0poV00UvQJOb5YVn_jgwz-AvPn6aQACKgEAAlKJkSM_2dC0M_P_EjYE", 
    "CAACAgIAAxkBAAE2o05oV03D4cY4PL1miwaTIJkVesewoAACkxEAAvXroUgH6q_y069udjYE",
    "CAACAgIAAxkBAAE2o1BoV03m9PlLTn4Z5mKDqnajd6c1_wACRwMAAm2wQgNSVSv5NcWAgjYE",
    
]

# 🤖 IT-стикеры для показа перед меню урока (1 из 5, авто-удаление)
IT_MENU_STICKERS = [
    "CAACAgIAAxkBAAIQxGlEygsK1CDVEgABN6jOaVIBNjm1ogACYxAAAvaWQUmNof6XoMsbajYE",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQxmlEyhiFkQT7P9YSwAfd3Y8vg71nAAKrEgACGOJASeltNUEW4IxONgQ",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQymlEykJzr6fQAqvtgTTwaSLP55-UAALYLgACQ7nYSMxMa3UjThHMNgQ",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQsGlExWMckBjTRHgKTyp04F95eThGAAL9DAACBlBAS0k4CbFNG6-0NgQ",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQ0mlEypViSYH9C3sWzeF5VCQHvPYHAALkEgACOHUAAUoE0LZNVG4hoDYE",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQrmlExVAUmsZxZhqY6Q0sHedu9ArTAAJUXAACp2-AS1fkWR4Yo5d4NgQ",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQrGlExR9h-U-6mBmdpV3fI2VoD_D-AAKBAAPBnGAM6PbLODBd3jc2BA",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQ5GlEyzQYEAudwYG6_rO0dv5pmzRrAAJiAAPANk8TCvfTpUq3n5Q2BA",  # 💬 вставь ID
    "CAACAgIAAxkBAAIQ7mlEy3qSidLYSqSvNY-Pl4ybYs69AALyEgAC8aOgSNoW844h2hMwNgQ",  # 💬 вставь ID
]


# 📦 ID стикеров для кнопки «🙊 Читать»
READ_STICKERS = [
    "CAACAgIAAxkBAAIQrGlExR9h-U-6mBmdpV3fI2VoD_D-AAKBAAPBnGAM6PbLODBd3jc2BA",  # 💬 сюда вставь ID стикера
    "CAACAgIAAxkBAAIQrmlExVAUmsZxZhqY6Q0sHedu9ArTAAJUXAACp2-AS1fkWR4Yo5d4NgQ",  # 💬 сюда вставь ID стикера
    "CAACAgIAAxkBAAIQsGlExWMckBjTRHgKTyp04F95eThGAAL9DAACBlBAS0k4CbFNG6-0NgQ",  # 💬 сюда вставь ID стикера
    "CAACAgIAAxkBAAIQqmlExOTyYtYHvJFnaU8veDz7KCRdAAIPPAAC81LISNODlD5N8m0pNgQ",  # 💬 сюда вставь ID стикера
]


# 📦 Стикер для временно закрытого раздела «Грамматика»
GRAMMAR_LOCKED_STICKER = "CAACAgIAAxkBAAINjmksZviqm03_fPbJTCZirDrJdVwhAALDEAACyy6YSWRm4_6tdy94NgQ"  # 💬 сюда вставь ID нужного стикера


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
    await asyncio.sleep(AUTO_DELETE_STICKER_DELAY_S)  # 💬 ждём удаления отказного стикера






# 💬 Строит зачёркнутый текст через combining overlay
def strike(text: str) -> str:
    return "".join(ch + "\u0336" for ch in text)


# ========= 📘📘📘НАЧАЛО ПОТОКА ПО СЛОВАРЮ или ПО СЛОВАМ 📘📘📘 =============
# ================================================================================  
#   🟡 4️⃣ Поток «Учить слова» (showing_vocab)  
# ================================================================================  



@dp.message(LessonStates.waiting_lesson_action, F.text == "📖 Учить слова")
@track_handler
async def show_phase_menu(message: Message, state: FSMContext):
    data      = await state.get_data()

    count = data.get("phase_entry_count", 0) + 1
    await state.update_data(phase_entry_count=count)


    # 💬 Спрятать клавиатуру и убрать предыдущее меню ДО показа рекламы
    # 💬 Скрываем меню ОДИН раз и без «пустышек»
    data = await state.get_data()
    if not data.get("menu_hidden"):  # 💬 защита от двойного удаления
        last_menu_msg_id = data.get("last_menu_msg_id")
        if last_menu_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=last_menu_msg_id)
            except Exception:
                pass
        # 💬 помечаем как скрыто и чистим id
        await state.update_data(menu_hidden=True, last_menu_msg_id=None)
    # 💬 ReplyKeyboardRemove отдаём в СЛЕДУЮЩЕМ полезном сообщении (список фаз)




    # 💬 Если ранее уже показали рекламный блок (ad_shown) — не показываем его снова,
    # 💬 а продолжаем показывать выбор фаз (код ниже). В противном случае — ставим флаг
    # 💬 и отправляем рекламу (send_ad_block) — затем функция завершится (return).
    if data.get("ad_shown"):
        # 💬 Реклама уже была показана — очищаем маркер и продолжаем дальше (покажем фазы)
        await state.update_data(ad_shown=False, pending_phase=False)
    else:
        # 💬 Реклама ещё не показана — пометим и отправим её
        await state.update_data(ad_shown=True, pending_phase=True)
        return await send_ad_block(message, state)



    topic_key = data.get("selected_topic")
    phases    = topics.get(topic_key, {}).get("vocab", [])

    # ── Скрыть старую Reply-клавиатуру ОДИН раз, без дублей ──
    # 💬 что делает эта часть: если клавиатура ещё не скрыта — отправляем «пустышку» и сразу удаляем
    data = await state.get_data()
    if not data.get("menu_hidden"):
        try:
            blank = await message.answer('Загружаю...⏳', reply_markup=ReplyKeyboardRemove())
            await blank.delete()
        except Exception:
            pass
        await state.update_data(menu_hidden=True)  # 💬 фиксируем, чтобы не повторять



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
        display_name = f"📦 Пак слов {ph['phase_id']}"  # 💬 единый шаблон названий паков
        if mark:
            # зачёркиваем название пака и добавляем галочку
            name = strike(display_name)
            btn_text = f"{name}{mark}"
        else:
            btn_text = display_name


        buttons.append(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"topic_phase:{ph['phase_id']}"  # 💬 теперь только ID фазы
        )
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn] for btn in buttons])

    # 💬 Легенда по цветам книг и выбор фазы
    await message.answer(
        "Выбери фазу для изучения:",
        reply_markup=kb
    )

    await state.set_state(LessonStates.waiting_vocab_phase)


# ─────────────────────────────────────────────────────────
# 4️⃣ Поток «Учить слова» (start_vocab)

@track_handler  # 💬 теперь это просто обёртка для логирования
async def start_vocab(message: Message, state: FSMContext):

        # 💬 попытка удалить предыдущее меню урока, если мы его показывали
    data = await state.get_data()
    last_menu_msg_id = data.get("last_menu_msg_id")
    if last_menu_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=last_menu_msg_id)
        except Exception:
            pass
        await state.update_data(last_menu_msg_id=None)

    # 💬 дополнительно прячем клавиатуру, чтобы кнопки меню исчезли
    await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
    try:
        # 💬 можно убрать и сам пользовательский клик «Учить слова» для чистоты
        await message.delete()
    except Exception:
        pass


    # 1) Регистрируем пользователя (имя, время и т.п.)
    await register_or_update_user(message)
    # 2) Дайс-анимация
    dice_msg = await message.answer_dice(reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(DICE_DELETE_DELAY_S)  # 💬 короткая задержка под анимацию

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

    # 5) Если всё пройдено → Просто сообщаем и выходим в меню (без лишних кнопок)
    if idx >= len(vocab_list):
        await smart_reply(message, "🎉 Все задания в этой фазе пройдены!", reply_markup=ReplyKeyboardRemove())
        return await lesson_menu_handler(message, state)
        
    # 6) Сохраняем в state stats по текст-квизам (печеньки)
    max_cookies = sum(1 for b in vocab_list if b.get("type") == "textquiz") * 2  # 💬 1 фраза = 2 слова = 2 🍪
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


    # 💬 считаем общее число квизов внутри выбранной фазы (для прогресс-бара OfferContinue)
    total_quizzes_phase = 0
    if phase:
        total_quizzes_phase += len(phase.get("quiz_pool", [])) + len(phase.get("textquiz_pool", []))
    total_quizzes_phase += sum(1 for b in blocks if b.get("type") in ("quiz", "textquiz"))
    total_quizzes_phase += sum(1 for b in blocks if b.get("quiz"))

    # 1) фаза уже пройдена?
    if total and passed >= threshold:
        # 💬 Пытаемся показать pop-up, но не падаем, если callback уже «протух»
        try:
            await cb.answer("🎉 Фаза уже пройдена, ты красавчик!", show_alert=True)
        except TelegramBadRequest as e:
            # 💬 Игнорируем только ситуацию «query is too old», остальные ошибки пробрасываем
            if "query is too old" not in str(e):
                raise
        # обновим inline-клавиатуру (зачёркнутые + ✅ остались)
        return

    # 2) иначе — сначала быстро отвечаем на callback, потом удаляем prompt и стартуем/возобновляем словарь
    try:
        await cb.answer()   # 💬 убираем «часики» на кнопке
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            # 💬 если другая ошибка Telegram — не молчим
            raise

    try:
        await cb.message.delete()  # 💬 удаляем сообщение с фазами, если оно ещё существует
    except TelegramBadRequest:
        # 💬 сообщение уже удалено/устарело — продолжаем без падения
        pass

    data = await state.get_data()
    prev_phase = data.get("selected_phase_id")

    # Если переключаемся на новую фазу — инициализируем счётчики
    if prev_phase != phase_id:
        await state.update_data(
            selected_phase_id       = phase_id,
            vocab_index             = 0,
            failed_vocab            = [],
            total_quizzes_phase     = total_quizzes_phase,  # 💬 total квизов именно в этой фазе
            quiz_correct_phase      = 0,                     # 💬 правильные poll-quiz внутри фазы
            textquiz_correct_phase  = 0,                     # 💬 правильные textquiz внутри фазы
        )

    else:
        # если возвращаемся в ту же фазу — просто обновляем ID фазы, остальные данные сохраняем
        await state.update_data(
            selected_phase_id   = phase_id,
            total_quizzes_phase = total_quizzes_phase,  # 💬 чтобы всегда был актуальный total по фазе
        )


    # 💬 показываем «загрузку» и удаляем её через 5 сек (не блокируем переход)
    asyncio.create_task(
        send_and_auto_delete_text(
            bot,
            cb.message.chat.id,
            "Гружу...🙄",
            delay=5
        )
    )

    return await start_vocab(cb.message, state)


# ─────────────────────────────────────────────────────────



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


   
# 🚩 ПРОВЕРКА ЗАВЕРШЕНИЯ СПИСКА
    if idx >= len(vocab_list):
        data = await state.get_data()
        failed = data.get("failed_vocab", [])
        
        # 1. Если есть ошибки — идем в ревью
        if failed:
            await state.set_state(LessonStates.review_failed_vocab)
            chat_id = message.chat.id if hasattr(message, "chat") else message.id
            return await send_failed_vocab(chat_id, state)

        # 💬 что делает эта часть: если это ALL IN (lex_mode_active) и раунды ещё не закончились = собираем следующий раунд, а не выходим в меню
        if data.get("lex_mode_active"):
            current_round = int(data.get("lex_round", 0) or 0)
            total_rounds = int(data.get("lex_round_total", 0) or 0)

            if total_rounds and current_round < (total_rounds - 1):
                next_round = current_round + 1
                await _lex_prepare_round_session(state, round_idx=next_round)

                data_after = await state.get_data()
                if not data_after.get("lex_session_vocab_list"):
                    # 💬 что делает эта часть: если следующий раунд пустой = завершаем без зацикливания
                    chat_id_local = message.chat.id if hasattr(message, "chat") else message.id
                    await send_and_auto_delete_text(
                        bot, chat_id_local,
                        "⚠️ Следующий раунд пустой. Проверь ALL IN: у каждой фразы должны быть polls и textquiz.",
                        delay=3
                    )
                    await state.update_data(lex_mode_active=False, lex_session_vocab_list=[])
                    return await lesson_menu_handler(message, state)

                chat_id_local = message.chat.id if hasattr(message, "chat") else message.id
                total = data_after.get("lex_round_total", total_rounds)
                asyncio.create_task(
                    send_and_auto_delete_text(
                        bot, chat_id_local,
                        f"Раунд {next_round + 1} из {total}",
                        delay=2
                    )
                )  # 💬 показываем короткий заголовок раунда без блокировки

                await state.set_state(LessonStates.showing_vocab)
                return await send_one_vocab(message, state)


        # 2. Если ошибок нет — финализируем
        chat_id = message.chat.id if hasattr(message, "chat") else message.id
        
        if not data.get("vocab_finished_once"):
            await bot.send_message(chat_id, "🎉 Ты красавчик, все задания пройдены!")
            await state.update_data(vocab_finished_once=True)
            
        # 💬 Прямой выход в меню урока
        return await lesson_menu_handler(message, state)
    
    # 📦 Берём текущий блок – сразу, один раз
    block = vocab_list[idx]
    btype = block.get("type", "link")

    btype = block.get("type")

    if btype == "phrase_selector":
        # 💬 что делает эта часть: показываем список фраз, даём удалить известные индексы, затем стартуем раунды
        phase = _lex_get_selected_phase(data)
        phrases = phase.get("phrases", []) if isinstance(phase, dict) else []
        if not isinstance(phrases, list) or not phrases:
            # если по ошибке нет phrases = пропускаем блок
            await state.update_data(vocab_index=idx + 1)
            return await send_one_vocab(message, state)

        # инициализация только один раз на вход в фазу
        if not isinstance(data.get("lex_active_phrases"), list):
            await state.update_data(
                lex_active_phrases=list(phrases),
                lex_round=0,
                lex_round_total=_lex_detect_total_rounds(list(phrases), default_total=4),
                lex_textquiz_phrase_cursor=0,
                lex_mode_active=False  # 💬 активируем только после нажатия Готово
            )

        data_now = await state.get_data()
        text = _lex_render_phrase_list(data_now.get("lex_active_phrases", []))

        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ Готово", callback_data="lex_phrases_done")]]
        )
        msg = await smart_reply(message, text, reply_markup=kb)

        await state.update_data(
            lex_phrases_msg_id=msg.message_id,
            lex_phrases_chat_id=msg.chat.id
        )
        await state.set_state(LessonStates.vocab_phrase_select)
        return


    if btype == "phrase_select":
        # 💬 показываем список фраз и ждём ввод номера
        topic_key = data.get("selected_topic")
        phase_id = data.get("selected_vocab_phase_id")
        phase = _get_vocab_phase(topic_key, phase_id)

        phrases = phase.get("phrases", [])
        hidden = set(data.get("session_hidden_phrases", []))
        active_indexes = _get_active_phrase_indexes(phrases, hidden)

        lines = [
            "📚 Фразы",
            "",
            "Напиши номер фразы, которую знаешь, чтобы скрыть из pull-quiz и textquiz.",
            "Когда закончишь = нажми ✅ Готово.",
            ""
        ]
        for n, real_idx in enumerate(active_indexes, start=1):
            ph = (phrases[real_idx] or {}).get("phrase", {}) or {}
            es = (ph.get("es") or "").strip()
            ru = (ph.get("ru") or "").strip()
            lines.append(f"{n}) {es} = {ru}".strip())

        if not active_indexes:
            lines.append("Пока нет фраз.")

        text = "\n".join(lines)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово", callback_data="lex_phrases_done")]
        ])

        chat_id = message.chat.id if hasattr(message, "chat") else message.id
        await _lex_cleanup_last_bot_message(chat_id, state)  # 💬 чистим прошлое сообщение перед списком фраз
        
        sent = await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
        await state.update_data(lex_last_bot_msg_id=sent.message_id)  # 💬 запоминаем последнее сообщение лексики

        await state.update_data(
            phrase_select_msg_id=sent.message_id,
            phrase_select_chat_id=sent.chat.id,
            current_stage="phrase_select",
            quiz_set_size=len(active_indexes),
        )
        return

    if btype == "round_header":
        # 💬 коротко показываем заголовок раунда и идём дальше
        round_num = int(block.get("round", 1))
        total_rounds = int(block.get("total_rounds", 4))

        header_msg = await message.answer(f"🔹 Раунд {round_num} из {total_rounds}")
        try:
            await asyncio.sleep(1.2)
            await header_msg.delete()
        except Exception:
            pass

        await state.update_data(vocab_index=idx + 1)
        await send_one_vocab(message, state)
        return



    # ——— Фото-блок ———
    if btype == "photo":
        return await send_one_vocab_photo(message, state)

    # ——— Quiz-блок ———
    if btype == "quiz":
        return await send_one_vocab_quiz(message, state)

    if btype == "textquiz":

        data = await state.get_data()
        vocab_list = get_vocab_list(data)

        # 💬 что делает эта часть: textquiz показываем только в финальной сессии, иначе копим индексы и пропускаем
        if not data.get("textquiz_session_active"):
            pending = data.get("pending_textquiz") or []
            if idx not in pending:
                pending.append(idx)  # 💬 копим textquiz для финала, не показывая между poll-сетами

            await state.update_data(pending_textquiz=pending, vocab_index=idx + 1)
            return await send_one_vocab(message, state)

        # 🔽 поддержка \n в JSON как переноса строки
        q = block.get("question", "")
        q = q.replace("\\n", "\n")

        # 💬 Спойлеры [[...]] → tg-spoiler
        q = q.replace("[[", '<span class="tg-spoiler">').replace("]]", "</span>")

        # 💬 что делает эта часть: помечаем показанный textquiz, чтобы не ловить дубли
        textquiz_seen = data.get("textquiz_seen", [])
        if idx not in textquiz_seen:
            textquiz_seen.append(idx)
            await state.update_data(textquiz_seen=textquiz_seen)

        msg = await smart_reply(message, q, reply_markup=ReplyKeyboardRemove())
        await state.update_data(last_prompt_id=msg.message_id)

        # ✍️ маленький маркер «пора писать» с авто-удалением
        asyncio.create_task(
            send_and_auto_delete_text(bot, message.chat.id, "✍️", delay=1)
        )
        return await state.set_state(LessonStates.vocab_textquiz)







    # ——— Text-блок ———
    if btype == "text":
        return await send_one_vocab_text(message, state)
    else:
        # 💬 default: link-блок
        # ——— Дальше обычный link-блок (без изменений) ———

        # ——— Link-блок: Title + кнопка-ссылка ———
        title = block.get("title", "Без названия")
        link  = block.get("link", "")

        # 💬 Анимированный эмодзи перед выдачей ссылки (не блокируем поток)
        chat_id = message.chat.id if hasattr(message, 'chat') else message.id
        asyncio.create_task(send_and_auto_delete_random_text(bot, chat_id, LINK_HINT_TEXTS, delay=LINK_HINT_DELETE_S))  # 💬 единая настройка

        await asyncio.sleep(LINK_HINT_DELETE_S)  # 💬 ждём пока подсказка «подышит»

        # 💬 чистим и валидируем ссылку, чтобы не падать на битом JSON
        link = str(link or "").strip().strip('"')
        if not (link.startswith("http://") or link.startswith("https://")):
            await state.update_data(vocab_index=idx + 1)  # 💬 пропускаем битый link-блок
            return await send_one_vocab(message, state)


        cta = random.choice(link_cta_phrases)
        link_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=cta, url=link)]
            ]
        )
        await bot.send_message(chat_id, f"<b>{title}</b>", reply_markup=link_kb, parse_mode="HTML")

        # 💬 Inline Confirm Done (через 2 сек после ссылки)
        scene = random.choice(scenarios["confirm_done"])
        await state.update_data(current_stage="confirm_done", current_scene=scene)
        await state.set_state(LessonStates.showing_vocab)

        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data=f"confirm_done:{btn}")
                for btn in scene["buttons"]
            ]]
        )
        chat_id = message.chat.id if hasattr(message, 'chat') else (await state.get_data())["last_chat_id"]
        return await bot.send_message(chat_id, scene["text"], reply_markup=inline_kb)  # 💬 отправляем кнопки


# ➕ ВСТАВЬ вот это после строки:
# return await bot.send_message(chat_id, scene["text"], reply_markup=inline_kb)  # 💬 отправляем кнопки
# и перед строкой:
# @track_handler
# 💬 что делает эта часть: добавляем безопасную загрузку рекламы из Railway (/data),
# чтобы не падать с NameError и молча пропускать рекламу, если она отключена/пустая.

ADS_DATA_PATH = "/data/ads_data.json"
ADS_DATA_BACKUP_PATH = "/data/ads_data_backup.json"

def load_ads_data() -> list:
    # 💬 что делает эта часть: читает ads_data.json из Railway, возвращает [] если файла нет/он пустой/битый
    import os
    import json

    candidates = [ADS_DATA_PATH, "ads_data.json"]  # 💬 fallback на локальный путь, если /data недоступен
    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            # 💬 поддерживаем оба формата: список или {"ads": [...]}
            if isinstance(raw, dict):
                ads = raw.get("ads", [])
            elif isinstance(raw, list):
                ads = raw
            else:
                ads = []

            # 💬 фильтруем битые элементы, чтобы send_ad_block не падал по KeyError
            clean = []
            for a in ads:
                if isinstance(a, dict) and a.get("channel_id") and a.get("message_id"):
                    clean.append(a)
            return clean
        except Exception:
            # 💬 не валим весь бот из-за рекламы
            return []

    return []

def save_ads_data(ads: list) -> None:
    # 💬 что делает эта часть: сохраняет рекламу в /data (Railway) в простом и безопасном формате
    import json
    try:
        with open(ADS_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump({"ads": ads or []}, f, ensure_ascii=False, indent=2)
    except Exception:
        # 💬 если /data недоступен, просто не сохраняем (не критично для ученического флоу)
        pass


@track_handler
async def send_ad_block(message: Message, state: FSMContext):
    ads = load_ads_data()
    if not ads:
        # 💬 если рекламы нет = молча продолжаем поток (без сообщений в чат)
        await state.update_data(pending_phase=False)  # 💬 снимаем флаг ожидания рекламы
        return await show_phase_menu(message, state)  # 💬 продолжаем дальше, не стопаемся

    

    data = await state.get_data()
    next_idx = data.get("ad_index", 0)
    ad = ads[next_idx % len(ads)]
    await state.update_data(ad_index=next_idx + 1)

    # 💬 форвардим, чтобы была шапка/глазки (не copy!)
    ad_msg = await bot.forward_message(
        chat_id=message.chat.id,
        from_chat_id=ad["channel_id"],
        message_id=ad["message_id"]
    )

    # 💬 одна кнопка OK, без вопросов/реакций
    ok_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅", callback_data="ad_ok")]
    ])

    # 💬 пробуем повесить кнопку прямо на форвард
    try:
        await bot.edit_message_reply_markup(
            chat_id=message.chat.id,
            message_id=ad_msg.message_id,
            reply_markup=ok_kb
        )
        ok_msg_id = None
    except Exception:
        # 💬 fallback: если нельзя редактировать форвард — шлём отдельную кнопку
        ok_msg = await message.answer("✅", reply_markup=ok_kb)
        ok_msg_id = ok_msg.message_id

    await state.update_data(
        current_ad_msg_id=ad_msg.message_id,
        current_ad_ok_msg_id=ok_msg_id,
        current_ad_question_id=None  # 💬 больше не используем
    )


@track_handler
@dp.callback_query(lambda c: c.data and c.data.startswith("ad_answer:"))
async def ad_reaction_handler(callback: CallbackQuery, state: FSMContext):
    # 💬 Обработчик клика по кнопке рекламы: показать реакцию, подождать 2с, удалить весь ad-блок, продолжить поток
    await callback.answer()  # 💬 acknowledge callback to avoid loading spinner
    data = await state.get_data()

    # 💬 Разбираем индексы из callback_data
    try:
        _, ad_idx_str, btn_idx_str = callback.data.split(":")
        ad_idx, btn_idx = int(ad_idx_str), int(btn_idx_str)
    except Exception:
        # 💬 некорректный формат — просто выйдем
        return

    ads = load_ads_data()
    reaction = None
    try:
        reaction = ads[ad_idx]["btns"][btn_idx]["reaction"]
    except Exception:
        reaction = "✅"  # 💬 fallback реакция

    chat_id = callback.message.chat.id
    bot_obj = callback.bot

    # 1) Показываем реакцию (видимое сообщение), сохраняем его id для удаления
    try:
        reaction_msg = await callback.message.answer(reaction)  # 💬 что увидит пользователь
        reaction_msg_id = reaction_msg.message_id
    except Exception:
        reaction_msg_id = None

    # 2) Ждём 2 секунды перед удалением всего рекламного блока
    await asyncio.sleep(AD_REACTION_DELETE_S)  # 💬 единая настройка задержки для рекламы


    # 3) Удаляем пост из канала (forwarded), вопрос с кнопками и саму реакцию (если есть)
    #    Используем те ключи, которые send_ad_block записывает в FSM: current_ad_msg_id, current_ad_question_id
    ad_msg_id = data.get("current_ad_msg_id")
    ad_q_id   = data.get("current_ad_question_id")

    for mid in (ad_msg_id, ad_q_id, reaction_msg_id):
        if mid:
            try:
                # 💬 удаляем без фатала (произойдёт молча, если сообщение уже удалено)
                await bot_obj.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                # 💬 игнорируем ошибки удаления (например, сообщение уже удалено)
                pass

    # 4) Очистим маркеры в state, чтобы логика дальше была корректной
    await state.update_data(pending_phase=False,
                            current_ad_msg_id=None,
                            current_ad_question_id=None)
        # 💬 что делает эта часть: фиксируем флаг до апдейта, чтобы избежать гонок и повторных вызовов меню
    was_pending = data.get("pending_phase")


    # 5) Продолжаем поток: если это был предфазный ad — возвращаемся в меню фаз, иначе — продолжаем vocab
    if was_pending:
        return await show_phase_menu(callback.message, state)


    return await send_one_vocab(callback.message, state)



@dp.callback_query(lambda c: c.data == "ad_ok")
@track_handler 
async def ad_ok_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    data = await state.get_data()
    chat_id = callback.message.chat.id

    ad_msg_id = data.get("current_ad_msg_id")
    ok_msg_id = data.get("current_ad_ok_msg_id")

    # 💬 сначала пробуем убрать inline-кнопку (если удаление вдруг не сработает)
    for mid in (ad_msg_id, ok_msg_id):
        if mid:
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
            except Exception:
                pass

    # 💬 удаляем сообщения рекламы (сам пост + отдельная кнопка, если была fallback)
    for mid in (ad_msg_id, ok_msg_id):
        if mid:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                pass

    was_pending_phase = data.get("pending_phase", False)

    # 💬 чистим state сразу, чтобы повторный тап не ломал логику
    await state.update_data(
        pending_phase=False,
        current_ad_msg_id=None,
        current_ad_ok_msg_id=None,
        current_ad_question_id=None
    )

    # 💬 имитация “гружу материал…” на 2 секунды и авто-удаление
    loading_msg = await bot.send_message(chat_id, "⏳ Гружу материал…")
    await asyncio.sleep(2)
    try:
        await bot.delete_message(chat_id, loading_msg.message_id)
    except Exception:
        pass

    # 💬 возвращаемся в тот же поток, что и раньше
    if was_pending_phase:
        return await show_phase_menu(callback.message, state)
    return await send_one_vocab(callback.message, state)


@dp.message(LessonStates.showing_vocab, F.text.regexp(r"^\s*\d+\s*$"))  # 💬 dp вместо router
@track_handler
async def lex_hide_phrase_by_number(message: Message, state: FSMContext):

    data = await state.get_data()
    if data.get("current_stage") != "phrase_select":
        return

    topic_key = data.get("selected_topic")
    phase_id = data.get("selected_vocab_phase_id")
    phase = _get_vocab_phase(topic_key, phase_id)

    phrases = phase.get("phrases", [])
    hidden = set(data.get("session_hidden_phrases", []))
    active_indexes = _get_active_phrase_indexes(phrases, hidden)

    try:
        n = int((message.text or "").strip())
    except Exception:
        return

    if n < 1 or n > len(active_indexes):
        # 💬 мягкая валидация индекса
        warn = await message.answer("⚠️ Нет такой строки. Напиши номер из списка.")
        try:
            await asyncio.sleep(1.2)
            await warn.delete()
            await message.delete()
        except Exception:
            pass
        return

    real_idx = active_indexes[n - 1]
    hidden.add(real_idx)

    await state.update_data(
        session_hidden_phrases=sorted(hidden),
        quiz_set_size=max(len(active_indexes) - 1, 0),
    )

    # 💬 обновляем список фраз (редактируем то же сообщение)
    new_active = _get_active_phrase_indexes(phrases, hidden)

    lines = [
        "📚 Фразы",
        "",
        "Напиши номер фразы, которую знаешь, чтобы скрыть из pull-quiz и textquiz.",
        "Когда закончишь = нажми ✅ Готово.",
        ""
    ]
    for nn, idx2 in enumerate(new_active, start=1):
        ph = (phrases[idx2] or {}).get("phrase", {}) or {}
        es = (ph.get("es") or "").strip()
        ru = (ph.get("ru") or "").strip()
        lines.append(f"{nn}) {es} = {ru}".strip())

    if not new_active:
        lines.append("Пока нет фраз.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="lex_phrases_done")]
    ])

    msg_id = data.get("phrase_select_msg_id")
    chat_id = data.get("phrase_select_chat_id") or message.chat.id
    try:
        if msg_id:
            await message.bot.edit_message_text(
                "\n".join(lines),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb
            )
    except Exception:
        pass

    try:
        await message.delete()
    except Exception:
        pass




@track_handler
async def send_failed_vocab(chat_id: int, state: FSMContext):
    data       = await state.get_data()
    # 💬 защитный сброс: при входе в ревью ошибок никаких запланированных textquiz быть не должно
    await state.update_data(pending_textquiz=[])

    vocab_list = get_vocab_list(data)  # 💬 берём актуальный список под текущую сессию (lex round или обычный)

    failed     = data.get("failed_vocab", [])
    idx        = failed[0]
    block      = vocab_list[idx]



    # ——— Повтор TEXTQUIZ и запоминаем ID сообщения для удаления
    if block.get("type") == "textquiz":
        # 1) подтягиваем вопрос, поддерживаем \n из JSON
        q = block.get("question", "").replace("\\n", "\n")

        # 2) конвертируем псевдо-спойлер [[...]] → HTML-формат Telegram
        #    [[PAGAR CON]] → <span class="tg-spoiler">PAGAR CON</span>
        q_html = re.sub(r"\[\[(.+?)\]\]", r'<span class="tg-spoiler">\1</span>', q)

        # 3) шлём отдельным сообщением и сохраняем message_id
        sent = await bot.send_message(chat_id, q_html, parse_mode="HTML")
        await state.update_data(last_failed_textquiz_message_id=sent.message_id)

        # 4) переходим в поток разбора ошибок textquiz
        await state.set_state(LessonStates.review_failed_textquiz)
        return



    # ——— Повтор встроенного quiz и запоминаем message_id для удаления
    if block.get("type") == "quiz":
        # 💬 что делает эта часть: в пересдаче тоже всегда 3 варианта, правильный = первый в options
        raw_opts = list(block.get("options") or [])
        correct_answer = (raw_opts[0].strip() if raw_opts and isinstance(raw_opts[0], str) else (block.get("correct_answer") or "").strip())
    
        wrong_pool: list[str] = []
        for o in raw_opts[1:]:
            if not o:
                continue
            oo = str(o).strip()
            if oo and oo != correct_answer and oo not in wrong_pool:
                wrong_pool.append(oo)
    
        opts = [correct_answer] + wrong_pool[:2]  # 💬 всегда 3 варианта
    
        if len(opts) < 3 or not correct_answer:
            # 💬 если блок битый = не падаем, убираем из начала очереди и идём дальше
            failed = (await state.get_data()).get("failed_vocab", [])
            if failed:
                await state.update_data(failed_vocab=failed[1:] + failed[:1])
            return await send_failed_vocab(chat_id, state)
    
        correct = block["correct_answer"]  # 💬 правильный ответ
        wrongs = [o for o in block.get("options", []) if o != correct]
        opts = [correct] + wrongs[:2]  # 💬 всегда 3 варианта
        random.shuffle(opts)
        correct_id = opts.index(correct)

        poll_msg = await bot.send_poll(
            chat_id=chat_id,
            question=_normalize_nl(block.get("question", "")),
            options=opts,
            type="quiz",
            correct_option_id=correct_id,
            is_anonymous=False,
            open_period=int(QUIZ_OPEN_PERIOD_S),
            explanation=f"✅ {correct_answer}"[:190]
        )
    
        # 💾 критично: сохраняем именно то, что реально отправили
        await state.update_data(
            last_chat_id=chat_id,  # 💬 нужно для удаления и реакций
            current_poll_id=poll_msg.poll.id,  # 💬 фильтрация ответов
            current_correct_option_id=correct_id,  # 💬 проверка правильности
            current_poll_message_id=poll_msg.message_id  # 💬 автоудаление
        )
    
        # 🚨 таймаут в пересдаче тоже нужен = иначе зависает на окончании времени
        asyncio.create_task(_review_failed_vocab_quiz_timeout_handler(
            poll_msg.poll.id, chat_id, state, delay=int(QUIZ_TIMEOUT_TASK_S)
        ))  # 💬 таймаут пересдачи
    
        await state.set_state(LessonStates.review_failed_vocab)
        return



    # создаём «фейковый» Message с нужным chat.id
    fake_chat = Chat(id=chat_id, type="private")
    fake_user = User(id=poll_answer.user.id, is_bot=False, first_name=poll_answer.user.first_name or "")
    fake_msg  = Message(
        message_id=0,
        date=datetime.datetime.now(),   # 💬 берём now() у класса datetime
        chat=fake_chat,
        from_user=fake_user,
        text=""
    )

    return await lesson_menu_handler(fake_msg, state)


@dp.message(LessonStates.vocab_phrase_select)
@track_handler
async def handle_vocab_phrase_select(message: Message, state: FSMContext):
    # 💬 что делает эта часть: ученик вводит номер фразы = скрываем её из сессионного списка и обновляем список

    txt = (message.text or "").strip()

    # чистим чат = удаляем любой мусорный ввод
    if not txt.isdigit():
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return

    idx = int(txt)
    data = await state.get_data()

    # 💬 при первом выборе цифры прячем главное меню и прогресс, чтобы не висели сверху
    if not data.get("menu_hidden"):
        last_menu_msg_id = data.get("last_menu_msg_id")
        last_progress_msg_id = data.get("last_progress_msg_id")

        if last_menu_msg_id:
            try:
                await bot.delete_message(message.chat.id, last_menu_msg_id)
            except Exception:
                pass

        if last_progress_msg_id:
            try:
                await bot.delete_message(message.chat.id, last_progress_msg_id)
            except Exception:
                pass

        await state.update_data(
            menu_hidden=True,
            last_menu_msg_id=None,
            last_progress_msg_id=None
        )

    phrases = data.get("lex_active_phrases") or []

    # если фраз нет = просто чистим ввод
    if not isinstance(phrases, list) or not phrases:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return

    # жёсткая валидация диапазона
    if idx < 1 or idx > len(phrases):
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return

    # нельзя удалить последнюю фразу = оставляем минимум 1
    if len(phrases) == 1:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return

    # удаляем выбранную фразу (индексы 1..N)
    phrases.pop(idx - 1)

    # корректируем курсор textquiz, чтобы "по очереди" не ломалось
    cursor = data.get("lex_textquiz_phrase_cursor", 0)
    if (idx - 1) < cursor:
        cursor = max(0, cursor - 1)

    await state.update_data(lex_active_phrases=phrases, lex_textquiz_phrase_cursor=cursor)

    # обновляем сообщение со списком фраз + оставляем кнопку Готово
    chat_id = data.get("lex_phrases_chat_id", message.chat.id)
    msg_id = data.get("lex_phrases_msg_id")
    if msg_id:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ Готово", callback_data="lex_phrases_done")]]
        )
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=_lex_render_phrase_list(phrases),
                reply_markup=kb
            )
        except Exception:
            pass

    # удаляем сообщение пользователя = чат не засоряем
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

@dp.message(LessonStates.vocab_phrase_select)
@track_handler
async def handle_vocab_phrase_select(message: Message, state: FSMContext):
    # 💬 пользователь пишет номер фразы, мы убираем её из сессионного списка и обновляем сообщение
    txt = (message.text or "").strip()

    if not txt.isdigit():
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return

    idx = int(txt)
    data = await state.get_data()
    active = data.get("lex_active_phrases", [])

    # жёсткая валидация индекса
    if idx < 1 or idx > len(active):
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return

    # удаляем выбранную фразу из сессионного списка
    active.pop(idx - 1)
    await state.update_data(lex_active_phrases=active)

    # удаляем сообщение пользователя с цифрой, чтобы не засорять чат
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # обновляем текст списка фраз (через edit_text у уже отправленного сообщения)
    phrases_msg_id = data.get("lex_phrases_msg_id")
    if phrases_msg_id:
        await _lex_update_phrase_list(message.chat.id, phrases_msg_id, state)  # 💬 перерисовываем список + кнопку "Готово"



@dp.callback_query(F.data == "lex_phrases_done", StateFilter(LessonStates.vocab_phrase_select))
@track_handler
async def handle_lex_phrases_done(cb: CallbackQuery, state: FSMContext):
    # 💬 что делает эта часть: фиксируем список фраз для сессии, собираем раунд 1, стартуем квизы
    await cb.answer()
    data = await state.get_data()

    # удаляем сообщение со списком
    chat_id = data.get("lex_phrases_chat_id")
    msg_id = data.get("lex_phrases_msg_id")
    if chat_id and msg_id:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
    # 💬 что делает эта часть: старт фазы ALL IN = фиксируем total и сбрасываем уникальный прогресс poll-квизов
    phrases = data.get("lex_active_phrases") or []
    if not isinstance(phrases, list):
        phrases = []
    total_rounds = data.get("lex_round_total") or _lex_detect_total_rounds(phrases, default_total=4)

    await state.update_data(
        poll_total_phase=len(phrases) * int(total_rounds or 0),
        poll_done_ids=[],
        quiz_correct_phase=0,
        quiz_correct_total=0,
        vocab_quiz_progress_msg_id=None,
        vocab_quiz_progress_last_phrase=None,
    )


    # собираем 1-й раунд (round_idx=0)
    await _lex_prepare_round_session(state, round_idx=0)

    data_check = await state.get_data()
    if not data_check.get("lex_session_vocab_list"):
        # 💬 что делает эта часть: если после сборки раунда нет poll/textquiz = выходим без зацикливания
        await send_and_auto_delete_text(
            bot, cb.message.chat.id,
            "⚠️ В этом раунде нет pull-quiz/textquiz. Проверь ALL IN: у каждой фразы должны быть polls и textquiz.",
            delay=3
        )
        await state.update_data(lex_mode_active=False, lex_session_vocab_list=[])
        return await lesson_menu_handler(cb.message, state)


    # заголовок раунда (авто-удаление)
    data2 = await state.get_data()
    total = data2.get("lex_round_total", 4)
    asyncio.create_task(send_and_auto_delete_text(bot, cb.message.chat.id, f"Раунд 1 из {total}", delay=2))

    await state.set_state(LessonStates.showing_vocab)
    return await send_one_vocab(cb.message, state)



# ------------------------------  
#   ПОТОК по показу type: quiz по VOCAB 📘📘📘
# ------------------------------

# 💬 что делает эта часть: рисуем и поддерживаем закреплённый прогресс-бар для poll-квизов в текущей фазе
def _render_vocab_quiz_progress(correct: int, total: int, phrase: str = "") -> str:
    # 💬 рисуем прогресс-бар + % + фразу (фразу выбираем снаружи, чтобы не повторялась)
    total = max(int(total or 0), 0)
    correct = max(int(correct or 0), 0)

    perc = int((min(correct, total) / total) * 100) if total else 0
    filled = min(10, max(0, perc // 10))
    bar = ("█" * filled) + ("░" * (10 - filled))

    phrase = (phrase or "").strip()
    return f"{bar} {perc}%\n{phrase}".strip()

# 💬 что делает эта часть: стабильный uid для poll-квиза, чтобы redo не увеличивал прогресс повторно
def _poll_quiz_uid(block: dict, extra: str = "") -> str:
    import hashlib

    if not isinstance(block, dict):
        return ""

    q = str(block.get("question", "") or "").strip()
    ca = str(block.get("correct_answer", "") or "").strip()
    opts = block.get("options") or []

    if isinstance(opts, list):
        opts_s = "|".join(str(o or "").strip() for o in opts)
    else:
        opts_s = str(opts)

    base = f"{q}|{ca}|{opts_s}"
    if extra:
        base = f"{extra}|{base}"

    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


@track_handler
async def _upsert_vocab_quiz_progress(chat_id: int, state: FSMContext):
    # 💬 что делает эта часть: создаёт прогресс-сообщение один раз и дальше редактирует его на каждом квизе
    data = await state.get_data()
    vocab_list = get_vocab_list(data)

    total = data.get("poll_total_phase")
    if total is None:
        # 💬 что делает эта часть: total считаем без redo-дублей
        if data.get("lex_mode_active"):
            phrases = data.get("lex_active_phrases") or []
            if not isinstance(phrases, list):
                phrases = []
            total_rounds = data.get("lex_round_total") or _lex_detect_total_rounds(phrases, default_total=4)
            total = len(phrases) * int(total_rounds or 0)
        else:
            uids = {
                _poll_quiz_uid(b, extra=str(data.get("selected_phase_id", "")))
                for b in vocab_list
                if (b or {}).get("type") == "quiz"
            }
            total = len(uids)

        await state.update_data(poll_total_phase=total)


    correct = data.get("quiz_correct_phase", 0)
    # 💬 выбираем фразу без повтора подряд
    last_phrase = data.get("vocab_quiz_progress_last_phrase")
    phrase = ""
    if vocab_quiz_progress_phrases:
        pool = [p for p in vocab_quiz_progress_phrases if p != last_phrase] or vocab_quiz_progress_phrases
        phrase = random.choice(pool)

    text = _render_vocab_quiz_progress(correct, total, phrase=phrase)
    await state.update_data(vocab_quiz_progress_last_phrase=phrase)  # 💬 запоминаем, чтобы не повторять подряд

    msg_id = data.get("vocab_quiz_progress_msg_id")
    try:
        if msg_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="HTML"
            )
            return
    except TelegramBadRequest as e:
        # 💬 если текст тот же = не шлём новый (иначе будет дубль)
        if "message is not modified" in str(e).lower():
            return
    except Exception:
        pass

    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    await state.update_data(vocab_quiz_progress_msg_id=msg.message_id)



@track_handler
async def _delete_vocab_quiz_progress_message(chat_id: int, state: FSMContext):
    # 💬 удаляем прогресс-строку вместе с poll-квизом (не сбрасываем счётчики фазы)
    data = await state.get_data()
    msg_id = data.get("vocab_quiz_progress_msg_id")
    if msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest:
            pass
    await state.update_data(vocab_quiz_progress_msg_id=None)


@track_handler
async def _clear_vocab_quiz_progress(chat_id: int, state: FSMContext):
    # 💬 что делает эта часть: удаляет закреплённый прогресс при выходе из квизов
    data = await state.get_data()
    msg_id = data.get("vocab_quiz_progress_msg_id")

    if msg_id:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    await state.update_data(vocab_quiz_progress_msg_id=None, poll_total_phase=None)




@track_handler
async def send_one_vocab_quiz(message: Message, state: FSMContext):
    data      = await state.get_data()
    topic_key = data["selected_topic"]
    vocab_list = get_vocab_list(data)
    idx       = data.get("vocab_index", 0)
    

    
    # 💬 что делает эта часть: гарантированно получаем chat_id (даже если пришли из таймаута с ChatFullInfo)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if chat_id is None:
        chat_id = getattr(message, "id", None) or data.get("last_chat_id")
    await state.update_data(last_chat_id=chat_id)

    # 💬 что делает эта часть: если message не настоящий Message (таймаут) — создаём фейковый Message для функций, где нужен message.chat.id
    if not hasattr(message, "chat"):
        fake_chat = Chat(id=chat_id, type="private")
        fake_user = User(id=chat_id, is_bot=False, first_name="")
        message = Message(
            message_id=0,
            date=datetime.datetime.now(),
            chat=fake_chat,
            from_user=fake_user,
            text=""
        )


    # 1) Если вышли за пределы — сначала ревью ошибок, потом меню
    if idx >= len(vocab_list):
        await _clear_vocab_quiz_progress(message.chat.id, state)  # 💬 выходим из квизов = убираем закреплённый прогресс

        failed = data.get("failed_vocab", [])
        if failed:
            await state.set_state(LessonStates.review_failed_vocab)
            # 💬 передаём chat_id вместо объекта Message
            return await send_failed_vocab(message.chat.id, state)
        return await lesson_menu_handler(message, state)


    # 2) Берём текущий блок, гарантированно в диапазоне
    block = vocab_list[idx]

    # 💬 что делает эта часть: если квизы закончились, удаляем закреплённый прогресс и выходим в общий отправщик
    if block.get("type") != "quiz":
        await _clear_vocab_quiz_progress(chat_id, state)  # 💬 убираем прогресс-бар, так как квизы закончились
        return await send_one_vocab(message, state)






    # 💬 что делает эта часть: берём правильный как первый, выбираем ещё 2 неверных, перемешиваем и считаем correct_id
    raw_opts = list(block.get("options") or [])
    correct_answer = (str(raw_opts[0]).strip() if raw_opts else (block.get("correct_answer") or "")).strip()

    wrong_pool: list[str] = []
    for o in raw_opts[1:]:
        oo = str(o).strip()
        if oo and oo != correct_answer and oo not in wrong_pool:
            wrong_pool.append(oo)

    opts = [correct_answer] + wrong_pool[:2]  # 💬 Telegram quiz = ровно 3 варианта
    if len(opts) < 3 or not correct_answer:
        # 💬 что делает эта часть: если блок битый, не падаем, просто идём дальше
        await state.update_data(current_poll_id=None, current_correct_option_id=None, current_poll_message_id=None)
        await state.update_data(vocab_index=idx + 1)
        return await send_one_vocab(message, state)

    random.shuffle(opts)
    correct_id = opts.index(correct_answer)

    await _upsert_vocab_quiz_progress(chat_id, state)  # 💬 сообщение 1: создаём или обновляем прогресс перед квизом


    
    poll_message = await bot.send_poll(
        chat_id=chat_id,
        question=_normalize_nl(block.get("question", "")),
        options=opts,
        type="quiz",
        correct_option_id=correct_id,
        is_anonymous=False,
        open_period=int(QUIZ_OPEN_PERIOD_S),
        explanation=f"✅ {correct_answer}"[:190],  # 💬 показываем правильный ответ внутри poll
    )
    
    # 💾 критично: без этого poll ответы и таймаут не отрабатывают
    await state.update_data(
        last_chat_id=chat_id,  # 💬 нужно для реакций и удаления без chat_id из PollAnswer
        current_poll_id=poll_message.poll.id,  # 💬 нужно для фильтрации ответов и таймаута
        current_correct_option_id=correct_id,  # 💬 нужно для проверки правильности
        current_poll_message_id=poll_message.message_id  # 💬 нужно для автоудаления
    )
    
    # 🚨 запускаем таймаут на ответ
    asyncio.create_task(_vocab_quiz_timeout_handler(
        poll_message.poll.id, chat_id, state, delay=int(QUIZ_TIMEOUT_TASK_S)
    ))  # 💬 единый таймаут watchdog
    
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

    # 💬 при верном ответе в ревью — чистим обе очереди для этого индекса
    failed = [i for i in data.get("failed_vocab", []) if i != idx]
    redo   = [i for i in data.get("redo_stack", [])   if i != idx]
    await state.update_data(failed_vocab=failed, redo_stack=redo)


    # 💬 при верном ответе в ревью — чистим обе очереди для этого индекса
    failed = data.get("failed_vocab", [])
    if failed:
        failed = [i for i in failed if i != idx]   # 💬 убрать текущий из списка ошибок
    redo = data.get("redo_stack", [])
    if idx in redo:
        redo = [i for i in redo if i != idx]       # 💬 и из стека пересдач
    await state.update_data(failed_vocab=failed, redo_stack=redo)


    # 💬 Реакция на правильный ответ при ревью (внутри текущего сета)
    if is_correct:
        try:
            msg_id = data.get("current_poll_message_id")
            if msg_id:
                await bot.set_message_reaction(
                    chat_id=poll_answer.user.id,
                    message_id=msg_id,
                    reaction=[ReactionTypeEmoji(emoji="🎉")],
                    is_big=True
                )
        except Exception:
            pass


    # 5) Начисляем XP по старой логике
    delta = random.randint(15, 25) if is_correct else -10
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
        await send_and_auto_delete_text(
            bot,
            user_id,
            random.choice(vocab_quiz_success_phrases),
            delay=SLEEP_BEFORE_FEEDBACK_S
        )  # 💬 короткий показ
        await asyncio.sleep(SLEEP_BEFORE_FEEDBACK_S)  # 💬 пауза перед XP/штрафом
    else:
        # 💬 при ошибке: правильный ответ 2 сек + иногда «негативный» стикер
        asyncio.create_task(_maybe_send_negative_sticker(bot, user_id))  # 💬 шанс/тайминги в константах
        await send_and_auto_delete_text(
            bot,
            user_id,
            f"✅ {block['correct_answer']}",
            delay=WRONG_FB_TEXT_TOTAL_S
        )


    xp_fb = await bot.send_message(
        user_id,
        f"{'🎉 +' + str(delta) + ' XP' if delta > 0 else '⚠️ ' + str(delta) + ' XP'}"
    )  # 💬 закрыли f-string, чтобы не падало на синтаксисе


    # 7) Подождать 1.5 с, чтобы успели прочесть
    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 единая пауза перед удалением


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
async def _vocab_quiz_timeout_handler(poll_id: str, chat_id: int, state: FSMContext, delay: float = QUIZ_TIMEOUT_TASK_S):
    # 💬 что делает эта часть: если юзер не ответил вовремя = считаем как ошибку, ставим реакцию, кидаем в повтор и двигаем дальше

    # 💬 таймаут квиза: считаем как неправильный ответ и крутим внутри текущего сета
    await asyncio.sleep(delay)

    # 💬 если мы уже НЕ в основном квизе = таймаут не срабатывает
    if await state.get_state() != LessonStates.vocab_exercise:
        return

    data = await state.get_data()

    streak = int(data.get("vocab_timeout_streak", 0) or 0) + 1
    await state.update_data(vocab_timeout_streak=streak)  # 💬 считаем серию тайм-аутов подряд (один инкремент)

    if data.get("current_poll_id") != poll_id:
        return  # 💬 квиз уже обработан или это не текущий poll

    poll_msg_id = data.get("current_poll_message_id")


    # 💬 что делает эта часть: закрываем poll и ставим реакцию таймаута прямо на poll
    if poll_msg_id:
        try:
            await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)
        except Exception:
            pass
        try:
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=poll_msg_id,
                reaction=[ReactionTypeEmoji(emoji="⏱")],
                is_big=True
            )
        except Exception:
            pass


    # 💬 сброс poll_id, чтобы не словить двойную обработку
    await state.update_data(current_poll_id=None)

    # 💬 короткий сигнал пользователю
    asyncio.create_task(
        send_and_auto_delete_text(bot, chat_id, "⏱ Время вышло!", delay=AUTO_DELETE_TEXT_DELAY_S)
    )

    await asyncio.sleep(SLEEP_BEFORE_FEEDBACK_S)

    # 💬 штраф XP: режем session_xp и topic_xp, но total_xp не уменьшаем
    topic_key = data.get("selected_topic", "unknown")
    await award_xp(-20, state)
    await add_xp(chat_id, topic_key, -20)

    if streak >= 2:
        await state.update_data(
            vocab_timeout_streak=0,
            current_poll_id=None,
            current_poll_message_id=None
        )  # 💬 2 тайм-аута подряд = сбрасываем серию и уходим в меню

        try:
            await bot.send_message(chat_id, "👀 Похоже, тебя уже нет. Возвращаю в меню 🙌")
        except Exception:
            pass

        fake_chat = Chat(id=chat_id, type="private")
        fake_user = User(id=chat_id, is_bot=False, first_name="")
        fake_msg = Message(
            message_id=0,
            date=datetime.datetime.now(),
            chat=fake_chat,
            from_user=fake_user,
            text=""
        )
        return await lesson_menu_handler(fake_msg, state)  # 💬 сохраняем то, что уже начислено, и выходим

    
    
    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)
    
    # 💬 чистим сообщения (опрос + прогресс) без отдельного XP-сообщения

    data = await state.get_data()
    try:
        pmid = data.get("current_poll_message_id")
        if pmid:
            await bot.delete_message(chat_id, pmid)
            await _delete_vocab_quiz_progress_message(chat_id, state)  # 💬 удаляем прогресс вместе с poll по таймауту

    except Exception:
        pass
    try:
        await bot.delete_message(chat_id, fb.message_id)
    except Exception:
        pass
        
    # 💬 прогресс обновится перед следующим квизом, здесь уже удалили его вместе с poll



    # ─────────────────────────────────────────────
    # 💬 дальше = логика пересдачи внутри текущего сета
    data = await state.get_data()
    vocab_list = get_vocab_list(data)
    idx = data.get("vocab_index", 0)

    def _fake_msg():
        fc = Chat(id=chat_id, type="private")
        fu = User(id=chat_id, is_bot=False, first_name="")
        return Message(
            message_id=0,
            date=datetime.datetime.now(),
            chat=fc,
            from_user=fu,
            text=""
        )

    if streak >= 2:
        await state.update_data(vocab_timeout_streak=0)  # 💬 авто-выход = сбрасываем серию тайм-аутов
        return await lesson_menu_handler(_fake_msg(), state)  # 💬 закрываем квиз и уходим в меню, сохранив набранное


    # 💬 защита от кривого idx или не quiz блока
    if idx >= len(vocab_list) or vocab_list[idx].get("type") != "quiz":
        await state.update_data(vocab_index=min(idx + 1, len(vocab_list)))
        return await send_one_vocab(_fake_msg(), state)

    # 💬 позиции только quiz блоков
    q_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "quiz"]
    if not q_positions:
        # 💬 если вдруг квизов нет = просто идём дальше
        await state.update_data(vocab_index=min(idx + 1, len(vocab_list)))
        return await send_one_vocab(_fake_msg(), state)

    try:
        q_idx = q_positions.index(idx)
    except ValueError:
        # 💬 если таймаут пришёл не на quiz позиции = прыгаем на ближайший quiz
        nxt_q = next((i for i in range(idx + 1, len(vocab_list)) if vocab_list[i].get("type") == "quiz"), None)
        if nxt_q is None:
            await state.update_data(vocab_index=min(idx + 1, len(vocab_list)))
            return await send_one_vocab(_fake_msg(), state)
        await state.update_data(vocab_index=nxt_q)
        return await send_one_vocab(_fake_msg(), state)

    BLOCK = data.get("lex_round_block_size") or 6
    if data.get("lex_mode_active"):
        BLOCK = max(1, len(q_positions))  # 💬 один сет на весь раунд

    block_start_q = (q_idx // BLOCK) * BLOCK
    block_end_q = min(block_start_q + BLOCK, len(q_positions))

    redo = data.get("redo_stack", [])
    if idx not in redo:
        redo.append(idx)  # 💬 таймаут = ошибка = кладём в конец текущего сета

    next_linear = q_positions[q_idx + 1] if (q_idx + 1) < block_end_q else None

    # 💬 если уже в режиме пересдач = крутим только redo
    if data.get("redo_active"):
        if redo:
            nxt = redo.pop(0)
            await state.update_data(
                vocab_index=nxt,
                redo_stack=redo,
                redo_active=True,
                current_poll_id=None
            )
            return await send_one_vocab(_fake_msg(), state)

        # 💬 redo пуста = сет закрыт = textquiz или offer_continue
        await state.update_data(redo_active=False, redo_stack=[])

        oc_scene = random.choice(scenarios["offer_continue"])
        
        # 💬 убираем старую ReplyKeyboard, чтобы она не висела
        try:
            rm = await bot.send_message(chat_id, "\u00AD", reply_markup=ReplyKeyboardRemove())
            await _safe_delete_message(chat_id, rm.message_id)
        except Exception:
            pass
        
        # 💬 Inline-кнопки offer_continue
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
            for btn in oc_scene["buttons"]
        ]])
        
        await state.update_data(
            current_stage="offer_continue",
            current_scene=oc_scene,
            last_oc_msg_id=None,  # 💬 обновим после отправки
            redo_stack=[],
            redo_active=False,
            pending_textquiz=[],
        )
        await state.set_state(LessonStates.showing_vocab)
        
        oc_msg = await smart_reply(_fake_msg(), oc_scene["text"], reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 чтобы удалить после клика
        return oc_msg


    # 💬 обычный режим = сначала добиваем линейку сета
    if next_linear is not None:
        await state.update_data(
            vocab_index=next_linear,
            redo_stack=redo,
            redo_active=False,
            current_poll_id=None
        )
        return await send_one_vocab(_fake_msg(), state)

    # 💬 конец линейки сета = стартуем пересдачу
    if redo:
        nxt = redo.pop(0)
        await state.update_data(
            vocab_index=nxt,
            redo_stack=redo,
            redo_active=True,
            current_poll_id=None
        )
        return await send_one_vocab(_fake_msg(), state)

    # 💬 вообще нечего пересдавать = textquiz или offer_continue
    pending = await _select_pending_textquiz_for_set(state)
    if pending:
        next_idx = pending[0]
        await state.update_data(
            vocab_index=next_idx,
            pending_textquiz=pending,
            current_poll_id=None
        )
        return await send_one_vocab(_fake_msg(), state)

    oc_scene = random.choice(scenarios["offer_continue"])
    
    # 💬 убираем старую ReplyKeyboard, чтобы она не висела
    try:
        rm = await bot.send_message(chat_id, "\u00AD", reply_markup=ReplyKeyboardRemove())
        await _safe_delete_message(chat_id, rm.message_id)
    except Exception:
        pass
    
    # 💬 Inline-кнопки offer_continue
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
        for btn in oc_scene["buttons"]
    ]])
    
    await state.update_data(
        current_stage="offer_continue",
        current_scene=oc_scene,
        last_oc_msg_id=None,  # 💬 обновим после отправки
        redo_stack=[],
        redo_active=False,
        pending_textquiz=[],
    )
    await state.set_state(LessonStates.showing_vocab)
    
    oc_msg = await smart_reply(_fake_msg(), oc_scene["text"], reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 чтобы удалить после клика
    return oc_msg



@track_handler
async def _review_failed_vocab_quiz_timeout_handler(poll_id: str, chat_id: int, state: FSMContext, delay: int = 20):
    # 💬 если в пересдаче не ответили = считаем как ошибку и переносим в конец очереди failed_vocab
    await asyncio.sleep(delay)

    data = await state.get_data()
    if data.get("current_poll_id") != poll_id:
        return

    # 💬 сбрасываем poll_id, чтобы не сработало дважды
    streak = int(data.get("vocab_timeout_streak", 0) or 0) + 1
    await state.update_data(current_poll_id=None, vocab_timeout_streak=streak)  # 💬 фиксируем серию тайм-аутов

    if streak >= 2:
        await state.update_data(
            vocab_timeout_streak=0,
            current_poll_id=None,
            current_poll_message_id=None
        )  # 💬 2 тайм-аута подряд в пересдаче = выходим в меню

        mid = data.get("current_poll_message_id")
        if mid:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                pass

        try:
            await bot.send_message(chat_id, "👀 Похоже, ты отвлёкся. Вернул в меню 🙌")
        except Exception:
            pass

        fake_chat = Chat(id=chat_id, type="private")
        fake_user = User(id=chat_id, is_bot=False, first_name="")
        fake_msg = Message(
            message_id=0,
            date=datetime.datetime.now(),
            chat=fake_chat,
            from_user=fake_user,
            text=""
        )
        return await lesson_menu_handler(fake_msg, state)  # 💬 выход без зацикливания пересдачи


    failed = data.get("failed_vocab", [])
    if failed:
        await state.update_data(failed_vocab=failed[1:] + [failed[0]])  # 💬 ошибка = в конец очереди

    # 💬 удаляем poll сообщение, чтобы чат не захламлялся
    mid = data.get("current_poll_message_id")
    if mid:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass

    return await send_failed_vocab(chat_id, state)


# 💬 Выбираем textquiz: по умолчанию 2 (мини-сессия), но можно запросить больше (финал)
async def _select_pending_textquiz_for_set(state: FSMContext, limit: int = 2) -> list[int]:
    """
    Логика выбора:
    1. Сохраняем якорь (last_main_quiz_index).
    2. Если limit == 2 (мини-сессия):
       - 1-й слот: Redo (или Новый).
       - 2-й слот: Всегда Новый.
    3. Если limit > 2 (финал/хвост):
       - Наполняем список сначала из Redo, затем из Новых, пока не наберем limit.
    """
    data = await state.get_data()
    if data.get("lex_mode_active"):
        # 💬 что делает эта часть: в ALL IN показываем ровно 1 textquiz после завершения сета квизов
        vocab_list = get_vocab_list(data)
        t_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "textquiz"]
        if not t_positions:
            return []
        if data.get("lex_textquiz_done_round"):
            return []
        await state.update_data(lex_textquiz_done_round=True)
        return [t_positions[0]]

    vocab_list = get_vocab_list(data)
    
    # --- Сохранение якоря для обычных квизов ---
    current_idx = data.get("vocab_index", 0)
    block_type = vocab_list[current_idx].get("type", "link")
    if block_type == "quiz":
        await state.update_data(last_main_quiz_index=current_idx)

    # Позиции textquiz
    t_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "textquiz"]
    if not t_positions:
        return []

    redo_t = data.get("redo_stack_text", [])
    cursor = data.get("textquiz_new_cursor", 0)
    pending = []

    # === ВЕТКА 1: Мини-сессия (строго 2 вопроса: 1 redo/new + 1 new) ===
    if limit == 2:
        # Слот 1:
        if redo_t:
            pending.append(redo_t.pop(0))
            await state.update_data(redo_stack_text=redo_t)
        elif cursor < len(t_positions):
            pending.append(t_positions[cursor])
            cursor += 1
        
        # Слот 2: (Всегда новый)
        if len(pending) < 2 and cursor < len(t_positions):
            pending.append(t_positions[cursor])
            cursor += 1

    # === ВЕТКА 2: Большой пакет (Финал, limit=6) ===
    else:
        # Сначала выгребаем ошибки (сколько влезет)
        while len(pending) < limit and redo_t:
            pending.append(redo_t.pop(0))
        
        # Обновляем стек ошибок (если что-то забрали)
        await state.update_data(redo_stack_text=redo_t)

        # Затем добираем новыми
        while len(pending) < limit and cursor < len(t_positions):
            pending.append(t_positions[cursor])
            cursor += 1

    # Сохраняем курсор новых
    await state.update_data(textquiz_new_cursor=cursor)

    return pending

async def _pick_textquiz_round(state: FSMContext, count: int = 2):
    """
    # 💬 Берём до 2 textquiz: один из ошибок, один новый (с сохранением курсора)
    """
    data = await state.get_data()
    textquiz_pool = data.get("textquiz_pool", [])
    wrong_q = data.get("textquiz_wrong_queue", [])[:]  # локальная копия
    cursor = data.get("textquiz_cursor", 0)

    picked = []

    # 1) из ошибок
    if wrong_q:
        picked.append(wrong_q.pop(0))

    # 2) новый по курсору
    while len(picked) < count and cursor < len(textquiz_pool):
        picked.append(textquiz_pool[cursor])
        cursor += 1

    # обновляем только если что-то взяли
    if picked:
        await state.update_data(
            textquiz_wrong_queue=wrong_q,
            textquiz_cursor=cursor
        )
    return picked


async def _pick_textquiz_fullpass(state: FSMContext):
    """
    # 💬 Когда обычные квизы закончились: вернуть ВСЁ, что осталось:
    # сначала все НОВЫЕ (с курсора до конца), затем весь хвост ошибок
    """
    data = await state.get_data()
    textquiz_pool = data.get("textquiz_pool", [])
    wrong_q = data.get("textquiz_wrong_queue", [])[:]
    cursor = data.get("textquiz_cursor", 0)

    new_rest = textquiz_pool[cursor:] if cursor < len(textquiz_pool) else []
    full = new_rest + wrong_q

    # курсор ставим в конец, ошибки очищаем (уйдут в pending_textquiz)
    if full:
        await state.update_data(
            textquiz_cursor=len(textquiz_pool),
            textquiz_wrong_queue=[]
        )
    return full


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
    await state.update_data(current_poll_id=None, vocab_timeout_streak=0)  # 💬 сбрасываем серию тайм-аутов после ответа

    # 3) Правильность и начисление XP
    idx = data.get("vocab_index", 0)
    selected = poll_answer.option_ids[0] if poll_answer.option_ids else None
    correct  = data["current_correct_option_id"]
    is_correct = (selected == correct)


    chat_id = poll_answer.user.id
    poll_msg_id = data.get("current_poll_message_id")  # 💬 id сообщения с poll

    # 💬 что делает эта часть: сразу закрываем poll и ставим реакцию, но НЕ удаляем poll тут
    if poll_msg_id:
        try:
            await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)  # 💬 убираем "зависание" после ответа
        except Exception:
            pass

        try:
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=poll_msg_id,
                reaction=[ReactionTypeEmoji(emoji="🎉" if is_correct else "❌")],
                is_big=True
            )  # 💬 реакция видна сразу
        except Exception:
            pass



    delta = 30 if is_correct else -10  # 💬 фиксированные значения для vocab quiz

    await award_xp(delta, state)

    # 💬 Уникальный прогресс poll-квизов: redo не накручивает прогресс повторно
    if is_correct:
        done_ids = data.get("poll_done_ids")
        if not isinstance(done_ids, list):
            done_ids = []

        vocab_list = get_vocab_list(data)  # 💬 берём текущий список блоков (lex или обычный)
        block = vocab_list[idx] if (isinstance(vocab_list, list) and 0 <= idx < len(vocab_list)) else {}  # 💬 текущий poll-квиз
        quiz_uid = _poll_quiz_uid(block, extra=str(data.get("selected_phase_id", "")))  # 💬 uid для уникального прогресса без redo


        if quiz_uid and quiz_uid not in done_ids:
            done_ids.append(quiz_uid)
            await state.update_data(
                poll_done_ids=done_ids,
                quiz_correct_phase=len(done_ids),
                quiz_correct_total=data.get("quiz_correct_total", 0) + 1
            )
        else:
            await state.update_data(poll_done_ids=done_ids)  # 💬 redo = уже было зачтено



    # 🔥 Level-Up: сохраняем прошлый глобальный XP
    user_id = poll_answer.user.id
    topic   = data.get("selected_topic", "unknown")
    xp_before = load_xp_data().get(str(user_id), {}).get("total_xp", 0)

    # 💬 что делает эта часть: total_xp не уменьшаем (штрафы режут только topic_xp), поэтому xp_after считаем локально
    will_level_up = ((xp_before + (delta if delta > 0 else 0)) // XP_PER_LEVEL) > (xp_before // XP_PER_LEVEL)
    if will_level_up:
        await add_xp(user_id, topic, delta)  # 💬 для level-up ждём запись, чтобы прогресс/медаль были точными
    else:
        asyncio.create_task(add_xp(user_id, topic, delta))  # 💬 обычный случай = не блокируем квиз
    
    # 🔥 Проверяем, перешли ли на новый уровень
    xp_after = xp_before + (delta if delta > 0 else 0)  # 💬 штрафы не уменьшают total_xp

    prev_lvl = xp_before // XP_PER_LEVEL
    new_lvl  = xp_after  // XP_PER_LEVEL

    if new_lvl > prev_lvl:
        # 💬 Определяем безопасные индексы уровня и медали (не выходим за границы массивов)
        lvl_idx = min(new_lvl, len(LEVELS) - 1)
        medal_idx = min(
            (xp_after % XP_PER_LEVEL) // (XP_PER_LEVEL // 3),
            len(MEDALS) - 1,
        )

        # 💬 Короткий прогресс по новой системе уровней
        progress_text = render_short_level_progress(user_id)

        await bot.send_message(
            user_id,
            f"🎉 Поздравляем! Вы достигли уровня {LEVELS[lvl_idx]}{MEDALS[medal_idx]}!\n\n"
            f"{progress_text}"
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
  
    # 💬 Новый: показываем правильный ответ или фразу похвалы перед XP
    if is_correct:
        # 💬 20% шанс — показать стикер, 80% — фразу поддержки
        if random.random() < 0.2:
            from scenarios_estiloso8_1 import exercise_stickers  # 💬 стикеры для успеха в упражнениях
            sticker_id = random.choice(exercise_stickers)
            await send_and_auto_delete_sticker(bot, user_id, sticker_id)
        else:
            await send_and_auto_delete_text(
                bot,
                user_id,
                random.choice(vocab_quiz_success_phrases),
                delay=SLEEP_BEFORE_FEEDBACK_S,  # 💬 короткий показ текста
            )
    else:
        # 💬 при ошибке: держим правильный ответ 2 сек + иногда даём «негативный» стикер поверх
        asyncio.create_task(_maybe_send_negative_sticker(bot, user_id))  # 💬 шанс/тайминги в константах
        await send_and_auto_delete_text(
            bot,
            user_id,
            f"✅ {block['correct_answer']}",
            delay=WRONG_FB_TEXT_TOTAL_S,  # 💬 чтобы успели прочитать
        )

    if is_correct:
        await asyncio.sleep(SLEEP_BEFORE_FEEDBACK_S)  # 💬 пауза перед XP только для «быстрого» фидбэка




    fb = None  # 💬 XP-фидбэк больше не показываем (только реакции)




    # 6) Ждём и удаляем опрос + feedback
    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 даём увидеть реакцию и при необходимости fb
    chat_id = poll_answer.user.id

    def _fake_msg():
        # 💬 что делает эта часть: создаём Message-заглушку, чтобы переиспользовать smart_reply/send_one_vocab
        fc = Chat(id=chat_id, type="private")
        fu = User(id=poll_answer.user.id, is_bot=False, first_name="")
        return Message(
            message_id=0,
            date=datetime.datetime.now(),
            chat=fc,
            from_user=fu,
            text=""
        )

    try:
        pmid = data.get("current_poll_message_id")
        if pmid:
            await bot.delete_message(chat_id, pmid)  # 💬 удаляем poll
        await _delete_vocab_quiz_progress_message(chat_id, state)  # 💬 удаляем прогресс вместе с poll
    except Exception:
        pass




    # 7) Переход по сетам (6) ТОЛЬКО по обычным quiz, с повтором ошибок внутри сета + offer_continue

    # 💬 если это пересдача и ответ верный — убираем индекс из redo_stack
    _cur = await state.get_data()
    _redo = _cur.get("redo_stack", [])
    if is_correct and idx in _redo:
        _redo = [i for i in _redo if i != idx]   # 💬 вычистили текущий индекс
        await state.update_data(redo_stack=_redo)

    # 💬 если исправили в пересдаче — чистим и очередь ошибок
    _failed = _cur.get("failed_vocab", [])
    if is_correct and idx in _failed:
        _failed = [i for i in _failed if i != idx]
        await state.update_data(failed_vocab=_failed)

    data = await state.get_data()
    vocab_list = get_vocab_list(data)
    
    # сначала строим позиции quiz
    q_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "quiz"]
    
    # потом считаем BLOCK
    BLOCK = data.get("lex_round_block_size") or 6
    if data.get("lex_mode_active"):
        BLOCK = max(1, len(q_positions))  # один сет на весь раунд



    # 👇 строим карту позиций только для type=="quiz"
    q_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "quiz"]
    # текущая позиция внутри q_positions (handle_vocab_poll_answer всегда обрабатывает quiz)
    try:
        q_idx = q_positions.index(idx)
    except ValueError:
        # на всякий случай: если попали сюда не с quiz = ищем ближайший следующий quiz
        nxt_q = next((i for i in range(idx + 1, len(vocab_list)) if vocab_list[i].get("type") == "quiz"), None)
        if nxt_q is None:
            # нет quiz = сразу в offer_continue
            oc_scene = random.choice(scenarios["offer_continue"])

            # 💬 убираем старую ReplyKeyboard, чтобы она не висела
            try:
                rm = await bot.send_message(chat_id, "\u00AD", reply_markup=ReplyKeyboardRemove())
                await _safe_delete_message(chat_id, rm.message_id)
            except Exception:
                pass

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                for btn in oc_scene["buttons"]
            ]])

            await state.update_data(current_stage="offer_continue", current_scene=oc_scene)
            await state.set_state(LessonStates.showing_vocab)

            await _clear_vocab_quiz_progress(chat_id, state)  # 💬 квизы закончились = чистим прогресс

            oc_msg = await smart_reply(_fake_msg(), oc_scene["text"], reply_markup=kb, parse_mode="HTML")
            await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 чтобы удалить после клика
            return oc_msg

        # 💬 есть следующий quiz = продолжаем с него
        idx = nxt_q
        q_idx = q_positions.index(idx)
        await state.update_data(vocab_index=idx, current_poll_id=None)



    block_start_q = (q_idx // BLOCK) * BLOCK
    block_end_q   = min(block_start_q + BLOCK, len(q_positions))

    redo = data.get("redo_stack", [])
    # 💬 симметрично: снимаем из redo при успехе, добавляем при ошибке
    if is_correct and idx in redo:
        redo = [i for i in redo if i != idx]    # 💬 удалить текущий из очереди
    elif not is_correct and idx not in redo:
        redo.append(idx)                         # 💬 добавить в конец



    # следующий quiz по прямой внутри текущего сета
    next_linear = q_positions[q_idx + 1] if (q_idx + 1) < block_end_q else None

    # 💬 если уже в режиме пересдач — игнорируем линейку и крутим ТОЛЬКО redo
    if data.get("redo_active"):
        if is_correct:
            # 💬 на верный ответ чистим текущий индекс из redo и берём следующий (или выходим)
            if idx in redo:
                redo = [i for i in redo if i != idx]

            if redo:
                # 💬 ещё есть ошибки в очереди — продолжаем пересдачи внутри ТЕКУЩЕГО сета
                nxt = redo.pop(0)
                await state.update_data(
                    vocab_index=nxt,
                    redo_stack=redo,
                    redo_active=True,
                    current_poll_id=None,
                )
                return await send_one_vocab(_fake_msg(), state)
            else:
                # 💬 очередь пересдач пуста — СЕТ ЗАКРЫТ → пробуем мини-сессию textquiz
                await state.update_data(redo_active=False)
                pending = await _select_pending_textquiz_for_set(state)  # 💬 выбираем 0–2 textquiz / финальный хвост

                if pending:
                    next_idx = pending[0]
                    await state.update_data(
                        vocab_index=next_idx,
                        pending_textquiz=pending,
                        current_poll_id=None,
                    )
                    return await send_one_vocab(_fake_msg(), state)


                # 💬 textquiz нет = показываем inline offer_continue, чтобы не захламлять чат
                oc_scene = random.choice(scenarios["offer_continue"])
                await state.update_data(
                    current_stage="offer_continue",
                    current_scene=oc_scene,
                )
                await state.set_state(LessonStates.showing_vocab)  # 💬 важно: cb_scenario_vocab слушает showing_vocab

                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")]
                        for btn in oc_scene["buttons"]
                    ]
                )

                oc_msg = await bot.send_message(
                    poll_answer.user.id,
                    oc_scene["text"],
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 чтобы удалить этот кусок после клика
                return

            # 💬 на неверный в redo — повторяем ТОТ ЖЕ квиз (ставим idx в голову очереди без дублей)
            redo = [i for i in redo if i != idx]
            redo.insert(0, idx)
            await state.update_data(redo_stack=redo, current_poll_id=None)
            # ВАЖНО: не меняем vocab_index — остаёмся на этом же idx
            return await send_one_vocab(_fake_msg(), state)



    if next_linear is not None:
        await state.update_data(
            vocab_index=next_linear,
            redo_stack=redo,
            redo_active=False,
            current_poll_id=None
        )  # 💬 явно НЕ redo
        return await send_one_vocab(_fake_msg(), state)
    else:
        # дошли до края линейного прохода по сету
        if redo:
            # есть ошибки — повторяем их внутри того же сета
            nxt = redo.pop(0)
            await state.update_data(
                vocab_index=nxt,
                redo_stack=redo,
                redo_active=True,
                current_poll_id=None
            )  # 💬 остаёмся в redo
            return await send_one_vocab(_fake_msg(), state)
        else:
            # 💬 textquiz тоже нет — обычный offer_continue
            # 💬 textquiz тоже нет — показываем inline offer_continue (единый формат с cb_scenario_vocab)
            oc = random.choice(scenarios["offer_continue"])
            await state.update_data(current_stage="offer_continue", current_scene=oc)

            kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                    for btn in oc["buttons"]
                ]]
            )  # 💬 inline-кнопки вместо reply keyboard

            oc_msg = await bot.send_message(
                poll_answer.user.id,
                oc["text"],
                reply_markup=kb,
                parse_mode="HTML"
            )
            await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 запоминаем id, чтобы удалить после клика
            await state.set_state(LessonStates.showing_vocab)  # 💬 дальше ждём callback
            return






# ---------------- КОНЕЦ по показу type: quiz📘📘📘 -----------------






# ---------------- НАЧАЛО по показу type: text_quiz📘📘📘 -----------------
@dp.message(LessonStates.vocab_textquiz)
@track_handler
async def handle_vocab_textquiz_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data.get("vocab_index", 0)
    vocab_list = get_vocab_list(data)

    # 💬 что делает эта часть: защита от выхода за границы списка
    if idx < 0 or idx >= len(vocab_list):
        await state.update_data(textquiz_session_active=False, pending_textquiz=[], redo_stack_text=[])
        await smart_reply(message, "🎉 Это конец блока. Молодец!")
        return await lesson_menu_handler(message, state)

    block = vocab_list[idx]
    user_norm = normalize_textquiz(message.text)

    # 💬 что делает эта часть: берём либо список correct_answers, либо строку correct_answer (в т.ч. с ';')
    answers_raw = block.get("correct_answers") or block.get("correct_answer", "")
    if isinstance(answers_raw, list):
        variants = [a for a in answers_raw if a]
    else:
        variants = [a.strip() for a in str(answers_raw).replace("|", ";").split(";") if a.strip()]

    variants_norm = [normalize_textquiz(v) for v in variants if v]
    is_correct = user_norm in variants_norm

    pending = (data.get("pending_textquiz") or [])[:]
    redo_text = (data.get("redo_stack_text") or [])[:]

    # 💬 что делает эта часть: убираем текущий idx из pending, чтобы очередь двигалась
    if idx in pending:
        pending = [p for p in pending if p != idx]

    if not is_correct:
        # 💬 что делает эта часть: неверно = показываем ✅ правильный ответ, ждём и удаляем, добавляем в redo_stack_text
        correct_str = " / ".join(variants) if variants else ""
        fb = await message.answer(f"✅ {correct_str}".strip())
        await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)
        try:
            await bot.delete_message(message.chat.id, fb.message_id)
        except Exception:
            pass

        if idx not in redo_text:
            redo_text.append(idx)
    else:
        # 💬 что делает эта часть: верно = засчитываем прогресс textquiz
        await award_xp(30, state)
        await state.update_data(
            textquiz_correct=data.get("textquiz_correct", 0) + 1,
            textquiz_correct_phase=data.get("textquiz_correct_phase", 0) + 1,
        )
        if idx in redo_text:
            redo_text = [r for r in redo_text if r != idx]

    # 💬 что делает эта часть: чистим вопрос + ответ пользователя (если бот имеет права)
    prompt_id = data.get("last_prompt_id")
    for mid in (prompt_id, message.message_id):
        if not mid:
            continue
        try:
            await bot.delete_message(message.chat.id, mid)
        except Exception:
            pass

    # 💬 что делает эта часть: выбираем следующий textquiz = сначала pending, потом redo_stack_text
    next_idx = None
    if pending:
        next_idx = pending[0]
    elif redo_text:
        next_idx = redo_text[0]

    await state.update_data(pending_textquiz=pending, redo_stack_text=redo_text)

    if next_idx is None:
        # 💬 что делает эта часть: все textquiz закрыты = финал и сразу меню
        await smart_reply(message, "🎉 Это конец блока. Молодец!")
        await state.update_data(
            textquiz_session_active=False,
            pending_textquiz=[],
            redo_stack_text=[],
            resume_vocab_index=None,
            last_main_quiz_index=None,
            redo_stack=[],
            redo_active=False,
        )
        return await lesson_menu_handler(message, state)

    await state.update_data(vocab_index=next_idx)
    return await send_one_vocab(message, state)




    # 🔐 Новый критерий разблокировки:
    #   1) глобальный XP по теме >= порога xp_threshold
    #   2) минимум 6 ПРАВИЛЬНЫХ TEXTQUIZ в рамках текущего урока
    data2 = await state.get_data()

    # 💬 берём текущий счётчик правильных TEXTQUIZ из state (по умолчанию 0)
    correct_cnt = data2.get("textquiz_correct", 0)

 
    if is_correct:
        correct_cnt += 1
        phase_cnt = data2.get("textquiz_correct_phase", 0) + 1  # 💬 прогресс именно внутри фазы
        await state.update_data(
            textquiz_correct=correct_cnt,
            textquiz_correct_phase=phase_cnt
        )
        data2["textquiz_correct"] = correct_cnt
        data2["textquiz_correct_phase"] = phase_cnt


    threshold = data2.get("xp_threshold", 0)
    topic_xp = (
        load_xp_data()
        .get(str(user_id), {})
        .get("by_topic", {})
        .get(topic_key, 0)
    )


    data2 = await state.get_data()
    
    # 💬 Разблокирование по прогрессу «Учить слова» (70% фаз)
    phases = topics.get(data2.get("selected_topic", ""), {}).get("vocab", [])
    total_phases = len(phases)
    per_phase = data2.get("vocab_done_per_phase", {})
    
    completed_phases = 0
    for ph in phases:
        phase_id = ph.get("phase_id")
        need_quizzes = len([b for b in ph.get("vocab", []) if b.get("type") in ("quiz", "textquiz")])
        done_here = per_phase.get(phase_id, 0)
        if need_quizzes > 0 and done_here >= need_quizzes:
            completed_phases += 1
    
    vocab_unlock_percent = (completed_phases / total_phases * 100) if total_phases else 100
    if not data2.get("unlocked", False) and vocab_unlock_percent >= 70:
        await state.update_data(unlocked=True)  # 💬 фиксируем разблокировку
        await message.answer("🔐 <b>Блоки разблокированы! 🎉</b>", parse_mode="HTML")



    # 💬 4) Дополнительный фидбэк: печенька или правильный ответ
    # 💬 Сколько уже дали за этот урок?
    data = await state.get_data()
    given = (load_xp_data()
             .get(str(user_id), {})
             .get("stats", {})
             .get("words_learned", 0)
         ) - data.get("initial_cookies", 0)

    max_cookies = data.get("max_cookies", 0)
    to_give = min(2, max(0, max_cookies - given))  # 💬 даём 2 🍪 за 1 текстквиз, но не превышаем лимит

    if is_correct and to_give > 0:
        # 📌 начисляем «слова выучено» как печеньки (1 слово = 1 🍪)
        for _ in range(to_give):
            await add_xp(user_id, topic_key, 0, action="words_learned")  # 💬 +1 слово (🍪)

        given_after = given + to_give

        # 💬 редко показываем прогресс внутри фазы и удаляем (каждые 6 слов = 3 фразы)
        if given_after % 6 == 0:
            asyncio.create_task(
                send_and_auto_delete_text(
                    bot,
                    message.chat.id,
                    f"📚 В этой фазе уже +{given_after} слов",
                    delay=2.0,
                    parse_mode="HTML"
                )
            )

        # 💬 показываем сколько «печенька» дала слов за этот текстквиз
        extra_fb = await message.answer(f"🍪 +{to_give}\n📚 +{to_give} слов", parse_mode="HTML")


    elif not is_correct:
        # 📌 показываем правильный ответ заглавными
        correct_str = " или ".join(variants).upper()
        extra_fb = await message.answer(f"👉 {correct_str}", parse_mode="HTML")

    else:
        # 📌 лимит печенек достигнут — пропускаем
        extra_fb = None


    # 💬 что делает эта часть: даём увидеть реакцию и на ✅ и на ❌ (иначе ❌ исчезает слишком быстро)
    await asyncio.sleep(max(SLEEP_AFTER_FEEDBACK_S, REPLY_REACTION_READ_DELAY_S))


    # 💬 5) Удаляем всё: вопрос, ответ пользователя, XP-фидбэк и (если есть) extra-фидбэк
    chat_id   = message.chat.id
    prompt_id = (await state.get_data()).get("last_prompt_id")
    # собираем ID (учитываем, что xp_fb может быть None, если был только стикер)
    to_delete = [prompt_id, message.message_id]  # 💬 базовый набор: вопрос + ответ
    if isinstance(xp_fb, Message):
        to_delete.append(xp_fb.message_id)       # 💬 удаляем текстовый XP-фидбэк, если он был
    if isinstance(extra_fb, Message):
        to_delete.append(extra_fb.message_id)    # 💬 удаляем доп. фидбэк (печенька / правильный ответ)
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


    # 💬 7) Интерливинг: упрощённая логика, если активна мини-сессия pending_textquiz
    data = await state.get_data()
    pending = data.get("pending_textquiz") or []

    if pending:
        # 💬 берём текущий стек ошибок для textquiz
        redo_t = data.get("redo_stack_text", [])

        # симметрия: снимаем при успехе, добавляем при ошибке
        if is_correct and idx in redo_t:
            redo_t = [i for i in redo_t if i != idx]
        elif not is_correct and idx not in redo_t:
            redo_t.append(idx)

        # 💬 убираем текущий индекс из pending, чтобы не повторять его в этой мини-сессии
        pending = [i for i in pending if i != idx]

        await state.update_data(
            redo_stack_text=redo_t,
            pending_textquiz=pending,
            redo_active_text=False,  # 💬 пересдачи textquiz — только между сетами, не внутри пары
        )

        if pending:
            # 💬 есть ещё один textquiz в текущей мини-сессии → показываем его
            next_idx = pending[0]
            await state.update_data(vocab_index=next_idx)
            return await send_one_vocab(message, state)
        else:
            if data.get("lex_mode_active"):
                await state.update_data(vocab_index=idx + 1)  # 💬 ALL IN: сдвигаем индекс за textquiz, чтобы send_one_vocab собрал следующий раунд
                return await send_one_vocab(message, state)

            # 💬 мини-сессия textquiz закончилась → обычный offer_continue
            oc_scene = random.choice(scenarios["offer_continue"])
            
            # 💬 убираем старую ReplyKeyboard, чтобы она не висела
            try:
                rm = await bot.send_message(message.chat.id, "\u00AD", reply_markup=ReplyKeyboardRemove())
                await _safe_delete_message(message.chat.id, rm.message_id)
            except Exception:
                pass
            
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                for btn in oc_scene["buttons"]
            ]])
            
            await state.update_data(current_stage="offer_continue", current_scene=oc_scene)
            await state.set_state(LessonStates.showing_vocab)
            
            oc_msg = await smart_reply(message, oc_scene["text"], reply_markup=kb, parse_mode="HTML")
            await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 чтобы удалить после клика


            data2 = await state.get_data()

            # 💬 что делает эта часть: OfferContinue показывает тот же poll progress-bar, что и основной поток poll-квизов
            done_ids = data2.get("poll_done_ids")
            if not isinstance(done_ids, list):
                done_ids = []

            poll_done = len(done_ids)

            poll_total = data2.get("poll_total_phase")
            if poll_total is None:
                vocab_list2 = get_vocab_list(data2)
                uids2 = {
                    _poll_quiz_uid(b, extra=str(data2.get("selected_phase_id", "")))
                    for b in vocab_list2
                    if (b or {}).get("type") == "quiz"
                }
                poll_total = len(uids2)
                await state.update_data(poll_total_phase=poll_total)

            progress_text = _render_vocab_quiz_progress(poll_done, poll_total, phrase="")  # 💬 единый стиль █░ + %


            # 💬 не блокируем поток: показываем прогресс и удаляем его через 5 секунд
            asyncio.create_task(
                send_and_auto_delete_text(
                    bot,
                    message.chat.id,
                    progress_text,
                    delay=5.0,  # ⏳ держим прогресс 5 секунд
                )
            )

            return oc_msg



    # Разбиваем TEXTQUIZ блоки по 6, повторяем ошибки внутри сета, печенька уже дана выше
    # 💬 TEXTQUIZ сет: считаем ТОЛЬКО позиции type=="textquiz", по 6 в сете
    data = await state.get_data()
    vocab_list = get_vocab_list(data)
    BLOCK = 6  # размер сета

    # 1) позиции всех textquiz
    t_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "textquiz"]

    # 2) индекс текущего textquiz внутри t_positions (если не нашли — ищем ближайший следующий textquiz)
    try:
        t_idx = t_positions.index(idx)
    except ValueError:
        nxt_t = next(
            (i for i in range(idx + 1, len(vocab_list)) if vocab_list[i].get("type") == "textquiz"),
            None
        )
        if nxt_t is None:
            # нет textquiz → сразу offer_continue
            oc_scene = random.choice(scenarios["offer_continue"])

            # 💬 что делает эта часть: гарантированно убираем старую ReplyKeyboard (если где-то осталась)
            try:
                rm = await bot.send_message(message.chat.id, "\u00AD", reply_markup=ReplyKeyboardRemove())
                await _safe_delete_message(message.chat.id, rm.message_id)
            except Exception:
                pass

            # 💬 что делает эта часть: показываем offer_continue только через inline-кнопки
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                for btn in oc_scene["buttons"]
            ]])

            await state.update_data(
                current_stage="offer_continue",
                current_scene=oc_scene,
                last_oc_msg_id=None,  # 💬 запишем после отправки, чтобы cb удалял всё корректно
                redo_stack_text=[],
                redo_active_text=False,
            )
            await state.set_state(LessonStates.showing_vocab)

            oc_msg = await smart_reply(message, oc_scene["text"], reply_markup=kb, parse_mode="HTML")
            await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 cb_scenario_vocab удалит это сообщение
            return

        else:
            await state.update_data(vocab_index=nxt_t)
            return await send_one_vocab(message, state)

    # 3) границы текущего textquiz-сета в пространстве t_positions
    block_start_t = (t_idx // BLOCK) * BLOCK
    block_end_t   = min(block_start_t + BLOCK, len(t_positions))

    # 4) стек пересдач для textquiz + флаг режима пересдач
    redo_t       = data.get("redo_stack_text", [])
    redo_active  = data.get("redo_active_text", False)

    # симметрия: снимаем при успехе, добавляем при ошибке
    if is_correct and idx in redo_t:
        redo_t = [i for i in redo_t if i != idx]
    elif not is_correct and idx not in redo_t:
        redo_t.append(idx)

    # 5) следующий textquiz по прямой внутри текущего сета (используем только в линейном режиме)
    next_linear = t_positions[t_idx + 1] if (t_idx + 1) < block_end_t else None

    # 6) Если мы уже в режиме пересдач — игнорируем next_linear, пока очередь не опустеет
    if redo_active:
        if is_correct:
            # верный ответ в redo: идём к следующему из очереди
            if redo_t:
                nxt = redo_t.pop(0)
                await state.update_data(
                    vocab_index=nxt,
                    redo_stack_text=redo_t,
                    redo_active_text=True,
                )
                return await send_one_vocab(message, state)
            else:
                # очередь пересдач пуста — выходим в offer_continue
                oc_scene = random.choice(scenarios["offer_continue"])

                # 💬 что делает эта часть: гарантированно убираем старую ReplyKeyboard (если где-то осталась)
                try:
                    rm = await bot.send_message(message.chat.id, "\u00AD", reply_markup=ReplyKeyboardRemove())
                    await _safe_delete_message(message.chat.id, rm.message_id)
                except Exception:
                    pass

                # 💬 что делает эта часть: показываем offer_continue только через inline-кнопки
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                    for btn in oc_scene["buttons"]
                ]])

                await state.update_data(
                    current_stage="offer_continue",
                    current_scene=oc_scene,
                    last_oc_msg_id=None,  # 💬 запишем после отправки, чтобы cb удалял всё корректно
                    redo_stack_text=[],
                    redo_active_text=False,
                )
                await state.set_state(LessonStates.showing_vocab)

                oc_msg = await smart_reply(message, oc_scene["text"], reply_markup=kb, parse_mode="HTML")
                await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 cb_scenario_vocab удалит это сообщение
                return


        else:
            # неверный ответ в redo — повторяем ТОТ ЖЕ textquiz, ставим его в голову очереди
            redo_t = [i for i in redo_t if i != idx]
            redo_t.insert(0, idx)
            await state.update_data(
                redo_stack_text=redo_t,
                redo_active_text=True,
            )
            # ВАЖНО: vocab_index не меняем — остаёмся на этом же idx
            return await _show_offer_continue_after_textquiz(message, state, target_idx=idx)  # 💬 перебивка перед повтором


    # 7) Линейный проход (redo_active_text == False): сначала проходим сет, потом пересдачи
    if next_linear is not None:
        # идём дальше по сету, ошибки остаются в redo_t
        await state.update_data(
            vocab_index=next_linear,
            redo_stack_text=redo_t,
            redo_active_text=False,
        )
        return await _show_offer_continue_after_textquiz(message, state, target_idx=next_linear)  # 💬 перебивка перед следующим textquiz

    else:
        # дошли до конца линейки в сете
        if redo_t:
            # есть ошибки — повторяем их внутри этого же сета, включаем redo-режим
            nxt = redo_t.pop(0)
            await state.update_data(
                vocab_index=nxt,
                redo_stack_text=redo_t,
                redo_active_text=True,
            )
            return await _show_offer_continue_after_textquiz(message, state, target_idx=nxt)  # 💬 перебивка перед пересдачей

        else:
            # сет textquiz завершён — теперь offer_continue
            oc_scene = random.choice(scenarios["offer_continue"])

            # 💬 что делает эта часть: гарантированно убираем старую ReplyKeyboard (если где-то осталась)
            try:
                rm = await bot.send_message(message.chat.id, "\u00AD", reply_markup=ReplyKeyboardRemove())
                await _safe_delete_message(message.chat.id, rm.message_id)
            except Exception:
                pass

            # 💬 что делает эта часть: показываем offer_continue только через inline-кнопки
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
                for btn in oc_scene["buttons"]
            ]])

            await state.update_data(
                current_stage="offer_continue",
                current_scene=oc_scene,
                last_oc_msg_id=None,  # 💬 запишем после отправки, чтобы cb удалял всё корректно
                redo_stack_text=[],
                redo_active_text=False,
            )
            await state.set_state(LessonStates.showing_vocab)

            oc_msg = await smart_reply(message, oc_scene["text"], reply_markup=kb, parse_mode="HTML")
            await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 cb_scenario_vocab удалит это сообщение
            return








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

    # 💬 отправляем текст как quote-блок вместо pre (TypeText)
    await send_quotedtext(message, block["text"], expandable=True)


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
        await asyncio.sleep(REPLY_REACTION_READ_DELAY_S)


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
    # 💬 безопасная отправка медиа с поддержкой: локальный файл / URL / file_id
    mt     = block.get("media_type", "photo")
    source = str(block.get("photo", "")).strip()

    try:
        if mt == "photo":
            # фото: локальный путь → FSInputFile; URL → строкой; file_id → строкой
            if source and os.path.exists(source):
                await bot.send_photo(chat_id, photo=FSInputFile(source))
            elif _is_url(source):
                await bot.send_photo(chat_id, photo=source)
            else:
                await bot.send_photo(chat_id, photo=source)  # допускаем file_id
        elif mt == "animation":
            # gif/mp4: локальный файл / URL / file_id
            if source and os.path.exists(source):
                await bot.send_animation(chat_id, animation=FSInputFile(source))
            elif _is_url(source):
                await bot.send_animation(chat_id, animation=source)
            else:
                await bot.send_animation(chat_id, animation=source)  # допускаем file_id
        elif mt == "sticker":
            # стикер: только валидный file_id или URL; заглушки пропускаем
            if source and source not in (".", "-", "none", "None"):
                await bot.send_sticker(chat_id=chat_id, sticker=source)
            else:
                # 💬 пустой/невалидный стикер — пропускаем блок и идём дальше
                logging.warning("⚠️ Пустой sticker в vocab, блок пропущен.")
                return await proceed_to_next(message, state)
    except TelegramBadRequest as e:
        # 💬 если файл битый/URL неверный — не падаем, а идём дальше
        logging.exception("⚠️ Ошибка отправки медиа: %s", e)
        await bot.send_message(chat_id, "⚠️ Пропустил битый медиа-блок.")
        return await proceed_to_next(message, state)


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
        await asyncio.sleep(REPLY_REACTION_READ_DELAY_S)  # ⏳ Задержка, чтобы пользователь увидел реакцию

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


    # 💬 Реакция на правильный ответ в optional-quiz
    if is_correct:
        try:
            msg_id = data.get("current_optional_message_id")  # уже сохраняется при отправке
            if msg_id:
                await bot.set_message_reaction(
                    chat_id=poll_answer.user.id,
                    message_id=msg_id,
                    reaction=[ReactionTypeEmoji(emoji="🎉")],
                    is_big=True
                )
        except Exception:
            pass


    # 2) фидбэк без XP
    if is_correct:
        await send_and_auto_delete_text(bot, user_id, "🎉 Правильно!", delay=AUTO_DELETE_TEXT_DELAY_S)
    else:
        correct_text = get_vocab_list(data)[data["vocab_index"]]["quiz"]["correct_answer"]
        await send_and_auto_delete_text(bot, user_id, f"✅ {correct_text}", delay=AUTO_DELETE_TEXT_DELAY_S)

    # 3) удаляем сам poll
    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 унификация паузы

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

    # 💬 UX: короткая псевдозагрузка перед следующим сетом
    loading_msg = await message.answer("Гружу... 🙄")        # 💬 что делает эта часть: имитация загрузки
    asyncio.create_task(send_and_auto_delete_text(bot, message.chat.id, "Гружу... 🙄", delay=5))


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


        ref_scene = random.choice(scenarios["refusal"])

        # 💬 что делает эта часть: показываем отказ только через Inline, ReplyKeyboard больше не используем
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=btn, callback_data=f"refusal:{btn}")]
                for btn in ref_scene["buttons"]
            ]
        )

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

    # 💬 НЕ перепрыгиваем в textquiz; пропускаем только если следующий — обычный quiz
    next_idx = data.get("vocab_index", 0) + 1
    vocab_list = get_vocab_list(await state.get_data())  # 💬 берём сессионную лексику (после скрытия фраз)

    '''
    if next_idx < len(vocab_list) and vocab_list[next_idx].get("type") == "quiz":
        # 🎭 небольшой префейс перед квизом
        prefix = random.choice(["👮‍♂️","👮‍♀️","🚓"])           # 💬 что делает эта часть: эмодзи-префейс
        await smart_reply(message, prefix, reply_markup=ReplyKeyboardRemove())  # 💬 скрываем клавиатуру
        phrase = random.choice(vocab_quiz_intro_phrases)
        await smart_reply(message, phrase, reply_markup=ReplyKeyboardRemove())
        await state.update_data(vocab_index=next_idx)
        return await send_one_vocab(message, state)
        '''
    # 💬 что делает эта часть: возвращаем правильный отступ, чтобы не ломался блок after else

    data = await state.get_data()
    topic_key = data["selected_topic"]
    vocab_list = get_vocab_list(data)
    next_idx = data.get("vocab_index", 0) + 1


    # ➕ Пропускаем textquiz, пока есть обычные quiz впереди
    if next_idx < len(vocab_list):
        nt = vocab_list[next_idx].get("type")
        # 💬 если попался textquiz, но дальше ещё есть хотя бы один quiz — прыгаем к ближайшему quiz
        if nt == "textquiz":
            q_idx = next((i for i in range(next_idx, len(vocab_list)) 
                          if vocab_list[i].get("type") == "quiz"), None)
            if q_idx is not None:
                next_idx = q_idx
                nt = "quiz"
        if nt == "quiz":
            # 💬 рандомный эмодзи перед фразой квиза
            emojis = ["👮‍♂️", "👮‍♀️", "🚓"]
            prefix = random.choice(emojis)
            await smart_reply(message, prefix, reply_markup=ReplyKeyboardRemove())

            # 💬 промежуточная фраза перед квизом
            phrase = random.choice(vocab_quiz_intro_phrases)
            await smart_reply(message, phrase, reply_markup=ReplyKeyboardRemove())

            # 💾 обновляем индекс и прыгаем в send_one_vocab
            await state.update_data(vocab_index=next_idx)  # 💬 индекс на старт нужного quiz
            return await send_one_vocab(message, state)
    # иначе — падаем в offer_continue ниже по коду (без изменений)



    # 4️⃣ Иначе — стандартное “offer_continue”
    oc_scene = random.choice(scenarios["offer_continue"])

    oc_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
        for btn in oc_scene["buttons"]
    ]])  # 💬 показываем offer_continue через inline

    await state.update_data(current_stage="offer_continue", current_scene=oc_scene)
    oc_msg = await smart_reply(message, oc_scene["text"], reply_markup=oc_kb, parse_mode="HTML")
    await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 чтобы удалить после клика
    return oc_msg




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

    # 💬 Если пользователь выбрал выход в меню — сразу уходим в меню урока
    if next_stage == "home":
        return await lesson_menu_handler(message, state)


# 💬 Если продолжаем — сначала сдвигаем индекс, потом отправляем следующий блок
    if next_stage == "next_item":

        phrase, sticker_id = random.choice(go_next_phrases)
        await smart_reply(message, phrase)
        # 💬 отправка стикера без await, чтобы не блочить поток
        asyncio.create_task(send_and_auto_delete_sticker(bot, message.chat.id, sticker_id, delay=3))

        if data.get("lex_mode_active"):
            # 💬 что делает эта часть: вместо старого "следующий сет" = запускаем следующий раунд
            data2 = await state.get_data()
            cur_round = data2.get("lex_round", 0)
            total = data2.get("lex_round_total", 4)
            next_round = cur_round + 1

            if next_round >= total:
                await state.update_data(
                    lex_mode_active=False,
                    lex_session_vocab_list=None,
                    lex_active_phrases=None,
                    lex_round=0,
                    lex_round_total=0,
                    lex_textquiz_phrase_cursor=0,
                    lex_textquiz_done_round=False
                )  # 💬 что делает эта часть: завершили все раунды = чистим и выходим
                return await lesson_menu_handler(message, state)

            await _lex_prepare_round_session(state, round_idx=next_round)

            asyncio.create_task(send_and_auto_delete_text(bot, message.chat.id, f"Раунд {next_round + 1} из {total}", delay=2))
            return await send_one_vocab(message, state)


        # 🚀 Переход к следующему сету или textquiz
        vocab_list = get_vocab_list(data)

        # --- 1️⃣ ищем первый quiz следующего сета ---
        # 💬 ВАЖНО: Ищем относительно последнего пройденного ОБЫЧНОГО квиза (якоря), а не текущего TextQuiz
        last_quiz_idx = data.get("last_main_quiz_index", -1)
        
        q_positions = [i for i, b in enumerate(vocab_list) if b.get("type") == "quiz"]
        next_quiz_set_start = None

        if q_positions:
            # Пытаемся найти позицию последнего квиза в списке всех квизов
            try:
                if last_quiz_idx == -1:
                    # Если якоря нет (первый запуск или баг), берем начало списка
                    current_q_pos_index = -1
                else:
                    current_q_pos_index = q_positions.index(last_quiz_idx)
                
                # Нам нужен следующий сет. Просто берем СЛЕДУЮЩИЙ квиз по списку.
                # Так как мы идем блоками по 6, следующий после последнего пройденного — это начало нового блока.
                if current_q_pos_index + 1 < len(q_positions):
                    next_quiz_set_start = q_positions[current_q_pos_index + 1]
                    
            except ValueError:
                # Если вдруг индекс потерялся, ищем первый квиз, который больше последнего сохраненного
                next_val = next((p for p in q_positions if p > last_quiz_idx), None)
                if next_val is not None:
                    next_quiz_set_start = next_val
                elif last_quiz_idx == 0:
                    # 💬 если последний был самый первый, пробуем взять следующий (если он есть)
                    next_quiz_set_start = q_positions[1] if len(q_positions) > 1 else None


        # 💬 Fallback: если якорь last_main_quiz_index не сохранён,
        # или не удалось вычислить старт следующего сета — берём следующий quiz от текущего индекса
        if next_quiz_set_start is None:
            cur_idx = data.get("vocab_index", -1)
            nxt_from_cur = next((p for p in q_positions if p > cur_idx), None)
            if nxt_from_cur is not None:
                next_quiz_set_start = nxt_from_cur  # 💬 гарантируем переход к 7-му и дальше


        if next_quiz_set_start is not None:
            # 💬 есть ещё quiz — двигаемся к следующему сету
            await state.update_data(
                vocab_index=next_quiz_set_start,
                redo_stack=[],
                redo_active=False,
                refusal_count=0
            )
            return await send_one_vocab(message, state)
        # 💬 что делает эта часть: quiz закончились = запускаем финальную textquiz-сессию (до полного закрытия)
        data_now = await state.get_data()
        vocab_list = get_vocab_list(data_now)
        pending = [i for i, b in enumerate(vocab_list) if b.get("type") == "textquiz"]

        if pending:
            await state.update_data(
                textquiz_session_active=True,
                vocab_index=pending[0],
                pending_textquiz=pending,
                redo_stack_text=[],
                resume_vocab_index=None,
                last_main_quiz_index=None,
                redo_stack=[],
                redo_active=False,
                refusal_count=0,
            )
            return await send_one_vocab(message, state)

        # 💬 что делает эта часть: нет textquiz = финал блока
        await smart_reply(message, "🎉 Это конец блока. Молодец!")
        await state.update_data(
            textquiz_session_active=False,
            pending_textquiz=[],
            redo_stack_text=[],
            redo_stack=[],
            redo_active=False,
            refusal_count=0,
            last_main_quiz_index=None
        )
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



    # 💬 Поддержка нескольких вариантов ответа через «;» или списком
    user_ans = normalize_textquiz(message.text)
    answers_raw = block.get("correct_answers") or block.get("correct_answer", "")
    if isinstance(answers_raw, list):
        variants = [v for v in answers_raw if v]
    else:
        variants = [p.strip() for p in str(answers_raw).split(";") if p.strip()]
    norm_variants = [normalize_textquiz(v) for v in variants]
    is_correct = user_ans in norm_variants


    # 💬 Начисляем XP в сессии
    delta = random.randint(15, 25) if is_correct else -10
    await award_xp(delta, state)

    # 🔥 Level-Up: предыдущий глобальный XP
    user_id = message.from_user.id
    xp_before = load_xp_data().get(str(user_id), {}).get("total_xp", 0)
    topic_key = data.get("selected_topic", "unknown")

    # 💬 Запись XP в общее накопление
    await add_xp(user_id, topic_key, delta)  # 💬 XP; слова считаем отдельно (ниже)


    # 🔥 Проверка перехода на новый уровень
    xp_after = load_xp_data().get(str(user_id), {}).get("total_xp", 0)

    if xp_after // XP_PER_LEVEL > xp_before // XP_PER_LEVEL:
        # 💬 что делает эта часть: безопасно берём индекс уровня, не выходим за пределы LEVELS
        lvl_idx = min(xp_after // XP_PER_LEVEL, len(LEVELS) - 1)

        # 💬 что делает эта часть: безопасно берём индекс медали, не выходим за пределы MEDALS
        medal_idx = min(
            (xp_after % XP_PER_LEVEL) // (XP_PER_LEVEL // 3),
            len(MEDALS) - 1,
        )

        # 💬 что делает эта часть: строим короткий прогресс по новой системе уровней
        progress_text = render_short_level_progress(user_id)

        await message.answer(
            f"🎉 Поздравляем! Вы достигли уровня {LEVELS[lvl_idx]}{MEDALS[medal_idx]}!\n\n"
            f"{progress_text}"
        )


        # 💬 Короткий прогресс по новой системе уровней
        progress_text = render_short_level_progress(user_id)

        await message.answer(
            f"🎉 Поздравляем! Вы достигли уровня {LEVELS[lvl_idx]}{MEDALS[medal_idx]}!\n\n"
            f"{progress_text}"
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

    max_cookies = data.get("max_cookies", 0)
    to_give = min(2, max(0, max_cookies - given))  # 💬 даём 2 🍪 за 1 текстквиз, но не превышаем лимит

    if is_correct and to_give > 0:
        # 📌 начисляем «слова выучено» как печеньки (1 слово = 1 🍪)
        for _ in range(to_give):
            await add_xp(user_id, topic_key, 0, action="words_learned")  # 💬 +1 слово (🍪)

        given_after = given + to_give

        # 💬 редко показываем прогресс внутри фазы и удаляем (каждые 6 слов = 3 фразы)
        if given_after % 6 == 0:
            asyncio.create_task(
                send_and_auto_delete_text(
                    bot,
                    message.chat.id,
                    f"📚 В этой фазе уже +{given_after} слов",
                    delay=2.0,
                    parse_mode="HTML"
                )
            )

        # 💬 показываем сколько «печенька» дала слов за этот текстквиз
        extra_fb = await message.answer(f"🍪 +{to_give}\n📚 +{to_give} слов", parse_mode="HTML")


    elif not is_correct:
        # 📌 показываем все допустимые ответы заглавными, через «или»
        correct_str = " или ".join(variants).upper()
        extra_fb = await message.answer(f"👉 {correct_str}", parse_mode="HTML")
        extra_fb = await message.answer(f"👉 {block['correct_answer'].upper()}", parse_mode="HTML")
    else:
        # 📌 лимит печенек достигнут — пропускаем
        extra_fb = None



    # 💬 Ждём 1.5 секунды перед удалением
    await asyncio.sleep(SLEEP_AFTER_FEEDBACK_S)  # 💬 единая пауза перед зачисткой


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
@track_handler
async def go_home(message: Message, state: FSMContext):
    # 💬 Возвращаем в главное меню урока, сохраняя прогресс
    return await lesson_menu_handler(message, state)

# ────────────────────────────────────────────────────────────────────
# 🎬 Поток «Смотреть видео» — выдаём ссылки по теме
# ────────────────────────────────────────────────────────────────────

async def start_video_viewing(message: Message, state: FSMContext):
    # 💬 Показываем следующее видео для текущей темы
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        # 💬 если тема не выбрана, возвращаем пользователя к старту
        return await start_handler(message, state)

    topic = topics.get(topic_key, {})
    videos = topic.get("videos", [])

    # 💬 На всякий случай: если кнопка появилась, а видео нет
    if not videos:
        await smart_reply(
            message,
            "Пока для этой темы нет видео 🙈",
            parse_mode="HTML",
        )
        return

    # 💬 Берём текущий индекс видео из FSM, если вышли за предел — начинаем сначала
    dv_idx = data.get("video_index", 0) or 0
    if dv_idx >= len(videos):
        dv_idx = 0

    video = videos[dv_idx]
    title = video.get("title") or "Видео"
    link  = video.get("link") or ""

    text = f"🎬 <b>{title}</b>"
    if link:
        text += f"\n{link}"

    # 💬 Инлайн-кнопка «галочка», чтобы отметить видео как просмотренное
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅", callback_data=f"video_done:{dv_idx}")]
        ]
    )

    await smart_reply(
        message,
        text,
        parse_mode="HTML",
        reply_markup=kb,
        # 💬 превью ссылки оставляем включённым
    )


@dp.callback_query(
    StateFilter(LessonStates.waiting_lesson_action),
    F.data.startswith("video_done:")
)
@track_handler
async def handle_video_done_inline(callback: CallbackQuery, state: FSMContext):
    # 💬 Отмечаем видео как просмотренное из инлайн-кнопки и возвращаем в меню
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        await callback.answer()
        return await start_handler(callback.message, state)

    topic = topics.get(topic_key, {})
    videos = topic.get("videos", [])

    # если вдруг кнопка есть, а видео нет — просто уводим домой
    if not videos:
        await callback.answer()
        return await lesson_menu_handler(callback.message, state)

    # парсим индекс из callback_data вида "video_done:0"
    try:
        _, idx_str = callback.data.split(":", 1)
        done_idx = int(idx_str)
    except Exception:
        done_idx = data.get("video_index", 0) or 0

    current_idx = data.get("video_index", 0) or 0

    # 💬 двигаем прогресс: минимум — current_idx, максимум — len(videos)
    new_idx = max(current_idx, done_idx + 1)
    if new_idx > len(videos):
        new_idx = len(videos)

    await state.update_data(video_index=new_idx)

    # 💬 убираем инлайн-клавиатуру под сообщением с ссылкой
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("✅ Видео отмечено как просмотренное")

    # 💬 возвращаем в меню урока, где пересчитаются звёздочки по видео
    await state.set_state(LessonStates.waiting_lesson_action)
    return await lesson_menu_handler(callback.message, state)



# ────────────────────────────────────────────────────────────────────
# 🙊 Поток «Читать диалоги» — новая версия (самопроверка по ✅ / ❌)
# ────────────────────────────────────────────────────────────────────

async def start_dialog_reading(message: Message, state: FSMContext):
    # 💬 Стартуем чтение диалогов для текущей темы

    # 1️⃣ Скрываем меню урока и Reply-клавиатуру (как в потоке «Учить слова»)
    data = await state.get_data()
    last_menu_msg_id = data.get("last_menu_msg_id")
    if last_menu_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=last_menu_msg_id)
        except Exception:
            pass
        # 💬 меню убрали, больше его не существует
        await state.update_data(last_menu_msg_id=None)

        last_progress_msg_id = data.get("last_progress_msg_id")
        if last_progress_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=last_progress_msg_id)
            except Exception:
                pass
            await state.update_data(last_progress_msg_id=None)  # 💬 прогресс-блок убрали, чтобы не висел при старте чтения


    # 💬 отправляем краткую «пустышку», чтобы убрать Reply-клавиатуру
    try:
        tmp = await message.answer("Загружаю...⏳", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass

    # 2️⃣ Проверяем, что выбрана тема и в ней есть диалоговые фазы
    data = await state.get_data()  # перечитываем после апдейта
    topic_key = data.get("selected_topic")
    if not topic_key:
        # 💬 если тема потерялась — возвращаем пользователя в старт
        return await start_handler(message, state)

    topic = topics.get(topic_key, {})
    dialog_phases = topic.get("translate", []) or topic.get("dialogs", [])  # 💬 сначала новый ключ translate, видим старый dialogs как fallback

    if not dialog_phases:
        await smart_reply(message, "Пока в этой теме нет переводов 🙈", parse_mode="HTML")  # 💬 UI для кнопки «Переводить»
        return await lesson_menu_handler(message, state)

    # 3️⃣ Показываем выбор фазы перевода (даже если она одна)
    buttons = [
        [InlineKeyboardButton(
            text=phase.get("phase_name", f"Фаза {phase.get('phase_id')}"),
            callback_data=f"dialog_phase:{phase.get('phase_id')}"
        )]
        for phase in dialog_phases
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await smart_reply(
        message,
        "Выбери фазу перевода:",
        reply_markup=kb,
        parse_mode="HTML",
    )

    await state.set_state(LessonStates.waiting_dialog_phase)


@dp.callback_query(
    StateFilter(LessonStates.waiting_dialog_phase),
    F.data.startswith("dialog_phase:")
)
@track_handler
async def handle_dialog_phase_choice(callback: CallbackQuery, state: FSMContext):
    # 💬 Пользователь выбрал фазу диалогов
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key:
        await callback.answer()
        return await start_handler(callback.message, state)

    try:
        phase_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    topic = topics.get(topic_key, {})
    dialog_phases = topic.get("translate", []) or topic.get("dialogs", [])  # 💬 сначала новый ключ translate, видим старый dialogs как fallback
    phase = next((p for p in dialog_phases if p.get("phase_id") == phase_id), None)
    if not phase:
        await callback.answer("Не нашёл такую фазу перевода 😕", show_alert=True)  # 💬 UI под «Переводить»
        return

    blocks = [b for b in phase.get("blocks", []) if b.get("lines")]
    if not blocks:
        await callback.answer("В этой фазе пока нет блоков перевода 🙈", show_alert=True)  # 💬 UI под «Переводить»
        return


    await state.update_data(
        dialog_phase_id=phase_id,
        dialog_blocks=blocks,
        dialog_index=0,
        dialog_failed=[],
        dialog_redo_stack=[],
        dialog_current_index=None,
        dialog_current_mode=None,
    )

    await callback.answer()
    try:
        # 💬 Удаляем сообщение с выбором фазы
        await callback.message.delete()
    except Exception:
        pass

    # 💬 Небольшое вступление перед запуском диалогов фазы
    phase_title = phase.get("phase_name", f"Фаза {phase_id}")
    intro_text = (
        f"🙊 Ок, читаем диалоги по фазе:\n"
        f"<b>{phase_title}</b>\n\n"
        "Переведи в голове на испанский\n"
        "Если получилось, жми ✅\n"
        "Если нет ❌ и фрагмент повториться"
    )  # 💬 новая короткая инструкция

    # 💬 Отправляем интро и ставим авто-удаление на 10 секунд
    intro_msg = await smart_reply(callback.message, intro_text, parse_mode="HTML")

    async def _delete_intro_later(chat_id: int, msg_id: int, delay: float = 10.0):
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    asyncio.create_task(_delete_intro_later(intro_msg.chat.id, intro_msg.message_id))

    # 💬 Сообщение-контейнер: дальше будем только редактировать его (без delete + без новых сообщений)
    marker_msg = await smart_reply(callback.message, "Читаем...", parse_mode="HTML")
    await state.update_data(
        dialog_msg_id=marker_msg.message_id,
        dialog_msg_chat_id=marker_msg.chat.id,
    )  # 💬 запоминаем, какое сообщение редактируем

    await state.set_state(LessonStates.showing_dialog)
    return await send_one_dialog_block(marker_msg, state)




async def send_one_dialog_block(message: Message, state: FSMContext):
    """
    💬 Показывает один блок диалога с кнопками самопроверки.
    """
    data = await state.get_data()
    blocks = data.get("dialog_blocks") or []
    index = data.get("dialog_index", 0)
    redo_stack = data.get("dialog_redo_stack") or []

    if not blocks:
        await smart_reply(message, "Пока в этой фазе нет диалогов 🙈", parse_mode="HTML")
        await state.set_state(LessonStates.waiting_lesson_action)
        return await lesson_menu_handler(message, state)

    # 💬 Всё пройдено и повтора не осталось — завершаем фазу
    if index >= len(blocks) and not redo_stack:
        delta = 30  # 💬 XP за одну пройденную фазу диалогов
        await award_dialog(delta, state)

        data = await state.get_data()
        topic_key = data.get("selected_topic", "unknown")
        user_id = message.from_user.id
        await add_xp(user_id, topic_key, delta)

        await smart_reply(
            message,
            "🎉 Ты прошёл(а) все диалоги в этой фазе!\n\nВозвращаю в меню темы.",
            parse_mode="HTML",
        )
        await state.set_state(LessonStates.waiting_lesson_action)
        return await lesson_menu_handler(message, state)

    # 💬 Определяем, какой индекс показываем: основной проход или redo_stack
    mode = "main"
    if index >= len(blocks) and redo_stack:
        current_index = redo_stack[0]
        mode = "redo"
    else:
        current_index = index

    block = blocks[current_index]
    lines = block.get("lines", [])

    # 💬 Конвертируем [[...]] → HTML-спойлеры Telegram
    rendered_lines = []
    for ln in lines:
        ln = ln.replace("\\n", "\n")

        html = re.sub(r"\[\[(.+?)\]\]", r'<span class="tg-spoiler">\1</span>', ln)

        # 💬 ставим стрелку прямо перед спойлером (перед ES строкой это будет выглядеть как "➜ [spoiler]")
        if '<span class="tg-spoiler">' in html:
            html = html.replace('<span class="tg-spoiler">', '➜ <span class="tg-spoiler">', 1)

        # 💬 текст внутри спойлера делаем жирным (курсив даст общий <i> ниже)
        html = re.sub(
            r'<span class="tg-spoiler">(.*?)</span>',
            r'<span class="tg-spoiler"><b>\1</b></span>',
            html
        )


        rendered_lines.append(html)

    text = "\n".join(rendered_lines)

    # 💬 вся карточка "Читать" = курсив, а внутри спойлера будет жирный+курсив
    if not text.startswith("<i>"):
        text = f"<i>{text}</i>"


    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅", callback_data="dialog:ok"),
            InlineKeyboardButton(text="❌", callback_data="dialog:fail"),
        ]]
    )

    # 💬 Запоминаем, какой блок сейчас показан
    await state.update_data(
        dialog_current_index=current_index,
        dialog_current_mode=mode,
    )

    chat_id = data.get("dialog_msg_chat_id") or message.chat.id
    msg_id = data.get("dialog_msg_id") or message.message_id

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )  # 💬 редактируем одно и то же сообщение, без удаления и без новых сообщений
    except Exception:
        new_msg = await smart_reply(message, text, reply_markup=kb, parse_mode="HTML")
        await state.update_data(
            dialog_msg_id=new_msg.message_id,
            dialog_msg_chat_id=new_msg.chat.id,
        )  # 💬 fallback если edit невозможен



@dp.callback_query(
    StateFilter(LessonStates.showing_dialog),
    F.data.in_(["dialog:ok", "dialog:fail"])
)
@track_handler
async def handle_dialog_selfcheck(callback: CallbackQuery, state: FSMContext):
    # 💬 Обработка нажатия ✅ / ❌ в диалогах
    data = await state.get_data()
    blocks = data.get("dialog_blocks") or []
    if not blocks:
        await callback.answer()
        await state.set_state(LessonStates.waiting_lesson_action)
        return await lesson_menu_handler(callback.message, state)

    current_index = data.get("dialog_current_index", 0)
    mode = data.get("dialog_current_mode", "main")
    index = data.get("dialog_index", 0)
    redo_stack = data.get("dialog_redo_stack") or []
    failed = data.get("dialog_failed") or []

    is_ok = (callback.data == "dialog:ok")

    if is_ok:
        # 💬 Убираем из списков ошибок
        if current_index in failed:
            failed = [i for i in failed if i != current_index]
        if current_index in redo_stack:
            redo_stack = [i for i in redo_stack if i != current_index]
        if mode == "main":
            index = max(index, current_index + 1)
        else:
            if redo_stack and redo_stack[0] == current_index:
                redo_stack = redo_stack[1:]
    else:
        # 💬 Добавляем в redo_stack
        if current_index not in failed:
            failed.append(current_index)
        if current_index not in redo_stack:
            redo_stack.append(current_index)
        if mode == "main":
            index = max(index, current_index + 1)
        else:
            if redo_stack and redo_stack[0] == current_index:
                redo_stack = redo_stack[1:]
            redo_stack.append(current_index)

    await state.update_data(
        dialog_index=index,
        dialog_redo_stack=redo_stack,
        dialog_failed=failed,
    )

    # 💬 если вдруг id контейнера ещё не записан (старые сессии) = запомним текущее сообщение
    if not data.get("dialog_msg_id"):
        await state.update_data(
            dialog_msg_id=callback.message.message_id,
            dialog_msg_chat_id=callback.message.chat.id,
        )  # 💬 чтобы дальше работал edit_message_text

    await callback.answer()  # 💬 гасим loading быстро, без delete

    # 💬 Переходим к следующему блоку (или завершаем фазу) через редактирование
    return await send_one_dialog_block(callback.message, state)


# ——————— Конец «🙊Читать диалог» ———————


@dp.callback_query(
    lambda c: c.data and c.data.startswith("check_subscription:"),
    StateFilter(LessonStates.waiting_subscription)
)
async def check_subscription(query: CallbackQuery, state: FSMContext):
    await query.answer()
    # 💬 получаем тему и канал из state
    data = await state.get_data()
    topic_key = data.get("selected_topic")

    # 💬 Берём полный список каналов из state (новая логика)
    required = data.get("required_channels") or []

    uid = str(query.from_user.id)

    # 💬 Восстанавливаем список каналов из state
    required = data.get("required_channels") or []
    if not required:
        # на всякий случай поддерживаем старый формат с одним каналом
        ch = data.get("required_channel")
        if ch:
            required = [ch]



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

            # удаляем старое сообщение и reply-кейборд
            try:
                await query.message.delete()  # 💬 если сообщение уже удалено = не падаем
            except TelegramBadRequest:
                pass
            blank = await query.message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
            await blank.delete()


            # показываем список каналов и inline-кнопку «Проверить подписку»
            channels_str = ", ".join(required)
            return await query.message.answer(
                "🔒 Для бесплатного доступа\n"
                "👇🏼 Подпишись на спонсорские каналы:",  # 💬 повторяем оффер при провале проверки
                reply_markup=check_subscription_kb(topic_key, required)
            )






    # 2) Всё ок — удаляем сообщение с кнопкой «Проверить подписку»
    await query.message.delete()
    # 💬 Оповещаем об открытии доступа
    await query.message.answer("✅ Доступ к теме открыт!")
    data    = load_user_data()
    u       = data.setdefault(uid, {})

    unlocked = u.setdefault("unlocked_topics", [])
    if topic_key not in unlocked:
        unlocked.append(topic_key)

    # — добавляем новую сессию подписки по каждому каналу из набора
    for ch in required:
        sessions = u.setdefault("channels", {}).setdefault(ch, [])
        if not sessions or sessions[-1].get("unsubscribed_at") is not None:
            sessions.append({"subscribed_at": now, "unsubscribed_at": None})

    # 💬 отключаем таймерный доступ = подписку проверяем каждый раз при входе в тему
    u.pop("ad_subscription", None)
    

    save_user_data(data)

    try:
        bonus_try_qualify_referral(uid, required)  # 💬 если пришёл по реф-ссылке = засчитываем приглашение
    except Exception:
        logging.exception("bonus_try_qualify_referral failed")


    # 3) Возвращаемся в меню урока
    return await lesson_menu_handler(query.message, state)





@dp.message(LessonStates.waiting_subscription)
@track_handler
async def handle_subscription_invalid_input(message: Message, state: FSMContext):
    # 💬 Если пользователь пишет что-то вместо нажатия кнопки — просим нажать inline-кнопку
    data         = await state.get_data()
    topic_key    = data.get("selected_topic")
    required_ch  = data.get("required_channel")  # 💬 канал, сохранённый при показе блока подписки
    required     = [required_ch] if required_ch else []

    # убираем reply-кейборд (лексика/грамматика)
    await message.answer('\u00AD', reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "Пожалуйста, нажмите кнопку «Проверить подписку».",
        reply_markup=check_subscription_kb(topic_key, required)  # 💬 та же инлайн-клавиатура с каналом
    )





async def _show_offer_continue_after_textquiz(message: Message, state: FSMContext, target_idx: int):
    data = await state.get_data()

    # 💬 что делает эта часть: удаляем вопрос textquiz и ответ пользователя перед offer_continue
    prompt_id = data.get("vocab_textquiz_prompt_id") or data.get("last_prompt_id")
    to_delete = [prompt_id, getattr(message, "message_id", None)]
    for mid in to_delete:
        if not mid:
            continue
        try:
            await bot.delete_message(message.chat.id, mid)
        except TelegramBadRequest:
            pass

    oc_scene = random.choice(scenarios["offer_continue"])

    # 💬 что делает эта часть: на всякий случай убираем ReplyKeyboard, чтобы не висела
    try:
        rm = await bot.send_message(message.chat.id, "\u00AD", reply_markup=ReplyKeyboardRemove())
        await _safe_delete_message(message.chat.id, rm.message_id)
    except Exception:
        pass

    # 💬 что делает эта часть: показываем offer_continue только через inline-кнопки
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=btn, callback_data=f"offer_continue:{btn}")
        for btn in oc_scene["buttons"]
    ]])

    await state.update_data(
        current_stage="offer_continue",
        current_scene=oc_scene,
        last_oc_msg_id=None,                 # 💬 запишем после отправки, чтобы cb удалял всё корректно
        offer_continue_target_idx=target_idx # 💬 куда прыгнуть после “Продолжить”
    )
    await state.set_state(LessonStates.showing_vocab)

    oc_msg = await smart_reply(message, oc_scene["text"], reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_oc_msg_id=oc_msg.message_id)  # 💬 cb_scenario_vocab удалит это сообщение
    return



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
    await asyncio.sleep(REPLY_REACTION_READ_DELAY_S)


    # 3) обработка по веткам — сначала confirm_done
    if stage == "confirm_done":
        next_stage = params["next"]
        if next_stage == "next_item":
            # 💬 после “Продолжить” прыгаем на ближайший следующий обычный quiz, а не на textquiz
            curr = data.get("vocab_index", 0)                 # 💬 что делает эта часть: текущий индекс
            vocab_list = get_vocab_list(data)                  # 💬 общий список блоков
            candidate = curr + 1

            # 💬 если следующий — textquiz, ищем следующий quiz вперёд
            if candidate < len(vocab_list) and vocab_list[candidate].get("type") == "textquiz":
                q_idx = next((i for i in range(candidate, len(vocab_list))
                              if vocab_list[i].get("type") == "quiz"), None)
                if q_idx is not None:
                    candidate = q_idx

            await state.update_data(vocab_index=candidate, refusal_count=0)  # 💬 сбрасываем счётчик отказов
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
            await asyncio.sleep(REPLY_REACTION_READ_DELAY_S)

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

        '''
        # ➕ Сначала пробуем найти ближайший обычный quiz (чтобы не запускать textquiz раньше времени)
        if next_idx < len(vocab_list):
            nt = vocab_list[next_idx].get("type")
            if nt == "textquiz":
                q_idx = next((i for i in range(next_idx, len(vocab_list)) 
                              if vocab_list[i].get("type") == "quiz"), None)
                if q_idx is not None:
                    next_idx = q_idx
                    nt = "quiz"
            if nt == "quiz":
                prefix = random.choice(["👮‍♂️","👮‍♀️","🚓"])
                await cb.message.answer(prefix)
                await asyncio.sleep(0.5)
                phrase = random.choice(vocab_quiz_intro_phrases)
                await cb.message.answer(phrase)
                await state.update_data(vocab_index=next_idx)
                return await send_one_vocab(cb.message, state)
            # иначе — рисуем inline-offer_continue как сейчас
                '''

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
        await asyncio.sleep(REPLY_REACTION_READ_DELAY_S)


        # 3) Убираем inline-кнопки
        try:
            await cb.message.edit_reply_markup()
        except TelegramBadRequest:
            pass

        # 💬 что делает эта часть: если textquiz поставил точный target_idx, то "Продолжить" прыгает туда без инкремента
        target_idx = data.get("offer_continue_target_idx")
        if next_stage == "next_item" and target_idx is not None:
            vocab_list = get_vocab_list(data)
            if 0 <= target_idx < len(vocab_list):
                await state.update_data(vocab_index=target_idx, offer_continue_target_idx=None)
                return await send_one_vocab(cb.message, state)

            # 💬 что делает эта часть: target сломан/вышел за границы = просто чистим и падаем в обычную логику ниже
            await state.update_data(offer_continue_target_idx=None)


        # 💬 удаляем сообщение offer_continue целиком: текст, реакцию, кнопки
        try:
            last_oc_msg_id = data.get("last_oc_msg_id")
            if last_oc_msg_id and last_oc_msg_id != cb.message.message_id:
                await bot.delete_message(cb.message.chat.id, last_oc_msg_id)  # 💬 удаляем сохранённый offer_continue
        except TelegramBadRequest:
            pass

        try:
            await cb.message.delete()  # 💬 удаляем то сообщение, по кнопке которого кликнули
        except TelegramBadRequest:
            pass

        await state.update_data(last_oc_msg_id=None)  # 💬 чистим, чтобы не пытаться удалить повторно


        # Переход по результату
        if next_stage == "next_item":
            curr = data.get("vocab_index", 0)
            vocab_list = get_vocab_list(data)
            candidate = curr + 1

            if candidate < len(vocab_list) and vocab_list[candidate].get("type") == "textquiz":
                q_idx = next((i for i in range(candidate, len(vocab_list)) 
                              if vocab_list[i].get("type") == "quiz"), None)
                if q_idx is not None:
                    candidate = q_idx

            await state.update_data(vocab_index=candidate, refusal_count=0)
            return await send_one_vocab(cb.message, state)

        if next_stage == "home":
            await state.update_data(
                lex_mode_active=False,
                lex_session_vocab_list=None,
                lex_active_phrases=None,
                lex_round=0,
                lex_round_total=0,
                lex_textquiz_phrase_cursor=0,
                lex_textquiz_done_round=False
            )  # 💬 что делает эта часть: чистим сессию ALL IN при выходе в меню

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

        migrate_runtime_files_to_volume()  # 💬 выполняется один раз при старте


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






































































