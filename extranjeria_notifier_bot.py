import os
import json
import asyncio
import random
import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest


# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MADRID_TZ = ZoneInfo("Europe/Madrid")

# 💬 окно слотов (по Мадриду): 14:00–16:00
WINDOW_START_HOUR = 14
WINDOW_END_HOUR = 16  # конец не включительно: < 16:00

# 💬 сколько “пингов” в день (случайные минуты внутри окна)
DAILY_PINGS_MIN = 6
DAILY_PINGS_MAX = 10

# 💬 как долго показывать “⚡️ есть слоты” перед возвратом базового экрана
ALERT_SHOW_SECONDS = 90

# 💾 хранилище (лучше положить на Volume, если Railway)
DATA_PATH = os.getenv("DATA_PATH", "./notifier_users.json")


bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# =========================
# JSON storage (atomic-ish)
# =========================
def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {"users": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}

def _save_json_atomic(path: str, data: dict) -> None:
    # 💬 упрощённый атомарный сейв: tmp -> replace
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# =========================
# Clean-chat helpers (из Core 8.1 по смыслу)
# =========================
async def send_and_auto_delete_text(bot: Bot, chat_id: int, text: str, delay: float = 3.0, **kwargs):
    # 💬 паттерн как в core: отправили -> подождали -> удалили
    msg = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except TelegramBadRequest:
        pass
    except Exception:
        pass

async def _safe_delete_message(chat_id: int, message_id: int | None):
    # 💬 паттерн как в core
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


# =========================
# UI (якорное сообщение)
# =========================
def _kb_main(enabled: bool) -> InlineKeyboardMarkup:
    if enabled:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔕 Отключить уведомления", callback_data="notif:disable")],
            [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="notif:info")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Включить уведомления", callback_data="notif:enable")],
        [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="notif:info")],
    ])

def _base_text(enabled: bool) -> str:
    if enabled:
        return (
            "✅ Уведомления включены\n\n"
            "Я пингану тебя в окне 14:00–16:00 (Мадрид), когда обычно появляются слоты.\n"
            "Чат будет чистый = я обновляю это сообщение."
        )
    return (
        "🔕 Уведомления выключены\n\n"
        "Нажми кнопку ниже, чтобы включить."
    )

async def _touch_ui_msg_id(store: dict, user_id: str, ui_msg_id: int):
    # 💬 аналог _mywords_touch_ui_msg_id
    store["users"][user_id]["ui_msg_id"] = ui_msg_id

async def _edit_or_send_ui(chat_id: int, store: dict, user_id: str, text: str, kb: InlineKeyboardMarkup):
    # 💬 аналог _mywords_edit_ui: пытаемся редактировать якорь, иначе создаём новый
    ui_msg_id = store["users"][user_id].get("ui_msg_id")
    if ui_msg_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=ui_msg_id, text=text, reply_markup=kb)
            return
        except Exception:
            # 💬 если якорь удалён/не найден = шлём новый
            pass

    m = await bot.send_message(chat_id, text, reply_markup=kb)
    await _touch_ui_msg_id(store, user_id, m.message_id)


# =========================
# Daily schedule generation
# =========================
def _today_key_madrid(now: dt.datetime) -> str:
    return now.astimezone(MADRID_TZ).date().isoformat()

def _gen_daily_minutes() -> list[int]:
    # 💬 минуты внутри окна (14:00–16:00) => 120 минут: 0..119
    k = random.randint(DAILY_PINGS_MIN, DAILY_PINGS_MAX)
    picks = sorted(set(random.sample(range(0, 120), k=k)))
    return picks

def _minute_index_in_window(now_madrid: dt.datetime) -> int | None:
    if now_madrid.hour < WINDOW_START_HOUR or now_madrid.hour >= WINDOW_END_HOUR:
        return None
    base = now_madrid.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    delta = now_madrid - base
    return int(delta.total_seconds() // 60)


# =========================
# Handlers
# =========================
@router.message(CommandStart())
async def on_start(message: Message):
    user_msg_id = message.message_id  # 💬 запомним id, удалим после ответа бота


    store = _load_json(DATA_PATH)
    user_id = str(message.chat.id)

    if user_id not in store["users"]:
        store["users"][user_id] = {
            "enabled": True,          # 💬 важно: /start = уже включён
            "ui_msg_id": None,
            "daily_key": None,
            "daily_minutes": [],
        }
    else:
        store["users"][user_id]["enabled"] = True  # 💬 повторный /start снова включает

    _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=message.chat.id,
        store=store,
        user_id=user_id,
        text=_base_text(True),
        kb=_kb_main(True)
    )
    _save_json_atomic(DATA_PATH, store)
    # 💬 теперь чистим /start, но уже после того как бот показал UI
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=user_msg_id)
    except Exception:
        pass



