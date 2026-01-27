# podcasts_feature.py
# 💬 модуль "Подкасты" (авторы -> эпизоды -> фрагменты) + админка /podcasts_admin

from __future__ import annotations
import asyncio  # 💬 нужен таймер для авто-удаления подсказки


import json
import os
import re
import time
import html
import logging  # 💬 чтобы logging.exception не падал
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
from aiogram.dispatcher.event.bases import SkipHandler  # 💬 пропускаем обработку, чтобы не блокировать админку


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

def _require_init() -> None:
    # 💬 Минимальная и безопасная инициализация на входе в подкасты
    # 💬 Гарантируем папки и базовый JSON, чтобы не падать в рантайме

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    try:
        _ensure_podcasts_file()
    except Exception:
        pass

    try:
        _ensure_podcast_notes_dir()
    except Exception:
        pass


FREE_PODCASTS_LIMIT = int(os.getenv("FREE_PODCASTS_LIMIT", "10"))

DEFAULT_PREMIUM_LINKS = {
    "week": os.getenv("PREMIUM_PAYLINK_WEEK", "https://buy.stripe.com/00wfZia9Eeby65JefbbbG0b"),
    "month": os.getenv("PREMIUM_PAYLINK_MONTH", "https://buy.stripe.com/bJeeVe1D8ffC0Lpc73bbG0a"),
    "year": os.getenv("PREMIUM_PAYLINK_YEAR", "https://buy.stripe.com/bJefZi3LgaZmcu74EBbbG0c"),
}

_is_premium_active: Optional[Callable[[int], bool]] = None
_premium_links: Dict[str, str] = dict(DEFAULT_PREMIUM_LINKS)



PREMIUM_ACCESS_PATH = os.getenv("PREMIUM_ACCESS_PATH", str(DATA_DIR / "premium_access.json"))  # 💬 файл, куда пишет Stripe webhook

def _premium_active(user_id: int) -> bool:
    # 💬 если кто то снаружи подал DI чекер = используем его
    if callable(_is_premium_active):
        try:
            return bool(_is_premium_active(user_id))
        except Exception:
            pass

    # 💬 поддержка схем, core пишет active_until
    # premium_users.json  = active_until
    # premium_access.json = until_ts
    # legacy              = premium_until

    candidate_paths = [
        Path(PREMIUM_ACCESS_PATH),
        DATA_DIR / "premium_users.json",
        DATA_DIR / "premium_access.json",
    ]

    now = time.time()

    for path in candidate_paths:
        try:
            if not path.exists():
                continue

            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                continue

            data = json.loads(raw)
            rec = data.get(str(user_id)) or {}

            until_ts = int(rec.get("active_until") or rec.get("until_ts") or rec.get("premium_until") or 0)  # 💬 единый ключ Premium как в core

            if until_ts > now:
                return True

        except Exception:
            continue

    return False


def _premium_paywall_text(user_id: int) -> str:
    # 💬 единый Premium текст (как в лексике) + Telegram ID для Stripe custom field
    return (
        "🔒 <b>Premium доступ</b>\n\n"
        "<b>Ты получаешь:</b>\n\n"
        "✅ <b>Подкасты:</b> все эпизоды без ограничений + новые выпуски\n"
        "✅ <b>Лексика:</b> все темы без лимитов + будущие темы\n"
        "✅ <b>Мои слова:</b> безлимит на создание категорий\n"
        "✅ <b>Грамматика:</b> доступ к разделу, когда он выйдет\n"
        "✅ <b>Обновления:</b> все новые функции включены\n\n"
        f"👉🏼<b>Твой Telegram ID:</b> <code>{user_id}</code>\n\n"
        "Укажи его при оплате → потом нажми <b>✅ Проверить Premium</b>\n"
        "🔓 Замки снимутся автоматически"
    )


