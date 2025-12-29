# battle_feature.py
# 💬 Отдельный модуль "Битва" = отдельные состояния, задачи, сохранение очков

import os
import json
import time
import random
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest


router = Router()

# 💬 Ссылка на topics из core8_1 (чтобы не делать круговой импорт)
TOPICS_REF: Dict[str, Any] = {}

def set_topics_ref(topics: Dict[str, Any]) -> None:
    global TOPICS_REF
    TOPICS_REF = topics or {}


# ─────────────────────────────────────────────────────────
# ⚔️ FSM
# ─────────────────────────────────────────────────────────
class BattleStates(StatesGroup):
    choosing_topic = State()
    matchmaking = State()
    in_battle = State()
    post_battle = State()


# ─────────────────────────────────────────────────────────
# ⚙️ Константы
# ─────────────────────────────────────────────────────────
BATTLE_DURATION_S = 60
BOT_SCORE_EVERY_S = 7
POLL_TIME_S = 7
MAX_QUESTIONS_PER_BATTLE = 8  # 💬 60 сек / 7 сек ≈ 8 вопросов
STOP_TEXT = "⛔ Stop"

BATTLE_DATA_PATH = "/data/battle_data.json"
BATTLE_DATA_TMP = "/data/battle_data.tmp"


# ─────────────────────────────────────────────────────────
# 💾 Хранилище очков
# ─────────────────────────────────────────────────────────
def _ensure_data_dir() -> None:
    os.makedirs("/data", exist_ok=True)

def load_battle_data() -> Dict[str, Any]:
    _ensure_data_dir()
    if not os.path.exists(BATTLE_DATA_PATH):
        return {}
    try:
        with open(BATTLE_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_battle_data(data: Dict[str, Any]) -> None:
    _ensure_data_dir()
    try:
        with open(BATTLE_DATA_TMP, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(BATTLE_DATA_TMP, BATTLE_DATA_PATH)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# 🧠 Runtime (задачи + ожидание ответа)
# ─────────────────────────────────────────────────────────
@dataclass
class BattleRuntime:
    stop: bool = False
    event: asyncio.Event = asyncio.Event()
    current_poll_id: Optional[str] = None
    chosen_option: Optional[int] = None

    opponent_name: str = "Opponent"
    topic_key: str = ""
    topic_title: str = ""

    start_monotonic: float = 0.0
    user_score: int = 0
    bot_score: int = 0

    score_msg_id: Optional[int] = None
    poll_msg_ids: List[int] = None

    task_tick: Optional[asyncio.Task] = None
    task_main: Optional[asyncio.Task] = None


BATTLES: Dict[int, BattleRuntime] = {}


def _stop_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=STOP_TEXT)]],
        resize_keyboard=True
    )

def _result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔁 Реванш", callback_data="battle:rematch"),
            InlineKeyboardButton(text="🏠 В меню", callback_data="battle:menu"),
        ]
    ])

