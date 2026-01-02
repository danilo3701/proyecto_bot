# podcasts_feature.py
# 💬 модуль "Подкасты" (авторы -> эпизоды -> фрагменты) + админка /podcasts_admin

from __future__ import annotations

import json
import os
import re
import time
import html
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from aiogram import Router, F
from aiogram.filters import Command
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
)

router = Router()

# -----------------------------
# 🔧 DI (проброс из core8_1.py)
# -----------------------------
_load_user_data: Optional[Callable[[], Dict[str, Any]]] = None
_save_user_data: Optional[Callable[[Dict[str, Any]], None]] = None
_load_subscription_channels: Optional[Callable[[], List[Dict[str, Any]]]] = None
_LessonStates = None
_ADMIN_CHAT_ID: Optional[int] = None
_bot = None

DATA_DIR = Path("/data")
PODCASTS_FILE = DATA_DIR / "podcasts_data.json"


def init_podcasts_feature(
    *,
    load_user_data: Callable[[], Dict[str, Any]],
    save_user_data: Callable[[Dict[str, Any]], None],
    load_subscription_channels: Callable[[], List[Dict[str, Any]]],
    LessonStates,
    admin_chat_id: int,
    bot,
) -> None:
    """
    💬 пробрасываем зависимости из core8_1.py
    """
    global _load_user_data, _save_user_data, _load_subscription_channels, _LessonStates, _ADMIN_CHAT_ID, _bot
    _load_user_data = load_user_data
    _save_user_data = save_user_data
    _load_subscription_channels = load_subscription_channels
    _LessonStates = LessonStates
    try:
        _ADMIN_CHAT_ID = int(admin_chat_id)  # 💬 приводим к int, чтобы админка не молчала/не падала
    except Exception:
        _ADMIN_CHAT_ID = None  # 💬 если не настроено, покажем понятное сообщение в /podcasts_admin

    _bot = bot

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    _ensure_podcasts_file()


# -----------------------------
# 🧠 FSM для админки
# -----------------------------
class PodcastAdminStates(StatesGroup):
    choosing_action = State()

    waiting_author_name = State()

    choosing_author_for_episode = State()
    waiting_episode_title = State()
    waiting_episode_desc = State()
    waiting_episode_audio = State()

    choosing_episode_for_fragments = State()
    waiting_fragments_text = State()

    choosing_episode_for_delete = State()


# -----------------------------
# 🗂️ Storage
# -----------------------------
def _ensure_podcasts_file() -> None:
    if not PODCASTS_FILE.exists():
        _atomic_write_json(PODCASTS_FILE, {"authors": {}, "episodes": {}})


def _read_podcasts() -> Dict[str, Any]:
    _ensure_podcasts_file()
    try:
        with PODCASTS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"authors": {}, "episodes": {}}


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _write_podcasts(data: Dict[str, Any]) -> None:
    _atomic_write_json(PODCASTS_FILE, data)


def _new_id(prefix: str) -> str:
    # 💬 короткий id под callback_data
    return f"{prefix}{int(time.time()*1000)}"


# -----------------------------
# ✅ Subscription check (только 1 канал = первый из Subscription Channels)
# -----------------------------
def _extract_channel_ref(ch: Dict[str, Any]) -> Optional[str]:
    # 💬 пытаемся достать chat_id/username/url
    if not ch:
        return None
    if ch.get("chat_id"):
        return str(ch["chat_id"])
    if ch.get("username"):
        u = str(ch["username"]).lstrip("@")
        return f"@{u}"
    url = ch.get("url") or ch.get("link")
    if url and "t.me/" in str(url):
        tail = str(url).split("t.me/")[-1].strip("/")
        if tail:
            return f"@{tail}"
    return None


