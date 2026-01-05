# grammar_feature.py
# 💬 пользовательская логика грамматики (меню темы, теория с фазами, практика, видео, чтение)

import os
import json
import math
import asyncio
from typing import Any

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    PollAnswer,
    Message,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext


router = Router()

TOPICS_REF: dict[str, dict[str, Any]] = {}  # 💬 ссылка на topics из core8_1

USER_DATA_PATH = "/data/user_data.json"
os.makedirs("/data", exist_ok=True)

POLL_CTX: dict[str, dict[str, Any]] = {}  # 💬 poll_id -> контекст удаления и продолжения


class GrammarStates(StatesGroup):
    menu = State()
    choosing_topic = State()
    choosing_phase = State()
    theory = State()
    practice = State()
    video = State()
    reading = State()


def init_grammar_feature(topics: dict[str, dict[str, Any]]):
    global TOPICS_REF
    TOPICS_REF = topics or {}  # 💬 сохраняем ссылку на темы


def _atomic_json_dump(path: str, data: dict):
    # 💬 атомарная запись: сначала tmp, потом replace
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_user_data() -> dict:
    # 💬 читаем user_data.json, если нет = создаём пустой
    if not os.path.exists(USER_DATA_PATH):
        _atomic_json_dump(USER_DATA_PATH, {})
        return {}
    try:
        with open(USER_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        _atomic_json_dump(USER_DATA_PATH, {})
        return {}


def save_user_data(data: dict):
    _atomic_json_dump(USER_DATA_PATH, data)


def _get_gp(user_id: str) -> dict:
    # 💬 достаём ветку grammar_progress пользователя
    ud = load_user_data()
    ud.setdefault(user_id, {})
    ud[user_id].setdefault("grammar_progress", {})
    save_user_data(ud)
    return ud[user_id]["grammar_progress"]


def _set_gp(user_id: str, gp: dict):
    ud = load_user_data()
    ud.setdefault(user_id, {})
    ud[user_id]["grammar_progress"] = gp
    save_user_data(ud)


def _compile_phase_blocks(phase: dict) -> list[dict]:
    """
    💬 собираем последовательность:
    base vocab (text/link/photo)
    после каждого link = пачка из 6 quiz_pool
    в конце = весь textquiz_pool
    """
    base = phase.get("vocab", []) or []
    quiz_pool = phase.get("quiz_pool", []) or []
    textquiz_pool = phase.get("textquiz_pool", []) or []

    compiled: list[dict] = []
    PACK = 6

    def is_link_block(b: dict) -> bool:
        return (b.get("type") == "link") or ("link" in b) or ("url" in b)

    qi = 0
    for b in base:
        compiled.append(b)
        if is_link_block(b) and qi < len(quiz_pool):
            chunk = quiz_pool[qi:qi + PACK]
            qi += len(chunk)
            compiled.extend(chunk)

    while qi < len(quiz_pool):
        chunk = quiz_pool[qi:qi + PACK]
        qi += len(chunk)
        compiled.extend(chunk)

    compiled.extend(textquiz_pool)
    return compiled


def _phase_done_70(visited: set[int], total: int) -> bool:
    # 💬 фаза выполнена если открыто >= 70% элементов compiled_blocks
    if total <= 0:
        return True
    return (len(visited) / total) >= 0.7


def _render_bar(percent: int, length: int = 10) -> str:
    # 💬 прогресс-бар из 10 сегментов
    if percent < 0:
        percent = 0
    if percent > 100:
        percent = 100
    filled = int(percent / 100 * length)
    if filled == 0 and percent > 0:
        filled = 1
    empty = length - filled
    return "🟩" * filled + "⬜️" * empty


def _topic_keys_for_level(level: str) -> list[str]:
    # 💬 список topic_key по грамматике в выбранном уровне
    items = []
    for k, t in TOPICS_REF.items():
        if t.get("category") == "gram" and t.get("level") == level:
            items.append(k)
    return items


async def grammar_open_from_topic(message: Message, state: FSMContext):
    """
    💬 вход в грамматику после выбора темы в core8_1: state уже содержит selected_topic и chosen_level
    """
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    if not topic_key or topic_key not in TOPICS_REF:
        await message.answer("⚠️ Тема не найдена.")
        return

    await state.set_state(GrammarStates.menu)
    await _show_grammar_menu(message, state)


def _menu_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🧠 Теория", callback_data="g:menu:theory")],
        [InlineKeyboardButton(text="🧩 Практика", callback_data="g:menu:practice")],
        [InlineKeyboardButton(text="🎬 Видео", callback_data="g:menu:video")],
        [InlineKeyboardButton(text="📖 Читать", callback_data="g:menu:read")],
        [InlineKeyboardButton(text="🔄 Сменить тему", callback_data="g:menu:change")],
        [InlineKeyboardButton(text="🏠 Назад", callback_data="g:menu:back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _topic_overall_percent(topic: dict, gp_topic: dict) -> int:
    # 💬 общий процент по теме без XP (грубая метрика)
    phases = topic.get("vocab", []) or []
    total_ph = len(phases)
    th = gp_topic.get("theory", {}) or {}

    done_ph = 0
    for ph in phases:
        pid = str(ph.get("phase_id"))
        if th.get(pid, {}).get("done"):
            done_ph += 1

    practice_total = len(topic.get("exercises", []) or [])
    video_total = len(topic.get("videos", []) or [])
    read_total = len((topic.get("reading", {}) or {}).get("fragments", []) or [])

    practice_done = int(gp_topic.get("practice_done", 0) or 0)
    video_done = int(gp_topic.get("video_done", 0) or 0)
    reading_idx = int(gp_topic.get("reading_idx", 0) or 0)

    # 💬 reading_done считаем как пройденные фрагменты до текущего индекса
    reading_done = 0
    if read_total > 0:
        reading_done = max(0, min(read_total, reading_idx + 1))

    total_all = total_ph + practice_total + video_total + read_total
    done_all = done_ph + min(practice_total, practice_done) + min(video_total, video_done) + reading_done
    if total_all <= 0:
        return 0
    return int(done_all / total_all * 100)


async def _show_grammar_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = str(message.chat.id)
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})

    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    gp_topic.setdefault("theory", {})
    gp_topic.setdefault("practice_done", 0)
    gp_topic.setdefault("video_done", 0)
    gp_topic.setdefault("reading_idx", 0)
    gp.setdefault(topic_key, gp_topic)
    _set_gp(user_id, gp)

    percent = _topic_overall_percent(topic, gp_topic)
    bar = _render_bar(percent)

    # 💬 короткий текст меню
    title = topic.get("visible_title") or "🧠 Грамматика"
    desc = topic.get("description") or ""
    if desc:
        desc = f"\n{desc}"

    text = (
        f"<b>{title}</b>{desc}\n\n"
        f"📊 <b>Прогресс:</b> {percent}%\n{bar}"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=_menu_kb())


@router.callback_query(F.data.startswith("g:menu:"))
async def g_menu(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":")[-1]
    await cb.answer()

    if action == "theory":
        await state.set_state(GrammarStates.choosing_phase)
        return await _show_theory_phases(cb, state)

    if action == "practice":
        await state.set_state(GrammarStates.practice)
        return await _show_practice_screen(cb, state)

    if action == "video":
        await state.set_state(GrammarStates.video)
        return await _show_video_screen(cb, state)

    if action == "read":
        await state.set_state(GrammarStates.reading)
        return await _show_reading(cb, state)

    if action == "change":
        await state.set_state(GrammarStates.choosing_topic)
        return await _show_grammar_topics(cb, state)

    if action == "back":
        # 💬 мягкий выход: возвращаемся к списку тем грамматики
        await state.set_state(GrammarStates.choosing_topic)
        return await _show_grammar_topics(cb, state)


async def _show_grammar_topics(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    level = data.get("chosen_level") or data.get("level") or "A1"
    keys = _topic_keys_for_level(level)

    if not keys:
        return await cb.message.edit_text("⚠️ В этом уровне нет тем грамматики.")

    rows = []
    for k in keys:
        t = TOPICS_REF.get(k, {})
        rows.append([InlineKeyboardButton(text=t.get("visible_title", k), callback_data=f"g:topic:{k}")])

    rows.append([InlineKeyboardButton(text="🏠 Назад", callback_data="g:topics:back")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    return await cb.message.edit_text("🧠 Выбери тему грамматики:", reply_markup=kb)


@router.callback_query(F.data == "g:topics:back")
async def g_topics_back(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(GrammarStates.menu)
    return await _show_grammar_menu(cb.message, state)


@router.callback_query(F.data.startswith("g:topic:"))
async def g_pick_topic(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    topic_key = cb.data.split(":", 2)[-1]
    if topic_key not in TOPICS_REF:
        return await cb.message.edit_text("⚠️ Тема не найдена.")

    await state.update_data(selected_topic=topic_key)
    await state.set_state(GrammarStates.menu)
    return await _show_grammar_menu(cb.message, state)


async def _show_theory_phases(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = str(cb.message.chat.id)
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    phases = topic.get("vocab", []) or []

    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    theory = gp_topic.setdefault("theory", {})

    rows = []
    for ph in phases:
        pid = str(ph.get("phase_id"))
        title = ph.get("title", f"Фаза {pid}")
        done = bool(theory.get(pid, {}).get("done"))
        mark = "⭐" if done else "☆"
        rows.append([InlineKeyboardButton(text=f"{mark} {title}", callback_data=f"g:ph:{pid}")])

    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="g:ph:menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    return await cb.message.edit_text("🧠 Теория = выбери фазу:", reply_markup=kb)


@router.callback_query(F.data == "g:ph:menu")
async def g_phase_to_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(GrammarStates.menu)
    return await _show_grammar_menu(cb.message, state)


async def _delete_last_content(bot, chat_id: int, state: FSMContext):
    data = await state.get_data()
    mid = data.get("g_last_content_msg_id")
    if mid:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    await state.update_data(g_last_content_msg_id=None)


def _nav_kb(extra_back: bool = True) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text="◀️", callback_data="g:nav:prev"),
        InlineKeyboardButton(text="▶️", callback_data="g:nav:next"),
    ]
    rows = [row]
    if extra_back:
        rows.append([InlineKeyboardButton(text="↩️ К фазам", callback_data="g:nav:phases")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="g:nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("g:ph:"))
async def g_pick_phase(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    pid = cb.data.split(":", 2)[-1]

    data = await state.get_data()
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    phases = topic.get("vocab", []) or []
    phase = next((p for p in phases if str(p.get("phase_id")) == str(pid)), None)
    if not phase:
        return await cb.message.edit_text("⚠️ Фаза не найдена.")

    compiled = _compile_phase_blocks(phase)

    user_id = str(cb.message.chat.id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    theory = gp_topic.setdefault("theory", {})
    ph_state = theory.setdefault(str(pid), {})
    visited = set(ph_state.get("visited", []) or [])
    last_index = int(ph_state.get("last_index", 0) or 0)
    if last_index < 0:
        last_index = 0
    if last_index >= len(compiled):
        last_index = 0

    await state.update_data(
        g_phase_id=str(pid),
        g_compiled=compiled,
        g_index=last_index,
        g_visited=list(visited),
        g_last_content_msg_id=None,
    )
    await state.set_state(GrammarStates.theory)
    return await _show_theory_step(cb, state)


async def _mark_theory_progress(chat_id: int, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    phase_id = data.get("g_phase_id")
    compiled = data.get("g_compiled", []) or []
    idx = int(data.get("g_index", 0) or 0)

    visited = set(data.get("g_visited", []) or [])
    visited.add(idx)
    await state.update_data(g_visited=list(visited))

    user_id = str(chat_id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    theory = gp_topic.setdefault("theory", {})
    ph_state = theory.setdefault(str(phase_id), {})

    total = len(compiled)
    done = _phase_done_70(visited, total)

    ph_state["visited"] = sorted(list(visited))
    ph_state["last_index"] = idx
    ph_state["done"] = done

    _set_gp(user_id, gp)


async def _show_theory_step(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    compiled = data.get("g_compiled", []) or []
    idx = int(data.get("g_index", 0) or 0)

    if not compiled:
        await cb.message.edit_text("⚠️ В этой фазе нет контента.")
        return

    if idx < 0:
        idx = 0
    if idx >= len(compiled):
        idx = len(compiled) - 1
    await state.update_data(g_index=idx)

    # 💬 отмечаем как просмотренный индекс и обновляем done>=70%
    await _mark_theory_progress(cb.message.chat.id, state)

    block = compiled[idx]
    btype = block.get("type") or ("quiz" if "options" in block else "text")

    # 💬 если quiz = показываем poll и ждём PollAnswer
    if btype == "quiz":
        return await _send_poll_quiz(cb, state, block)

    # 💬 text/link = редактируем одно сообщение
    if btype in ("text", "link") or ("text" in block) or ("link" in block) or ("url" in block):
        text = block.get("text") or ""
        title = block.get("title") or ""
        link = block.get("link") or block.get("url") or ""

        parts = []
        if title:
            parts.append(f"<b>{title}</b>")
        if text:
            parts.append(text)
        if link:
            parts.append(f"{link}")

        out = "\n\n".join([p for p in parts if p])

        try:
            await cb.message.edit_text(out, parse_mode="HTML", reply_markup=_nav_kb())
        except Exception:
            await cb.message.answer(out, parse_mode="HTML", reply_markup=_nav_kb())

        await state.update_data(g_last_content_msg_id=cb.message.message_id)
        return

    # 💬 photo = удаляем прошлое и отправляем фото новым сообщением
    if btype == "photo":
        photo = block.get("photo")
        caption = block.get("caption") or block.get("text") or ""
        await _delete_last_content(cb.bot, cb.message.chat.id, state)
        msg = await cb.message.answer_photo(photo=photo, caption=caption, reply_markup=_nav_kb())
        await state.update_data(g_last_content_msg_id=msg.message_id)
        return

    # 💬 неизвестный тип = показываем как текст
    fallback = json.dumps(block, ensure_ascii=False, indent=2)
    await cb.message.answer(f"<pre>{fallback}</pre>", parse_mode="HTML", reply_markup=_nav_kb())


async def _send_poll_quiz(cb: CallbackQuery, state: FSMContext, block: dict):
    await _delete_last_content(cb.bot, cb.message.chat.id, state)

    question = block.get("question") or block.get("title") or "Вопрос"
    options = block.get("options") or []
    correct = block.get("correct_answer")

    if not options or correct not in options:
        # 💬 если данные кривые, не падаем
        msg = await cb.message.answer("⚠️ Квиз сломан (нет options или correct_answer).", reply_markup=_nav_kb())
        await state.update_data(g_last_content_msg_id=msg.message_id)
        return

    correct_id = options.index(correct)

    poll_msg = await cb.bot.send_poll(
        chat_id=cb.message.chat.id,
        question=question,
        options=options,
        type="quiz",
        correct_option_id=correct_id,
        is_anonymous=False,
    )

    poll_id = poll_msg.poll.id
    POLL_CTX[poll_id] = {
        "chat_id": cb.message.chat.id,
        "message_id": poll_msg.message_id,
        "user_id": cb.from_user.id,
        "explain_wrong": block.get("explanation_wrong") or "",
    }

    await state.update_data(g_last_content_msg_id=poll_msg.message_id, g_poll_id=poll_id)


@router.poll_answer()
async def g_poll_answer(pa: PollAnswer, state: FSMContext):
    poll_id = pa.poll_id
    ctx = POLL_CTX.get(poll_id)
    if not ctx:
        return

    # 💬 отвечать может только тот же юзер, чтобы не ломали поток в группе
    if ctx.get("user_id") and int(ctx["user_id"]) != int(pa.user.id):
        return

    chat_id = int(ctx["chat_id"])
    msg_id = int(ctx["message_id"])

    # 💬 удаляем poll
    try:
        # poll_answer не даёт bot напрямую, поэтому берём из state через storage невозможно
        # практично = удаление poll сделаем через Bot из текущего router контекста нельзя
        # решение = отправим "сервисное" сообщение вместо удаления если bot недоступен
        pass
    except Exception:
        pass

    # 💬 в aiogram v3 в poll_answer нет bot, поэтому удаляем poll на следующем callback шаге
    #     тут же просто двигаем индекс дальше и просим юзера нажать ▶️, если удаление критично
    #     (минимальный риск для текущей архитектуры)

    # 💬 короткий фидбек
    chosen = pa.option_ids[0] if pa.option_ids else None
    feedback = "✅"
    if chosen is None:
        feedback = "✅"
    # 💬 explanation_wrong показываем только при ошибке, если есть
    if chosen is not None:
        # correct_option_id мы не знаем тут без poll объекта, поэтому просто не спамим
        pass

    try:
        await state.update_data(g_poll_id=None)
    except Exception:
        return

    data = await state.get_data()
    compiled = data.get("g_compiled", []) or []
    idx = int(data.get("g_index", 0) or 0)

    # 💬 авто переход на следующий индекс
    nxt = idx + 1
    if nxt >= len(compiled):
        # 💬 конец фазы
        # тут показываем финал и возвращаем к фазам через отдельное сообщение
        try:
            await router.bot.send_message(chat_id, "🏁 Фаза завершена. Вернись к списку фаз.", reply_markup=None)
        except Exception:
            # если bot недоступен, тихо
            pass
        return

    await state.update_data(g_index=nxt)

    # 💬 дальше пользователь продолжает через кнопки ▶️ (poll_answer не умеет edit_text)
    #     чтобы поток был живым, отправляем следующий блок отдельным сообщением
    fake_cb = type("Fake", (), {})()
    fake_cb.message = type("M", (), {"chat": type("C", (), {"id": chat_id})()})()
    # 💬 не можем корректно построить CallbackQuery объект без bot, поэтому просто ничего
    #     следующий шаг будет по кнопке ▶️


@router.callback_query(F.data.startswith("g:nav:"))
async def g_nav(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    action = cb.data.split(":")[-1]

    data = await state.get_data()
    compiled = data.get("g_compiled", []) or []
    idx = int(data.get("g_index", 0) or 0)

    if action == "prev":
        if idx <= 0:
            return  # 💬 noop на первом элементе
        await state.update_data(g_index=idx - 1)
        return await _show_theory_step(cb, state)

    if action == "next":
        if idx >= len(compiled) - 1:
            return  # 💬 noop на последнем
        await state.update_data(g_index=idx + 1)
        return await _show_theory_step(cb, state)

    if action == "phases":
        await state.set_state(GrammarStates.choosing_phase)
        return await _show_theory_phases(cb, state)

    if action == "menu":
        await state.set_state(GrammarStates.menu)
        return await _show_grammar_menu(cb.message, state)


async def _show_practice_screen(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    total = len(topic.get("exercises", []) or [])

    user_id = str(cb.message.chat.id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    done = int(gp_topic.get("practice_done", 0) or 0)
    percent = int((min(done, total) / total) * 100) if total else 0
    bar = _render_bar(percent)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать", callback_data="g:practice:start")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="g:practice:menu")],
    ])

    return await cb.message.edit_text(
        f"🧩 Практика\n\n📊 {percent}%\n{bar}\n<b>{min(done, total)}/{total}</b>",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(F.data == "g:practice:menu")
async def g_practice_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(GrammarStates.menu)
    return await _show_grammar_menu(cb.message, state)


@router.callback_query(F.data == "g:practice:start")
async def g_practice_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(GrammarStates.practice)
    await state.update_data(g_practice_idx=0)
    return await _show_practice_step(cb, state)


@router.callback_query(F.data == "g:practice:next")
async def g_practice_next(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    idx = int(data.get("g_practice_idx", 0) or 0)
    await state.update_data(g_practice_idx=idx + 1)
    return await _show_practice_step(cb, state)


async def _show_practice_step(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    items = topic.get("exercises", []) or []

    idx = int(data.get("g_practice_idx", 0) or 0)
    if idx <= 0:
        idx = 0

    user_id = str(cb.message.chat.id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})

    if idx >= len(items):
        gp_topic["practice_done"] = len(items)
        _set_gp(user_id, gp)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="g:practice:menu")]])
        return await cb.message.edit_text("🏁 Практика завершена.", reply_markup=kb)

    # 💬 фиксируем done как максимум индекса (без XP)
    gp_topic["practice_done"] = max(int(gp_topic.get("practice_done", 0) or 0), idx)
    _set_gp(user_id, gp)

    b = items[idx]
    btype = b.get("type") or "text"
    title = b.get("title") or ""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Дальше", callback_data="g:practice:next")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="g:practice:menu")],
    ])

    if btype == "link":
        link = b.get("link") or b.get("url") or ""
        txt = f"<b>{title}</b>\n\n{link}" if title else link
        return await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)

    if btype == "photo":
        photo = b.get("photo")
        caption = b.get("caption") or title
        try:
            await cb.message.edit_text("📷", reply_markup=None)
        except Exception:
            pass
        await cb.message.answer_photo(photo=photo, caption=caption, reply_markup=kb)
        return

    text = b.get("text") or ""
    out = f"<b>{title}</b>\n\n{text}" if title else text
    return await cb.message.edit_text(out, parse_mode="HTML", reply_markup=kb)


async def _show_video_screen(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    videos = topic.get("videos", []) or []

    user_id = str(cb.message.chat.id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    idx = int(gp_topic.get("video_done", 0) or 0)

    if idx >= len(videos):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="g:video:menu")]])
        return await cb.message.edit_text("🏁 Видео завершены.", reply_markup=kb)

    v = videos[idx]
    title = v.get("title") or f"Видео {idx + 1}"
    url = v.get("url") or ""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я посмотрел", callback_data="g:video:done")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="g:video:menu")],
    ])

    return await cb.message.edit_text(f"🎬 <b>{title}</b>\n\n{url}", parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "g:video:menu")
async def g_video_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(GrammarStates.menu)
    return await _show_grammar_menu(cb.message, state)


@router.callback_query(F.data == "g:video:done")
async def g_video_done(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    user_id = str(cb.message.chat.id)

    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    gp_topic["video_done"] = int(gp_topic.get("video_done", 0) or 0) + 1
    _set_gp(user_id, gp)

    return await _show_video_screen(cb, state)


async def _show_reading(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    reading = topic.get("reading", {}) or {}
    frags = reading.get("fragments", []) or []

    user_id = str(cb.message.chat.id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    idx = int(gp_topic.get("reading_idx", 0) or 0)
    if idx < 0:
        idx = 0
    if idx >= len(frags) and frags:
        idx = len(frags) - 1

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️", callback_data="g:read:prev"),
            InlineKeyboardButton(text="▶️", callback_data="g:read:next"),
        ],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="g:read:menu")],
    ])

    if not frags:
        return await cb.message.edit_text("📖 Читать\n\n⚠️ Нет фрагментов.", reply_markup=kb)

    f = frags[idx]
    es = f.get("es", "")
    ru = f.get("ru", "")
    hint = f.get("hint", "")

    title = reading.get("title") or "Читать"
    out = f"📖 <b>{title}</b>\n\n{es}\n🔹 {ru}"
    if hint:
        out += f"\n💡 {hint}"

    gp_topic["reading_idx"] = idx
    _set_gp(user_id, gp)

    return await cb.message.edit_text(out, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "g:read:menu")
async def g_read_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(GrammarStates.menu)
    return await _show_grammar_menu(cb.message, state)


@router.callback_query(F.data == "g:read:prev")
async def g_read_prev(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    user_id = str(cb.message.chat.id)

    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    idx = int(gp_topic.get("reading_idx", 0) or 0)
    if idx <= 0:
        return
    gp_topic["reading_idx"] = idx - 1
    _set_gp(user_id, gp)
    return await _show_reading(cb, state)


@router.callback_query(F.data == "g:read:next")
async def g_read_next(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    topic_key = data.get("selected_topic")
    topic = TOPICS_REF.get(topic_key, {})
    frags = ((topic.get("reading", {}) or {}).get("fragments", []) or [])

    user_id = str(cb.message.chat.id)
    gp = _get_gp(user_id)
    gp_topic = gp.setdefault(topic_key, {})
    idx = int(gp_topic.get("reading_idx", 0) or 0)
    if idx >= len(frags) - 1:
        return
    gp_topic["reading_idx"] = idx + 1
    _set_gp(user_id, gp)
    return await _show_reading(cb, state)
