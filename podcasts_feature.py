# podcasts_feature.py
# 💬 модуль "Подкасты" (авторы -> эпизоды -> фрагменты) + админка /podcasts_admin

from __future__ import annotations
import asyncio  # 💬 нужен таймер для авто-удаления подсказки

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
from aiogram.exceptions import TelegramBadRequest  # 💬 чтобы не падать, если сообщение уже удалено


router = Router()

async def _safe_delete_message(bot, chat_id: int, message_id: int) -> None:
    # 💬 безопасно удаляем сообщение (без падений, если уже удалено/нельзя удалить)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _autodelete_message(bot, chat_id: int, message_id: int, delay: int = 7) -> None:
    # 💬 удаляем сообщение через delay секунд, чтобы не засорять чат
    await asyncio.sleep(delay)
    await _safe_delete_message(bot, chat_id, message_id)


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
PODCAST_NOTES_DIR = DATA_DIR / "podcast_notes"  # 💬 заметки подкастов по пользователю (отдельные файлы)



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
    _ensure_podcast_notes_dir()  # 💬 гарантируем папку для заметок подкастов



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
    choosing_episode_for_edit_fragments = State()  # 💬 выбор эпизода для очистки/перезаписи фрагментов

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

def _ensure_podcast_notes_dir() -> None:
    # 💬 создаём /data/podcast_notes для отдельных файлов заметок
    try:
        PODCAST_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _podcast_notes_file(uid: str) -> Path:
    # 💬 файл заметок конкретного пользователя
    _ensure_podcast_notes_dir()
    return PODCAST_NOTES_DIR / f"{uid}.json"


def _ensure_podcast_notes_file(uid: str) -> None:
    # 💬 если файла нет = создаём пустой
    path = _podcast_notes_file(uid)
    if not path.exists():
        _atomic_write_json(path, {"notes": []})


def _read_podcast_notes(uid: str) -> List[Dict[str, Any]]:
    # 💬 читаем заметки пользователя (самые свежие = в начале списка)
    _ensure_podcast_notes_file(uid)
    try:
        with _podcast_notes_file(uid).open("r", encoding="utf-8") as f:
            data = json.load(f) or {}
        notes = data.get("notes", [])
        return notes if isinstance(notes, list) else []
    except Exception:
        return []


def _write_podcast_notes(uid: str, notes: List[Dict[str, Any]]) -> None:
    # 💬 атомарно сохраняем заметки пользователя
    _atomic_write_json(_podcast_notes_file(uid), {"notes": notes})



def _new_id(prefix: str) -> str:
    # 💬 короткий id под callback_data
    return f"{prefix}{int(time.time()*1000)}"


# -----------------------------
# ✅ Subscription check (только 1 канал = первый из Subscription Channels)
# -----------------------------
def _extract_channel_ref(ch: Any) -> Optional[str]:
    # 💬 достаём chat_ref из dict или str (username/url/chat_id)
    if not ch:
        return None

    # 💬 если в channels лежит строка
    if isinstance(ch, str):
        s = ch.strip()
        if not s:
            return None
        # chat_id строкой
        if s.lstrip("-").isdigit():
            return s
        # url t.me/...
        if "t.me/" in s:
            tail = s.split("t.me/")[-1].strip("/").strip()
            if tail:
                return f"@{tail.lstrip('@')}"
        # username
        if s.startswith("@"):
            return s
        return f"@{s}"

    # 💬 если в channels лежит dict
    if isinstance(ch, dict):
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

    return None