def _kb_premium_paywall() -> InlineKeyboardMarkup:
    # 💬 кнопки оплаты + проверка + назад (назад удаляет это сообщение)
    week = _premium_links.get("week")
    month = _premium_links.get("month")
    year = _premium_links.get("year")

    rows: List[List[InlineKeyboardButton]] = []
    pay_row: List[InlineKeyboardButton] = []
    if week:
        pay_row.append(InlineKeyboardButton(text="Premium 1 неделя", url=week))
    if month:
        pay_row.append(InlineKeyboardButton(text="Premium 1 месяц", url=month))
    if year:
        pay_row.append(InlineKeyboardButton(text="Premium 1 год", url=year))
    if pay_row:
        rows.append(pay_row)

    rows.append([InlineKeyboardButton(text="✅ Проверить Premium", callback_data="pod:premium_check")])
    rows.append([InlineKeyboardButton(text="👈 Назад", callback_data="pod:premium_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# -----------------------------
# 🧠 FSM для админки
# -----------------------------
class PodcastAdminStates(StatesGroup):
    choosing_action = State()

    waiting_author_name = State()
    choosing_author_for_edit_name = State()  # 💬 выбор автора для переименования
    waiting_edit_author_name = State()  # 💬 ввод нового имени автора


    choosing_author_for_episode = State()
    choosing_episode_category = State()  # 💬 выбор категории перед названием эпизода
    choosing_episode_level = State()  # 💬 выбор уровня эпизода (B / X1 / X2)
    
    waiting_episode_title = State()
    waiting_episode_desc = State()
    waiting_episode_audio = State()

    choosing_episode_for_fragments = State()
    choosing_episode_for_edit_fragments = State()  # 💬 выбор эпизода для очистки/перезаписи фрагментов
    waiting_edit_episode_title = State()  # 💬 ввод нового названия эпизода
    waiting_edit_episode_desc = State()  # 💬 ввод нового описания эпизода


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
            raw = json.load(f)  # 💬 читаем единый файл /data/podcasts_data.json, иначе authors всегда будут пустыми
    except Exception:
        raw = {}


    # 💬 Если внезапно старый формат = список, конвертируем в dict-форму
    if isinstance(raw, list):
        # 💬 старый формат: список авторов (dict или str)
        authors_map: Dict[str, Any] = {}
        for i, a in enumerate(raw, start=1):
            if isinstance(a, str):
                name = a.strip()
                if not name:
                    continue
                authors_map[str(i)] = {"name": name, "order": i}  # 💬 authors=["Roi", ...]
                continue
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or a.get("author_id") or i)
            authors_map[aid] = a
        raw = {"authors": authors_map, "episodes": {}}


    # 💬 Если прилетело вообще не dict = приводим к безопасной структуре
    if not isinstance(raw, dict):
        raw = {"authors": {}, "episodes": {}}

    authors = raw.get("authors") or {}
    episodes = raw.get("episodes") or {}

    # 💬 Подстраховка типов, чтобы .items() и .get() дальше не падали
    if isinstance(authors, list):
        conv: Dict[str, Any] = {}
        for i, a in enumerate(authors, start=1):
            if isinstance(a, str):
                name = a.strip()
                if not name:
                    continue
                conv[str(i)] = {"name": name, "order": i}  # 💬 поддержка authors=["Roi", ...]
                continue
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or a.get("author_id") or i)
            conv[aid] = a
        authors = conv


    if not isinstance(authors, dict):
        authors = {}
    if not isinstance(episodes, dict):
        episodes = {}

    raw["authors"] = authors
    raw["episodes"] = episodes
    return raw




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


def _episodes_menu_html(author_name: str, level_key: str | None, topic_key: str | None, show_help: bool = False) -> str:
    # 💬 Компактный экран эпизодов (по умолчанию) + разворачиваемый help по фильтрам
    def _norm_level_key(s: str | None) -> str | None:
        # 💬 приводим уровни к B/X (поддержка старых X1/X2 и ввода A1/B2 и т.д.)
        if not s:
            return None
        t = str(s).strip().upper()
        if t in {"X1", "X2", "A2", "B1", "B2", "C1", "C2", "X"}:
            return "X"
        if t in {"A0", "A1", "B"}:
            return "B"
        return t

    level_key = _norm_level_key(level_key)

    filter_line = ""
    if level_key or topic_key:
        parts = []
        if level_key:
            parts.append(level_key.upper())
        if topic_key:
            parts.append(topic_key.upper())
        filter_line = f"<b>ОТФИЛЬТРОВАНО ПО =</b> <code>{' '.join(parts)}</code>\n\n"

    if not show_help:
        return (
            f"<b>🎙 {author_name}</b>\n"
            "<b>🔎 Фильтры</b>\n\n"
            f"{filter_line}"
            "<b>Выбери эпизод:</b>"
        )

    # 💬 Развёрнутый экран подсказки (открывается по кнопке «Фильтры»)
    return (
        f"<b>🎙 {author_name}</b>\n\n"
        f"{filter_line}"
        "🔎 <b>Фильтр по ключам</b>\n\n"
        "<b>Уровень:</b> B = basic (начальный) | X = средний\n"
        "<b>Разделы:</b>\n"
        "C = разговор двух людей\n"
        "D = диалоги из истории\n"
        "G = грамматика и лексика\n\n"
        "<b>Пример ввода:</b> <code>b</code> | <code>x</code> | <code>x g</code> | <code>b c</code> | <code>reset</code>\n\n"
        "Чтобы сбросить фильтр = нажми «🧹 СБРОСИТЬ ФИЛЬТР» или напиши <code>reset</code>"
    )





# -----------------------------
# 🎛️ UI builders
# -----------------------------
def _kb_authors(data: Any) -> InlineKeyboardMarkup:
    # 💬 Не падаем, даже если data не dict
    if not isinstance(data, dict):
        data = {"authors": {}, "episodes": {}}

    authors = data.get("authors") or {}

    # 💬 Если authors внезапно list = конвертим в dict
    if isinstance(authors, list):
        conv: Dict[str, Any] = {}
        for i, a in enumerate(authors, start=1):
            if isinstance(a, str):
                name = a.strip()
                if not name:
                    continue
                conv[str(i)] = {"name": name, "order": i}  # 💬 поддержка старого формата authors=["Roi", ...]
                continue
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or a.get("author_id") or i)
            conv[aid] = a
        authors = conv


    if not isinstance(authors, dict):
        authors = {}

    items = sorted(
        authors.items(),
        key=lambda x: ((x[1] or {}).get("order", 9999), (((x[1] or {}).get("name") or "")).lower())
    )

    rows = []
    for aid, a in items:
        a = a or {}
        rows.append([InlineKeyboardButton(text=f"🎙 {a.get('name','Автор')}", callback_data=f"pod:author:{aid}")])

    if not rows:
        rows = [[InlineKeyboardButton(text="(пусто)", callback_data="pod:noop")]]

    rows.append([InlineKeyboardButton(text="⭐ Мои заметки", callback_data="pod:notes")])  # 💬 открыть заметки
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")])    # 💬 выход в меню
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_episodes(
    data: dict,
    user_id: int,
    author_id: str,
    level_key: str = None,
    topic_key: str = None,
    page: int = 0
) -> InlineKeyboardMarkup:
    episodes = data.get("episodes") or {}
    premium_active = _premium_active(user_id)

    PER_PAGE = 5

    def _norm_level_key(s: str | None) -> str | None:
        # 💬 приводим уровни к B/X (поддержка старых X1/X2 и мусорных значений)
        if not s:
            return None
        t = str(s).strip().upper()
        if t in {"X1", "X2", "A2", "B1", "B2", "C1", "C2", "X"}:
            return "X"
        if t in {"A0", "A1", "B"}:
            return "B"
        return t

    level_key = _norm_level_key(level_key)  # 💬 нормализуем входящий фильтр уровня

    def _lock_title(s: str) -> str:
        s = (s or "").strip()
        if not s:
            s = "Эпизод"

        # 💬 замок должен ЗАМЕНЯТЬ первый эмоджи (как ты просил), а не добавляться рядом
        for pref in ("🎧", "🎙️", "🎙"):
            if s.startswith(pref):
                s = s[len(pref):].lstrip()
                break

        if len(s) > 28:
            s = s[:27].rstrip() + "…"
        return f"🔒 {s}"

    def _title_open(s: str) -> str:
        # 💬 открытый эпизод: гарантируем 🎧 в начале и подрежем длину
        s = (s or "").strip()
        if not s:
            s = "Эпизод"
        if not (s.startswith("🎧") or s.startswith("🎙") or s.startswith("🎙️")):
            s = f"🎧 {s}"
        if len(s) > 32:
            s = s[:31].rstrip() + "…"
        return s

    def _episode_level_key(e: dict) -> str:
        raw = (e or {}).get("level") or (e or {}).get("level_key") or (e or {}).get("lvl") or ""
        raw = str(raw).strip().upper()

        if raw in {"X1", "X2"}:
            return "X"
        if raw in {"A2", "B1", "B2", "C1", "C2", "X"}:
            return "X"
        if raw in {"A0", "A1", "B"}:
            return "B"
        return raw

    def _filtered_items() -> list:
        items_local = []
        for eid, e in episodes.items():
            # 💬 1) сначала ограничиваем по автору
            if str((e or {}).get("author_id")) != str(author_id):
                continue

            # 💬 2) фильтр по уровню
            if level_key:
                if _episode_level_key(e) != str(level_key).strip().upper():
                    continue

            # 💬 3) фильтр по разделу/категории
            if topic_key:
                tk = topic_key.strip().upper()

                topics = (e or {}).get("topics") or (e or {}).get("topic") or []
                if isinstance(topics, str):
                    topics = [topics]
                topics_norm = {str(t).strip().upper() for t in topics if t}

                category = str((e or {}).get("category") or "").strip().lower()

                ok_topic = True
                if tk == "C":
                    ok_topic = (("C" in topics_norm) or (category == "talks"))
                elif tk == "D":
                    ok_topic = (("D" in topics_norm) or (category == "daily"))
                elif tk == "G":
                    ok_topic = (("G" in topics_norm) or (category in ("grammar", "lexica")))
                else:
                    ok_topic = (tk in topics_norm)

                if not ok_topic:
                    continue

            items_local.append((str(eid), e))

        def _sort_key(pair):
            eid_local, _e_local = pair
            try:
                return (int(eid_local),)
            except Exception:
                return (10**9, eid_local)

        items_local.sort(key=_sort_key)
        return items_local

    items = _filtered_items()
    total = len(items)

    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(int(page or 0), pages - 1))

    start = page * PER_PAGE
    end = start + PER_PAGE

    rows: List[List[InlineKeyboardButton]] = []

    is_filtered = bool(level_key or topic_key)
    if is_filtered:
        rows.append([InlineKeyboardButton(text="🧹 СБРОСИТЬ ФИЛЬТР", callback_data="pod:filter_reset")])

    if total == 0:
        # 💬 нижняя панель: 🔎 ⬅️ 🏠 (в одну строку, как ты просил)
        rows.append([
            InlineKeyboardButton(text="🔎", callback_data="pod:filter"),
            InlineKeyboardButton(text="🔄", callback_data="pod:authors"),
            InlineKeyboardButton(text="🏠", callback_data="back_to_menu"),
        ])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    # 💬 список эпизодов на текущей странице
    for global_idx, (eid, e) in enumerate(items[start:end], start=start):
        title = (e or {}).get("title") or "Эпизод"

        # 💬 после FREE_PODCASTS_LIMIT = замок, если нет Premium
        if (not premium_active) and (global_idx >= FREE_PODCASTS_LIMIT):
            rows.append([
                InlineKeyboardButton(
                    text=_lock_title(title),
                    callback_data=f"pod:locked:{author_id}:{eid}"
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    text=_title_open(title),
                    callback_data=f"pod:ep:{author_id}:{eid}"
                )
            ])

    # 💬 пагинация (как в лексике: стрелки + 2/3)
    if pages > 1:
        prev_cb = "pod:ep_page_prev" if page > 0 else "pod:noop"
        next_cb = "pod:ep_page_next" if page < (pages - 1) else "pod:noop"
        rows.append([
            InlineKeyboardButton(text="⬅️", callback_data=prev_cb),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="pod:noop"),
            InlineKeyboardButton(text="➡️", callback_data=next_cb),
        ])

    # 💬 фильтры, назад, меню
    # 💬 нижняя панель: 🔎 ⬅️ 🏠 (в одну строку, как ты просил)
    rows.append([
        InlineKeyboardButton(text="🔎", callback_data="pod:filter"),
        InlineKeyboardButton(text="🔄", callback_data="pod:authors"),
        InlineKeyboardButton(text="🏠", callback_data="back_to_menu"),
    ])


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


