# grammar_feature.py
# 💬 модуль "Грамматика" (Теория по фазам -> навигация -> PollQuiz/Фото/Текст) + Практика + Видео + Читать

from __future__ import annotations

import asyncio  # 💬 таймер для авто удаления
import html
from typing import Any, Callable, Dict, List, Optional, Tuple

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    PollAnswer,
)
from aiogram.exceptions import TelegramBadRequest  # 💬 чтобы не падать, если нельзя удалить/изменить

router = Router()

# -----------------------------
# 🔧 DI (проброс из core8_1 (76).py)
# -----------------------------
_load_user_data: Optional[Callable[[], Dict[str, Any]]] = None
_save_user_data: Optional[Callable[[Dict[str, Any]], None]] = None
_show_topics_for_category_level: Optional[Callable[..., Any]] = None
_start_handler: Optional[Callable[..., Any]] = None
_ADMIN_CHAT_ID: Optional[int] = None
_bot = None

_topics: Dict[str, Any] = {}  # 💬 topics ref из core


def init_grammar_feature(*args, **kwargs) -> None:
    """
    💬 пробрасываем зависимости из core8_1
    💬 совместимость = если старый core вызывает init_grammar_feature(topics)
    """
    global _load_user_data, _save_user_data, _show_topics_for_category_level, _start_handler, _ADMIN_CHAT_ID, _bot

    # 💬 Backward compatibility: старый вызов init_grammar_feature(topics)
    if args and len(args) == 1 and isinstance(args[0], dict) and not kwargs:
        set_topics_ref(args[0])  # 💬 принимаем topics и сохраняем как ref
        return

    load_user_data = kwargs.get("load_user_data")
    save_user_data = kwargs.get("save_user_data")
    show_topics_for_category_level = kwargs.get("show_topics_for_category_level")
    start_handler = kwargs.get("start_handler")
    admin_chat_id = kwargs.get("admin_chat_id")
    bot = kwargs.get("bot")

    _load_user_data = load_user_data
    _save_user_data = save_user_data
    _show_topics_for_category_level = show_topics_for_category_level
    _start_handler = start_handler
    try:
        _ADMIN_CHAT_ID = int(admin_chat_id) if admin_chat_id is not None else None  # 💬 приводим к int
    except Exception:
        _ADMIN_CHAT_ID = None
    _bot = bot


def set_topics_ref(topics: Dict[str, Any]) -> None:
    global _topics
    _topics = topics or {}


# -----------------------------
# 🧠 FSM "Грамматика"
# -----------------------------
class GrammarStates(StatesGroup):
    menu = State()                # 💬 главное меню грамматики внутри темы
    theory_phases = State()        # 💬 список фаз теории
    theory_view = State()          # 💬 показ элементов внутри фазы (текст/фото)
    theory_poll = State()          # 💬 ждём ответ на PollQuiz внутри теории

    practice_intro = State()       # 💬 экран "Начать" практику
    practice_view = State()        # 💬 показ практики (текст/фото)
    practice_poll = State()        # 💬 ждём PollQuiz в практике

    video_intro = State()          # 💬 старт видео
    video_view = State()           # 💬 показ видео

    read_intro = State()           # 💬 старт читать
    read_view = State()            # 💬 показ фрагмента читать


# -----------------------------
# 🧱 helpers
# -----------------------------
async def _safe_delete_message(bot, chat_id: int, message_id: int) -> None:
    # 💬 безопасно удаляем сообщение
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        return

def _normalize_quiz_options(opts: List[str], correct: int) -> Tuple[List[str], int]:
    # 💬 приводим к 3 вариантам, убираем дубли и фиксируем correct в 0
    clean: List[str] = []
    for x in opts or []:
        s = str(x).strip()
        if not s:
            continue
        clean.append(s)

    if not clean:
        return (["...","..."], 0)  # 💬 Telegram требует минимум 2 варианта

    if correct < 0 or correct >= len(clean):
        correct = 0

    correct_text = clean[correct]

    # 💬 если у тебя 4й вариант дублирует правильный, выкидываем его
    if len(clean) >= 4 and clean[-1] == correct_text:
        clean = clean[:-1]

    # 💬 собираем 3 варианта: правильный + 2 уникальных неправильных
    rest: List[str] = []
    for o in clean:
        if o == correct_text:
            continue
        if o not in rest:
            rest.append(o)

    final_opts = [correct_text] + rest[:2]
    if len(final_opts) < 2:
        final_opts = [correct_text, "..."]  # 💬 минимально безопасно

    return (final_opts, 0)


async def _tg_retry(factory: Callable[[], Any], tries: int = 3, base_delay: float = 0.8) -> Any:
    # 💬 не даём боту падать на таймаутах Telegram, повторяем запрос
    for attempt in range(tries):
        try:
            return await factory()
        except Exception as e:
            name = e.__class__.__name__
            is_timeout = isinstance(e, (asyncio.TimeoutError, TimeoutError))
            is_network = name in {"TelegramNetworkError", "TelegramRetryAfter", "RetryAfter"}
            if not (is_timeout or is_network):
                return None  # 💬 не роняем хендлер на неожиданных сетевых ошибках

            if attempt == tries - 1:
                return None

            await asyncio.sleep(base_delay * (attempt + 1))


