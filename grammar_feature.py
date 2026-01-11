# grammar_feature.py
# 💬 модуль "Грамматика" (Теория по фазам -> навигация -> PollQuiz/Фото/Текст) + Практика + Видео + Читать

from __future__ import annotations

import asyncio  # 💬 таймер для авто удаления
import html
import random  # 💬 для выбора CTA фраз и случайных кнопок Feedback
# 💬 FeedbackDifficulty: берём из отдельного файла, но не падаем если файла нет / структура изменилась
try:
    from feedback_difficulty_block import feedback_difficulty as feedback_questions  # 💬 список сценариев
except Exception:
    feedback_questions = [
        {
            "text": "Было легко? 😌",
            "buttons": ["Легко! 😃", "Сложно… 😓"],
            "replies": {
                "Легко! 😃": {"reaction": "Вижу, звёзды тебе по плечу! ⭐️", "next": "offer_continue"},
                "Сложно… 😓": {"reaction": "Скоро будет проще! 💪", "next": "offer_continue"},
            },
        }
    ]



from scenarios_estiloso8_1 import link_cta_phrases  # 💬 CTA фразы для ссылок
grammar_quiz_success_phrases = [
    "✅ Так держать! Двигаем дальше",
    "🔥 Отлично! Следующий",
    "💪 Так держать! Погнали",
    "🎯 В точку! Едем дальше",
]  # 💬 короткие реакции как в лексике

grammar_quiz_fail_phrases = [
    "❌ Неа…",
    "😅 Почти…",
    "🙃 Мимо…",
    "🤏 Чуть-чуть не то…",
]  # 💬 короткие реакции на ошибку



import random  # 💬 CTA фразы для link-блоков

from typing import Any, Callable, Dict, List, Optional, Tuple

from aiogram import Router, F
from aiogram.filters import StateFilter  # 💬 фильтр FSM для poll_answer (иначе хендлер может не срабатывать)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    PollAnswer,
    ReactionTypeEmoji,
    InputMediaPhoto,  # 💬 нужно для edit_message_media, чтобы не удалять и не слать заново фото в Теории

)

from aiogram.exceptions import TelegramBadRequest  # 💬 чтобы не падать, если нельзя удалить/изменить

router = Router()
# -----------------------------
# 🧩 runtime caches (PollAnswer)
# -----------------------------
_GRAM_POLL_CTX: Dict[str, Dict[str, Any]] = {}  # 💬 poll_id -> ctx для poll_answer
_GRAM_RENDER_LOCKS: Dict[int, asyncio.Lock] = {}  # 💬 lock на чат, чтобы не было дублей

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


def _safe_html(x: Any) -> str:
    # 💬 безопасно экранируем HTML и приводим к строке (чтобы не падать на None/числах)
    try:
        return html.escape(str(x)).strip()
    except Exception:
        return ""


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


def _bar(pct: float, width: int = 20) -> str:
    # 💬 прогресс бар текстом = 20 сегментов (5% за сегмент) и минимум 1 сегмент по умолчанию
    if pct < 0:
        pct = 0
    if pct > 1:
        pct = 1

    filled = int(round(pct * width))
    if filled <= 0:
        filled = 1  # 💬 по дефолту показываем 1 заполненный сегмент (5% при width=20)
    if filled > width:
        filled = width

    return "█" * filled + "░" * (width - filled)

def _sess_progress_from_state(st: Dict[str, Any]) -> Dict[str, Any]:
    # 💬 session progress хранится только в FSM state (не в RailwayData)
    sp = st.get("gram_session_progress") or {}
    if not isinstance(sp, dict):
        sp = {}
    sp.setdefault("theory", {})   # 💬 phase_idx -> {seen:[], pct:float, done:bool}
    sp.setdefault("practice", {}) # 💬 {done:int, seen:[], pct:float}
    sp.setdefault("video", {})    # 💬 {done_idx:int}
    sp.setdefault("read", {})     # 💬 {done_idx:int}
    return sp


async def _mark_seen_session(
    state: FSMContext,
    section: str,
    phase_idx: Optional[int],
    item_idx: int,
    total: int
) -> None:
    # 💬 отмечаем прогресс только в session (FSM), без сохранения в user_data
    st = await state.get_data()
    sp = _sess_progress_from_state(st)

    if section == "theory" and phase_idx is not None:
        th = sp.setdefault("theory", {})
        ph = th.setdefault(str(phase_idx), {})
        seen = ph.setdefault("seen", [])
        if not isinstance(seen, list):
            seen = []
            ph["seen"] = seen

        if 0 <= int(item_idx) < int(total):
            if int(item_idx) not in seen:
                seen.append(int(item_idx))

        pct = (len(seen) / int(total)) if total else 0.0
        ph["pct"] = pct
        if pct >= 0.7:
            ph["done"] = True  # 💬 фаза засчитана на 70% в рамках сессии

    elif section == "practice":
        pr = sp.setdefault("practice", {})
        seen = pr.setdefault("seen", [])
        if not isinstance(seen, list):
            seen = []
            pr["seen"] = seen

        if 0 <= int(item_idx) < int(total):
            if int(item_idx) not in seen:
                seen.append(int(item_idx))

        pct = (len(seen) / int(total)) if total else 0.0
        pr["pct"] = pct
        pr["done"] = len(seen)  # 💬 done как количество просмотренных в рамках сессии

    elif section == "video":
        vd = sp.setdefault("video", {})
        try:
            done_idx = int(vd.get("done_idx")) if vd.get("done_idx") is not None else -1
        except Exception:
            done_idx = -1
        if int(item_idx) > done_idx:
            vd["done_idx"] = int(item_idx)  # 💬 max индекс видео в рамках сессии

    elif section == "read" and phase_idx is not None:
        rd = sp.setdefault("read", {})
        ph = rd.setdefault(str(phase_idx), {})
        seen = ph.setdefault("seen", [])
        if not isinstance(seen, list):
            seen = []
            ph["seen"] = seen

        if 0 <= int(item_idx) < int(total):
            if int(item_idx) not in seen:
                seen.append(int(item_idx))

        pct = (len(set(int(x) for x in seen if isinstance(x, int) or str(x).isdigit())) / int(total)) if total else 0.0
        ph["pct"] = pct
        if pct >= 0.999999:
            ph["done"] = True  # 💬 фаза Читать зачёркивается только при 100%


    await state.update_data(gram_session_progress=sp)


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

def _strike_text(text: str) -> str:
    # 💬 псевдо-зачёркивание для InlineKeyboard (HTML/Markdown в кнопках не работает)
    return "".join(ch + "\u0336" for ch in str(text))