SPEAKER_EMOJI = {
    "roi": "🌝",
    "paco": "🌚",
}

def _split_speaker_prefix(text: str) -> Tuple[Optional[str], str]:
    """
    Возвращает (emoji, body).
    Если префикса спикера нет, emoji=None, body=text.
    """
    s = (text or "").strip()
    m = re.match(r"^(Roi|Paco)\s*:\s*(.*)$", s, flags=re.IGNORECASE)
    if not m:
        return None, s
    who = (m.group(1) or "").strip().lower()
    body = (m.group(2) or "").strip()
    return SPEAKER_EMOJI.get(who), body



def _format_fragment(es: str, ru: str, hint: str = "") -> str:
    es_emoji, es_body = _split_speaker_prefix(es)
    _, ru_body = _split_speaker_prefix(ru)  # 💬 в RU убираем Paco:/Roi:, но эмоджи не используем

    es_prefix = es_emoji or "🇪🇸"
    ru_prefix = "🔹"  # 💬 RU всегда начинается с ромбика, без 🌚/🌝

    es_txt = html.escape(es_body)
    ru_txt = html.escape(ru_body)
    hint_txt = html.escape((hint or "").strip())

    lines = [
        f"<b>{es_prefix} {es_txt}</b>",
        f"<i>{ru_prefix} <tg-spoiler>{ru_txt}</tg-spoiler></i>",
    ]
    if hint_txt:
        lines.append(f"<b><i>💡 {hint_txt}</i></b>")

    return "\n".join(lines)