def _topics_kb(topic_keys: List[str]) -> InlineKeyboardMarkup:
    rows = []
    for k in topic_keys[:18]:
        info = TOPICS_REF.get(k, {})
        title = info.get("title") or k
        rows.append([InlineKeyboardButton(text=f"⚔️ {title}", callback_data=f"battle:topic:{k}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="battle:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _left_seconds(rt: BattleRuntime) -> int:
    elapsed = time.monotonic() - rt.start_monotonic
    left = int(BATTLE_DURATION_S - elapsed)
    return max(0, left)

def _format_score(rt: BattleRuntime) -> str:
    left = _left_seconds(rt)
    return (
        f"⚔️ <b>Битва</b>\n"
        f"📌 Тема: <b>{rt.topic_title}</b>\n\n"
        f"👤 Ты: <b>{rt.user_score}</b>\n"
        f"🤖 {rt.opponent_name}: <b>{rt.bot_score}</b>\n\n"
        f"⏱ Осталось: <b>{left}</b> сек\n\n"
        f"💬 Нажми {STOP_TEXT} чтобы выйти"
    )


def _collect_poll_quizzes(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    💬 Берём только poll quiz (без textquiz).
    Поддержка 2 мест:
      1) phase["quiz_pool"]
      2) блоки внутри phase["vocab"] где b.get("quiz") и это poll-quiz
    """
    out: List[Dict[str, Any]] = []
    for ph in topic.get("vocab", []) or []:
        for q in (ph.get("quiz_pool") or []):
            if isinstance(q, dict) and q.get("options") and q.get("correct_index") is not None:
                out.append(q)

        for b in (ph.get("vocab") or []):
            q = b.get("quiz") if isinstance(b, dict) else None
            if isinstance(q, dict) and q.get("options") and q.get("correct_index") is not None:
                out.append(q)

    return out


async def _safe_delete(bot: Bot, chat_id: int, msg_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


async def _cancel_battle(user_id: int) -> None:
    rt = BATTLES.get(user_id)
    if not rt:
        return
    rt.stop = True
    try:
        rt.event.set()
    except Exception:
        pass

    for t in [rt.task_tick, rt.task_main]:
        if t and not t.done():
            t.cancel()


async def _tick_loop(bot: Bot, chat_id: int, user_id: int, state: FSMContext) -> None:
    rt = BATTLES.get(user_id)
    if not rt:
        return

    while not rt.stop and _left_seconds(rt) > 0:
        await asyncio.sleep(BOT_SCORE_EVERY_S)
        if rt.stop or _left_seconds(rt) <= 0:
            break

        rt.bot_score += 1  # 💬 соперник набирает очки по таймеру
        if rt.score_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=rt.score_msg_id,
                    text=_format_score(rt),
                    parse_mode="HTML",
                    reply_markup=_stop_kb(),
                )
            except TelegramBadRequest:
                pass


async def _battle_loop(bot: Bot, chat_id: int, user_id: int, state: FSMContext) -> None:
    rt = BATTLES.get(user_id)
    if not rt:
        return

    rt.start_monotonic = time.monotonic()
    rt.poll_msg_ids = []

    # 💬 scoreboard сообщение
    score_msg = await bot.send_message(
        chat_id=chat_id,
        text=_format_score(rt),
        parse_mode="HTML",
        reply_markup=_stop_kb(),
    )
    rt.score_msg_id = score_msg.message_id

    # 💬 вопросы
    topic = TOPICS_REF.get(rt.topic_key, {}) or {}
    quiz_list = _collect_poll_quizzes(topic)
    random.shuffle(quiz_list)

    # 💬 "полквиза" и лимит под 60 секунд
    n = max(1, len(quiz_list) // 2) if quiz_list else 0
    n = min(n, MAX_QUESTIONS_PER_BATTLE)

    for i in range(n):
        if rt.stop or _left_seconds(rt) <= 0:
            break

        q = quiz_list[i]
        question = (q.get("question") or "Вопрос").strip()
        options = list(q.get("options") or [])
        correct = int(q.get("correct_index") or 0)

        # 💬 Telegram = максимум 10 вариантов
        options = options[:10]
        if correct >= len(options):
            correct = 0

        rt.event.clear()
        rt.current_poll_id = None
        rt.chosen_option = None

        poll_msg = await bot.send_poll(
            chat_id=chat_id,
            question=question[:290],
            options=[str(x)[:100] for x in options],
            type="quiz",
            correct_option_id=correct,
            is_anonymous=False,
            open_period=POLL_TIME_S,
        )
        rt.current_poll_id = poll_msg.poll.id
        rt.poll_msg_ids.append(poll_msg.message_id)

        # 💬 ждём ответ или таймаут
        try:
            await asyncio.wait_for(rt.event.wait(), timeout=POLL_TIME_S + 1)
        except asyncio.TimeoutError:
            pass

        # 💬 проверяем ответ
        if rt.chosen_option is not None and rt.chosen_option == correct:
            rt.user_score += 1

        # 💬 обновляем scoreboard
        if rt.score_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=rt.score_msg_id,
                    text=_format_score(rt),
                    parse_mode="HTML",
                    reply_markup=_stop_kb(),
                )
            except TelegramBadRequest:
                pass

        # 💬 чистим poll чтобы чат не захламлять
        await _safe_delete(bot, chat_id, poll_msg.message_id)

    # 💬 стопаем и финализируем
    rt.stop = True

    # 💬 убираем stop клавиатуру
    try:
        await bot.send_message(chat_id, "\u00AD", reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass

    # 💬 результат
    win = rt.user_score > rt.bot_score
    draw = rt.user_score == rt.bot_score

    header = "🏁 <b>Финиш</b>\n"
    if draw:
        header += "🤝 <b>Ничья</b>\n\n"
    elif win:
        header += "🏆 <b>Победа</b>\n\n"
    else:
        header += "😈 <b>Поражение</b>\n\n"

    result_text = (
        header
        + f"👤 Ты: <b>{rt.user_score}</b>\n"
        + f"🤖 {rt.opponent_name}: <b>{rt.bot_score}</b>\n\n"
        + f"💰 Очки в копилку: <b>+{rt.user_score}</b>"
    )

    # 💬 сохраняем очки
    bd = load_battle_data()
    uid = str(user_id)
    u = bd.setdefault(uid, {})
    u["total_points"] = int(u.get("total_points", 0)) + int(rt.user_score)
    u["wins"] = int(u.get("wins", 0)) + (1 if win else 0)
    u["losses"] = int(u.get("losses", 0)) + (1 if (not win and not draw) else 0)
    u["draws"] = int(u.get("draws", 0)) + (1 if draw else 0)

    by_topic = u.setdefault("by_topic", {})
    t = by_topic.setdefault(rt.topic_key, {})
    t["points"] = int(t.get("points", 0)) + int(rt.user_score)
    t["wins"] = int(t.get("wins", 0)) + (1 if win else 0)
    t["losses"] = int(t.get("losses", 0)) + (1 if (not win and not draw) else 0)
    t["draws"] = int(t.get("draws", 0)) + (1 if draw else 0)

    u["last_played"] = int(time.time())
    save_battle_data(bd)

    # 💬 кнопки результата
    res_msg = await bot.send_message(
        chat_id=chat_id,
        text=result_text,
        parse_mode="HTML",
        reply_markup=_result_kb(),
    )

    await state.set_state(BattleStates.post_battle)
    await state.update_data(battle_last_topic=rt.topic_key, battle_last_result_msg_id=res_msg.message_id)


# ─────────────────────────────────────────────────────────
# ✅ Публичный вход из core8_1 (кнопка в меню "Лексика")
# ─────────────────────────────────────────────────────────
async def start_battle_from_lex_menu(message: Message, state: FSMContext) -> None:
    # 💬 отменяем предыдущий бой если вдруг уже был
    await _cancel_battle(message.from_user.id)

    # 💬 собираем темы где есть poll-quiz
    keys = []
    for k, info in (TOPICS_REF or {}).items():
        if not isinstance(info, dict):
            continue
        if info.get("category") != "lex":
            continue
        if len(_collect_poll_quizzes(info)) > 0:
            keys.append(k)

    if not keys:
        await message.answer("Пока нет тем для битвы 🙈")
        return

    random.shuffle(keys)
    await state.set_state(BattleStates.choosing_topic)

    await message.answer(
        "⚔️ <b>Выбери тему для битвы</b>",
        parse_mode="HTML",
        reply_markup=_topics_kb(keys),
    )


# ─────────────────────────────────────────────────────────
# 🎯 Выбор темы
# ─────────────────────────────────────────────────────────
@router.callback_query(StateFilter(BattleStates.choosing_topic, BattleStates.post_battle), F.data.startswith("battle:topic:"))
async def battle_choose_topic(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()

    # 💬 убираем inline чтобы не нажали 2 раза
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    topic_key = callback.data.split("battle:topic:", 1)[1]
    info = TOPICS_REF.get(topic_key, {}) or {}
    title = info.get("title") or topic_key

    await state.set_state(BattleStates.matchmaking)
    await state.update_data(battle_last_topic=topic_key)

    # 💬 “загружаем соперника”
    loading = await callback.message.answer("🔎 Загружаем соперника…")
    await asyncio.sleep(1)

    opponent = random.choice([
        "Rival_Pro", "ElJefe", "TurboJuan", "Sombra", "Lobo", "MisterX",
        f"User{random.randint(1000, 9999)}"
    ])

    try:
        await loading.edit_text(f"✅ Соперник найден: <b>{opponent}</b>\n⏱ Бой = {BATTLE_DURATION_S} сек", parse_mode="HTML")
    except TelegramBadRequest:
        pass

    # 💬 создаём runtime и запускаем задачи
    user_id = callback.from_user.id
    rt = BattleRuntime()
    rt.opponent_name = opponent
    rt.topic_key = topic_key
    rt.topic_title = title
    BATTLES[user_id] = rt

    await state.set_state(BattleStates.in_battle)

    rt.task_tick = asyncio.create_task(_tick_loop(bot, callback.message.chat.id, user_id, state))
    rt.task_main = asyncio.create_task(_battle_loop(bot, callback.message.chat.id, user_id, state))


# ─────────────────────────────────────────────────────────
# 🛑 Stop во время боя
# ─────────────────────────────────────────────────────────
@router.message(StateFilter(BattleStates.in_battle), F.text == STOP_TEXT)
async def battle_stop(message: Message, state: FSMContext, bot: Bot):
    # 💬 останавливаем бой и возвращаем в меню битвы
    await _cancel_battle(message.from_user.id)

    try:
        await message.answer("\u00AD", reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass

    await message.answer("⛔ Бой остановлен")
    await start_battle_from_lex_menu(message, state)


# ─────────────────────────────────────────────────────────
# 🗳 poll_answer во время боя
# ─────────────────────────────────────────────────────────
@router.poll_answer(StateFilter(BattleStates.in_battle))
async def battle_poll_answer(poll_answer, state: FSMContext):
    user_id = poll_answer.user.id
    rt = BATTLES.get(user_id)
    if not rt or rt.stop:
        return

    if rt.current_poll_id and poll_answer.poll_id != rt.current_poll_id:
        return

    # 💬 фиксируем вариант и пробуждаем ожидание
    try:
        rt.chosen_option = int(poll_answer.option_ids[0]) if poll_answer.option_ids else None
    except Exception:
        rt.chosen_option = None

    try:
        rt.event.set()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# 🔁 Реванш
# ─────────────────────────────────────────────────────────
@router.callback_query(StateFilter(BattleStates.post_battle), F.data == "battle:rematch")
async def battle_rematch(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    # 💬 убираем inline чтобы не нажали 2 раза
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    data = await state.get_data()
    topic_key = data.get("battle_last_topic")
    if not topic_key:
        await callback.message.answer("Не нашёл тему для реванша 🙈")
        return

    # 💬 запускаем матчмейкинг тем же путём
    fake_cb = callback
    fake_cb.data = f"battle:topic:{topic_key}"
    await battle_choose_topic(fake_cb, state, bot=callback.bot)


# ─────────────────────────────────────────────────────────
# 🏠 В меню битвы
# ─────────────────────────────────────────────────────────
@router.callback_query(StateFilter(BattleStates.post_battle), F.data == "battle:menu")
async def battle_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    # 💬 убираем inline чтобы не нажали 2 раза
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await start_battle_from_lex_menu(callback.message, state)


# ─────────────────────────────────────────────────────────
# ⬅️ Закрыть список тем
# ─────────────────────────────────────────────────────────
@router.callback_query(StateFilter(BattleStates.choosing_topic), F.data == "battle:close")
async def battle_close(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await state.clear()  # 💬 выходим из битвы полностью