async def _is_subscribed_main_channel(user_id: int) -> bool:
    # 💬 проверяем членство через Telegram API
    if _bot is None or _load_subscription_channels is None:
        return True  # 💬 если не пробросили зависимости = не блокируем

    channels = []
    try:
        channels = _load_subscription_channels() or []
        if isinstance(channels, dict):
            channels = channels.get("channels", []) or []  # 💬 защита, если вернули dict
    except Exception:
        channels = []  # 💬 если не смогли прочитать = не блокируем по ошибке


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
    # 💬 ссылка для кнопки "подписаться" (поддержка dict и str)
    try:
        channels = _load_subscription_channels() or []
        # 💬 если вдруг вернули dict {"channels":[...]}
        if isinstance(channels, dict):
            channels = channels.get("channels", []) or []
        ch = channels[0] if channels else None
        if not ch:
            return "https://t.me/espanolingooo"

        if isinstance(ch, str):
            s = ch.strip()
            if "t.me/" in s:
                return s
            s = s.lstrip("@")
            return f"https://t.me/{s}" if s else "https://t.me/espanolingooo"

        if isinstance(ch, dict):
            return ch.get("url") or ch.get("link") or "https://t.me/espanolingooo"

        return "https://t.me/espanolingooo"
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

    if not rows:
        rows = [[InlineKeyboardButton(text="(пусто)", callback_data="pod:noop")]]

    rows.append([InlineKeyboardButton(text="⭐ Мои заметки", callback_data="pod:notes")])  # 💬 открыть сохранённые заметки из подкастов


    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")])  # 💬 выход в главное меню без тупика
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
                InlineKeyboardButton(text="🏠", callback_data="pod:back"),
                InlineKeyboardButton(text="▶️", callback_data="pod:next"),
            ]
        ]
    )  # 💬 добавили Back рядом со звёздочкой без reply-кнопок

def _kb_notes_controls() -> InlineKeyboardMarkup:
    # 💬 навигация по заметкам (влево/удалить/домой к авторам/вправо)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️", callback_data="pod:notes_prev"),
                InlineKeyboardButton(text="🗑", callback_data="pod:notes_del"),
                InlineKeyboardButton(text="🏠", callback_data="pod:authors"),
                InlineKeyboardButton(text="▶️", callback_data="pod:notes_next"),
            ]
        ]
    )


def _format_note_screen(notes: List[Dict[str, Any]], idx: int) -> str:
    # 💬 экран заметки = "2/7\n...заметка..."
    total = len(notes)
    if total <= 0:
        return "Нет заметок"
    idx = max(0, min(idx, total - 1))
    body = notes[idx].get("text_html", "")
    return f"{idx + 1}/{total}\n{body}"



def _format_fragment(es: str, ru: str, hint: str = "") -> str:
    es_txt = html.escape(es.strip())
    ru_txt = html.escape(ru.strip())
    hint_txt = html.escape(hint.strip())

    lines = [
        f"<b>🇪🇸 {es_txt}</b>",  # 💬 испанская строка всегда жирным
        f"<i>🔹 <tg-spoiler>{ru_txt}</tg-spoiler></i>",

    ]
    if hint_txt:
        lines.append(f"<b><i>💡 {hint_txt}</i></b>")  # 💬 подсказка всегда жирный курсив

    return "\n".join(lines)