# =============================================================================
#   🟢 1) User Flow
# =============================================================================
@router.callback_query(F.data == "podcasts_open")
async def podcasts_open(callback: CallbackQuery, state: FSMContext) -> None:
    # 💬 Совместимость: если в файле есть _require_init() = вызываем, если нет = не падаем
    try:
        _require_init()
    except NameError:
        pass
    except Exception:
        # 💬 если init есть, но ругается = не валим пользователя
        logging.exception("podcasts_open: _require_init failed")

    await callback.answer()

    data = _read_podcasts()  # 💬 гарантированно dict после нашего патча

    await state.update_data(
        pod_ctx=True,
        pod_author_id=None,
        pod_ep_id=None,
        pod_idx=0,
        pod_notes_idx=0,      # 💬 индекс заметок
        pod_frag_msg_id=None,
        pod_nav_msg_id=callback.message.message_id,
        pod_filter_level=None,
        pod_filter_topic=None,
        pod_ep_page=0,
        pod_screen="authors",
    )

    try:
        await callback.message.edit_text("🎧 Выбери автора:", reply_markup=_kb_authors(data))
    except Exception:
        msg = await callback.message.answer("🎧 Выбери автора:", reply_markup=_kb_authors(data))
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 fallback если edit невозможен



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
        pod_filter_level=None,  # 💬 фильтр уровня
        pod_filter_topic=None,  # 💬 фильтр темы
        pod_ep_page=0,  # 💬 пагинация эпизодов
        pod_screen="authors",  # 💬 после проверки подписки мы на авторах

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
        pod_filter_level=None,  # 💬 сбрасываем фильтр при смене автора
        pod_filter_topic=None,  # 💬 сбрасываем фильтр при смене автора
        pod_ep_page=0,  # 💬 сбрасываем пагинацию
        pod_show_filter_panel=False,  # 💬 выключаем режим ввода фильтра
        pod_screen="authors",  # 💬 возвращаемся на экран авторов
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
    parts = (cb.data or "").split(":")
    # 💬 поддержка 2 форматов:
    # 💬 1) pod:author:<author_id>
    # 💬 2) pod:author:<author_id>:<page>
    author_id = parts[2] if len(parts) >= 3 else None

    page = 0
    if len(parts) >= 4 and str(parts[3]).isdigit():
        page = int(parts[3])

    data = _read_podcasts()
    author = (data.get("authors") or {}).get(author_id)

    if not author_id or not author:
        await cb.answer("Автор не найден", show_alert=True)
        return

    st = await state.get_data()

    is_page_nav = (
        bool(st.get("pod_ctx"))
        and st.get("pod_screen") == "episodes"
        and str(st.get("pod_author_id")) == str(author_id)
        and len(parts) >= 4
    )  # 💬 если это тот же автор и есть :page = это листание, фильтр не трогаем

    if is_page_nav:
        level_key = st.get("pod_filter_level")
        topic_key = st.get("pod_filter_topic")
        show_help = bool(st.get("pod_show_filter_panel"))

        await state.update_data(
            pod_author_id=author_id,
            pod_ep_id=None,
            pod_nav_msg_id=cb.message.message_id,
            pod_ep_page=page,  # 💬 обновляем только страницу
            pod_screen="episodes",
        )
    else:
        level_key = None
        topic_key = None
        show_help = False

        await state.update_data(
            pod_author_id=author_id,
            pod_ep_id=None,
            pod_idx=0,
            pod_notes_idx=0,  # 💬 индекс для режима "Мои заметки"
            pod_frag_msg_id=None,
            pod_nav_msg_id=cb.message.message_id,  # 💬 меню “живёт” в одном сообщении
            pod_filter_level=None,  # 💬 фильтр сбрасывается при смене автора
            pod_filter_topic=None,  # 💬 фильтр сбрасывается при смене автора
            pod_ep_page=page,  # 💬 стартуем с нужной страницы
            pod_show_filter_panel=False,  # 💬 новый автор = выключаем режим ввода фильтра
            pod_screen="episodes",  # 💬 теперь мы на экране эпизодов
        )

    author_name = author.get("name", "Автор")  # 💬 имя автора для заголовка
    text = _episodes_menu_html(author_name, level_key, topic_key, show_help=show_help)  # 💬 меню с учетом фильтра/панели

    try:
        await cb.message.edit_text(
            text,
            reply_markup=_kb_episodes(data, cb.from_user.id, author_id, level_key, topic_key, page),
            parse_mode="HTML",
        )
    except Exception:
        msg = await cb.message.answer(
            text,
            reply_markup=_kb_episodes(data, cb.from_user.id, author_id, level_key, topic_key, page),
            parse_mode="HTML",
        )
        await state.update_data(pod_nav_msg_id=msg.message_id)  # 💬 fallback

    await cb.answer()