def _bar(pct: float, width: int = 10) -> str:
    # 💬 прогресс бар текстом
    if pct < 0:
        pct = 0
    if pct > 1:
        pct = 1
    filled = int(round(pct * width))
    return "█" * filled + "░" * (width - filled)


def _get_topic(topic_key: str) -> Dict[str, Any]:
    # 💬 достаём тему из общего topics
    return _topics.get(topic_key, {}) if _topics else {}


def _get_grammar_root(topic: Dict[str, Any]) -> Dict[str, Any]:
    # 💬 поддерживаем несколько вариантов ключа
    return topic.get("grammar") or topic.get("gram") or {}


def _get_theory_phases(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 💬 CreateLessonBlock: фазы лежат в topic["vocab"]
    phases = topic.get("vocab") or []
    return phases if isinstance(phases, list) else []

def _phase_title(phase: Dict[str, Any], idx: int) -> str:
    # 💬 название фазы, поддержка разных ключей (админка и ручные JSON)
    return str(phase.get("title") or phase.get("name") or phase.get("phase_name") or f"Фаза {idx + 1}")

def _phase_items(phase: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    💬 копируем логику core get_vocab_list:
       после каждого link добавляем 6 quiz из quiz_pool,
       затем докладываем остаток quiz_pool,
       затем добавляем textquiz_pool в конец
    """
    base = phase.get("vocab") or []
    quiz_pool = list(phase.get("quiz_pool") or [])
    textquiz_pool = list(phase.get("textquiz_pool") or [])

    PACK = 6
    compiled: List[Dict[str, Any]] = []

    def take_pack(pool, start, pack=PACK):
        return pool[start:start + pack], start + min(pack, max(0, len(pool) - start))

    qi = 0
    for block in base:
        compiled.append(block)
        if ("link" in block) or ("url" in block) or (block.get("type") == "link"):
            if qi < len(quiz_pool):
                chunk, qi = take_pack(quiz_pool, qi)
                compiled.extend(chunk)

    while qi < len(quiz_pool):
        chunk, qi = take_pack(quiz_pool, qi)
        compiled.extend(chunk)

    compiled.extend(textquiz_pool)
    return compiled


def _practice_items(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 💬 CreateLessonBlock: практика лежит в topic["exercises"]
    items = topic.get("exercises") or []
    return items if isinstance(items, list) else []


def _video_items(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = topic.get("videos") or []
    return items if isinstance(items, list) else []


def _read_packs(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 💬 CreateLessonBlock: чтение лежит в topic["reading"] как список пакетов
    packs = topic.get("reading") or []
    return packs if isinstance(packs, list) else []


def _read_fragments_from_pack(topic: Dict[str, Any], pack_idx: int) -> List[Dict[str, Any]]:
    packs = _read_packs(topic)
    if pack_idx < 0 or pack_idx >= len(packs):
        return []
    frags = packs[pack_idx].get("fragments") or []
    return frags if isinstance(frags, list) else []

def _read_fragments(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 💬 совместимость: собираем все fragments из всех пакетов чтения в один список
    packs = _read_packs(topic)
    out: List[Dict[str, Any]] = []
    for p in packs:
        fr = p.get("fragments") or []
        if isinstance(fr, list):
            out.extend(fr)
    return out


def _item_type(item: Dict[str, Any]) -> str:
    # 💬 нормализуем тип элемента
    t = (item.get("type") or "").strip().lower()
    if t:
        return t
    if "question" in item and ("options" in item or "answers" in item):
        return "poll"
    if "photo" in item or "file_id" in item or "image" in item:
        return "photo"
    return "text"


def _user_progress_get(uid: str) -> Dict[str, Any]:
    # 💬 прогресс держим в user_data (RailwayData)
    if not _load_user_data:
        return {}
    data = _load_user_data() or {}
    u = data.setdefault(uid, {})
    u.setdefault("grammar_progress", {})
    return data


def _user_progress_save(data: Dict[str, Any]) -> None:
    if _save_user_data:
        _save_user_data(data)


def _ensure_di() -> bool:
    return bool(_load_user_data and _save_user_data and _show_topics_for_category_level and _start_handler and _bot)


def _kb_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Теория", callback_data="gram:theory"),
                InlineKeyboardButton(text="🧪 Практика", callback_data="gram:practice"),
            ],
            [
                InlineKeyboardButton(text="🎬 Видео", callback_data="gram:video"),
                InlineKeyboardButton(text="📚 Читать", callback_data="gram:read"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Темы", callback_data="gram:topics"),
                InlineKeyboardButton(text="🏠 В меню", callback_data="gram:menu"),  # 💬 возвращаемся в меню грамматики темы
            ],

        ]
    )


def _kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="gram:menu")]
        ]
    )


def _kb_phases(phases: List[Dict[str, Any]], done_flags: List[bool]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i, ph in enumerate(phases):
        label = _phase_title(ph, i)
        if i < len(done_flags) and done_flags[i]:
            label = f"⭐ {label}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"gram:phase:{i}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="gram:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_nav_in_phase() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data="gram:nav:prev"),
                InlineKeyboardButton(text="➡️", callback_data="gram:nav:next"),
            ],
            [
                InlineKeyboardButton(text="↩️ К фазам", callback_data="gram:theory"),
                InlineKeyboardButton(text="🏠 В меню", callback_data="gram:menu"),
            ],
        ]
    )


def _kb_practice_intro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать", callback_data="gram:practice:start")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="gram:menu")],
        ]
    )


def _kb_video_controls() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Посмотрел", callback_data="gram:video:done"),
                InlineKeyboardButton(text="⏭️ Дальше", callback_data="gram:video:next"),
            ],
            [
                InlineKeyboardButton(text="⬅️ В меню", callback_data="gram:menu")
            ],
        ]
    )


def _kb_read_controls() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data="gram:read:prev"),
                InlineKeyboardButton(text="⭐", callback_data="gram:read:star"),
                InlineKeyboardButton(text="➡️", callback_data="gram:read:next"),
            ],
            [
                InlineKeyboardButton(text="⬅️ В меню", callback_data="gram:menu")
            ],
        ]
    )


async def _replace_content(
    chat_id: int,
    state: FSMContext,
    send_factory=None,
    *,
    send_coro=None,
) -> Optional[Message]:
    # 💬 backward compatibility: поддерживаем старые вызовы send_coro=...
    st = await state.get_data()
    old_id = st.get("gram_content_msg_id")

    if send_factory is None and send_coro is not None:
        send_factory = send_coro  # 💬 принимаем старый параметр, чтобы не падало

    async def _call():
        if callable(send_factory):
            return await send_factory()
        return await send_factory

    msg = await _tg_retry(_call)  # 💬 ретраи при таймауте
    if not msg:
        return None

    if old_id:
        await _safe_delete_message(_bot, chat_id, int(old_id))  # 💬 удаляем старый экран только после успеха

    await state.update_data(gram_content_msg_id=msg.message_id)
    return msg




def _progress_flags(uid: str, topic_key: str, phases_count: int) -> Tuple[List[bool], float]:
    # 💬 done_flags по фазам + pct по теории
    data = _user_progress_get(uid)
    u = (data.get(uid) or {})
    gp = (u.get("grammar_progress") or {})
    tp = (gp.get(topic_key) or {})
    theory = (tp.get("theory") or {})
    done_flags: List[bool] = []
    for i in range(phases_count):
        ph = theory.get(str(i)) or {}
        done_flags.append(bool(ph.get("done")))
    pct = (sum(1 for x in done_flags if x) / phases_count) if phases_count else 0.0
    return done_flags, pct


async def open_grammar_topic(message: Message, state: FSMContext) -> None:
    """
    💬 вход в грамматику после выбора темы
    """
    if not _ensure_di():
        await message.answer("⚠️ Грамматика пока не подключена. Проверь init_grammar_feature.")
        return

    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        await message.answer("⚠️ Не вижу выбранную тему.")
        return

    topic = _get_topic(str(topic_key))
    title = html.escape(str(topic.get("visible_title") or topic.get("title") or "Грамматика"))

    uid = str(message.from_user.id)
    phases = _get_theory_phases(topic)
    done_flags, theory_pct = _progress_flags(uid, str(topic_key), len(phases))

    practice = _practice_items(topic)
    videos = _video_items(topic)
    reads = _read_fragments(topic)

    # 💬 практика pct
    data = _user_progress_get(uid)
    u = data.setdefault(uid, {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(str(topic_key), {})
    pr = tp.setdefault("practice", {})
    pr_done = int(pr.get("done", 0))
    pr_total = len(practice) if practice else 0
    pr_pct = (pr_done / pr_total) if pr_total else 0.0

    # 💬 видео pct
    vd = tp.setdefault("video", {})
    vd_done = int(vd.get("done", 0))
    vd_total = len(videos) if videos else 0
    vd_pct = (vd_done / vd_total) if vd_total else 0.0

    # 💬 читать pct
    rd = tp.setdefault("read", {})
    rd_done = int(rd.get("done", 0))
    rd_total = len(reads) if reads else 0
    rd_pct = (rd_done / rd_total) if rd_total else 0.0

    _user_progress_save(data)

    text = (
        f"<b>{title}</b>\n\n"
        f"📖 Теория:  {_bar(theory_pct)}  {int(theory_pct * 100)}%\n"
        f"🧪 Практика: {_bar(pr_pct)}  {int(pr_pct * 100)}%\n"
        f"🎬 Видео:    {_bar(vd_pct)}  {int(vd_pct * 100)}%\n"
        f"📚 Читать:   {_bar(rd_pct)}  {int(rd_pct * 100)}%\n"
    )

    await state.set_state(GrammarStates.menu)
    await state.update_data(gram_ctx=True, gram_topic_key=str(topic_key))  # 💬 не сбрасываем id, чтобы удалять прошлый экран

    await _replace_content(
        chat_id=message.chat.id,
        state=state,
        send_coro=message.answer(text, reply_markup=_kb_menu(), parse_mode="HTML"),
    )  # 💬 показываем меню грамматики одним сообщением



# -----------------------------
# 🟢 MENU callbacks
# -----------------------------
@router.callback_query(F.data == "gram:menu")
async def gram_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await open_grammar_topic(cb.message, state)


@router.callback_query(F.data == "gram:home")
async def gram_home(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    # 💬 возвращаем в /start (главное меню)
    try:
        await state.clear()
    except Exception:
        pass
    if _start_handler:
        await _start_handler(cb.message, state)  # 💬 используем start_handler из core
    else:
        await cb.message.answer("Нажми /start")


@router.callback_query(F.data == "gram:topics")
async def gram_topics(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    old_id = st.get("gram_content_msg_id")
    if old_id:
        await _safe_delete_message(_bot, cb.from_user.id, int(old_id))  # 💬 убираем экран грамматики перед списком тем
    await state.update_data(gram_content_msg_id=None)  # 💬 сбрасываем текущий экран грамматики

    # 💬 возвращаемся к списку тем грамматики выбранного уровня
    st = await state.get_data()
    lvl = st.get("selected_level")
    if not lvl:
        await cb.message.answer("⚠️ Не вижу уровень. Нажми /start и выбери заново.")
        return
    if _show_topics_for_category_level:
        await _show_topics_for_category_level(cb, state, category="gram", level=lvl)  # 💬 обратно к темам
    else:
        await cb.message.answer("⚠️ Нет show_topics_for_category_level.")


# -----------------------------
# 📖 THEORY
# -----------------------------
@router.callback_query(F.data == "gram:theory")
async def gram_theory(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    old_id = st.get("gram_content_msg_id")
    if old_id:
        await _safe_delete_message(_bot, cb.from_user.id, int(old_id))  # 💬 убираем экран грамматики перед выходом
    await state.update_data(gram_content_msg_id=None)  # 💬 сбрасываем, чтобы главное меню не плодилось

    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        await cb.message.answer("⚠️ Не вижу тему.")
        return
    topic = _get_topic(str(topic_key))
    phases = _get_theory_phases(topic)
    if not phases:
        await _replace_content(
            chat_id=cb.from_user.id,
            state=state,
            send_coro=cb.message.answer("Пока нет фаз в Теории.", reply_markup=_kb_back_to_menu()),
        )  # 💬 не плодим сообщения
        return

    uid = str(cb.from_user.id)
    done_flags, _ = _progress_flags(uid, str(topic_key), len(phases))

    await state.set_state(GrammarStates.theory_phases)
    await _replace_content(
        chat_id=cb.from_user.id,
        state=state,
        send_coro=cb.message.answer("Выбери фазу:", reply_markup=_kb_phases(phases, done_flags)),
    )  # 💬 список фаз в одном сообщении

@router.callback_query(F.data.startswith("gram:phase:"))
async def gram_phase_open(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        await cb.message.answer("⚠️ Не вижу тему.")
        return

    try:
        phase_idx = int(cb.data.split(":", 2)[2])
    except Exception:
        await cb.message.answer("⚠️ Не понял фазу.")
        return

    topic = _get_topic(str(topic_key))
    phases = _get_theory_phases(topic)
    if phase_idx < 0 or phase_idx >= len(phases):
        await cb.message.answer("⚠️ Фаза не найдена.")
        return

    phase = phases[phase_idx]
    items = _phase_items(phase)
    if not items:
        await cb.message.answer("Пока нет блоков в этой фазе.", reply_markup=_kb_back_to_menu())
        return

    await state.set_state(GrammarStates.theory_view)
    await state.update_data(
        gram_section="theory",
        gram_phase_idx=phase_idx,
        gram_item_idx=0,
        gram_poll_id=None,
        gram_poll_msg_id=None,
    )
    await _show_current_item(chat_id=cb.from_user.id, state=state, topic=topic)


@router.callback_query(F.data.in_(["gram:nav:prev", "gram:nav:next"]))
async def gram_nav(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    if st.get("gram_section") != "theory":
        return

    idx = int(st.get("gram_item_idx") or 0)
    if cb.data.endswith("prev"):
        idx -= 1
    else:
        idx += 1

    await state.update_data(gram_item_idx=idx)
    topic = _get_topic(str(st.get("selected_topic")))
    await _show_current_item(chat_id=cb.from_user.id, state=state, topic=topic)


async def _mark_seen(uid: str, topic_key: str, section: str, phase_idx: Optional[int], item_idx: int, total: int) -> None:
    # 💬 отмечаем просмотр индекса и считаем порог 70%
    data = _user_progress_get(uid)
    u = data.setdefault(uid, {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(topic_key, {})

    if section == "theory" and phase_idx is not None:
        th = tp.setdefault("theory", {})
        ph = th.setdefault(str(phase_idx), {})
        seen = ph.setdefault("seen", [])
        if item_idx not in seen:
            seen.append(item_idx)
        pct = (len(seen) / total) if total else 0.0
        ph["pct"] = pct
        if pct >= 0.7:
            ph["done"] = True  # 💬 фаза засчитана на 70%
    elif section == "practice":
        pr = tp.setdefault("practice", {})
        seen = pr.setdefault("seen", [])
        if item_idx not in seen:
            seen.append(item_idx)
        pct = (len(seen) / total) if total else 0.0
        pr["pct"] = pct
        if pct >= 0.7:
            pr["done_flag"] = True
        pr["done"] = len(seen)
    elif section == "video":
        vd = tp.setdefault("video", {})
        vd["done"] = item_idx
    elif section == "read":
        rd = tp.setdefault("read", {})
        rd["done"] = item_idx

    _user_progress_save(data)


async def _show_current_item(chat_id: int, state: FSMContext, topic: Dict[str, Any]) -> None:
    # 💬 показываем текущий элемент (текст/фото) или шлём poll
    st = await state.get_data()
    section = st.get("gram_section")
    topic_key = str(st.get("selected_topic") or "")

    if section == "theory":
        phase_idx = int(st.get("gram_phase_idx") or 0)
        phases = _get_theory_phases(topic)
        if phase_idx < 0 or phase_idx >= len(phases):
            await _replace_content(
                chat_id,
                state,
                _bot.send_message(chat_id, "⚠️ Фаза не найдена.", reply_markup=_kb_back_to_menu()),
            )  # 💬 показываем ошибку одним сообщением
            return

        phase = phases[phase_idx]
        items = _phase_items(phase)
        total = len(items)

        idx = int(st.get("gram_item_idx") or 0)
        if idx < 0:
            idx = 0
        if idx >= total:
            # 💬 конец фазы
            await _replace_content(
                chat_id,
                state,
                _bot.send_message(chat_id, "✅ Фаза закончилась.", reply_markup=_kb_back_to_menu()),
            )  # 💬 конец фазы без накопления сообщений
            return


        item = items[idx]
        t = _item_type(item)

        await _mark_seen(str(chat_id), topic_key, "theory", phase_idx, idx, total)  # 💬 фиксируем просмотр

        title = html.escape(_phase_title(phase, phase_idx))
        pct = 0.0
        data = _user_progress_get(str(chat_id))
        u = data.get(str(chat_id), {})
        ph = (u.get("grammar_progress", {}).get(topic_key, {}).get("theory", {}).get(str(phase_idx), {}) or {})
        try:
            pct = float(ph.get("pct") or 0.0)
        except Exception:
            pct = 0.0

        header = f"📖 <b>{title}</b>\n{_bar(pct)}  {int(pct * 100)}%\n\n"

        if t == "poll":
            q = str(item.get("question") or "Выбери ответ")
            opts = item.get("options") or item.get("answers") or []
            opts = [str(x) for x in opts][:12]

            correct = 0  # 💬 по умолчанию первый
            if "correct_option_id" in item:
                try:
                    correct = int(item.get("correct_option_id"))
                except Exception:
                    correct = 0
            elif isinstance(item.get("correct"), int):
                correct = int(item.get("correct"))
            elif item.get("correct_answer") in opts:
                correct = opts.index(item.get("correct_answer"))  # 💬 correct_answer = текст правильного варианта

            opts, correct = _normalize_quiz_options(opts, correct)  # 💬 строго 3 варианта, правильный всегда 0

            poll_msg = await _replace_content(
                chat_id,
                state,
                lambda: _bot.send_poll(
                    chat_id=chat_id,
                    question=q,
                    options=opts,
                    type="quiz",
                    correct_option_id=correct,
                    is_anonymous=False,
                ),
            )  # 💬 Poll тоже не копится в чате и не роняет хендлер

            if not poll_msg:
                return

            await state.set_state(GrammarStates.theory_poll)  # 💬 ждём PollAnswer для теории
            await state.update_data(
                gram_poll_id=poll_msg.poll.id,
                gram_poll_msg_id=poll_msg.message_id,
                gram_poll_correct=correct,
                gram_poll_options=opts,
                gram_poll_section="theory",  # 💬 отмечаем, что это теория
            )
            return



        if t == "photo":
            photo = item.get("photo") or item.get("file_id") or item.get("image") or item.get("url")
            cap = header + html.escape(str(item.get("caption") or ""))
            await _replace_content(
                chat_id,
                state,
                _bot.send_photo(chat_id=chat_id, photo=photo, caption=cap, reply_markup=_kb_nav_in_phase(), parse_mode="HTML"),
            )
            return

        # text
        text = header + str(item.get("text") or "")
        await _replace_content(
            chat_id,
            state,
            _bot.send_message(chat_id=chat_id, text=text, reply_markup=_kb_nav_in_phase(), parse_mode="HTML", disable_web_page_preview=True),
        )
        return

    # 💬 safety
    await _replace_content(
        chat_id,
        state,
        _bot.send_message(chat_id, "⚠️ Не понимаю, что показывать ("),
    )  # 💬 без спама сообщениями



@router.poll_answer(GrammarStates.theory_poll)
async def gram_poll_answer_theory(ans: PollAnswer, state: FSMContext) -> None:
    # 💬 обработка PollQuiz в теории
    st = await state.get_data()
    poll_id = st.get("gram_poll_id")
    if not poll_id or poll_id != ans.poll_id:
        return

    chat_id = ans.user.id
    correct = int(st.get("gram_poll_correct") or 0)
    opts = st.get("gram_poll_options") or []
    chosen = ans.option_ids[0] if ans.option_ids else -1

    # 💬 реакция + правильный ответ
    if chosen == correct:
        txt = "✅ Правильно"
    else:
        right = opts[correct] if 0 <= correct < len(opts) else "не найден"
        txt = f"❌ Неправильно\n✅ Правильно: {html.escape(str(right))}"

    msg = await _bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")

    await asyncio.sleep(1.5)
    await _safe_delete_message(_bot, chat_id, msg.message_id)

    # 💬 удаляем Poll сообщение
    poll_msg_id = st.get("gram_poll_msg_id")
    if poll_msg_id:
        await _safe_delete_message(_bot, chat_id, int(poll_msg_id))

    # 💬 идём дальше по индексу
    idx = int(st.get("gram_item_idx") or 0) + 1
    await state.update_data(
        gram_item_idx=idx,
        gram_poll_id=None,
        gram_poll_msg_id=None,
        gram_poll_correct=None,
        gram_poll_options=None,
    )
    await state.set_state(GrammarStates.theory_view)

    topic = _get_topic(str(st.get("selected_topic")))
    await _show_current_item(chat_id=chat_id, state=state, topic=topic)


# -----------------------------
# 🧪 PRACTICE
# -----------------------------
@router.callback_query(F.data == "gram:practice")
async def gram_practice_intro(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        await cb.message.answer("⚠️ Не вижу тему.")
        return

    topic = _get_topic(str(topic_key))
    items = _practice_items(topic)
    if not items:
        await cb.message.answer("Пока нет Практики.", reply_markup=_kb_back_to_menu())
        return

    uid = str(cb.from_user.id)
    data = _user_progress_get(uid)
    u = data.setdefault(uid, {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(str(topic_key), {})
    pr = tp.setdefault("practice", {})
    done = int(pr.get("done", 0))
    total = len(items)
    pct = (done / total) if total else 0.0
    _user_progress_save(data)

    await state.set_state(GrammarStates.practice_intro)
    await cb.message.answer(
        f"🧪 Практика\n{_bar(pct)}  {int(pct * 100)}%\n\nНажми «Начать».",
        reply_markup=_kb_practice_intro(),
    )


@router.callback_query(F.data == "gram:practice:start")
async def gram_practice_start(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    topic = _get_topic(str(st.get("selected_topic")))
    items = _practice_items(topic)
    if not items:
        await cb.message.answer("Пока нет Практики.", reply_markup=_kb_back_to_menu())
        return

    await state.set_state(GrammarStates.practice_view)
    await state.update_data(
        gram_section="practice",
        gram_item_idx=0,
        gram_poll_id=None,
        gram_poll_msg_id=None,
    )
    await _show_practice_item(chat_id=cb.from_user.id, state=state, topic=topic)


async def _show_practice_item(chat_id: int, state: FSMContext, topic: Dict[str, Any]) -> None:
    st = await state.get_data()
    topic_key = str(st.get("selected_topic") or "")
    items = _practice_items(topic)
    total = len(items)
    idx = int(st.get("gram_item_idx") or 0)
    if idx < 0:
        idx = 0
    if idx >= total:
        await _replace_content(
            chat_id,
            state,
            _bot.send_message(chat_id, "✅ Практика закончилась.", reply_markup=_kb_back_to_menu()),
        )  # 💬 конец практики одним сообщением
        return


    item = items[idx]
    t = _item_type(item)

    await _mark_seen(str(chat_id), topic_key, "practice", None, idx, total)  # 💬 фиксируем просмотр

    # 💬 header
    data = _user_progress_get(str(chat_id))
    u = data.get(str(chat_id), {})
    pr = (u.get("grammar_progress", {}).get(topic_key, {}).get("practice", {}) or {})
    try:
        pct = float(pr.get("pct") or 0.0)
    except Exception:
        pct = 0.0
    header = f"🧪 <b>Практика</b>\n{_bar(pct)}  {int(pct * 100)}%\n\n"

    if t == "poll":
        q = str(item.get("question") or "Выбери ответ")
        opts = item.get("options") or item.get("answers") or []
        opts = [str(x) for x in opts][:12]

        correct = 0  # 💬 по умолчанию первый
        if "correct_option_id" in item:
            try:
                correct = int(item.get("correct_option_id"))
            except Exception:
                correct = 0
        elif isinstance(item.get("correct"), int):
            correct = int(item.get("correct"))
        elif item.get("correct_answer") in opts:
            correct = opts.index(item.get("correct_answer"))  # 💬 correct_answer = текст правильного варианта

        opts, correct = _normalize_quiz_options(opts, correct)  # 💬 строго 3 варианта, правильный всегда 0

        poll_msg = await _replace_content(
            chat_id,
            state,
            lambda: _bot.send_poll(
                chat_id=chat_id,
                question=q,
                options=opts,
                type="quiz",
                correct_option_id=correct,
                is_anonymous=False,
            ),
        )  # 💬 Poll тоже не копится в чате и не роняет хендлер

        if not poll_msg:
            return

        await state.set_state(GrammarStates.practice_poll)  # 💬 ждём PollAnswer для практики
        await state.update_data(
            gram_poll_id=poll_msg.poll.id,
            gram_poll_msg_id=poll_msg.message_id,
            gram_poll_correct=correct,
            gram_poll_options=opts,
            gram_poll_section="practice",  # 💬 отмечаем, что это практика
        )
        return



    if t == "photo":
        photo = item.get("photo") or item.get("file_id") or item.get("image") or item.get("url")
        cap = header + html.escape(str(item.get("caption") or ""))
        await _replace_content(
            chat_id,
            state,
            _bot.send_photo(chat_id=chat_id, photo=photo, caption=cap, reply_markup=_kb_back_to_menu(), parse_mode="HTML"),
        )
        # 💬 авто переход вперёд
        await asyncio.sleep(0.7)
        await state.update_data(gram_item_idx=idx + 1)
        return await _show_practice_item(chat_id, state, topic)

    text = header + str(item.get("text") or "")
    await _replace_content(
        chat_id,
        state,
        _bot.send_message(chat_id=chat_id, text=text, reply_markup=_kb_back_to_menu(), parse_mode="HTML", disable_web_page_preview=True),
    )
    # 💬 авто переход вперёд
    await asyncio.sleep(0.7)
    await state.update_data(gram_item_idx=idx + 1)
    return await _show_practice_item(chat_id, state, topic)


@router.poll_answer(GrammarStates.practice_poll)
async def gram_poll_answer_practice(ans: PollAnswer, state: FSMContext) -> None:
    # 💬 обработка PollQuiz в практике
    st = await state.get_data()
    poll_id = st.get("gram_poll_id")
    if not poll_id or poll_id != ans.poll_id:
        return

    chat_id = ans.user.id
    correct = int(st.get("gram_poll_correct") or 0)
    opts = st.get("gram_poll_options") or []
    chosen = ans.option_ids[0] if ans.option_ids else -1

    if chosen == correct:
        txt = "✅ Правильно"
    else:
        right = opts[correct] if 0 <= correct < len(opts) else "не найден"
        txt = f"❌ Неправильно\n✅ Правильно: {html.escape(str(right))}"

    msg = await _bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")

    await asyncio.sleep(1.5)
    await _safe_delete_message(_bot, chat_id, msg.message_id)

    poll_msg_id = st.get("gram_poll_msg_id")
    if poll_msg_id:
        await _safe_delete_message(_bot, chat_id, int(poll_msg_id))

    idx = int(st.get("gram_item_idx") or 0) + 1
    await state.update_data(
        gram_item_idx=idx,
        gram_poll_id=None,
        gram_poll_msg_id=None,
        gram_poll_correct=None,
        gram_poll_options=None,
    )
    await state.set_state(GrammarStates.practice_view)

    topic = _get_topic(str(st.get("selected_topic")))
    await _show_practice_item(chat_id=chat_id, state=state, topic=topic)


# -----------------------------
# 🎬 VIDEO
# -----------------------------
@router.callback_query(F.data == "gram:video")
async def gram_video_intro(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    topic = _get_topic(str(st.get("selected_topic")))
    vids = _video_items(topic)
    if not vids:
        await cb.message.answer("Пока нет видео.", reply_markup=_kb_back_to_menu())
        return

    await state.set_state(GrammarStates.video_intro)
    await state.update_data(gram_section="video", gram_item_idx=0)
    await _show_video(chat_id=cb.from_user.id, state=state, topic=topic)


async def _show_video(chat_id: int, state: FSMContext, topic: Dict[str, Any]) -> None:
    st = await state.get_data()
    topic_key = str(st.get("selected_topic") or "")
    vids = _video_items(topic)
    total = len(vids)
    idx = int(st.get("gram_item_idx") or 0)
    if idx < 0:
        idx = 0
    if idx >= total:
        await _replace_content(
            chat_id,
            state,
            _bot.send_message(chat_id, "✅ Видео закончились.", reply_markup=_kb_back_to_menu()),
        )  # 💬 конец видео одним сообщением
        return


    vid = vids[idx]
    title = html.escape(str(vid.get("title") or f"Видео {idx + 1}"))
    link = str(vid.get("link") or vid.get("url") or "")

    # 💬 считаем done как max просмотренного индекса
    data = _user_progress_get(str(chat_id))
    u = data.setdefault(str(chat_id), {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(topic_key, {})
    vd = tp.setdefault("video", {})
    done = int(vd.get("done", 0))
    if idx > done:
        done = idx
        vd["done"] = done
        _user_progress_save(data)

    pct = (done / total) if total else 0.0
    text = (
        f"🎬 <b>{title}</b>\n"
        f"{_bar(pct)}  {int(pct * 100)}%\n\n"
        f"{html.escape(link)}"
    )

    await _replace_content(
        chat_id,
        state,
        _bot.send_message(chat_id=chat_id, text=text, reply_markup=_kb_video_controls(), parse_mode="HTML", disable_web_page_preview=True),
    )


@router.callback_query(F.data.in_(["gram:video:done", "gram:video:next"]))
async def gram_video_controls(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    if st.get("gram_section") != "video":
        return

    idx = int(st.get("gram_item_idx") or 0)

    # 💬 "done" и "next" одинаково двигают вперёд
    idx += 1
    await state.update_data(gram_item_idx=idx)

    topic = _get_topic(str(st.get("selected_topic")))
    await _show_video(chat_id=cb.from_user.id, state=state, topic=topic)


# -----------------------------
# 📚 READ (как подкасты: фрагменты)
# -----------------------------
@router.callback_query(F.data == "gram:read")
async def gram_read_intro(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    topic = _get_topic(str(st.get("selected_topic")))
    frags = _read_fragments(topic)
    if not frags:
        await cb.message.answer("Пока нет фрагментов для Читать.", reply_markup=_kb_back_to_menu())
        return

    await state.set_state(GrammarStates.read_view)
    await state.update_data(gram_section="read", gram_item_idx=0)
    await _show_read(chat_id=cb.from_user.id, state=state, topic=topic)


def _format_read_fragment(f: Dict[str, Any]) -> str:
    es = html.escape(str(f.get("es") or ""))
    ru = html.escape(str(f.get("ru") or ""))
    hint = str(f.get("hint") or "")
    hint = html.escape(hint) if hint else ""
    text = ""
    if es:
        text += f"<b>ES</b>\n{es}\n\n"
    if ru:
        text += f"<b>RU</b>\n{ru}\n\n"
    if hint:
        text += f"💡 hint\n{hint}"
    return text.strip() or "Пустой фрагмент"


async def _show_read(chat_id: int, state: FSMContext, topic: Dict[str, Any]) -> None:
    st = await state.get_data()
    topic_key = str(st.get("selected_topic") or "")
    frags = _read_fragments(topic)
    total = len(frags)
    idx = int(st.get("gram_item_idx") or 0)
    if idx < 0:
        idx = 0
    if idx >= total:
        await _replace_content(
            chat_id,
            state,
            _bot.send_message(chat_id, "✅ Читать закончено.", reply_markup=_kb_back_to_menu()),
        )  # 💬 конец чтения одним сообщением
        return


    f = frags[idx]
    t = _item_type(f)

    # 💬 read done = max индекс
    data = _user_progress_get(str(chat_id))
    u = data.setdefault(str(chat_id), {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(topic_key, {})
    rd = tp.setdefault("read", {})
    done = int(rd.get("done", 0))
    if idx > done:
        rd["done"] = idx
        _user_progress_save(data)

    pct = (done / total) if total else 0.0
    header = f"📚 <b>Читать</b>\n{_bar(pct)}  {int(pct * 100)}%\n\n"

    if t == "photo":
        photo = f.get("photo") or f.get("file_id") or f.get("image") or f.get("url")
        cap = header + html.escape(str(f.get("caption") or ""))
        await _replace_content(
            chat_id,
            state,
            _bot.send_photo(chat_id=chat_id, photo=photo, caption=cap, reply_markup=_kb_read_controls(), parse_mode="HTML"),
        )
        return

    text = header + _format_read_fragment(f)
    await _replace_content(
        chat_id,
        state,
        _bot.send_message(chat_id=chat_id, text=text, reply_markup=_kb_read_controls(), parse_mode="HTML", disable_web_page_preview=True),
    )


@router.callback_query(F.data.in_(["gram:read:prev", "gram:read:next"]))
async def gram_read_nav(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    if st.get("gram_section") != "read":
        return

    idx = int(st.get("gram_item_idx") or 0)
    if cb.data.endswith("prev"):
        idx -= 1
    else:
        idx += 1
    await state.update_data(gram_item_idx=idx)

    topic = _get_topic(str(st.get("selected_topic")))
    await _show_read(chat_id=cb.from_user.id, state=state, topic=topic)


@router.callback_query(F.data == "gram:read:star")
async def gram_read_star(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    topic_key = str(st.get("selected_topic") or "")
    idx = int(st.get("gram_item_idx") or 0)

    topic = _get_topic(topic_key)
    frags = _read_fragments(topic)
    if idx < 0 or idx >= len(frags):
        await cb.answer("Фрагмент не найден", show_alert=False)
        return

    uid = str(cb.from_user.id)
    data = _user_progress_get(uid)
    u = data.setdefault(uid, {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(topic_key, {})
    notes = tp.setdefault("read_notes", [])

    # 💬 антидубликаты по idx
    for n in notes:
        try:
            if int(n.get("idx", -1)) == idx:
                await cb.answer("Уже сохранено ⭐", show_alert=False)
                return
        except Exception:
            continue

    notes.append({"idx": idx, "frag": frags[idx]})
    _user_progress_save(data)
    await cb.answer("Сохранено ⭐", show_alert=False)