def _phase_items(phase: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    💬 Теория = ТОЛЬКО текст и фото
    💬 полностью вырезаем poll/quiz/textquiz/link и любые блоки с question/options
    """
    base = phase.get("vocab") or []

    out: List[Dict[str, Any]] = []

    for x in (base or []):
        # 💬 строки нормализуем в dict, иначе _show_current_item упадёт на item.get(...)
        if isinstance(x, str):
            s = x.strip()
            if s:
                out.append({"type": "text", "text": s})
            continue

        if not isinstance(x, dict):
            continue

        t = (x.get("type") or "").strip().lower()



        # 💬 PHOTO
        media = x.get("photo") or x.get("file_id") or x.get("image") or x.get("file") or ""
        if media:
            out.append(x)
            continue

        # 💬 TEXT (включая случай когда подпись лежит в caption)
        txt = (x.get("text") or x.get("caption") or "").strip()
        hint = (x.get("hint") or "").strip()
        if txt or hint:
            out.append({"type": "text", "text": txt, "hint": hint})
            continue

    return out



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

        assets = p.get("assets") or []
        if isinstance(assets, list):
            for a in assets:
                if isinstance(a, dict) and (a.get("type") == "asset"):
                    # 💬 совместимость со старым форматом CreateLessonBlock: assets -> photo
                    media = a.get("file") or a.get("photo") or a.get("file_id") or a.get("url") or ""
                    cap = a.get("text") or a.get("caption") or ""
                    if media:
                        out.append({"type": "photo", "photo": media, "caption": cap})
                else:
                    # 💬 если вдруг там уже лежит нормальный dict = просто добавим
                    out.append(a)

    return out


def _item_type(item: Any) -> str:
    # 💬 нормализуем тип элемента, включая совместимость со строками в reading.fragments
    if isinstance(item, str):
        return "text"  # 💬 если фрагмент = строка, считаем обычным текстом
    if not isinstance(item, dict):
        return "text"  # 💬 защита от неожиданных типов

    t = (item.get("type") or "").strip().lower()

    # 💬 если блок содержит медиа, считаем его фото (бывает, что подпись лежит в text)
    if isinstance(item, dict):
        if (item.get("photo") or item.get("file_id") or item.get("image") or item.get("file")) and (t in (None, "", "text", "asset")):
            return "photo"


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
            ],
        ]
    )  # 💬 меню без счётчиков внутри кнопок



def _kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu")]  # 💬 возвращаемся в меню топика
        ]
    )


def _kb_phases(
    phases: List[Dict[str, Any]],
    done_flags: List[bool],
    phase_pcts: Optional[List[float]] = None,
    *,
    show_return_button: bool = False
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    if show_return_button:
        rows.append([InlineKeyboardButton(text="↩️ Вернуться к практике", callback_data="gram:practice:return")])  # 💬 возврат в link-практику

    for i, ph in enumerate(phases):
        label = _phase_title(ph, i)

        if i < len(done_flags) and done_flags[i]:
            label = f"⭐ {label}"  # 💬 старый бейдж за “done” оставляем

        # 💬 зачёркиваем строго при 100% (все блоки фазы просмотрены)
        if phase_pcts and i < len(phase_pcts) and phase_pcts[i] >= 0.999999:
            label = _strike_text(label)

        rows.append([InlineKeyboardButton(text=label, callback_data=f"gram:phase:{i}")])

    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu")])  # 💬 назад в меню топика
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_nav_in_phase(back_to_phases: bool = False) -> InlineKeyboardMarkup:
    # 💬 если пришли из практики = "Меню" ведёт назад к выбору фаз (чтобы была кнопка "Вернуться к практике")
    back_btn = InlineKeyboardButton(
        text="⬅️ Назад" if back_to_phases else "⬅️ Меню",
        callback_data="gram:theory" if back_to_phases else "gram:menu",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data="gram:nav:prev"),
                InlineKeyboardButton(text="➡️", callback_data="gram:nav:next"),
            ],
            [
                back_btn,
            ],
        ]
    )




def _kb_practice_intro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать", callback_data="gram:practice:start")],
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu")],  # 💬 назад в меню топика

        ]
    )

def _kb_practice_continue_menu(done, total):
    # 💬 клавиатура после Feedback: Продолжить или Меню
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"▶️ Продолжить ({done}/{total})", callback_data="gram:practice:next")],
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu")]
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
                InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu"),

            ],  # 💬 одна кнопка

        ]
    )


def _kb_read_controls() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data="gram:read:prev"),
                InlineKeyboardButton(text="➡️", callback_data="gram:read:next"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu"),
            ],  # 💬 одна кнопка
        ]
    )


def _kb_read_packs(
    packs: List[Dict[str, Any]],
    phase_pcts: Optional[List[float]] = None
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    for i, p in enumerate(packs or []):
        title = str((p or {}).get("title") or f"Фаза {i + 1}").strip()
        if len(title) > 40:
            title = title[:37] + "..."  # 💬 чтобы кнопки не разъезжались

        # 💬 зачёркиваем фазу Читать строго при 100%, как в Теории
        if phase_pcts and i < len(phase_pcts) and phase_pcts[i] >= 0.999999:
            title = _strike_text(title)

        rows.append([InlineKeyboardButton(text=title, callback_data=f"gram:read_pack:{i}")])

    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu")])  # 💬 выход в меню
    return InlineKeyboardMarkup(inline_keyboard=rows)


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

    tries = int(st.get("gram_replace_tries") or 3)  # 💬 дефолт 3, но для Теории можно снизить до 1
    msg = await _tg_retry(_call, tries=tries)  # 💬 ретраи при таймауте, tries управляем через state

    if not msg:
        return None

    if old_id:
        await _safe_delete_message(_bot, chat_id, int(old_id))  # 💬 удаляем старый экран только после успеха

    await state.update_data(
        gram_content_msg_id=msg.message_id,
        gram_last_message_id=msg.message_id,  # 💬 чтобы дальше можно было edit_text/edit_media без удаления
    )
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



def _theory_overall_pct(uid: str, topic_key: str, topic: Dict[str, Any]) -> float:
    # 💬 общий прогресс Теории = по всем индексам элементов во всех фазах (а не по done фазам)
    phases = _get_theory_phases(topic)

    data = _user_progress_get(uid)
    u = (data.get(uid) or {})
    gp = (u.get("grammar_progress") or {})
    tp = (gp.get(topic_key) or {})
    theory = (tp.get("theory") or {})

    total_all = 0
    seen_all = 0

    for i, ph in enumerate(phases):
        items = _phase_items(ph)
        total_phase = len(items)
        total_all += total_phase

        ph_prog = theory.get(str(i)) or {}
        seen = ph_prog.get("seen") or []
        if not isinstance(seen, list):
            seen = []

        # 💬 считаем уникальные валидные индексы внутри фазы, чтобы не было дублей/мусора
        uniq_valid = set()
        for x in seen:
            try:
                xi = int(x)
            except Exception:
                continue
            if 0 <= xi < total_phase:
                uniq_valid.add(xi)

        seen_all += len(uniq_valid)

    return (seen_all / total_all) if total_all else 0.0


def _theory_phase_pcts(uid: str, topic_key: str, phases: List[Dict[str, Any]]) -> List[float]:
    # 💬 pct по каждой фазе Теории = уникальные просмотренные индексы / всего блоков фазы
    data = _user_progress_get(uid)
    u = (data.get(uid) or {})
    gp = (u.get("grammar_progress") or {})
    tp = (gp.get(topic_key) or {})
    theory = (tp.get("theory") or {})

    pcts: List[float] = []

    for i, ph in enumerate(phases):
        items = _phase_items(ph)
        total_phase = len(items)

        ph_prog = theory.get(str(i)) or {}
        seen = ph_prog.get("seen") or []
        if not isinstance(seen, list):
            seen = []

        # 💬 уникальные валидные индексы, чтобы не было дублей/мусора
        uniq_valid = set()
        for x in seen:
            try:
                xi = int(x)
            except Exception:
                continue
            if 0 <= xi < total_phase:
                uniq_valid.add(xi)

        pct = (len(uniq_valid) / total_phase) if total_phase else 0.0
        pcts.append(pct)

    return pcts



async def open_grammar_topic(message: Message, state: FSMContext) -> None:
    """
    💬 вход в грамматику после выбора темы
    """
    if not _ensure_di():
        await message.answer("⚠️ Грамматика пока не подключена. Проверь init_grammar_feature.")
        return

    st = await state.get_data()
    lvl = (
        st.get("selected_level")
        or st.get("level")
        or st.get("lvl")
        or st.get("level_key")
        or st.get("selected_category_level")
        or st.get("category_level")
        or st.get("chosen_level")
    )  # 💬 подхватываем уровень из core, даже если ключ называется иначе

    if lvl and not st.get("selected_level"):
        await state.update_data(selected_level=lvl)  # 💬 фиксируем ожидаемый ключ для кнопки "Темы"

    topic_key = st.get("selected_topic")
    if not topic_key:
        await message.answer("⚠️ Не вижу выбранную тему.")
        return

    topic = _get_topic(str(topic_key))
    title = html.escape(str(topic.get("visible_title") or topic.get("title") or "Грамматика"))

    phases = _get_theory_phases(topic)

    st_now = await state.get_data()
    sp = _sess_progress_from_state(st_now)
    th = sp.get("theory") or {}

    # 💬 done_flags по фазам = из session (pct>=0.7)
    done_flags = []
    for i in range(len(phases)):
        ph = th.get(str(i)) or {}
        done_flags.append(bool(ph.get("done")))

    # 💬 Теория общий % = все просмотренные индексы по всем фазам в рамках сессии
    theory_total = 0
    theory_seen = 0
    for i, ph in enumerate(phases):
        items = _phase_items(ph)
        total_phase = len(items)
        theory_total += total_phase

        ph_prog = th.get(str(i)) or {}
        seen = ph_prog.get("seen") or []
        if not isinstance(seen, list):
            seen = []

        uniq_valid = set()
        for x in seen:
            try:
                xi = int(x)
            except Exception:
                continue
            if 0 <= xi < total_phase:
                uniq_valid.add(xi)

        theory_seen += len(uniq_valid)

    theory_pct = (theory_seen / theory_total) if theory_total else 0.0

    # 💬 Практика в меню считаем по ссылкам (FeedbackDifficulty done) в рамках сессии
    exercises = topic.get("exercises") or []
    link_items = [x for x in exercises if (isinstance(x, dict) and (x.get("url") or x.get("link")))]
    pr_total = len(link_items)
    pr_done = int(st_now.get("gram_links_done") or 0)
    pr_done = min(pr_done, pr_total) if pr_total else 0
    pr_pct = (pr_done / pr_total) if pr_total else 0.0

    # 💬 Видео session
    videos = _video_items(topic)
    vd_total = len(videos) if videos else 0
    try:
        vd_done_idx = int((sp.get("video") or {}).get("done_idx")) if (sp.get("video") or {}).get("done_idx") is not None else -1
    except Exception:
        vd_done_idx = -1
    vd_done = (min(vd_done_idx + 1, vd_total) if (vd_total and vd_done_idx >= 0) else 0)
    vd_pct = (vd_done / vd_total) if vd_total else 0.0

    # 💬 Читать session: считаем прогресс по фазам (пакетам), как в Теории
    packs = _read_packs(topic)
    rd_total_phases = 0
    rd_done_phases = 0

    rd_map = (sp.get("read") or {}) if isinstance(sp.get("read"), dict) else {}

    for i, _p in enumerate(packs or []):
        fr = _read_fragments_from_pack(topic, i)
        fr = [x for x in (fr or []) if _item_type(x) != "photo"]  # 💬 Читать = только текст
        total = len(fr)
        if total <= 0:
            continue  # 💬 пустую фазу не считаем в прогресс
        rd_total_phases += 1

        ph = rd_map.get(str(i)) or {}
        seen = ph.get("seen") or []
        if not isinstance(seen, list):
            seen = []
        uniq_valid = set()
        for x in seen:
            try:
                xi = int(x)
            except Exception:
                continue
            if 0 <= xi < total:
                uniq_valid.add(xi)

        pct = (len(uniq_valid) / total) if total else 0.0
        if pct >= 0.999999:
            rd_done_phases += 1

    rd_pct = (rd_done_phases / rd_total_phases) if rd_total_phases else 0.0


    def _line(icon: str, pct: float) -> str:
        # 💬 строка прогресса: только эмоджи + бар(10) + проценты, ✅ если 100%
        p = int(pct * 100)
        if p > 100:
            p = 100
        tick = " ✅" if p >= 100 else ""
        return f"{icon}  {_bar(pct, width=10)}  {p}%{tick}"

    text = (
        f"<b><i>🫴🏼 {title}</i></b>\n\n"
        f"<pre>"
        f"{_line('📖', theory_pct)}\n"
        f"{_line('🧪', pr_pct)}\n"
        f"{_line('🎬', vd_pct)}\n"
        f"{_line('📚', rd_pct)}"
        f"</pre>"
    )



    await state.set_state(GrammarStates.menu)
    await state.update_data(gram_ctx=True, gram_topic_key=str(topic_key))  # 💬 не сбрасываем id, чтобы удалять прошлый экран

    await _replace_content(
        chat_id=message.chat.id,
        state=state,
        send_coro=message.answer(
            text,
            reply_markup=_kb_menu(),
            parse_mode="HTML",
        ),
    )  # 💬 показываем меню грамматики одним сообщением




# -----------------------------
# 🟢 MENU callbacks
# -----------------------------
@router.callback_query(F.data == "gram:menu")
async def gram_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await _safe_delete_message(_bot, cb.message.chat.id, cb.message.message_id)  # 💬 сразу убираем экран с кнопками после нажатия

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

    # 💬 чистим poll ctx и локи при выходе из грамматики, чтобы не было утечек/фантомных poll
    cid = int(cb.from_user.id)
    for k, v in list(_GRAM_POLL_CTX.items()):
        try:
            if int((v or {}).get("chat_id") or 0) == cid:
                _GRAM_POLL_CTX.pop(k, None)
        except Exception:
            continue
    _GRAM_RENDER_LOCKS.pop(cid, None)

    # 💬 не удаляем текущее сообщение, core будет редактировать его через edit_text
    await state.update_data(gram_content_msg_id=None)  # 💬 выходим из грамматики в список тем
    await state.update_data(
        gram_session_progress=None,  # 💬 сбрасываем progress внутри темы
        gram_links_done=0,
        gram_links_total=0,
        gram_link_idx=0,
        gram_link_items=None,
        gram_section=None,
        gram_phase_idx=None,
        gram_item_idx=None,
    )  # 💬 при новом входе в тему прогресс начинается с нуля


    # 💬 возвращаемся к списку тем грамматики выбранного уровня
    st = await state.get_data()

    lvl = (
        st.get("selected_level")
        or st.get("level")
        or st.get("lvl")
        or st.get("level_key")
        or st.get("selected_category_level")
        or st.get("category_level")
        or st.get("chosen_level")
    )  # 💬 поддерживаем разные ключи уровня из core

    if not lvl:
        # 💬 если уровень не сохранился, не ругаемся, а возвращаем в /start
        if _start_handler:
            try:
                await state.clear()
            except Exception:
                pass
            await _start_handler(cb.message, state)
            return
        await cb.message.answer("Нажми /start")
        return

    # 💬 сохраняем в expected key, чтобы дальше работало стабильно
    await state.update_data(selected_level=lvl)

    if _show_topics_for_category_level:
        try:
            await _show_topics_for_category_level(cb, state, category="gram", level=lvl)  # 💬 обратно к темам
        except TelegramBadRequest:
            # 💬 если текущее сообщение уже исчезло, возвращаем в старт без падения
            if _start_handler:
                try:
                    await state.clear()
                except Exception:
                    pass
                await _start_handler(cb.message, state)
            else:
                await cb.message.answer("Нажми /start")


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

    st_now = await state.get_data()
    sp = _sess_progress_from_state(st_now)
    th = sp.get("theory") or {}

    done_flags = []
    phase_pcts = []
    for i, ph in enumerate(phases):
        items = _phase_items(ph)
        total_phase = len(items)

        ph_prog = th.get(str(i)) or {}
        seen = ph_prog.get("seen") or []
        if not isinstance(seen, list):
            seen = []

        uniq_valid = set()
        for x in seen:
            try:
                xi = int(x)
            except Exception:
                continue
            if 0 <= xi < total_phase:
                uniq_valid.add(xi)

        pct = (len(uniq_valid) / total_phase) if total_phase else 0.0
        phase_pcts.append(pct)
        done_flags.append(bool(ph_prog.get("done")))  # 💬 done в рамках сессии

    await state.set_state(GrammarStates.theory_phases)
    await _replace_content(
        chat_id=cb.from_user.id,
        state=state,
        send_coro=cb.message.answer(
            "Выбери фазу:",
            reply_markup=_kb_phases(
                phases,
                done_flags,
                phase_pcts=phase_pcts,  # 💬 зачёркиваем фазу при 100%
                show_return_button=bool((await state.get_data()).get("gram_return_to_practice")),
            ),

        ),
    )  # 💬 список фаз в одном сообщении


@router.callback_query(F.data == "gram:practice:done")
async def gram_practice_done(cb: CallbackQuery, state: FSMContext):
    # 💬 кнопка "Сделано" -> показываем FeedbackDifficulty
    await cb.answer()
    q = random.choice(feedback_questions) if feedback_questions else {}

    buttons = q.get("buttons") or ["Легко", "Сложно"]
    btn1 = str(buttons[0]) if len(buttons) > 0 else "Легко"
    btn2 = str(buttons[1]) if len(buttons) > 1 else "Сложно"
    text = str(q.get("text") or "Как тебе было это упражнение?")

    await state.update_data(gram_last_feedback_question=q)  # 💬 сохраняем вопрос для реакции

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=btn1, callback_data="gram:practice:fd:0"),
                InlineKeyboardButton(text=btn2, callback_data="gram:practice:fd:1"),
            ]
        ]
    )

    await _replace_content(
        cb.message.chat.id,
        state,
        _bot.send_message(
            chat_id=cb.message.chat.id,
            text=text,
            reply_markup=kb
        )
    )


@router.callback_query(F.data.startswith("gram:practice:fd:"))
async def gram_practice_feedback(cb: CallbackQuery, state: FSMContext):
    # 💬 выбор сложности -> реакция + инкремент прогресса + экран продолжить/меню
    await cb.answer()
    data = await state.get_data()

    q = data.get("gram_last_feedback_question") or {}
    try:
        choice = int(str(cb.data).split(":")[-1])
    except Exception:
        choice = 0

    buttons = q.get("buttons") or []
    chosen_btn = str(buttons[choice]) if isinstance(buttons, list) and choice < len(buttons) else None

    reaction_text = None
    replies = q.get("replies") or {}
    if chosen_btn and isinstance(replies, dict):
        reaction_text = (replies.get(chosen_btn) or {}).get("reaction")

    done = int(data.get("gram_links_done", 0)) + 1
    total = int(data.get("gram_links_total", 1))
    await state.update_data(gram_links_done=done)  # 💬 прогресс считаем здесь

    # 💬 сохраняем прогресс практики только в session (FSM), чтобы меню обновлялось без RailwayData
    st_now = await state.get_data()
    sp = _sess_progress_from_state(st_now)
    pr = sp.setdefault("practice", {})
    safe_done = min(int(done), int(total)) if total else int(done)
    pr["done"] = safe_done
    pr["pct"] = (safe_done / int(total)) if total else 0.0
    await state.update_data(gram_session_progress=sp)


    bar = _bar((done / total) if total else 1.0)
    txt = (str(reaction_text).strip() + "\n\n") if reaction_text else ""
    txt += f"{bar}  {done}/{total}"

    if done >= total:
        await _replace_content(
            cb.message.chat.id,
            state,
            _bot.send_message(
                chat_id=cb.message.chat.id,
                text=txt,
                reply_markup=_kb_practice_continue_menu(done, total),  # 💬 остаёмся в Практике, меню доступно
                parse_mode="HTML"
            )
        )
        return


    await _replace_content(
        cb.message.chat.id,
        state,
        _bot.send_message(
            chat_id=cb.message.chat.id,
            text=txt,
            reply_markup=_kb_practice_continue_menu(done, total),
            parse_mode="HTML"
        )
    )


@router.callback_query(F.data == "gram:practice:next")
async def gram_practice_next(cb: CallbackQuery, state: FSMContext):
    # 💬 "Продолжить" = если это конец, не меняем экран, только подсказка
    data = await state.get_data()
    items = data.get("gram_link_items", []) or []
    cur_idx = int(data.get("gram_link_idx", 0))
    next_idx = cur_idx + 1

    if next_idx >= len(items):
        await cb.answer("Это конец", show_alert=False)  # 💬 остаёмся на текущем экране
        return

    await cb.answer()
    await _safe_delete_message(_bot, cb.message.chat.id, cb.message.message_id)  # 💬 убираем экран только если реально идём дальше

    await state.update_data(gram_link_idx=next_idx)

    await _replace_content(
        cb.message.chat.id,
        state,
        _bot.send_message(
            chat_id=cb.message.chat.id,
            text="⏳ Гружу следующую ссылку...",
            parse_mode="HTML"
        )
    )
    await asyncio.sleep(0.8)
    return await _show_practice_link(cb.message.chat.id, state)



@router.callback_query(F.data == "gram:practice:theory")
async def gram_practice_theory(cb: CallbackQuery, state: FSMContext):
    # 💬 переход в теорию с возможностью вернуться к практике
    await cb.answer()
    data = await state.get_data()
    await state.update_data(
        gram_return_to_practice=True,
        gram_return_practice_idx=int(data.get("gram_link_idx", 0))
    )
    return await gram_theory(cb, state)  # 💬 открываем выбор фаз теории


@router.callback_query(F.data == "gram:practice:return")
async def gram_return_to_practice(cb: CallbackQuery, state: FSMContext):
    # 💬 вернуться из теории обратно к той же ссылке практики
    await cb.answer()
    data = await state.get_data()
    idx = int(data.get("gram_return_practice_idx", 0))

    await state.update_data(
        gram_return_to_practice=False,
        gram_link_idx=idx
    )
    await state.set_state(GrammarStates.practice_view)  # 💬 возвращаем state в практику
    return await _show_practice_link(cb.message.chat.id, state)



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
        back_to_phases = bool(st.get("gram_return_to_practice"))  # 💬 если пришли из практики = кнопка ведёт назад к фазам
        await _replace_content(
            chat_id=cb.from_user.id,
            state=state,
            send_coro=cb.message.answer(
                "Пока нет блоков в этой фазе.",
                reply_markup=_kb_nav_in_phase(back_to_phases=back_to_phases),
            ),
        )  # 💬 не плодим сообщения, возвращаемся корректно
        return


    await state.set_state(GrammarStates.theory_view)
    await state.update_data(
        gram_section="theory",
        gram_phase_idx=phase_idx,
        gram_item_idx=0,
    )
    await _show_current_item(chat_id=cb.from_user.id, state=state, topic=topic)



@router.callback_query(F.data.in_(["gram:nav:prev", "gram:nav:next"]))
async def gram_nav(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    if st.get("gram_section") != "theory":
        return

    topic = _get_topic(str(st.get("selected_topic")))
    phase_idx = int(st.get("gram_phase_idx") or 0)
    phases = _get_theory_phases(topic)
    if phase_idx < 0 or phase_idx >= len(phases):
        await cb.answer("Фаза не найдена", show_alert=False)
        return

    items = _phase_items(phases[phase_idx])
    total = len(items)
    if total <= 0:
        await cb.answer("Пока нет блоков", show_alert=False)
        return

    idx = int(st.get("gram_item_idx") or 0)

    if cb.data.endswith("prev"):
        if idx <= 0:
            await cb.answer("Это начало", show_alert=False)  # 💬 не уходим в минус, просто подсказка
            return
        idx -= 1
    else:
        if idx >= total - 1:
            await cb.answer("Это конец", show_alert=False)  # 💬 не уходим за предел, просто подсказка
            return
        idx += 1

    await state.update_data(gram_item_idx=idx)
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


async def _gram_edit_or_replace_text(chat_id: int, state: FSMContext, text: str, kb):  # 💬 edit текста как в подкастах, иначе fallback на replace
    st = await state.get_data()
    last_id = st.get("gram_last_message_id")
    last_kind = st.get("gram_last_message_kind") or "text"

    if last_id and last_kind == "text":
        try:
            await _bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(last_id),
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True
            )
            return  # 💬 успешно отредактировали, новое сообщение не шлём
        except Exception:
            pass  # 💬 если нельзя отредактировать (например, прошлое было photo) = уйдём в fallback

    await _replace_content(  # 💬 fallback: удаляем прошлое и шлём заново
        chat_id,
        state,
        _bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True
        )
    )
    await state.update_data(gram_last_message_kind="text")  # 💬 помечаем тип последнего сообщения

async def _gram_edit_or_replace_photo(chat_id: int, state: FSMContext, file_id: str, caption: str, kb: InlineKeyboardMarkup) -> None:
    # 💬 редактируем photo-блок через edit_message_media, чтобы Теория листалась быстро без удаления
    st = await state.get_data()
    last_id = st.get("gram_last_message_id")
    last_kind = st.get("gram_last_message_kind") or "text"

    if last_id and last_kind == "photo":
        try:
            media = InputMediaPhoto(
                media=file_id,
                caption=caption,
                parse_mode="HTML",
            )
            await _bot.edit_message_media(
                chat_id=chat_id,
                message_id=int(last_id),
                media=media,
                reply_markup=kb,
            )
            return  # 💬 успешно отредактировали фото
        except Exception:
            pass  # 💬 fallback ниже

    msg = await _replace_content(
        chat_id,
        state,
        _bot.send_photo(
            chat_id,
            file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
            disable_notification=True
        ),
    )
    await state.update_data(
        gram_last_message_kind="photo",  # 💬 фиксируем тип
        gram_last_message_id=msg.message_id,  # 💬 фиксируем id для следующих edit
    )




async def _show_current_item(chat_id: int, state: FSMContext, topic: Dict[str, Any]) -> None:
    # 💬 показываем текущий элемент (текст/фото) или шлём poll
    st = await state.get_data()
    section = st.get("gram_section")
    lock = _GRAM_RENDER_LOCKS.setdefault(chat_id, asyncio.Lock())  # 💬 один рендер за раз, антидубли
    async with lock:
        st = await state.get_data()  # 💬 обновляем данные внутри лока
        section = st.get("gram_section")

    topic_key = str(st.get("selected_topic") or "")
    back_to_phases = bool(st.get("gram_return_to_practice"))  # 💬 из практики назад ведём к фазам, а не в меню


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
            idx = max(0, total - 1)  # 💬 clamp на последний, навигация остаётся
            await state.update_data(gram_item_idx=idx)


        item = items[idx]
        t = _item_type(item)

        await _mark_seen_session(state, "theory", phase_idx, idx, total)  # 💬 фиксируем просмотр только в session


        title = html.escape(_phase_title(phase, phase_idx))
        pct = 0.0
        st_now = await state.get_data()
        sp = _sess_progress_from_state(st_now)
        ph = ((sp.get("theory") or {}).get(str(phase_idx)) or {})
        try:
            pct = float(ph.get("pct") or 0.0)
        except Exception:
            pct = 0.0


        header = f"📖 <b>{title}</b>\n{_bar(pct)} {int(pct * 100)}% {idx + 1}/{total}"  # 💬 компактный header без лишних пустых строк
        await state.update_data(gram_replace_tries=1)  # 💬 в Теории не ретраим send, чтобы не плодить дубли
        kb = _kb_nav_in_phase(back_to_phases=back_to_phases)  # 💬 единая клавиатура навигации для фазы (fix NameError kb)



        # =========================
        # 📷 PHOTO (единый блок)  # 💬 показываем фото и опциональный caption, иначе fallback
        # =========================
        if t == "photo":
            file_id = item.get("photo") or ""  # 💬 file_id фото
            cap_user = (item.get("caption") or item.get("text") or "").strip()  # 💬 caption опционален (fallback на text)

            cap_full = header if not cap_user else (header + "\n\n" + _safe_html(cap_user))  # 💬 header всегда сверху

            if not file_id:
                # 💬 если по ошибке нет photo id = покажем хотя бы текст
                await _gram_edit_or_replace_text(chat_id, state, header + "\n\n⚠️ Фото не найдено в блоке.", kb)
                return

            try:
                await _gram_edit_or_replace_photo(chat_id, state, file_id, cap_full, kb)  # 💬 edit вместо удаления
                await state.update_data(gram_last_message_kind="photo")  # 💬 фиксируем тип
                return
            except Exception:

                # 💬 перестраховка = пробуем без caption (только header)
                try:
                    await _gram_edit_or_replace_photo(chat_id, state, file_id, header, kb)  # 💬 edit вместо удаления
                    await state.update_data(gram_last_message_kind="photo")  # 💬 фиксируем тип
                    return
                except Exception:

                    # 💬 последний fallback = текстом, чтобы не было "залипания" и двойного клика
                    fallback_txt = header + "\n\n⚠️ Фото не удалось показать."
                    if cap_user:
                        fallback_txt += "\n\n" + _safe_html(cap_user)
                    await _gram_edit_or_replace_text(chat_id, state, fallback_txt, kb)
                    return

        # =========================
        # 🔗 LINK / 🧾 TEXT  # 💬 всё текстовое = edit как в подкастах
        # =========================


        # 💬 дефолт = обычный текстовый блок (компакт + форматирование)
        body_raw = (item.get("text") or "").strip()
        hint = (item.get("hint") or "").strip()
        
        # 💬 чистим лишние пустые строки внутри body, чтобы не было "простыней"
        while "\n\n\n" in body_raw:
            body_raw = body_raw.replace("\n\n\n", "\n\n")
        
        text = header
        
        if body_raw:
            body_html = _safe_html(body_raw)

            # 💬 quote-оформление для теории (без дублей текста)
            body_pretty = f"<blockquote><b><i>{body_html}</i></b></blockquote>"

            text += "\n\n" + body_pretty

        
        if hint:
            text += "\n\n " + _safe_html(hint)  # 💬 hint не спойлерим
        
        await _gram_edit_or_replace_text(chat_id, state, text, kb)
        return



@router.poll_answer(StateFilter(GrammarStates.practice_poll))  # 💬 Теория без poll, оставляем poll только для Практики
async def gram_poll_answer_router(ans: PollAnswer, state: FSMContext):

    # 💬 общий обработчик PollQuiz: реакция + фидбек 1 сек = удаляем poll+фидбек = автопереход дальше
    st = await state.get_data()

    poll_key = str(ans.poll_id)  # 💬 приводим к строке для стабильного ключа
    ctx = _GRAM_POLL_CTX.get(poll_key) or _GRAM_POLL_CTX.get(ans.poll_id)  # 💬 поддерживаем старый ключ, если где то сохранился иначе

    poll_id = st.get("gram_poll_id")
    if not ctx and (not poll_id or str(poll_id) != poll_key):
        return  # 💬 не наш poll_answer

    section = str((ctx or {}).get("section") or st.get("gram_poll_section") or st.get("gram_section") or "")


    chat_id = int((ctx or {}).get("chat_id") or ans.user.id)

    # 💬 синхронизируем FSM из ctx, чтобы автопереход работал даже если ключ FSM у PollAnswer отличается (группы, разные chat_id)
    if ctx:
        upd: Dict[str, Any] = {
            "selected_topic": str(ctx.get("topic_key") or st.get("selected_topic") or ""),
        }
        upd.update(
            gram_section="practice",
            gram_item_idx=int(ctx.get("item_idx") or 0),
        )  # 💬 poll работает только в Практике

        await state.update_data(**upd)
        st = await state.get_data()

    try:
        correct = int((ctx or {}).get("correct") if ctx else (st.get("gram_poll_correct") or 0))
    except Exception:
        correct = 0

    opts = (ctx or {}).get("opts") if ctx else (st.get("gram_poll_options") or [])
    chosen = ans.option_ids[0] if ans.option_ids else -1
    poll_msg_id = (ctx or {}).get("poll_msg_id") if ctx else st.get("gram_poll_msg_id")

    is_correct = (chosen == correct)

    # 💬 закрываем poll чтобы не висел и ставим реакцию как в лексике
    if poll_msg_id:
        try:
            await _bot.stop_poll(chat_id=chat_id, message_id=int(poll_msg_id))
        except Exception:
            pass

        try:
            await _bot.set_message_reaction(
                chat_id=chat_id,
                message_id=int(poll_msg_id),
                reaction=[ReactionTypeEmoji(emoji="🎉" if is_correct else "😅")],
                is_big=True
            )
        except Exception:
            pass

    # 💬 фидбек как в лексике: похвала или правильный ответ
    if is_correct:
        txt = random.choice(grammar_quiz_success_phrases)
    else:
        right = opts[correct] if 0 <= correct < len(opts) else "не найден"
        txt = f"{random.choice(grammar_quiz_fail_phrases)}\n✅ {html.escape(str(right))}"

    fb = await _bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")

    await asyncio.sleep(1.0)  # 💬 даём увидеть фидбек

    _GRAM_POLL_CTX.pop(poll_key, None)  # 💬 чистим контекст poll
    _GRAM_POLL_CTX.pop(ans.poll_id, None)  # 💬 на всякий случай чистим не нормализованный ключ

    # 💬 удаляем фидбек и poll сообщение
    await _safe_delete_message(_bot, chat_id, fb.message_id)
    if poll_msg_id:
        await _safe_delete_message(_bot, chat_id, int(poll_msg_id))

    # 💬 идём дальше автоматически и чистим poll ключи чтобы не было повторов
    idx = int(st.get("gram_item_idx") or 0) + 1
    await state.update_data(
        gram_item_idx=idx,
        gram_poll_id=None,
        gram_poll_msg_id=None,
        gram_poll_correct=None,
        gram_poll_options=None,
        gram_poll_section=None,
    )

    topic = _get_topic(str(st.get("selected_topic")))

    await state.set_state(GrammarStates.practice_view)  # 💬 poll только практика
    await _show_practice_item(chat_id=chat_id, state=state, topic=topic)



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

    exercises = topic.get("exercises") or []
    link_items = [x for x in exercises if (x.get("url") or x.get("link"))]  # 💬 берём ссылки из exercises (как в админке)

    if not link_items:
        await cb.message.answer("Пока нет ссылок для Практики.", reply_markup=_kb_back_to_menu())
        return

    uid = str(cb.from_user.id)
    data = _user_progress_get(uid)
    u = data.setdefault(uid, {})
    gp = u.setdefault("grammar_progress", {})
    tp = gp.setdefault(str(topic_key), {})
    pr = tp.setdefault("practice", {})
    done = int(pr.get("done", 0))
    total = len(link_items)  # 💬 прогресс считаем по количеству ссылок
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
    chat_id = cb.message.chat.id  # 💬 единый chat_id для replace/delete
    await _safe_delete_message(_bot, chat_id, cb.message.message_id)  # 💬 удаляем экран "Практика + прогресс + Нажми Начать" вместе с кнопками

    st = await state.get_data()
    topic = _get_topic(str(st.get("selected_topic")))

    exercises = topic.get("exercises") or []
    link_items = [x for x in exercises if (x.get("url") or x.get("link"))]  # 💬 поддержка url/link

    if not link_items:
        await cb.message.answer("Пока нет ссылок для Практики.", reply_markup=_kb_back_to_menu())
        return

    await state.set_state(GrammarStates.practice_view)

    await state.update_data(
        gram_link_items=link_items,
        gram_link_idx=0,
        gram_links_done=0,
        gram_links_total=len(link_items),
        gram_return_to_practice=False,
        gram_return_practice_idx=None
    )

    await _replace_content(
        chat_id,
        state,
        lambda: _bot.send_message(
            chat_id=chat_id,
            text="🚀 Начинаем практику!\n⏳ Гружу ссылку...",
            parse_mode="HTML"
        )
    )  # 💬 не копим сообщения, работаем одним фрагментом

    await asyncio.sleep(0.8)
    return await _show_practice_link(chat_id, state)



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
        # 💬 PollQuiz в практике: отправляем quiz-полл и ждём PollAnswer
        q = str(item.get("question") or item.get("q") or "").strip()
        if not q:
            q = "Выбери правильный вариант"

        raw_opts = item.get("options") or item.get("answers") or []
        if not isinstance(raw_opts, list):
            raw_opts = []

        try:
            correct_raw = item.get("correct")
            if correct_raw is None:
                correct_raw = item.get("correct_option_id")
            correct = int(correct_raw) if correct_raw is not None else 0
        except Exception:
            correct = 0

        opts, correct = _normalize_quiz_options(raw_opts, correct)

        poll_question = f"🧪 Практика {idx + 1}/{total}\n{_bar(pct)}  {int(pct * 100)}%\n\n{q}"
        if len(poll_question) > 280:
            poll_question = poll_question[:277] + "..."

        poll_msg = await _replace_content(
            chat_id,
            state,
            lambda: _bot.send_poll(
                chat_id=chat_id,
                question=poll_question,
                options=opts,
                type="quiz",
                correct_option_id=int(correct),
                is_anonymous=False,
            ),
        )  # 💬 заменяем экран на poll, чтобы не копить сообщения

        if not poll_msg or not getattr(poll_msg, "poll", None):
            await _replace_content(
                chat_id,
                state,
                _bot.send_message(
                    chat_id=chat_id,
                    text=header + "⚠️ Не удалось отправить квиз.",
                    reply_markup=_kb_back_to_menu(),
                    parse_mode="HTML",
                ),
            )  # 💬 fallback на текст, чтобы не зависнуть
            return

        _GRAM_POLL_CTX[str(poll_msg.poll.id)] = {
            "chat_id": chat_id,
            "section": "practice",
            "topic_key": topic_key,
            "item_idx": idx,
            "poll_msg_id": poll_msg.message_id,
            "correct": correct,
            "opts": opts,
        }  # 💬 сохраняем контекст poll, чтобы PollAnswer не зависел от FSM-ключа

        await state.set_state(GrammarStates.practice_poll)  # 💬 ждём PollAnswer для практики
        await state.update_data(
            gram_poll_id=poll_msg.poll.id,
            gram_poll_msg_id=poll_msg.message_id,
            gram_poll_correct=correct,
            gram_poll_options=opts,
            gram_poll_section="practice",  # 💬 отмечаем, что это практика
            gram_section="practice",  # 💬 дублируем секцию, чтобы PollAnswer не залипал на пустом gram_poll_section
        )
        return



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


async def _show_practice_link(chat_id, state: FSMContext):
    # 💬 показываем текущую ссылку в практике
    data = await state.get_data()
    items = data.get("gram_link_items", [])
    idx = data.get("gram_link_idx", 0)
    done = data.get("gram_links_done", 0)
    total = data.get("gram_links_total", len(items))

    if idx >= len(items):
        # 💬 все ссылки закончились
        bar = f"[{done}/{total}] ✅"
        return await _replace_content(
            chat_id,
            state,
            _bot.send_message(
                chat_id=chat_id,
                text=f"Практика завершена!\n{bar}",
                reply_markup=_kb_practice_continue_menu(done, total),
                parse_mode="HTML"
            )
        )

    item = items[idx]
    title = item.get("title") or item.get("name") or "Упражнение"
    url = str(item.get("url") or item.get("link") or "").strip()  # 💬 поддержка url/link из JSON
    phrases = globals().get("link_cta_phrases") or []  # 💬 защита от NameError, если список не подключён
    cta = random.choice(phrases) if phrases else "Перейти"
    bar = f"[{done}/{total}]"

    rows = []
    if url and (url.startswith("http://") or url.startswith("https://")):
        rows.append([InlineKeyboardButton(text=cta, url=url)])  # 💬 кнопка-ссылка, только если URL валиден
        extra_line = ""
    else:
        rows.append([InlineKeyboardButton(text="⚠️ Ссылка не задана", callback_data="gram:practice:done")])  # 💬 не зависаем, даём перейти дальше
        extra_line = "\n\n⚠️ Ссылка не задана в упражнении."

    rows += [
        [InlineKeyboardButton(text="✅ Сделано", callback_data="gram:practice:done")],
        [InlineKeyboardButton(text="📚 Теория", callback_data="gram:practice:theory")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="gram:menu")],
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await _replace_content(
        chat_id,
        state,
        _bot.send_message(
            chat_id=chat_id,
            text=f"{bar}\n<b>{html.escape(title)}</b>{extra_line}",
            reply_markup=kb,
            parse_mode="HTML"
        )
    )

'''
@router.poll_answer()  # 💬 PollAnswer не всегда корректно матчится по FSM state, фильтруем по poll_id из state
async def gram_poll_answer_practice(ans: PollAnswer, state: FSMContext) -> None:
    # 💬 обработка PollQuiz в практике: фидбек 1 сек -> удаляем poll+фидбек -> автопереход
    st = await state.get_data()

    ctx = _GRAM_POLL_CTX.get(ans.poll_id)  # 💬 запасной путь, если FSM ключ для PollAnswer не совпал
    if ctx and str(ctx.get("section")) != "practice":
        return  # 💬 это poll из другой ветки

    poll_id = st.get("gram_poll_id")
    if (not poll_id or poll_id != ans.poll_id) and not ctx:
        return  # 💬 чужой poll_answer или уже сброшен

    chat_id = int((ctx or {}).get("chat_id") or ans.user.id)

    if ctx:
        await state.update_data(
            selected_topic=str(ctx.get("topic_key") or st.get("selected_topic") or ""),
            gram_item_idx=int(ctx.get("item_idx") or 0),
        )  # 💬 синхронизируем FSM, чтобы автопереход работал стабильно
        st = await state.get_data()

    try:
        correct = int((ctx or {}).get("correct") if ctx else (st.get("gram_poll_correct") or 0))
    except Exception:
        correct = 0

    opts = (ctx or {}).get("opts") if ctx else (st.get("gram_poll_options") or [])
    chosen = ans.option_ids[0] if ans.option_ids else -1
    poll_msg_id = (ctx or {}).get("poll_msg_id") if ctx else st.get("gram_poll_msg_id")


    is_correct = (chosen == correct)

    # 💬 закрываем poll (без таймаута), чтобы не висел
    if poll_msg_id:
        try:
            await _bot.stop_poll(chat_id=chat_id, message_id=int(poll_msg_id))
        except Exception:
            pass

    # 💬 реакция как в лексике
    if is_correct:
        txt = random.choice(grammar_quiz_success_phrases)
    else:
        right = opts[correct] if 0 <= correct < len(opts) else "не найден"
        txt = f"{random.choice(grammar_quiz_fail_phrases)}\n✅ {html.escape(str(right))}"

    fb = await _bot.send_message(chat_id=chat_id, text=txt, parse_mode="HTML")

    await asyncio.sleep(1.0)  # 💬 даём увидеть фидбек
    _GRAM_POLL_CTX.pop(ans.poll_id, None)  # 💬 чистим контекст, чтобы не копился

    # 💬 удаляем фидбек и poll-сообщение
    await _safe_delete_message(_bot, chat_id, fb.message_id)
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

'''

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

    # 💬 session progress видео (FSM only)
    st_now = await state.get_data()
    sp = _sess_progress_from_state(st_now)
    vd = sp.setdefault("video", {})
    raw_done = vd.get("done_idx")
    try:
        done_idx = int(raw_done) if raw_done is not None else -1
    except Exception:
        done_idx = -1

    if idx > done_idx:
        done_idx = idx
        vd["done_idx"] = done_idx  # 💬 фиксируем просмотр видео в рамках сессии
        await state.update_data(gram_session_progress=sp)

    done = (min(done_idx + 1, total) if (total and done_idx >= 0) else 0)
    pct = (done / total) if total else 0.0


    done = (min(done_idx + 1, total) if (total and done_idx >= 0) else 0)  # 💬 индекс -> количество
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
    packs = _read_packs(topic)

    # 💬 считаем прогресс Читать по фазам, чтобы зачёркивать при 100%
    sp = _sess_progress_from_state(st)
    rd = (sp.get("read") or {}) if isinstance(sp.get("read"), dict) else {}
    phase_pcts: List[float] = []
    for i, p in enumerate(packs or []):
        fr = _read_fragments_from_pack(topic, i)
        fr = [x for x in (fr or []) if _item_type(x) != "photo"]  # 💬 Читать = только текст
        total = len(fr)
        ph = rd.get(str(i)) or {}
        seen = ph.get("seen") or []
        if not isinstance(seen, list):
            seen = []
        uniq_valid = set()
        for x in seen:
            try:
                xi = int(x)
            except Exception:
                continue
            if 0 <= xi < total:
                uniq_valid.add(xi)
        pct = (len(uniq_valid) / total) if total else 0.0
        phase_pcts.append(pct)


    if not packs:
        await cb.message.answer("Пока нет фаз для Читать.", reply_markup=_kb_back_to_menu())
        return  # 💬 защита от пустого чтения

    await state.set_state(GrammarStates.read_intro)
    await state.update_data(
        gram_section="read_intro",
        gram_read_pack_idx=None,  # 💬 пока фаза не выбрана
        gram_item_idx=0,
    )

    await _replace_content(
        chat_id=cb.from_user.id,
        state=state,
        send_coro=cb.message.answer(
            "📚 Выбери фазу Читать:",
            reply_markup=_kb_read_packs(packs, phase_pcts=phase_pcts),  # 💬 зачёркиваем фазы при 100%

        ),
    )  # 💬 список фаз в одном сообщении

@router.callback_query(F.data.startswith("gram:read_pack:"))
async def gram_read_pack_open(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()

    st = await state.get_data()
    topic_key = st.get("selected_topic")
    if not topic_key:
        await cb.message.answer("⚠️ Не вижу тему.")
        return  # 💬 защита от пустого контекста

    try:
        pack_idx = int(cb.data.split(":", 2)[2])
    except Exception:
        await cb.answer("⚠️ Не понял фазу", show_alert=False)
        return  # 💬 защита от мусорного callback

    topic = _get_topic(str(topic_key))
    packs = _read_packs(topic)
    if pack_idx < 0 or pack_idx >= len(packs):
        await cb.answer("Фаза не найдена", show_alert=False)
        return  # 💬 защита от выхода за пределы

    await state.set_state(GrammarStates.read_view)
    await state.update_data(
        gram_section="read",
        gram_read_pack_idx=pack_idx,  # 💬 фиксируем выбранную фазу
        gram_item_idx=0,
    )

    await _show_read(
        chat_id=cb.from_user.id,
        state=state,
        topic=topic,
        message=cb.message,
    )  # 💬 показываем первый фрагмент через edit_text как в подкастах


def _format_read_fragment(f: Any) -> str:
    # 💬 стиль как в подкастах: ES видно, RU спрятано, hint видно
    if isinstance(f, str):
        ru_txt = html.escape((f or "").strip())
        return (f"<i>🔹 <tg-spoiler>{ru_txt}</tg-spoiler></i>").strip() or "Пустой фрагмент"

    if not isinstance(f, dict):
        return "Пустой фрагмент"  # 💬 защита от мусора

    es_txt = html.escape(str(f.get("es") or "").strip())
    ru_txt = html.escape(str(f.get("ru") or "").strip())
    hint_txt = html.escape(str(f.get("hint") or "").strip())

    lines: List[str] = []
    if es_txt:
        lines.append(f"<b>🇪🇸 {es_txt}</b>")
    if ru_txt:
        lines.append(f"<i>🔹 <tg-spoiler>{ru_txt}</tg-spoiler></i>")
    if hint_txt:
        lines.append(f"<b><i>💡 {hint_txt}</i></b>")

    return "\n".join(lines).strip() or "Пустой фрагмент"


async def _show_read(chat_id: int, state: FSMContext, topic: Dict[str, Any], message: Optional[Message] = None) -> None:
    st = await state.get_data()

    pack_idx = int(st.get("gram_read_pack_idx") or 0)
    frags = _read_fragments_from_pack(topic, pack_idx)
    frags = [x for x in (frags or []) if _item_type(x) != "photo"]  # 💬 в Читать используем только текст

    if not frags:
        text = "Пока нет фрагментов для Читать."
        if message:
            try:
                await message.edit_text(text, reply_markup=_kb_back_to_menu())
            except Exception:
                await message.answer(text, reply_markup=_kb_back_to_menu())
        else:
            await _replace_content(chat_id, state, _bot.send_message(chat_id, text, reply_markup=_kb_back_to_menu()))
        return

    idx = int(st.get("gram_item_idx") or 0)
    idx = max(0, min(len(frags) - 1, idx))  # 💬 как в подкастах, не выходим за пределы
    await state.update_data(gram_item_idx=idx)
    await _mark_seen_session(state, "read", pack_idx, idx, len(frags))  # 💬 прогресс Читать по фазам в session для меню


    frag = frags[idx]
    text = _format_read_fragment(frag)

    try:
        if message:
            await message.edit_text(
                text,
                reply_markup=_kb_read_controls(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            await _replace_content(
                chat_id,
                state,
                _bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=_kb_read_controls(),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                ),
            )
    except Exception:
        await _replace_content(
            chat_id,
            state,
            _bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=_kb_read_controls(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            ),
        )  # 💬 fallback, если edit_text невозможен



@router.callback_query(F.data.in_(["gram:read:prev", "gram:read:next"]))
async def gram_read_nav(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    st = await state.get_data()
    if st.get("gram_section") != "read":
        return

    topic = _get_topic(str(st.get("selected_topic")))
    pack_idx = int(st.get("gram_read_pack_idx") or 0)

    frags = _read_fragments_from_pack(topic, pack_idx)
    frags = [x for x in (frags or []) if _item_type(x) != "photo"]  # 💬 в Читать только текст
    if not frags:
        return  # 💬 нечего листать

    idx = int(st.get("gram_item_idx") or 0)  # 💬 текущий индекс фрагмента


    if cb.data.endswith("prev"):
        if idx <= 0:
            await cb.answer("Это начало", show_alert=False)  # 💬 не уходим за пределы
            return
        idx -= 1
    else:
        if idx >= len(frags) - 1:
            await cb.answer("Это конец", show_alert=False)  # 💬 не уходим за пределы
            return
        idx += 1

    await state.update_data(gram_item_idx=idx)
    await _show_read(chat_id=cb.from_user.id, state=state, topic=topic, message=cb.message)  # 💬 остаёмся в этом же экране