@router.callback_query(F.data == "pod:filter_reset")
async def pod_filter_reset(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 reset фильтра кнопкой без мусора в чате
    st = await state.get_data()
    if not st.get("pod_ctx") or st.get("pod_screen") != "episodes":
        await cb.answer()
        return

    author_id = st.get("pod_author_id")
    if not author_id:
        await cb.answer()
        return

    await state.update_data(
        pod_filter_level=None,
        pod_filter_topic=None,
        pod_ep_page=0,
        pod_show_filter_panel=False,  # 💬 при сбросе = возвращаем компактный экран
    )


    data = _read_podcasts()
    author = data.get("authors", {}).get(author_id, {})
    author_name = author.get("name", "Автор")

    text = _episodes_menu_html(author_name, None, None)  # 💬 HTML меню без фильтра
    try:
        await cb.message.edit_text(
            text,
            reply_markup=_kb_episodes(data, cb.from_user.id, author_id, None, None, 0),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await cb.answer()


@router.callback_query(F.data == "pod:filter")
async def pod_filter_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 Тоггл: показываем/прячем help по фильтрам внутри того же сообщения
    st = await state.get_data()
    if not st.get("pod_ctx") or st.get("pod_screen") != "episodes":
        await cb.answer()
        return

    author_id = st.get("pod_author_id")
    if not author_id:
        await cb.answer()
        return

    show_help = not bool(st.get("pod_show_filter_panel"))
    await state.update_data(pod_show_filter_panel=show_help)  # 💬 запоминаем режим

    level_key = st.get("pod_filter_level")
    topic_key = st.get("pod_filter_topic")
    page = int(st.get("pod_ep_page") or 0)

    data = _read_podcasts()
    author = data.get("authors", {}).get(author_id, {})
    author_name = author.get("name", "Автор")

    text = _episodes_menu_html(author_name, level_key, topic_key, show_help=show_help)

    try:
        await cb.message.edit_text(
            text,
            reply_markup=_kb_episodes(data, cb.from_user.id, author_id, level_key, topic_key, page),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await cb.answer()



@router.callback_query(F.data.in_(["pod:ep_page_prev", "pod:ep_page_next"]))
async def pod_ep_page_nav(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 листаем страницы эпизодов (по 8) и не ломаем фильтры
    st = await state.get_data()
    if not st.get("pod_ctx") or st.get("pod_screen") != "episodes":
        await cb.answer()
        return

    author_id = st.get("pod_author_id")
    if not author_id:
        await cb.answer()
        return

    level_key = st.get("pod_filter_level")
    topic_key = st.get("pod_filter_topic")
    page = int(st.get("pod_ep_page") or 0)

    if cb.data == "pod:ep_page_prev":
        page = max(0, page - 1)
    else:
        page = page + 1

    data = _read_podcasts()
    author = data.get("authors", {}).get(author_id, {})
    author_name = author.get("name", "Автор")

    # 💬 аккуратно ограничиваем page по факту (внутри _kb_episodes тоже есть clamp)
    await state.update_data(pod_ep_page=page)

    text = _episodes_menu_html(author_name, level_key, topic_key)  # 💬 HTML меню + фильтр строкой
    try:
        await cb.message.edit_text(
            text,
            reply_markup=_kb_episodes(data, cb.from_user.id, author_id, level_key, topic_key, page),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await cb.answer()



@router.message(F.text)
async def pod_filter_input(message: Message, state: FSMContext) -> None:
    # 💬 пользователь пишет ключи фильтра в чат, мы удаляем сообщение и обновляем инлайн-список
    st = await state.get_data()
    if (not st.get("pod_ctx")) or (st.get("pod_screen") != "episodes") or (not st.get("pod_show_filter_panel")):
        raise SkipHandler  # 💬 ввод фильтра слушаем только когда открыта панель фильтра


    author_id = st.get("pod_author_id")
    nav_msg_id = st.get("pod_nav_msg_id")
    if not author_id or not nav_msg_id:
        raise SkipHandler  # 💬 нет контекста = не блокируем другие сценарии


    raw = (message.text or "").strip()
    upper = raw.upper()

    # 💬 удаляем ввод пользователя сразу, чтобы не засорять чат
    await _safe_delete_message(message.bot, message.chat.id, message.message_id)

    # 💬 парсим токены
    if upper == "RESET":
        level_key = None
        topic_key = None
    else:
        tokens = re.findall(r"[A-Z0-9]+", upper)
        tokens = [t for t in tokens if t]

        level_alias = {
            "A0": "B", "A1": "B", "B": "B",
            "A2": "X", "B1": "X", "B2": "X", "C1": "X", "C2": "X",
            "X1": "X", "X2": "X", "X": "X",
        }  # 💬 вводим B/X (и принимаем старые X1/X2 + A1/B2 и т.д.)

        tokens = [level_alias.get(t, t) for t in tokens]  # 💬 нормализуем уровни перед проверкой

        level_set = {"B", "X"}
        topic_set = {"C", "D", "G"}  # 💬 N убрали, новости входят в D



        level_key = None
        topic_key = None

        ok = True
        if len(tokens) == 1:
            t = tokens[0]
            if t in level_set:
                level_key = t
            elif t in topic_set:
                topic_key = t
            else:
                ok = False
        elif len(tokens) == 2:
            a, b = tokens[0], tokens[1]
            if a in level_set and b in topic_set:
                level_key, topic_key = a, b
            elif a in topic_set and b in level_set:
                level_key, topic_key = b, a
            else:
                ok = False
        else:
            ok = False

        if not ok:
            warn = await message.answer("🙂 Используй ключи которые в меню")  # 💬 короткое предупреждение на 1 секунду без засора чата
            await asyncio.sleep(1)
            await _safe_delete_message(message.bot, message.chat.id, warn.message_id)
            return

    await state.update_data(
        pod_filter_level=level_key,
        pod_filter_topic=topic_key,
        pod_ep_page=0,  # 💬 при новом фильтре всегда с первой страницы
    )
    try:
        if upper == "RESET":
            hint = await message.answer("🧹 Фильтр сброшен")  # 💬 короткое подтверждение
        else:
            hint = await message.answer(f"✅ Отфильтровано по ключу: {upper}")  # 💬 подтверждаем введённый ключ
        asyncio.create_task(_autodelete_message(message.bot, message.chat.id, hint.message_id, delay=2))
    except Exception:
        pass


    data = _read_podcasts()
    author = data.get("authors", {}).get(author_id, {})
    author_name = author.get("name", "Автор")

    text = _episodes_menu_html(author_name, level_key, topic_key)  # 💬 HTML меню + строка фильтра

    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=int(nav_msg_id),
            text=text,
            reply_markup=_kb_episodes(data, message.from_user.id, author_id, level_key, topic_key, 0),
            parse_mode="HTML",
        )
    except Exception:
        pass



@router.callback_query(F.data.startswith("pod:locked:"))
async def pod_episode_locked(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 показываем paywall отдельным сообщением, чтобы потом удалить без мусора
    st = await state.get_data()
    if not st.get("pod_ctx") or st.get("pod_screen") != "episodes":
        await cb.answer()
        return

    if _premium_active(cb.from_user.id):
        await cb.answer("✅ Premium активен. Нажми эпизод ещё раз.", show_alert=True)
        return

    old_id = st.get("pod_premium_msg_id")
    if old_id:
        await _safe_delete_message(cb.bot, cb.message.chat.id, int(old_id))  # 💬 удаляем старое предупреждение
        await state.update_data(pod_premium_msg_id=None)

    msg = await cb.message.answer(
        _premium_paywall_text(cb.from_user.id),  # 💬 Telegram ID для Stripe
        reply_markup=_kb_premium_paywall(),
        disable_web_page_preview=True
    )

    await state.update_data(pod_premium_msg_id=msg.message_id)
    await cb.answer()

@router.callback_query(F.data == "pod:premium_back")
async def pod_premium_back(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 закрываем paywall и удаляем сообщение
    await state.update_data(pod_premium_msg_id=None)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()

@router.callback_query(F.data == "pod:premium_check")
async def pod_premium_check(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 проверка Premium, затем обновляем список эпизодов (снимаем замки)
    st = await state.get_data()
    ok = _premium_active(cb.from_user.id)

    async def _delete_later(msgs, delay: int = 5):
        await asyncio.sleep(delay)
        for m in msgs:
            try:
                await m.delete()
            except Exception:
                pass  # 💬 тихо чистим реакцию

    if not ok:
        try:
            msgs = []
            msgs.append(await cb.message.answer_sticker("CAACAgIAAxkBAAIWH2l21bO_xugzDFap9zCvHnG64If-AAKRMwACkKbJSE_T26pSZdruOAQ"))  # 💬 стикер нет Premium
            msgs.append(await cb.message.answer("⏳ Premium ещё не активен. Если оплатил, подожди немного и нажми ещё раз.\nЕсли не срабатывает, напиши @Drancherrro"))  # 💬 подсказка
            asyncio.create_task(_delete_later(msgs, 5))
        except Exception:
            pass

        await cb.answer("⏳ Premium ещё не активен. Попробуй ещё раз через немного.\nЕсли не срабатывает, напиши @Drancherrro", show_alert=True)
        return

    try:
        msgs = []
        msgs.append(await cb.message.answer_sticker("CAACAgIAAxkBAAIWI2l21eTj7Ea12Kr5IFDAPatBQzZoAALYLgACQ7nYSMxMa3UjThHMOAQ"))  # 💬 стикер Premium есть
        msgs.append(await cb.message.answer("✅ Premium активен. Открываю доступ"))  # 💬 подтверждение
        asyncio.create_task(_delete_later(msgs, 5))
    except Exception:
        pass


    await state.update_data(pod_premium_msg_id=None)
    try:
        await cb.message.delete()  # 💬 удаляем предупреждение
    except Exception:
        pass

    author_id = st.get("pod_author_id")
    nav_msg_id = st.get("pod_nav_msg_id")
    level_key = st.get("pod_filter_level")
    topic_key = st.get("pod_filter_topic")
    page = int(st.get("pod_ep_page") or 0)

    if author_id and nav_msg_id:
        data = _read_podcasts()
        author = data.get("authors", {}).get(author_id, {})
        author_name = author.get("name", "Автор")
        text = _episodes_menu_html(author_name, level_key, topic_key)
        try:
            await cb.bot.edit_message_text(
                chat_id=cb.message.chat.id,
                message_id=int(nav_msg_id),
                text=text,
                reply_markup=_kb_episodes(data, cb.from_user.id, author_id, level_key, topic_key, page),
                parse_mode="HTML",
            )  # 💬 обновили список без замков
        except Exception:
            pass

    await cb.answer("✅ Premium активен", show_alert=True)


@router.callback_query(F.data.startswith("pod:ep:"))
async def pod_episode_open(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 механика как раньше = сначала аудио, потом отдельным сообщением фрагмент с кнопками
    parts = (cb.data or "").split(":")
    author_id = parts[2] if len(parts) >= 4 else None
    ep_id = parts[-1] if parts else ""

    data = _read_podcasts()

    # 💬 Доп.защита: даже если кто-то “подделал” callback_data, не даём открыть >10 без Premium
    if author_id and (not _premium_active(cb.from_user.id)):
        try:
            # 💬 строим общий список эпизодов автора (как в меню) и считаем индекс
            author_items = []
            for _eid, _e in (data.get("episodes") or {}).items():
                if str((_e or {}).get("author_id")) == str(author_id):
                    author_items.append(str(_eid))

            def _sort_key(x: str):
                try:
                    return (int(x),)
                except Exception:
                    return (10**9, x)

            author_items.sort(key=_sort_key)

            if str(ep_id) in author_items:
                idx = author_items.index(str(ep_id))
                if idx >= FREE_PODCASTS_LIMIT:
                    # 💬 показываем тот же paywall, что и при клике по 🔒
                    await pod_episode_locked(cb, state)
                    return
        except Exception:
            pass

    ep = (data.get("episodes") or {}).get(ep_id)

    st = await state.get_data()  # 💬 берём прошлые msg_id (аудио/прочее) для чистки

    prem_id = st.get("pod_premium_msg_id")
    if prem_id:
        await _safe_delete_message(cb.bot, cb.message.chat.id, int(prem_id))  # 💬 убираем paywall, если пользователь пошёл дальше
        await state.update_data(pod_premium_msg_id=None)


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
    await state.update_data(pod_ep_id=ep_id, pod_idx=0, pod_frag_msg_id=None, pod_screen="player")  # 💬 фиксируем эпизод и выключаем фильтр-ввод


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
        author = data.get("authors", {}).get(author_id, {})
        author_name = author.get("name", "Автор")

        level_key = st.get("pod_filter_level")
        topic_key = st.get("pod_filter_topic")
        page = int(st.get("pod_ep_page") or 0)

        text = _episodes_menu_html(author_name, level_key, topic_key)  # 💬 HTML меню + строка фильтра

        msg = await cb.bot.send_message(
            chat_id=cb.message.chat.id,
            text=text,
            reply_markup=_kb_episodes(data, cb.from_user.id, author_id, level_key, topic_key, page),
            parse_mode="HTML",
        )  # 💬 возвращаем список эпизодов без мусора


        await state.update_data(pod_nav_msg_id=msg.message_id, pod_screen="episodes")  # 💬 держим актуальный экран
    else:
        msg = await cb.bot.send_message(
            chat_id=cb.message.chat.id,
            text="🎧 Выбери автора:",
            reply_markup=_kb_authors(data),
        )  # 💬 fallback, если author_id потерялся
        await state.update_data(pod_nav_msg_id=msg.message_id, pod_screen="authors")  # 💬 возвращаемся в авторы


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
    # 💬 главное меню админки подкастов
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать автора", callback_data="podadm:edit_author")],  # 💬 подменю автора
            [InlineKeyboardButton(text="➕ Добавить эпизод", callback_data="podadm:add_episode")],
            [InlineKeyboardButton(text="➕ Добавить фрагменты", callback_data="podadm:add_frags")],
            [InlineKeyboardButton(text="✏️ Редактировать эпизод", callback_data="podadm:edit_frags")],  # 💬 редактирование эпизода
            [InlineKeyboardButton(text="🗑 Удалить эпизод", callback_data="podadm:del_ep")],
            [InlineKeyboardButton(text="📋 Список", callback_data="podadm:list")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="podadm:close")],
        ]
    )


def _kb_admin_author_edit_menu() -> InlineKeyboardMarkup:
    # 💬 подменю редактирования автора
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить автора", callback_data="podadm:add_author")],  # 💬 существующий поток
            [InlineKeyboardButton(text="✏️ Редактировать имя автора", callback_data="podadm:edit_author_name")],  # 💬 новый поток
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")],
        ]
    )


def _kb_admin_frags_continue() -> InlineKeyboardMarkup:
    # 💬 кнопка выхода из режима добавления фрагментов без зависаний
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")]
        ]
    )

def _kb_admin_episode_categories() -> InlineKeyboardMarkup:
    # 💬 выбор категории эпизода для сохранения в JSON
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧩 Грамматика", callback_data="podadm:epcat:grammar")],
            [InlineKeyboardButton(text="📚 Лексика", callback_data="podadm:epcat:lexica")],
            [InlineKeyboardButton(text="☀️ Дневной подкаст", callback_data="podadm:epcat:daily")],
            [InlineKeyboardButton(text="💬 Разговоры", callback_data="podadm:epcat:talks")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")],
        ]
    )
    