# -----------------------------
# 👤 USER FLOW
# -----------------------------
async def podcasts_open(message: Message, state: FSMContext) -> None:
    # 💬 точка входа из core8_1.py (menu:podcasts) = заменяем главное меню, а не шлём новое
    ok = await _is_subscribed_main_channel(message.from_user.id)
    if not ok:
        text = "🔒 Подкасты доступны после подписки на канал.\n\nНажми кнопку ниже и потом = проверить подписку."
        try:
            await message.edit_text(text, reply_markup=_kb_subscribe_check())
        except Exception:
            await message.answer(text, reply_markup=_kb_subscribe_check())
        return

    data = _read_podcasts()
    await state.update_data(
        pod_ctx=True,
        pod_author_id=None,
        pod_ep_id=None,
        pod_idx=0,
        pod_notes_idx=0,  # 💬 индекс для режима "Мои заметки"
        pod_frag_msg_id=None,
        pod_nav_msg_id=None,
        pod_hint_msg_id=None,
        pod_audio_msg_id=None,  # 💬 id аудио текущего эпизода
    )

    try:
        await message.edit_text("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await state.update_data(pod_nav_msg_id=message.message_id)  # 💬 запоминаем “главное сообщение навигации”
    except Exception:
        msg = await message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 если edit невозможен

@router.callback_query(F.data == "pod:checksub")
async def pod_checksub(cb: CallbackQuery, state: FSMContext) -> None:
    ok = await _is_subscribed_main_channel(cb.from_user.id)
    if not ok:
        await cb.answer("Ещё не вижу подписку. Попробуй ещё раз.", show_alert=True)
        return

    await cb.answer("✅ Подписка ок", show_alert=False)
    data = _read_podcasts()
    await state.update_data(
        pod_ctx=True,
        pod_author_id=None,
        pod_ep_id=None,
        pod_idx=0,
        pod_notes_idx=0,  # 💬 индекс для режима "Мои заметки"
        pod_frag_msg_id=None,
        pod_nav_msg_id=cb.message.message_id,
    )

    try:
        await cb.message.edit_text("🎧 Выбери автора:", reply_markup=_kb_authors(data))
    except Exception:
        msg = await cb.message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 fallback


@router.callback_query(F.data == "pod:authors")
async def pod_back_authors(cb: CallbackQuery, state: FSMContext) -> None:
    data = _read_podcasts()
    await state.update_data(
        pod_author_id=None,
        pod_ep_id=None,
        pod_idx=0,
        pod_notes_idx=0,  # 💬 индекс для режима "Мои заметки"
        pod_frag_msg_id=None,
        pod_nav_msg_id=cb.message.message_id,  # 💬 остаёмся в том же “нав-сообщении”
    )

    try:
        await cb.message.edit_text("🎧 Выбери автора:", reply_markup=_kb_authors(data))
    except Exception:
        msg = await cb.message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 fallback

    await cb.answer()



@router.callback_query(F.data == "pod:notes")
async def pod_notes_open(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 "Мои заметки" = открываем в том же сообщении и начинаем с самой свежей
    st = await state.get_data()
    if not st.get("pod_ctx"):
        await cb.answer()
        return

    uid = str(cb.from_user.id)
    notes = _read_podcast_notes(uid)
    idx = 0
    await state.update_data(pod_notes_idx=idx, pod_nav_msg_id=cb.message.message_id)  # 💬 держим один экран

    text = _format_note_screen(notes, idx)
    try:
        await cb.message.edit_text(text, reply_markup=_kb_notes_controls())
    except Exception:
        msg = await cb.message.answer(text, reply_markup=_kb_notes_controls())
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 fallback

    await cb.answer()


@router.callback_query(F.data.in_(["pod:notes_prev", "pod:notes_next", "pod:notes_del"]))
async def pod_notes_controls(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 листаем/удаляем заметки в реальном времени (RailwayData /data)
    st = await state.get_data()
    if not st.get("pod_ctx"):
        await cb.answer()
        return

    uid = str(cb.from_user.id)
    notes = _read_podcast_notes(uid)
    if not notes:
        try:
            await cb.message.edit_text("Нет заметок", reply_markup=_kb_notes_controls())
        except Exception:
            pass
        await state.update_data(pod_notes_idx=0)
        await cb.answer("Нет заметок", show_alert=False)
        return

    idx = int(st.get("pod_notes_idx") or 0)
    idx = max(0, min(idx, len(notes) - 1))

    if cb.data == "pod:notes_prev":
        if idx <= 0:
            await cb.answer("Это первая", show_alert=False)
            return
        idx -= 1

    elif cb.data == "pod:notes_next":
        if idx >= len(notes) - 1:
            await cb.answer("Это последняя", show_alert=False)
            return
        idx += 1

    elif cb.data == "pod:notes_del":
        # 💬 удаляем текущую заметку и подвигаем индексы
        try:
            notes.pop(idx)
        except Exception:
            notes = _read_podcast_notes(uid)

        _write_podcast_notes(uid, notes)

        if not notes:
            await state.update_data(pod_notes_idx=0)
            try:
                await cb.message.edit_text("Нет заметок", reply_markup=_kb_notes_controls())
            except Exception:
                await cb.message.answer("Нет заметок", reply_markup=_kb_notes_controls())
            await cb.answer("Удалено", show_alert=False)
            return

        if idx >= len(notes):
            idx = len(notes) - 1

    text = _format_note_screen(notes, idx)
    try:
        await cb.message.edit_text(text, reply_markup=_kb_notes_controls())
        await state.update_data(pod_notes_idx=idx)
        if cb.data == "pod:notes_del":
            await cb.answer("Удалено", show_alert=False)
        else:
            await cb.answer()
    except Exception:
        await cb.answer("Не смог обновить экран", show_alert=False)



@router.callback_query(F.data.startswith("pod:author:"))
async def pod_author(cb: CallbackQuery, state: FSMContext) -> None:
    author_id = cb.data.split(":")[-1]
    data = _read_podcasts()
    author = data.get("authors", {}).get(author_id)

    if not author:
        await cb.answer("Автор не найден", show_alert=True)
        return

    await state.update_data(
        pod_author_id=author_id,
        pod_ep_id=None,
        pod_idx=0,
        pod_notes_idx=0,  # 💬 индекс для режима "Мои заметки"
        pod_frag_msg_id=None,
        pod_nav_msg_id=cb.message.message_id,  # 💬 меню “живёт” в одном сообщении
    )

    text = f"🎙 {author.get('name','Автор')}\n\nВыбери эпизод:"
    try:
        await cb.message.edit_text(text, reply_markup=_kb_episodes(data, author_id))
    except Exception:
        msg = await cb.message.answer(text, reply_markup=_kb_episodes(data, author_id))
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 fallback

    await cb.answer()


@router.callback_query(F.data.startswith("pod:ep:"))
async def pod_episode_open(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 механика как раньше = сначала аудио, потом отдельным сообщением фрагмент с кнопками
    ep_id = cb.data.split(":")[-1]
    data = _read_podcasts()
    ep = data.get("episodes", {}).get(ep_id)
    st = await state.get_data()  # 💬 берём прошлые msg_id (аудио/прочее) для чистки


    if not ep:
        await cb.answer("Эпизод не найден", show_alert=True)
        return

    desc = (ep.get("description") or "").strip()
    if desc and desc != "-":
        await cb.answer(desc[:190], show_alert=True)
    else:
        await cb.answer()

    # 💬 удаляем меню "Выбери эпизод", чтобы не копилось в чате
    try:
        await cb.message.delete()
    except Exception:
        pass

    old_audio_id = st.get("pod_audio_msg_id")
    if old_audio_id:
        await _safe_delete_message(cb.bot, cb.message.chat.id, int(old_audio_id))  # 💬 удаляем прошлое аудио, чтобы не копилось


    # 💬 1) сначала аудио
    audio_file_id = ep.get("audio_file_id")
    audio_type = ep.get("audio_type", "audio")

    if audio_file_id:
        try:
            if audio_type == "voice":
                audio_msg = await cb.bot.send_voice(chat_id=cb.message.chat.id, voice=audio_file_id)  # 💬 шлём аудио и сохраняем msg_id
            else:
                audio_msg = await cb.bot.send_audio(chat_id=cb.message.chat.id, audio=audio_file_id)  # 💬 шлём аудио и сохраняем msg_id

            await state.update_data(pod_audio_msg_id=audio_msg.message_id)  # 💬 запоминаем id аудио для удаления по Back

        except Exception:
            await cb.bot.send_message(
                chat_id=cb.message.chat.id,
                text="⚠️ Не смог отправить аудио (file_id). Проверь, что эпизод добавлен правильно.",
            )


    frags = ep.get("fragments", []) or []
    await state.update_data(pod_ep_id=ep_id, pod_idx=0, pod_frag_msg_id=None)  # 💬 фиксируем текущий эпизод

    if not frags:
        await cb.message.answer("Пока нет фрагментов для этого эпизода.")  # 💬 без reply-кнопок и без “Навигации…”
        return

    # 💬 2) потом фрагмент (отдельным сообщением)
    frag = frags[0]
    text = _format_fragment(frag.get("es", ""), frag.get("ru", ""), frag.get("hint", ""))

    msg = await cb.message.answer(text, reply_markup=_kb_fragment_controls())
    await state.update_data(pod_frag_msg_id=msg.message_id)  # 💬 чтобы знать, какое сообщение редактируем кнопками



@router.callback_query(F.data == "pod:back")
async def pod_back_inline(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 Back = удалить фрагмент и заново показать список эпизодов
    st = await state.get_data()
    author_id = st.get("pod_author_id")
    audio_id = st.get("pod_audio_msg_id")  # 💬 аудио текущего эпизода


    await state.update_data(pod_ep_id=None, pod_idx=0, pod_frag_msg_id=None, pod_audio_msg_id=None)  # 💬 очищаем id аудио


    try:
        await cb.message.delete()  # 💬 удаляем сообщение с фрагментом
    except Exception:
        pass
    if audio_id:
        await _safe_delete_message(cb.bot, cb.message.chat.id, int(audio_id))  # 💬 удаляем аудио вместе с эпизодом


    data = _read_podcasts()
    if author_id:
        await cb.bot.send_message(
            chat_id=cb.message.chat.id,
            text="Выбери эпизод:",
            reply_markup=_kb_episodes(data, author_id),
        )  # 💬 возвращаем список эпизодов
    else:
        await cb.bot.send_message(
            chat_id=cb.message.chat.id,
            text="🎧 Выбери автора:",
            reply_markup=_kb_authors(data),
        )  # 💬 fallback, если author_id потерялся

    await cb.answer()



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
        # 💬 сохраняем текущий фрагмент как заметку в отдельный файл (/data/podcast_notes)
        uid = str(cb.from_user.id)
        frag = frags[idx]
        note_html = _format_fragment(frag.get("es", ""), frag.get("ru", ""), frag.get("hint", ""))
        notes = _read_podcast_notes(uid)

        # 💬 антидубликаты по episode_id + index
        for n in notes:
            try:
                saved_idx = int(n.get("index", -1))
            except Exception:
                saved_idx = -1
            if n.get("episode_id") == ep_id and saved_idx == idx:
                await cb.answer("Уже сохранено ⭐", show_alert=False)
                return

        notes.insert(
            0,
            {
                "ts": int(time.time()),
                "episode_id": ep_id,
                "index": idx,
                "text_html": note_html,
            },
        )
        _write_podcast_notes(uid, notes)
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
            [InlineKeyboardButton(text="✏️ Редактировать фрагменты", callback_data="podadm:edit_frags")],  # 💬 очистить и вставить заново
            [InlineKeyboardButton(text="🗑 Удалить эпизод", callback_data="podadm:del_ep")],
            [InlineKeyboardButton(text="📋 Список", callback_data="podadm:list")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="podadm:close")],
        ]
    )

def _kb_admin_frags_continue() -> InlineKeyboardMarkup:
    # 💬 кнопка выхода из режима добавления фрагментов без зависаний
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")]
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


@router.callback_query(F.data.in_([
    "podadm:close",
    "podadm:back",
    "podadm:list",
    "podadm:add_author",
    "podadm:add_episode",
    "podadm:add_frags",
    "podadm:edit_frags",
    "podadm:del_ep",
]))
async def podcasts_admin_cb(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 ловим только “меню-экшены”, а pick_* отдадим отдельным хендлерам



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

    
    if action == "edit_frags":
        data = _read_podcasts()
        await state.set_state(PodcastAdminStates.choosing_episode_for_edit_fragments)
        await cb.message.answer(
            "Выбери эпизод, чтобы очистить фрагменты и вставить заново:",
            reply_markup=_kb_admin_eps_pick(data, "podadm:pick_ep_edit_frags"),
        )
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


@router.callback_query(F.data.startswith("podadm:pick_ep_edit_frags:"))
async def admin_pick_ep_edit_frags(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 подтверждение очистки + переход в режим перезаписи
    eid = cb.data.split(":")[-1]
    await state.update_data(adm_frag_eid=eid, adm_frag_mode="replace")  # 💬 replace = перезаписываем список фрагментов

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить фрагменты и вставить заново", callback_data=f"podadm:clear_frags:{eid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")],
    ])

    await cb.message.answer(
        "⚠️ Это удалит ВСЕ фрагменты у выбранного эпизода.\n"
        "Аудио, автора и описание не трогаем.\n\n"
        "Нажми кнопку ниже:",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:clear_frags:"))
async def admin_clear_frags(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 очищаем фрагменты и ждём новый текст фрагментов
    eid = cb.data.split(":")[-1]

    data = _read_podcasts()
    ep = data.get("episodes", {}).get(eid)
    if not ep:
        await cb.message.answer("Эпизод не найден. /podcasts_admin")
        await state.clear()
        await cb.answer()
        return

    ep["fragments"] = []  # 💬 очищаем все фрагменты
    _write_podcasts(data)  # 💬 сохраняем в RailwayData (/data)
    try:
        st = PODCASTS_FILE.stat()
        await cb.message.answer(
            f"🧾 podcasts_data.json очищен и сохранён\n"
            f"mtime={int(st.st_mtime)} size={st.st_size}"
        )  # 💬 что делает эта часть: подтверждаем, что файл реально перезаписался
    except Exception:
        pass


    await state.update_data(adm_frag_eid=eid, adm_frag_mode="replace")  # 💬 дальше перезапишем целиком
    await state.set_state(PodcastAdminStates.waiting_fragments_text)

    await cb.message.answer(
        "✅ Фрагменты очищены.\n\n"
        "Теперь вставь фрагменты одним сообщением.\n\n"
        "Каждый фрагмент = одна строка.\n"
        "Формат:\n"
        "ES | RU\n"
        "ES | RU | 💡 подсказка (опционально)\n\n"
        "Между фрагментами пустые строки не нужны.\n"
        "Важно = символ | используй только как разделитель.",
        reply_markup=_kb_admin_frags_continue(),
    )  # 💬 добавили выход назад, чтобы можно было выйти без команд

    await cb.answer()




@router.callback_query(F.data.startswith("podadm:pick_ep_frags:"))
async def admin_pick_ep_frags(cb: CallbackQuery, state: FSMContext) -> None:

    eid = cb.data.split(":")[-1]
    await state.update_data(adm_frag_eid=eid)
    await state.update_data(adm_frag_mode="append")  # 💬 обычный режим = дописываем к существующим

    await state.set_state(PodcastAdminStates.waiting_fragments_text)
    await cb.message.answer(
        "Вставь фрагменты одним сообщением.\n\n"
        "Каждый фрагмент = одна строка.\n"
        "Формат:\n"
        "ES | RU\n"
        "ES | RU | 💡 подсказка (опционально)\n\n"
        "Между фрагментами пустые строки не нужны.\n"
        "Важно = символ | используй только как разделитель.",
        reply_markup=_kb_admin_frags_continue(),
    )  # 💬 добавили выход назад, чтобы админка не становилась тупиком


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

def _clean_cell(s: str) -> str:
    # 💬 чистим префиксы, если они вдруг попали в текст
    t = (s or "").strip()
    t = re.sub(r"^(🇪🇸|🇷🇺|💡)\s*", "", t)
    t = re.sub(r"^(ES|RU|HINT)\s+", "", t, flags=re.IGNORECASE)
    return t.strip()



def _parse_fragments(text: str) -> List[Dict[str, str]]:
    raw = (text or "").strip()
    if not raw:
        return []

    # 💬 новый формат: 1 строка = 1 фрагмент, части разделены через |
    all_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # 💬 новый формат: парсим каждую строку с | как отдельный фрагмент
    out: List[Dict[str, str]] = []
    for ln in all_lines:
        if "|" not in ln:
            continue

        parts = [p.strip() for p in ln.split("|")]  # 💬 режем по всем | и хвост склеиваем в hint
        if len(parts) < 2:
            continue

        es = _clean_cell(parts[0])
        ru = _strip_spoilers_ru(_clean_cell(parts[1]))

        hint = ""
        if len(parts) > 2:
            hint = _clean_cell(" | ".join(parts[2:]))  # 💬 всё после RU = подсказка (если есть)

        out.append({"es": es, "ru": ru, "hint": hint})

    if out:
        return out  # 💬 что делает эта часть: если нашли хотя бы 1 строку с | = используем новый формат

    # 💬 старый формат: блоки через пустую строку, внутри 2 или 3 строки
    blocks = re.split(r"\n\s*\n", raw)
    out = []
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        es = _clean_cell(_strip_prefix(lines[0]))
        ru = _strip_spoilers_ru(_clean_cell(_strip_prefix(lines[1])))
        hint = ""
        if len(lines) >= 3:
            hint = _clean_cell(_strip_prefix(lines[2]))
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

    mode = (st.get("adm_frag_mode") or "append").strip()
    if mode == "replace":
        ep["fragments"] = frags  # 💬 перезаписываем фрагменты целиком
    else:
        ep["fragments"].extend(frags)  # 💬 дописываем

    _write_podcasts(data)  # 💬 сохраняем в RailwayData (/data)
    try:
        st = PODCASTS_FILE.stat()
        await message.answer(
            f"🧾 podcasts_data.json сохранён\n"
            f"mtime={int(st.st_mtime)} size={st.st_size}"
        )  # 💬 что делает эта часть: показываем факт перезаписи файла на диске
    except Exception:
        pass

    if mode == "replace":
        await state.update_data(adm_frag_mode="append")  # 💬 если Telegram разрежет = следующая часть допишется, а не перезатрёт

    await message.answer(
        f"✅ Добавлено фрагментов: {len(frags)}\n"
        f"Всего теперь: {len(ep['fragments'])}\n\n"
        "Если Telegram разрезал текст = просто пришли продолжение.\n"
        "Для выхода нажми ⬅️ Назад.",
        reply_markup=_kb_admin_frags_continue(),
    )  # 💬 держим состояние открытым, чтобы следующая часть тоже сохранилась


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