async def _is_subscribed_main_channel(user_id: int) -> bool:
    # 💬 проверяем членство через Telegram API
    if _bot is None or _load_subscription_channels is None:
        return True  # 💬 если не пробросили зависимости = не блокируем

    channels = []
    try:
        channels = _load_subscription_channels() or []
    except Exception:
        channels = []

    if not channels:
        return True

    main_ref = _extract_channel_ref(channels[0])
    if not main_ref:
        return True

    try:
        member = await _bot.get_chat_member(main_ref, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def _main_channel_url() -> str:
    # 💬 ссылка для кнопки "подписаться"
    try:
        ch = (_load_subscription_channels() or [None])[0]
        if not ch:
            return "https://t.me/espanolingooo"
        return ch.get("url") or ch.get("link") or "https://t.me/espanolingooo"
    except Exception:
        return "https://t.me/espanolingooo"


def _kb_subscribe_check() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подписаться", url=_main_channel_url())],
            [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="pod:checksub")],
        ]
    )


# -----------------------------
# 🎛️ UI builders
# -----------------------------
def _kb_authors(data: Dict[str, Any]) -> InlineKeyboardMarkup:
    authors = data.get("authors", {})
    items = sorted(authors.items(), key=lambda x: (x[1].get("order", 9999), x[1].get("name", "")))

    rows = []
    for aid, a in items:
        rows.append([InlineKeyboardButton(text=f"🎙 {a.get('name','Автор')}", callback_data=f"pod:author:{aid}")])

    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="(пусто)", callback_data="pod:noop")]])


def _kb_episodes(data: Dict[str, Any], author_id: str) -> InlineKeyboardMarkup:
    eps = data.get("episodes", {})
    items = [(eid, e) for eid, e in eps.items() if e.get("author_id") == author_id]
    items.sort(key=lambda x: x[1].get("order", 9999))

    rows = []
    for eid, e in items:
        rows.append([InlineKeyboardButton(text=e.get("title", "🎧 Эпизод"), callback_data=f"pod:ep:{eid}")])

    rows.append([InlineKeyboardButton(text="⬅️ К авторам", callback_data="pod:authors")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_fragment_controls() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️", callback_data="pod:prev"),
                InlineKeyboardButton(text="⭐", callback_data="pod:star"),
                InlineKeyboardButton(text="▶️", callback_data="pod:next"),
            ]
        ]
    )


def _kb_episode_back() -> ReplyKeyboardMarkup:
    # 💬 "назад" только в reply keyboard (как ты хотел)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ К эпизодам"), KeyboardButton(text="🏠 К авторам")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=True,
    )


def _format_fragment(es: str, ru: str, hint: str = "") -> str:
    es_txt = html.escape(es.strip())
    ru_txt = html.escape(ru.strip())
    hint_txt = html.escape(hint.strip())

    lines = [
        f"🇪🇸 {es_txt}",
        f"🇷🇺 <tg-spoiler>{ru_txt}</tg-spoiler>",
    ]
    if hint_txt:
        lines.append(f"💡 {hint_txt}")
    return "\n".join(lines)


# -----------------------------
# 👤 USER FLOW
# -----------------------------
async def podcasts_open(message: Message, state: FSMContext) -> None:
    # 💬 точка входа из core8_1.py (menu:podcasts)
    ok = await _is_subscribed_main_channel(message.from_user.id)
    if not ok:
        await message.answer(
            "🔒 Подкасты доступны после подписки на канал.\n\nНажми кнопку ниже и потом = проверить подписку.",
            reply_markup=_kb_subscribe_check(),
        )
        return

    data = _read_podcasts()
    await state.update_data(pod_ctx=True, pod_author_id=None, pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None)
    await message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))


@router.callback_query(F.data == "pod:checksub")
async def pod_checksub(cb: CallbackQuery, state: FSMContext) -> None:
    ok = await _is_subscribed_main_channel(cb.from_user.id)
    if not ok:
        await cb.answer("Ещё не вижу подписку. Попробуй ещё раз.", show_alert=True)
        return

    await cb.answer("✅ Подписка ок", show_alert=False)
    data = _read_podcasts()
    await state.update_data(pod_ctx=True, pod_author_id=None, pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None)
    await cb.message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))


@router.callback_query(F.data == "pod:authors")
async def pod_back_authors(cb: CallbackQuery, state: FSMContext) -> None:
    data = _read_podcasts()
    await state.update_data(pod_author_id=None, pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None)
    await cb.message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
    await cb.answer()