def _kb_admin_episode_levels() -> InlineKeyboardMarkup:
    # 💬 выбор уровня эпизода (сохраняем как level_key = B/X)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="«B» Basic (начальный)", callback_data="podadm:eplvl:B")],
            [InlineKeyboardButton(text="«X» Средний", callback_data="podadm:eplvl:X")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")],
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

    PAD = "\u2800"  # 💬 невидимый символ (Braille blank) для выравнивания текста в кнопках

    def _pad_btn(text: str, target_len: int) -> str:
        # 💬 добавляем невидимые символы справа, чтобы все кнопки были одинаковой длины
        t = (text or "").strip()
        if len(t) >= target_len:
            return t
        return t + (PAD * (target_len - len(t)))

    # 💬 готовим тексты и выравниваем длину, чтобы 🎧 не "прыгало" из-за центрирования
    titles = []
    for eid, e in items:
        t = (e.get("title") or "Эпизод").strip()
        if not t.startswith("🎧"):
            t = f"🎧 {t}"  # 💬 единый префикс
        titles.append((eid, t))

    max_len = max((len(t) for _, t in titles), default=0)
    max_len = min(max_len, 60)  # 💬 защита, чтобы не раздувать кнопки при очень длинных названиях

    rows = []
    for eid, t in titles:
        rows.append(
            [InlineKeyboardButton(text=_pad_btn(t, max_len), callback_data=f"{cb_prefix}:{eid}")]
        )  # 💬 важно: используем cb_prefix, чтобы попасть в админ-хендлеры

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def _kb_admin_episode_edit_menu(eid: str) -> InlineKeyboardMarkup:
    # 💬 меню редактирования выбранного эпизода (внутри "Редактировать фрагменты")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить фрагменты и вставить заново", callback_data=f"podadm:clear_frags:{eid}")],
            [InlineKeyboardButton(text="✏️ Редактировать название", callback_data=f"podadm:edit_title:{eid}")],
            [InlineKeyboardButton(text="📝 Редактировать описание", callback_data=f"podadm:edit_desc:{eid}")],
            [InlineKeyboardButton(text="🗂 Редактировать категорию", callback_data=f"podadm:edit_cat:{eid}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="podadm:back")],
        ]
    )


def _kb_admin_episode_categories_edit(eid: str) -> InlineKeyboardMarkup:
    # 💬 выбор категории для сохранения в JSON (редактирование эпизода)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧩 Грамматика", callback_data=f"podadm:set_cat:{eid}:grammar")],
            [InlineKeyboardButton(text="📚 Лексика", callback_data=f"podadm:set_cat:{eid}:lexica")],
            [InlineKeyboardButton(text="☀️ Дневной подкаст", callback_data=f"podadm:set_cat:{eid}:daily")],
            [InlineKeyboardButton(text="💬 Разговоры", callback_data=f"podadm:set_cat:{eid}:talks")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"podadm:pick_ep_edit_frags:{eid}")],
        ]
    )


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
    "podadm:edit_author",
    "podadm:edit_author_name",
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

    if action == "edit_author":
        await state.set_state(PodcastAdminStates.choosing_action)
        await cb.message.answer("✏️ Автор:", reply_markup=_kb_admin_author_edit_menu())
        await cb.answer()
        return

    if action == "edit_author_name":
        data = _read_podcasts()
        await state.set_state(PodcastAdminStates.choosing_author_for_edit_name)
        await cb.message.answer(
            "Выбери автора для переименования:",
            reply_markup=_kb_admin_authors_pick(data, "podadm:pick_author_rename"),
        )  # 💬 выбираем автора, потом просим новое имя
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
    await state.set_state(PodcastAdminStates.choosing_episode_category)  # 💬 перед названием выбираем категорию
    await cb.message.answer("Выбери категорию эпизода:", reply_markup=_kb_admin_episode_categories())
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:epcat:"))
async def admin_pick_episode_category(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 сохраняем категорию эпизода и идём к вводу названия
    cat = cb.data.split(":")[-1]
    await state.update_data(adm_episode_category=cat)  # 💬 сохраняем категорию
    await state.set_state(PodcastAdminStates.choosing_episode_level)  # 💬 дальше выбираем уровень
    await cb.message.answer("Выбери уровень эпизода:", reply_markup=_kb_admin_episode_levels())
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:eplvl:"), PodcastAdminStates.choosing_episode_level)
async def admin_pick_episode_level(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 выбираем уровень и идём к вводу названия
    level = cb.data.split(":")[-1].strip().upper()
    if level not in {"B", "X"}:
        await cb.answer("❗ Используй кнопки уровня (B, X).", show_alert=True)
        return


    await state.update_data(adm_episode_level=level)  # 💬 сохраняем level_key в FSM
    await state.set_state(PodcastAdminStates.waiting_episode_title)  # 💬 дальше как было
    await cb.message.answer("Теперь пришли название эпизода (одной строкой).")
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:pick_author_rename:"))
async def admin_pick_author_rename(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 выбрали автора, просим новое имя
    author_id = cb.data.split(":")[-1]
    await state.update_data(adm_edit_author_id=author_id)  # 💬 запоминаем автора для переименования
    await state.set_state(PodcastAdminStates.waiting_edit_author_name)
    await cb.message.answer("Пришли новое имя автора одним сообщением:")
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


@router.message(PodcastAdminStates.waiting_edit_author_name)
async def admin_save_author_new_name(message: Message, state: FSMContext) -> None:
    # 💬 сохраняем новое имя автора в podcasts_data.json
    st = await state.get_data()
    aid = st.get("adm_edit_author_id")
    new_name = (message.text or "").strip()
    if not aid or not new_name:
        await message.answer("Имя пустое. Пришли ещё раз.")
        return

    data = _read_podcasts()
    authors = data.get("authors", {})
    if aid not in authors:
        await message.answer("Автор не найден. /podcasts_admin")
        await state.clear()
        return

    authors[aid]["name"] = new_name  # 💬 обновляем имя автора
    _write_podcasts(data)  # 💬 сохраняем в RailwayData (/data)

    await state.set_state(PodcastAdminStates.choosing_action)
    await message.answer("✅ Имя автора обновлено.", reply_markup=_kb_admin_menu())


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
    category = (st.get("adm_episode_category") or "").strip()  # 💬 категория эпизода из выбора кнопкой

    level_key = (st.get("adm_episode_level") or "B").strip().upper()  # 💬 уровень эпизода для фильтра (fallback = B)
    if level_key not in {"B", "X"}:
        level_key = "X"  # 💬 защита от мусора


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
        "category": category,
        "level_key": level_key,  # 💬 уровень эпизода для фильтрации (B / X1 / X2)
        "audio_file_id": audio_file_id,
        "audio_type": audio_type,
        "order": order,
        "fragments": [],
        "created_at": int(time.time()),
    }

    _write_podcasts(data)

    await state.clear()
    await message.answer(f"✅ Эпизод создан\nid = {eid}\n\nТеперь можешь добавить фрагменты: /podcasts_admin")


@router.message(PodcastAdminStates.waiting_edit_episode_title)
async def admin_save_episode_title(message: Message, state: FSMContext) -> None:
    # 💬 сохраняем новое название выбранного эпизода
    st = await state.get_data()
    eid = st.get("adm_edit_eid")
    title = (message.text or "").strip()
    if not eid or not title:
        await message.answer("Название пустое. Пришли ещё раз.")
        return

    data = _read_podcasts()
    ep = (data.get("episodes", {}) or {}).get(eid)
    if not ep:
        await message.answer("Эпизод не найден. /podcasts_admin")
        await state.clear()
        return

    ep["title"] = title  # 💬 обновляем title
    _write_podcasts(data)  # 💬 сохраняем в RailwayData (/data)

    await state.set_state(PodcastAdminStates.choosing_action)
    await message.answer("✅ Название обновлено.", reply_markup=_kb_admin_episode_edit_menu(eid))


@router.message(PodcastAdminStates.waiting_edit_episode_desc)
async def admin_save_episode_desc(message: Message, state: FSMContext) -> None:
    # 💬 сохраняем новое описание выбранного эпизода
    st = await state.get_data()
    eid = st.get("adm_edit_eid")
    desc = (message.text or "").strip()
    if not eid or not desc:
        await message.answer("Описание пустое. Пришли ещё раз.")
        return

    data = _read_podcasts()
    ep = (data.get("episodes", {}) or {}).get(eid)
    if not ep:
        await message.answer("Эпизод не найден. /podcasts_admin")
        await state.clear()
        return

    ep["description"] = desc  # 💬 обновляем description
    _write_podcasts(data)  # 💬 сохраняем в RailwayData (/data)

    await state.set_state(PodcastAdminStates.choosing_action)
    await message.answer("✅ Описание обновлено.", reply_markup=_kb_admin_episode_edit_menu(eid))


@router.callback_query(F.data.startswith("podadm:pick_ep_edit_frags:"))
async def admin_pick_ep_edit_frags(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 подтверждение очистки + переход в режим перезаписи
    eid = cb.data.split(":")[-1]
    await state.update_data(adm_frag_eid=eid, adm_frag_mode="replace")  # 💬 replace = перезаписываем список фрагментов

    kb = _kb_admin_episode_edit_menu(eid)  # 💬 расширенное меню редактирования эпизода


    await cb.message.answer(
        "✏️ Редактирование эпизода.\n",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:edit_title:"))
async def admin_edit_episode_title(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 просим новое название эпизода
    eid = cb.data.split(":")[-1]
    await state.update_data(adm_edit_eid=eid)  # 💬 запоминаем эпизод для редактирования
    await state.set_state(PodcastAdminStates.waiting_edit_episode_title)
    await cb.message.answer("Пришли новое название эпизода (одной строкой).", reply_markup=_kb_admin_episode_edit_menu(eid))
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:edit_desc:"))
async def admin_edit_episode_desc(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 просим новое описание эпизода
    eid = cb.data.split(":")[-1]
    await state.update_data(adm_edit_eid=eid)  # 💬 запоминаем эпизод для редактирования
    await state.set_state(PodcastAdminStates.waiting_edit_episode_desc)
    await cb.message.answer("Пришли новое описание эпизода.", reply_markup=_kb_admin_episode_edit_menu(eid))
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:edit_cat:"))
async def admin_edit_episode_cat(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 показываем категории для редактирования
    eid = cb.data.split(":")[-1]
    await state.update_data(adm_edit_eid=eid)  # 💬 запоминаем эпизод для редактирования
    await cb.message.answer("Выбери категорию:", reply_markup=_kb_admin_episode_categories_edit(eid))
    await cb.answer()


@router.callback_query(F.data.startswith("podadm:set_cat:"))
async def admin_set_episode_cat(cb: CallbackQuery, state: FSMContext) -> None:
    # 💬 сохраняем категорию эпизода в podcasts_data.json
    parts = cb.data.split(":")
    if len(parts) < 4:
        await cb.answer()
        return

    eid = parts[2]
    category = parts[3]

    data = _read_podcasts()
    ep = (data.get("episodes", {}) or {}).get(eid)
    if not ep:
        await cb.message.answer("Эпизод не найден. /podcasts_admin")
        await cb.answer()
        return

    ep["category"] = category  # 💬 сохраняем категорию для будущей фильтрации
    _write_podcasts(data)  # 💬 сохраняем в RailwayData (/data)

    await cb.message.answer("✅ Категория обновлена.", reply_markup=_kb_admin_episode_edit_menu(eid))
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


def _parse_fragments_with_tail(text: str) -> Tuple[List[Dict[str, str]], str, int]:
    # 💬 парсим строки с | и сохраняем незавершённую последнюю строку как tail
    raw = (text or "")
    if not raw.strip():
        return [], "", 0

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    out: List[Dict[str, str]] = []
    tail = ""
    bad = 0

    for i, ln in enumerate(lines):
        is_last = i == len(lines) - 1

        if "|" not in ln:
            if is_last:
                tail = ln  # 💬 похоже на разрез внутри строки, ждём продолжение
            else:
                bad += 1  # 💬 мусорная строка не по формату
            continue

        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 2:
            if is_last:
                tail = ln  # 💬 незавершено
            else:
                bad += 1
            continue

        es = _clean_cell(parts[0])
        ru = _strip_spoilers_ru(_clean_cell(parts[1]))

        if not ru:
            if is_last:
                tail = ln  # 💬 есть |, но RU пустой, ждём продолжение
            else:
                bad += 1
            continue

        hint = ""
        if len(parts) > 2:
            hint = _clean_cell(" | ".join(parts[2:]))  # 💬 всё после RU = подсказка (если есть)

        out.append({"es": es, "ru": ru, "hint": hint})

    return out, tail, bad




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

    prev_tail = (st.get("adm_frag_tail") or "").strip()
    raw_in = message.text or ""
    if prev_tail:
        raw_in = f"{prev_tail}{raw_in}"  # 💬 склеиваем разрезанную строку без переноса

    frags, tail, bad_lines = _parse_fragments_with_tail(raw_in)
    await state.update_data(adm_frag_tail=tail)  # 💬 сохраняем хвост, если строка разрезана

    if not frags and tail:
        await message.answer(
            "⚠️ Вижу незавершённую строку. Пришли продолжение следующим сообщением.",
            reply_markup=_kb_admin_frags_continue(),
        )  # 💬 не закрываем FSM, ждём продолжение
        return

    if not frags:
        await message.answer(
            "Не смог распарсить. Проверь формат и пришли ещё раз.",
            reply_markup=_kb_admin_frags_continue(),
        )  # 💬 даём выход назад, чтобы не было тупика
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


    if mode == "replace":
        await state.update_data(adm_frag_mode="append")  # 💬 если Telegram разрежет = следующая часть допишется, а не перезатрёт

    warn = ""
    if bad_lines:
        warn += f"\n⚠️ Пропущено строк без | = {bad_lines}"
    if (st.get("adm_frag_tail") or "").strip():
        warn += "\n⚠️ В конце есть незавершённая строка. Пришли продолжение."

    
    await message.answer(
        f"✅ Добавлено фрагментов: {len(frags)}\n"
        f"Всего теперь: {len(ep['fragments'])}\n\n"
        "Если Telegram разрезал текст = просто пришли продолжение.\n"
        f"Для выхода нажми ⬅️ Назад.{warn}",
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