@router.callback_query(F.data == "notif:disable")
async def cb_disable(call: CallbackQuery):
    await call.answer()
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)

    if user_id in store["users"]:
        store["users"][user_id]["enabled"] = False
        _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=_base_text(False),
        kb=_kb_main(False)
    )
    _save_json_atomic(DATA_PATH, store)


@router.callback_query(F.data == "notif:enable")
async def cb_enable(call: CallbackQuery):
    await call.answer()
    store = _load_json(DATA_PATH)
    user_id = str(call.message.chat.id)

    if user_id not in store["users"]:
        store["users"][user_id] = {
            "enabled": True,
            "ui_msg_id": call.message.message_id,
            "daily_key": None,
            "daily_minutes": [],
        }
    else:
        store["users"][user_id]["enabled"] = True

    _save_json_atomic(DATA_PATH, store)

    await _edit_or_send_ui(
        chat_id=call.message.chat.id,
        store=store,
        user_id=user_id,
        text=_base_text(True),
        kb=_kb_main(True)
    )
    _save_json_atomic(DATA_PATH, store)


@router.callback_query(F.data == "notif:info")
async def cb_info(call: CallbackQuery):
    await call.answer()
    # 💬 короткая заметка и автоудаление (паттерн как в core)
    await send_and_auto_delete_text(
        bot, call.message.chat.id,
        "ℹ️ Я работаю так: в 14:00–16:00 (Мадрид) я несколько раз случайно обновляю это сообщение, если пора.",
        delay=6
    )


# =========================
# Background runner
# =========================
async def notifier_loop():
    while True:
        now = dt.datetime.now(tz=MADRID_TZ)
        store = _load_json(DATA_PATH)

        today_key = _today_key_madrid(now)
        minute_idx = _minute_index_in_window(now)

        # 💬 раз в сутки генерим “случайные минуты” для всех (если ещё не сгенерено)
        for uid, u in store.get("users", {}).items():
            if u.get("daily_key") != today_key:
                u["daily_key"] = today_key
                u["daily_minutes"] = _gen_daily_minutes()

        _save_json_atomic(DATA_PATH, store)

        # 💬 если мы внутри окна и есть совпадение минуты = “пингуем”
        if minute_idx is not None:
            for uid, u in store.get("users", {}).items():
                if not u.get("enabled"):
                    continue
                if minute_idx not in (u.get("daily_minutes") or []):
                    continue

                chat_id = int(uid)

                # 1) показать алерт (редактированием якоря)
                alert_text = (
                    "⚡️ Слоты могут быть доступны\n\n"
                    "Проверь сайт/систему записи прямо сейчас.\n"
                    "Окно 14:00–16:00 (Мадрид)."
                )
                try:
                    await _edit_or_send_ui(chat_id, store, uid, alert_text, _kb_main(True))
                except Exception:
                    # 💬 если юзер заблокировал бота/чат недоступен = просто пропускаем
                    pass

                # 2) через N секунд вернуть базовый экран
                async def _revert_later(_chat_id: int, _uid: str):
                    await asyncio.sleep(ALERT_SHOW_SECONDS)
                    s2 = _load_json(DATA_PATH)
                    u2 = s2.get("users", {}).get(_uid)
                    if not u2:
                        return
                    enabled = bool(u2.get("enabled"))
                    try:
                        await _edit_or_send_ui(_chat_id, s2, _uid, _base_text(enabled), _kb_main(enabled))
                        _save_json_atomic(DATA_PATH, s2)
                    except Exception:
                        pass

                asyncio.create_task(_revert_later(chat_id, uid))

        # 💬 шаг цикла = раз в 20 секунд (достаточно, чтобы не пропустить минуту)
        await asyncio.sleep(20)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    # 💬 запускаем фоновый раннер
    asyncio.create_task(notifier_loop())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