@router.callback_query(F.data.startswith("pod:author:"))
async def pod_author(cb: CallbackQuery, state: FSMContext) -> None:
    author_id = cb.data.split(":")[-1]
    data = _read_podcasts()
    author = data.get("authors", {}).get(author_id)

    if not author:
        await cb.answer("Автор не найден", show_alert=True)
        return

    await state.update_data(pod_author_id=author_id, pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None)
    await cb.message.answer(f"🎙 {author.get('name','Автор')}\n\nВыбери эпизод:", reply_markup=_kb_episodes(data, author_id))
    await cb.answer()


@router.callback_query(F.data.startswith("pod:ep:"))
async def pod_episode_open(cb: CallbackQuery, state: FSMContext) -> None:
    ep_id = cb.data.split(":")[-1]
    data = _read_podcasts()
    ep = data.get("episodes", {}).get(ep_id)

    if not ep:
        await cb.answer("Эпизод не найден", show_alert=True)
        return

    desc = (ep.get("description") or "").strip()
    if desc and desc != "-":
        await cb.answer(desc[:190], show_alert=True)
    else:
        await cb.answer()

    # 💬 отправляем аудио отдельным сообщением
    audio_file_id = ep.get("audio_file_id")
    audio_type = ep.get("audio_type", "audio")

    if audio_file_id:
        try:
            if audio_type == "voice":
                await cb.message.answer_voice(audio_file_id)
            else:
                await cb.message.answer_audio(audio_file_id)
        except Exception:
            await cb.message.answer("⚠️ Не смог отправить аудио (file_id). Проверь, что эпизод добавлен правильно.")

    frags = ep.get("fragments", []) or []
    if not frags:
        await cb.message.answer("Пока нет фрагментов для этого эпизода.")
        await state.update_data(pod_ep_id=ep_id, pod_idx=0, pod_frag_msg_id=None)
        return

    idx = 0
    frag = frags[idx]
    text = _format_fragment(frag.get("es", ""), frag.get("ru", ""), frag.get("hint", ""))

    msg = await cb.message.answer(
        text,
        reply_markup=_kb_fragment_controls(),
    )
    await cb.message.answer("Навигация = кнопками ниже.\nНазад = кнопками внизу.", reply_markup=_kb_episode_back())

    await state.update_data(pod_ep_id=ep_id, pod_idx=idx, pod_frag_msg_id=msg.message_id)


@router.callback_query(F.data.in_(["pod:prev", "pod:next", "pod:star"]))
async def pod_fragment_controls(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    if not st.get("pod_ctx"):
        await cb.answer()
        return

    ep_id = st.get("pod_ep_id")
    if not ep_id:
        await cb.answer()
        return

    data = _read_podcasts()
    ep = data.get("episodes", {}).get(ep_id)
    if not ep:
        await cb.answer("Эпизод не найден", show_alert=True)
        return

    frags = ep.get("fragments", []) or []
    if not frags:
        await cb.answer()
        return

    idx = int(st.get("pod_idx") or 0)

    if cb.data == "pod:star":
        # 💬 сохраняем текущий фрагмент в user_data (RailwayData)
        if _load_user_data and _save_user_data:
            ud = _load_user_data()
            uid = str(cb.from_user.id)
            ud.setdefault(uid, {})
            ud[uid].setdefault("podcasts_favorites", [])
            frag = frags[idx]
            ud[uid]["podcasts_favorites"].append(
                {
                    "ts": int(time.time()),
                    "episode_id": ep_id,
                    "index": idx,
                    "es": frag.get("es", ""),
                    "ru": frag.get("ru", ""),
                    "hint": frag.get("hint", ""),
                }
            )
            _save_user_data(ud)
        await cb.answer("Сохранено ⭐", show_alert=False)
        return

    if cb.data == "pod:prev":
        idx = max(0, idx - 1)
    elif cb.data == "pod:next":
        idx = min(len(frags) - 1, idx + 1)

    frag = frags[idx]
    text = _format_fragment(frag.get("es", ""), frag.get("ru", ""), frag.get("hint", ""))

    try:
        await cb.message.edit_text(text, reply_markup=_kb_fragment_controls())
        await state.update_data(pod_idx=idx)
        await cb.answer()
    except Exception:
        await cb.answer("Не смог обновить экран", show_alert=False)


@router.message(F.text.in_(["⬅️ К эпизодам", "🏠 К авторам"]))
async def pod_reply_nav(message: Message, state: FSMContext) -> None:
    st = await state.get_data()
    if not st.get("pod_ctx"):
        return

    data = _read_podcasts()

    if message.text == "🏠 К авторам":
        await state.update_data(pod_author_id=None, pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None)
        await message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await message.answer(" ", reply_markup=ReplyKeyboardRemove())
        return

    # ⬅️ К эпизодам
    author_id = st.get("pod_author_id")
    if not author_id:
        await message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await message.answer(" ", reply_markup=ReplyKeyboardRemove())
        return

    await state.update_data(pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None)
    await message.answer("Выбери эпизод:", reply_markup=_kb_episodes(data, author_id))
    await message.answer(" ", reply_markup=ReplyKeyboardRemove())


# -----------------------------
# 👑 ADMIN FLOW
# -----------------------------
def _admin_only(message_or_cb) -> bool:
    if _ADMIN_CHAT_ID is None:
        return False
    return int(message_or_cb.from_user.id) == int(_ADMIN_CHAT_ID)


def _kb_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить автора", callback_data="podadm:add_author")],
            [InlineKeyboardButton(text="➕ Добавить эпизод", callback_data="podadm:add_episode")],
            [InlineKeyboardButton(text="➕ Добавить фрагменты", callback_data="podadm:add_frags")],
            [InlineKeyboardButton(text="🗑 Удалить эпизод", callback_data="podadm:del_ep")],
            [InlineKeyboardButton(text="📋 Список", callback_data="podadm:list")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="podadm:close")],
        ]
    )


def _kb_admin_authors_pick(data: Dict[str, Any], cb_prefix: str) -> InlineKeyboardMarkup:
    authors = data.get("authors", {})
    items = sorted(authors.items(), key=lambda x: (x[1].get("order", 9999), x[1].get("name", "")))
    rows = []
    for aid, a in items:
        rows.append([InlineKeyboardButton(text=f"🎙 {a.get('name','Автор')}", callback_data=f"{cb_prefix}:{aid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_admin_eps_pick(data: Dict[str, Any], cb_prefix: str) -> InlineKeyboardMarkup:
    eps = data.get("episodes", {})
    items = list(eps.items())
    items.sort(key=lambda x: x[1].get("order", 9999))
    rows = []
    for eid, e in items:
        rows.append([InlineKeyboardButton(text=e.get("title", "🎧 Эпизод"), callback_data=f"{cb_prefix}:{eid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(Command(commands=["podcasts_admin", "podcast_admin", "pod_admin"]))
async def podcasts_admin_cmd(message: Message, state: FSMContext) -> None:
    # 💬 секретная команда без проверки админа
    await state.clear()
    await state.set_state(PodcastAdminStates.choosing_action)
    await message.answer("👑 Админка подкастов:", reply_markup=_kb_admin_menu())


@router.message(F.text.lower().in_(["подкаст админ", "подкасты админ"]))
async def podcasts_admin_text_alias(message: Message, state: FSMContext) -> None:
    await podcasts_admin_cmd(message, state)  # 💬 алиас на админ-команду без слэша


@router.callback_query(F.data.startswith("podadm:"))
async def podcasts_admin_cb(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 секретная админка без проверки админа
    # 💬 если человек сюда попал = значит он ввёл секретную команду
    pass



    action = cb.data.split(":", 1)[1]

    if action == "close":
        await state.clear()
        await cb.message.answer("Ок.", reply_markup=ReplyKeyboardRemove())
        await cb.answer()
        return

    if action == "back":
        await state.clear()
        await state.set_state(PodcastAdminStates.choosing_action)
        await cb.message.answer("👑 Админка подкастов:", reply_markup=_kb_admin_menu())
        await cb.answer()
        return

    if action == "list":
        data = _read_podcasts()
        authors = data.get("authors", {})
        eps = data.get("episodes", {})
        txt = f"📋 Подкасты\n\nАвторы: {len(authors)}\nЭпизоды: {len(eps)}"
        await cb.message.answer(txt)
        await cb.answer()
        return

    if action == "add_author":
        await state.set_state(PodcastAdminStates.waiting_author_name)
        await cb.message.answer("Введи имя автора одним сообщением:")
        await cb.answer()
        return

    if action == "add_episode":
        data = _read_podcasts()
        await state.set_state(PodcastAdminStates.choosing_author_for_episode)
        await cb.message.answer("Выбери автора для эпизода:", reply_markup=_kb_admin_authors_pick(data, "podadm:pick_author"))
        await cb.answer()
        return

    if action == "add_frags":
        data = _read_podcasts()
        await state.set_state(PodcastAdminStates.choosing_episode_for_fragments)
        await cb.message.answer("Выбери эпизод, куда добавить фрагменты:", reply_markup=_kb_admin_eps_pick(data, "podadm:pick_ep_frags"))
        await cb.answer()
        return

    if action == "del_ep":
        data = _read_podcasts()
        await state.set_state(PodcastAdminStates.choosing_episode_for_delete)
        await cb.message.answer("Выбери эпизод для удаления:", reply_markup=_kb_admin_eps_pick(data, "podadm:pick_ep_del"))
        await cb.answer()
        return

    await cb.answer()


@router.callback_query(F.data.startswith("podadm:pick_author:"))
async def admin_pick_author(cb: CallbackQuery, state: FSMContext) -> None:

    author_id = cb.data.split(":")[-1]
    await state.update_data(adm_author_id=author_id)
    await state.set_state(PodcastAdminStates.waiting_episode_title)
    await cb.message.answer("Теперь пришли название эпизода (одной строкой).")
    await cb.answer()


@router.message(PodcastAdminStates.waiting_author_name)
async def admin_add_author_name(message: Message, state: FSMContext) -> None:

    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя пустое. Попробуй ещё раз.")
        return

    data = _read_podcasts()
    authors = data.setdefault("authors", {})

    aid = _new_id("a")
    order = len(authors) + 1
    authors[aid] = {"name": name, "order": order}

    _write_podcasts(data)

    await state.clear()
    await message.answer(f"✅ Автор добавлен\nid = {aid}\nИмя = {name}\n\n/podcasts_admin")
    

@router.message(PodcastAdminStates.waiting_episode_title)
async def admin_episode_title(message: Message, state: FSMContext) -> None:

    title = (message.text or "").strip()
    if not title:
        await message.answer("Название пустое. Пришли ещё раз.")
        return

    await state.update_data(adm_episode_title=title)
    await state.set_state(PodcastAdminStates.waiting_episode_desc)
    await message.answer("Теперь пришли описание (или просто -).")


@router.message(PodcastAdminStates.waiting_episode_desc)
async def admin_episode_desc(message: Message, state: FSMContext) -> None:

    desc = (message.text or "").strip()
    if not desc:
        desc = "-"

    await state.update_data(adm_episode_desc=desc)
    await state.set_state(PodcastAdminStates.waiting_episode_audio)
    await message.answer("Теперь пришли аудио (Audio или Voice) одним сообщением.")


@router.message(PodcastAdminStates.waiting_episode_audio)
async def admin_episode_audio(message: Message, state: FSMContext) -> None:


    audio_file_id = None
    audio_type = "audio"

    if message.voice:
        audio_file_id = message.voice.file_id
        audio_type = "voice"
    elif message.audio:
        audio_file_id = message.audio.file_id
        audio_type = "audio"

    if not audio_file_id:
        await message.answer("Я не вижу Audio/Voice. Пришли именно аудио файлом или голосовым.")
        return

    st = await state.get_data()
    author_id = st.get("adm_author_id")
    title = st.get("adm_episode_title")
    desc = st.get("adm_episode_desc")

    if not author_id or not title:
        await message.answer("Ошибка состояния. Зайди заново: /podcasts_admin")
        await state.clear()
        return

    data = _read_podcasts()
    eps = data.setdefault("episodes", {})

    eid = _new_id("e")
    order = len(eps) + 1
    eps[eid] = {
        "author_id": author_id,
        "title": title,
        "description": desc,
        "audio_file_id": audio_file_id,
        "audio_type": audio_type,
        "order": order,
        "fragments": [],
        "created_at": int(time.time()),
    }

    _write_podcasts(data)

    await state.clear()
    await message.answer(f"✅ Эпизод создан\nid = {eid}\n\nТеперь можешь добавить фрагменты: /podcasts_admin")


@router.callback_query(F.data.startswith("podadm:pick_ep_frags:"))
async def admin_pick_ep_frags(cb: CallbackQuery, state: FSMContext) -> None:

    eid = cb.data.split(":")[-1]
    await state.update_data(adm_frag_eid=eid)
    await state.set_state(PodcastAdminStates.waiting_fragments_text)
    await cb.message.answer(
        "Вставь фрагменты одним сообщением.\n\n"
        "Формат каждого фрагмента:\n"
        "1) 🇪🇸 ...\n"
        "2) 🇷🇺 ...\n"
        "3) 💡 ... (опционально)\n\n"
        "Между фрагментами = пустая строка."
    )
    await cb.answer()


def _strip_prefix(line: str) -> str:
    return re.sub(r"^(🇪🇸|🇷🇺|💡)\s*", "", line.strip())


def _strip_spoilers_ru(line: str) -> str:
    # 💬 убираем ||...|| или <tg-spoiler>...</tg-spoiler>
    s = line.strip()
    s = re.sub(r"^\|\|", "", s)
    s = re.sub(r"\|\|$", "", s)
    s = re.sub(r"^<tg-spoiler>", "", s)
    s = re.sub(r"</tg-spoiler>$", "", s)
    return s.strip()


def _parse_fragments(text: str) -> List[Dict[str, str]]:
    raw = (text or "").strip()
    if not raw:
        return []

    blocks = re.split(r"\n\s*\n", raw)
    out = []
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        es = _strip_prefix(lines[0])
        ru = _strip_spoilers_ru(_strip_prefix(lines[1]))
        hint = ""
        if len(lines) >= 3:
            hint = _strip_prefix(lines[2])
        out.append({"es": es, "ru": ru, "hint": hint})
    return out


@router.message(PodcastAdminStates.waiting_fragments_text)
async def admin_add_fragments(message: Message, state: FSMContext) -> None:

    st = await state.get_data()
    eid = st.get("adm_frag_eid")
    if not eid:
        await message.answer("Ошибка состояния. /podcasts_admin")
        await state.clear()
        return

    frags = _parse_fragments(message.text or "")
    if not frags:
        await message.answer("Не смог распарсить. Проверь формат и пришли ещё раз.")
        return

    data = _read_podcasts()
    ep = data.get("episodes", {}).get(eid)
    if not ep:
        await message.answer("Эпизод не найден. /podcasts_admin")
        await state.clear()
        return

    ep.setdefault("fragments", [])
    ep["fragments"].extend(frags)
    _write_podcasts(data)

    await state.clear()
    await message.answer(f"✅ Добавлено фрагментов: {len(frags)}\nВсего теперь: {len(ep['fragments'])}\n\n/podcasts_admin")


@router.callback_query(F.data.startswith("podadm:pick_ep_del:"))
async def admin_pick_ep_del(cb: CallbackQuery, state: FSMContext) -> None:

    eid = cb.data.split(":")[-1]
    data = _read_podcasts()
    eps = data.get("episodes", {})
    if eid in eps:
        del eps[eid]
        _write_podcasts(data)
        await cb.message.answer("✅ Удалено.")
    else:
        await cb.message.answer("Эпизод не найден.")
    await state.clear()
    await cb.answer()


@router.callback_query(F.data == "pod:noop")
async def pod_noop(cb: CallbackQuery) -> None:
    await cb.answer()
