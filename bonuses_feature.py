# bonuses_feature.py
# 💬 модуль «🎁

import time
import logging
from math import ceil
from urllib.parse import quote

from aiogram import Router, F
from aiogram.filters import Command  # 💬 команды типа /refstats
from aiogram.fsm.context import FSMContext  # 💬 FSMContext нужен для bonus_test_cmd

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.exceptions import TelegramNetworkError  # 💬 ловим таймауты Telegram
import asyncio  # 💬 нужен для asyncio.TimeoutError


router = Router()

# ===== SAFE TELEGRAM WRAPPERS =====

async def _safe_cb_answer(callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    # 💬 что делает эта часть: гасим "loading…" и не падаем на Telegram таймаутах
    try:
        await callback.answer(text or "", show_alert=show_alert, request_timeout=60)
    except (TelegramNetworkError, asyncio.TimeoutError):
        pass


async def _safe_edit_or_answer(message: Message, text: str, reply_markup=None) -> None:
    # 💬 что делает эта часть: обновляем текст без засорения чата (edit_text, иначе delete+answer)
    try:
        await message.edit_text(text, reply_markup=reply_markup, request_timeout=60)
        return
    except TelegramBadRequest as e:
        # 💬 что делает эта часть: если текст не изменился, не шлём дубль
        if "message is not modified" in str(e).lower():
            return
    except (TelegramNetworkError, asyncio.TimeoutError):
        # 💬 что делает эта часть: при сетевых таймаутах ничего не добавляем в чат
        return

    # 💬 что делает эта часть: если edit невозможен, удаляем старое сообщение бота и шлём новое
    try:
        if getattr(message, "from_user", None) and getattr(message.from_user, "is_bot", False):
            await message.delete(request_timeout=60)
    except Exception:
        pass

    try:
        await message.answer(text, reply_markup=reply_markup, request_timeout=60)
    except (TelegramNetworkError, asyncio.TimeoutError):
        pass



def _split_text(text: str, limit: int = 3800) -> list[str]:
    # 💬 что делает эта часть: режем длинный текст, чтобы не ловить TelegramBadRequest (4096)
    chunks = []
    buf = ""
    for line in (text or "").split("\n"):
        if len(buf) + len(line) + 1 > limit:
            chunks.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}".strip() if buf else line
    if buf:
        chunks.append(buf)
    return chunks


async def _safe_send_long(message: Message, text: str) -> None:
    # 💬 что делает эта часть: отправляем длинное сообщение кусками
    for chunk in _split_text(text):
        try:
            await message.answer(chunk, request_timeout=60)
        except (TelegramNetworkError, asyncio.TimeoutError, TelegramBadRequest):
            break



# 💬 зависимости подставляем из core8_1.py через init_bonus_feature()
_load_user_data = None
_save_user_data = None
_load_subscription_channels = None
_LessonStates = None

_admin_chat_id: int | None = None

_materials_url: str = ""
_contact_url: str = ""

# 💬 если хочешь жёстко зафиксировать главный канал = поставь сюда "@espanolingooo"
_main_channel_override: str | None = None

# 💬 окно накопления: 7 дней
_CYCLE_SECONDS = 7 * 24 * 60 * 60

# 💬 таблица наград (итоговый бонус, не сумма)
# 1 друг = 5⭐ (прогресс)
# 2 друга = 15⭐ (можно просить подарок)
# 3 друга = 25⭐
# 5 друзей = 50⭐
_REWARD_TABLE = [
    (1, 5),
    (2, 15),
    (3, 25),
    (5, 50),
]
_MIN_CLAIM_STARS = 15  # 💬 минимальная сумма, с которой можно запрашивать подарок


def init_bonus_feature(
    *,
    load_user_data,
    save_user_data,
    load_subscription_channels,
    LessonStates,
    materials_url: str,
    contact_url: str,
    admin_chat_id: int,
    main_channel_override: str | None = None,
):
    # 💬 что делает эта часть: пробрасываем зависимости из core8_1.py, чтобы не было циклических импортов
    global _load_user_data, _save_user_data, _load_subscription_channels, _LessonStates
    global _admin_chat_id, _materials_url, _contact_url, _main_channel_override

    _load_user_data = load_user_data
    _save_user_data = save_user_data
    _load_subscription_channels = load_subscription_channels
    _LessonStates = LessonStates

    _admin_chat_id = int(admin_chat_id)

    _materials_url = materials_url or ""
    _contact_url = contact_url or ""
    _main_channel_override = main_channel_override


def _get_main_channel() -> str:
    # 💬 что делает эта часть: берём главный канал = первый в subscription_channels.json (fallback = @espanolingooo)
    if _main_channel_override:
        return _main_channel_override

    try:
        if callable(_load_subscription_channels):
            chans = _load_subscription_channels() or []
            if chans and isinstance(chans[0], str) and chans[0].strip():
                return chans[0].strip()
    except Exception:
        logging.exception("_get_main_channel: failed")

    return "@espanolingooo"


def _calc_stars(qualified: int) -> int:
    # 💬 что делает эта часть: превращаем кол-во друзей в «звёзды» по таблице
    stars = 0
    for need, value in _REWARD_TABLE:
        if qualified >= need:
            stars = value
    return stars


def _ensure_ref_bonus(u: dict) -> dict:
    # 💬 что делает эта часть: гарантируем структуру в user_data для реф-бонусов
    rb = u.setdefault("ref_bonus", {})
    rb.setdefault("cycle_started_at", 0)

    rb.setdefault("qualified", 0)
    rb.setdefault("qualified_users", [])

    rb.setdefault("stars", 0)

    rb.setdefault("claim_status", "none")  # none | pending
    rb.setdefault("pending_stars", 0)
    rb.setdefault("claim_requested_at", 0)

    rb.setdefault("claims", [])  # история выдач
    rb.setdefault("last_declined_at", 0)

    return rb


def _reset_cycle_if_expired(rb: dict) -> None:
    # 💬 что делает эта часть: сбрасываем накопление, если прошло 7 дней (кроме pending заявки)
    now = int(time.time())
    started = int(rb.get("cycle_started_at", 0) or 0)
    if not started:
        return

    expired = now >= started + _CYCLE_SECONDS
    if expired and rb.get("claim_status") != "pending":
        rb["cycle_started_at"] = 0
        rb["qualified"] = 0
        rb["qualified_users"] = []
        rb["stars"] = 0
        rb["claim_status"] = "none"
        rb["pending_stars"] = 0
        rb["claim_requested_at"] = 0

def _time_left_days(rb: dict) -> int:
    # 💬 что делает эта часть: показываем цикл 7→1→7 по дням (без 0)
    now = int(time.time())
    started = int(rb.get("cycle_started_at", 0) or 0)
    if not started:
        return 7

    days_passed = int((now - started) // 86400)
    left = 7 - (days_passed % 7)
    return left if left > 0 else 7



def _next_target(qualified: int) -> int:
    # 💬 что делает эта часть: показываем ближайшую цель по друзьям
    if qualified < 2:
        return 2
    if qualified < 3:
        return 3
    if qualified < 5:
        return 5
    return 5


def bonus_register_referral_from_start(new_user_id: str, payload: str | None):
    """
    💬 /start ref_<inviter_id>
    фиксируем, кто пригласил пользователя (только 1 раз, без перезаписи)
    """
    if not callable(_load_user_data) or not callable(_save_user_data):
        return

    if not payload:
        return

    payload = str(payload).strip()
    if not payload.startswith("ref_"):
        return

    inviter_id = payload.replace("ref_", "", 1).strip()
    if not inviter_id.isdigit():
        return
    if inviter_id == str(new_user_id):
        return

    data = _load_user_data()
    u = data.setdefault(str(new_user_id), {})

    # 💬 если уже есть реферер = не перезаписываем
    if u.get("referred_by"):
        return

    u["referred_by"] = inviter_id
    u["ref_status"] = "clicked"
    u["ref_clicked_at"] = int(time.time())

    # 💬 у пригласившего держим список кликов (не засчитанных)
    inviter = data.setdefault(inviter_id, {})
    _ensure_ref_bonus(inviter)
    pending = inviter.setdefault("ref_pending", [])
    if str(new_user_id) not in pending:
        pending.append(str(new_user_id))

    _save_user_data(data)


def bonus_try_qualify_referral(user_id: str, subscribed_channels: list[str] | None = None) -> bool:
    """
    💬 Засчитываем друга после успешной проверки подписки (в core8_1.py).
    На деле проверяем только главный канал.
    """
    if not callable(_load_user_data) or not callable(_save_user_data):
        return False

    main_ch = _get_main_channel()
    if subscribed_channels is not None and main_ch not in subscribed_channels:
        return False

    data = _load_user_data()
    u = data.setdefault(str(user_id), {})

    inviter_id = u.get("referred_by")
    if not inviter_id:
        return False

    # 💬 уже засчитан = второй раз не считаем
    if u.get("ref_status") == "qualified":
        return False

    u["ref_status"] = "qualified"
    u["ref_qualified_at"] = int(time.time())

    inviter = data.setdefault(str(inviter_id), {})
    rb = _ensure_ref_bonus(inviter)

    # 💬 сброс по времени перед начислением
    _reset_cycle_if_expired(rb)

    # 💬 старт окна накопления = при первом засчитанном друге
    if not int(rb.get("cycle_started_at", 0) or 0):
        rb["cycle_started_at"] = int(time.time())

    qualified_users = rb.setdefault("qualified_users", [])
    if str(user_id) not in qualified_users:
        qualified_users.append(str(user_id))
        rb["qualified"] = int(rb.get("qualified", 0)) + 1

    rb["stars"] = _calc_stars(int(rb.get("qualified", 0)))

    # 💬 убираем из pending, если был там
    pending = inviter.setdefault("ref_pending", [])
    if str(user_id) in pending:
        pending.remove(str(user_id))

    _save_user_data(data)
    return True


def _build_bonuses_kb(user_id: str) -> InlineKeyboardMarkup:
    # 💬 что делает эта часть: строим клавиатуру «Бонусы» под текущий прогресс
    data = _load_user_data() if callable(_load_user_data) else {}
    u = data.get(str(user_id), {})
    rb = _ensure_ref_bonus(u)

    _reset_cycle_if_expired(rb)

    stars = int(rb.get("stars", 0))
    can_claim = stars >= _MIN_CLAIM_STARS and rb.get("claim_status") != "pending"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📨 Пригласить друга", callback_data="bonuses:share")],
        [
            InlineKeyboardButton(text="ℹ️ Инструкция", callback_data="bonuses:how"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="bonuses:refresh"),
        ],
    ]

    if can_claim:
        rows.append([InlineKeyboardButton(text=f"🎁 Запросить подарок ({stars}⭐)", callback_data="bonuses:claim")])
    else:
        rows.append([InlineKeyboardButton(text="🔒 Запросить подарок", callback_data="bonuses:locked")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="bonuses:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def bonuses_open(message: Message, state):


    # 💬 что делает эта часть: главный экран «🎁 Бонусы»
    if not callable(_load_user_data) or not callable(_save_user_data):
        return await message.answer("⚠️ Модуль «Бонусы» не инициализирован.")

    uid = str(message.from_user.id)
    data = _load_user_data()
    u = data.setdefault(uid, {})
    rb = _ensure_ref_bonus(u)

    _reset_cycle_if_expired(rb)

    qualified = int(rb.get("qualified", 0))
    stars = _calc_stars(qualified)
    rb["stars"] = stars  # 💬 синхронизируем на всякий случай

    days_left = _time_left_days(rb)
    main_ch = _get_main_channel()


    # 💬 что делает эта часть: показываем только счётчики и награды (без целей/статусов)
    text_out = (
        "🎁 <b>Бонусы</b>\n\n"
        "<b>Приглашай друзей и получай телеграм звезды</b>\n"
        "<b>Обменивай звезды на Телеграм Подарки</b>\n\n"
        f"<b>👥 Приглашено = {qualified}</b>\n"
        f"<b>⭐ Баланс = {stars}</b>\n"
        f"<b>⏳ До сброса = {days_left} дней</b>\n\n"
        "<b>Награды:</b>\n"
        "<b>1 друг = 5⭐</b>\n"
        "<b>2 друга = 15⭐</b>\n"
        "<b>3 друга = 25⭐</b>\n"
        "<b>5 друзей = 50⭐</b>\n\n"
    )

    _save_user_data(data)

    kb = _build_bonuses_kb(uid)

    await _safe_edit_or_answer(message, text_out, reply_markup=kb)  # 💬 безопасная отрисовка экрана бонусов



    if _LessonStates:
        try:
            await state.set_state(_LessonStates.choosing_category)
        except Exception:
            pass

@router.callback_query(F.data == "bonuses:refresh")
async def bonuses_refresh(callback: CallbackQuery, state):
    # 💬 что делает эта часть: обновляем экран и не падаем на таймаутах Telegram
    await _safe_cb_answer(callback)

    if not getattr(callback, "message", None):
        return  # 💬 иногда message отсутствует

    return await bonuses_open(callback.message, state)  # 💬 перерисовываем экран




@router.callback_query(F.data == "bonuses:how")
async def bonuses_how(callback: CallbackQuery):
    # 💬 что делает эта часть: показываем простую инструкцию и не падаем на таймаутах Telegram
    await _safe_cb_answer(callback)

    main_ch = _get_main_channel()
    text_out = (
        "ℹ️ <b>Как это работает</b>\n\n"
        "1) Ты отправляешь другу свою ссылку\n"
        "2) Друг нажимает Start\n"
        "3) Друг набирает <b>100 XP</b> в любой теме\n"
        f"4) Друг должен быть подписан на главный канал {main_ch}\n\n"
        "После этого тебе начисляются ⭐ звёзды.\n\n"
        "🎁 Когда накопишь звёзды = можешь запросить подарок\n"
        "себе или другу, как захочешь \n\n"

    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="bonuses:refresh")]
    ])

    if getattr(callback, "message", None):
        await _safe_edit_or_answer(callback.message, text_out, reply_markup=kb)


@router.callback_query(F.data == "bonuses:locked")
async def bonuses_locked(callback: CallbackQuery):
    # 💬 что делает эта часть: объясняем, почему «запросить» пока нельзя (мало звёзд или заявка уже pending)

    msg = "Нужно минимум 15⭐ (2 друга)."

    try:
        if callable(_load_user_data):
            data = _load_user_data() or {}
            uid = str(callback.from_user.id)
            u = data.get(uid, {}) or {}
            rb = _ensure_ref_bonus(u)

            if rb.get("claim_status") == "pending":
                msg = "⏳ Заявка уже отправлена. Если нужно = нажми «Написать админу» в экране после заявки."
    except Exception:
        pass

    await _safe_cb_answer(callback, msg, show_alert=True)  # 💬 безопасно



@router.callback_query(F.data == "bonuses:share")
async def bonuses_share(callback: CallbackQuery):
 
    await _safe_cb_answer(callback)  # 💬 безопасно

    me = await callback.bot.get_me()  # 💬 берём @username бота

    uid = str(callback.from_user.id)
    link = f"https://t.me/{me.username}?start=ref_{uid}"

    text_msg = (
        "Залетай в мой тренажёр по испанскому 😎\n"
        "Жми Start, подпишись на канал и начни учиться.\n"
    )

    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote(text_msg)}"

    if getattr(callback, "message", None):
        await _safe_edit_or_answer(
            callback.message,
            f"🔗 Твоя ссылка:\n{link}\n\nНажми «Поделиться» или просто скопируй ссылку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Поделиться", url=share_url)],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="bonuses:refresh")],  # 💬 возвращаемся на экран бонусов без спама
            ])
        )  # 💬 безопасно




def _build_main_menu_kb() -> InlineKeyboardMarkup:

    # 💬 что делает эта часть: главное меню (для кнопки «Назад» из бонусов)

    # 💬 что делает эта часть: главное меню (для кнопки «Назад» из бонусов)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 УЧИТЬСЯ",    callback_data="menu:learn")],
        [
            InlineKeyboardButton(text="📎 Материалы", url=_materials_url),
            InlineKeyboardButton(text="Связь 💬", url=_contact_url)
        ],
        [
            InlineKeyboardButton(text="⚔️ Битва",   callback_data="menu:battle"),
            InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords")
        ],
        [InlineKeyboardButton(text="🎁 Бонусы", callback_data="menu:bonuses")],
        [
            InlineKeyboardButton(text="🏆 Рейтинг",    callback_data="menu:rating"),
            InlineKeyboardButton(text="Настройки ⚙️",  callback_data="menu:settings")
        ],
    ])


@router.callback_query(F.data == "bonuses:back")
async def bonuses_back(callback: CallbackQuery, state):

    await _safe_cb_answer(callback)  # 💬 безопасно
    kb = _build_main_menu_kb()
    await _safe_edit_or_answer(callback.message, "Что изучаем?⭐", reply_markup=kb)  # 💬 безопасно


    if _LessonStates:
        try:
            await state.set_state(_LessonStates.choosing_category)
        except Exception:
            pass


@router.callback_query(F.data == "bonuses:claim")
async def bonuses_claim(callback: CallbackQuery, state):
    await _safe_cb_answer(callback)  # 💬 не падаем на таймаутах Telegram

    if _admin_chat_id is None:
        return await callback.message.answer("⚠️ Админ-чат не настроен.")

    uid = str(callback.from_user.id)

    data = _load_user_data()
    u = data.setdefault(uid, {})
    rb = _ensure_ref_bonus(u)

    _reset_cycle_if_expired(rb)

    qualified = int(rb.get("qualified", 0))
    stars = _calc_stars(qualified)
    rb["stars"] = stars

    if rb.get("claim_status") == "pending":
        return await callback.message.answer("⏳ Заявка уже отправлена.")

    if stars < _MIN_CLAIM_STARS:
        return await callback.message.answer("🔒 Подарок доступен от 15⭐ (нужно минимум 2 друга).")

    rb["claim_status"] = "pending"
    rb["pending_stars"] = stars
    rb["claim_requested_at"] = int(time.time())

    _save_user_data(data)

    user_tag = callback.from_user.username
    user_tag = f"@{user_tag}" if user_tag else "(нет username)"

    ids_short = ", ".join(rb.get("qualified_users", [])[-10:])  # последние 10
    if not ids_short:
        ids_short = "нет"

    admin_text = (
        "🎁 <b>Заявка на подарок</b>\n\n"
        f"Пользователь = {callback.from_user.full_name}\n"
        f"Username = {user_tag}\n"
        f"User ID = <code>{uid}</code>\n\n"
        f"Друзья = {qualified}\n"
        f"⭐ Звёзды = <b>{stars}⭐</b>\n"
        f"ID друзей (последние) = {ids_short}\n"
    )

    # 💬 что делает эта часть: отправляем админу только текст, без кнопок
    try:
        await callback.bot.send_message(_admin_chat_id, admin_text, request_timeout=60)
    except (TelegramNetworkError, asyncio.TimeoutError):
        # 💬 что делает эта часть: если не отправилось админу = откатываем pending, чтобы пользователь не залип
        rb["claim_status"] = "none"
        rb["pending_stars"] = 0
        rb["claim_requested_at"] = 0
        _save_user_data(data)
        return await callback.message.answer("⚠️ Не удалось отправить заявку (Telegram тормозит). Нажми ещё раз позже.")

    # 💬 что делает эта часть: после успешной отправки показываем следующий шаг пользователю
    write_text = "Хочу подарок 🎁"
    write_url = f"https://t.me/Drancherrro?text={quote(write_text)}"  # 💬 открываем чат админа с предзаполненным текстом

    user_text = (
        "✅ <b>Заявка отправлена</b>\n\n"
        "Теперь можешь написать админу:\n"
        "• какой подарок хочешь\n"
        "• себе или кому-то другому\n"
        "• если другому = пришли @username\n\n"
        "Сообщение можно не писать. Я сам увижу заявку и напишу тебе"
    )

    kb2 = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать админу", url=write_url)],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="bonuses:refresh"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="bonuses:back"),
        ],
    ])

    await callback.message.answer(user_text, reply_markup=kb2)
    return

@router.message(Command("bonus_test"))
async def bonus_test_cmd(message: Message, state: FSMContext):
    # 💬 что делает эта часть: админ-чит для теста «Запросить подарок» без приглашённых друзей

    if _admin_chat_id is None:
        return await message.answer("⚠️ ADMIN_CHAT_ID не настроен.")

    # 💬 защита: только админ (либо в админ-чате, либо от админ-юзера)
    if str(message.chat.id) != str(_admin_chat_id) and str(message.from_user.id) != str(_admin_chat_id):
        return await message.answer("⛔ Команда доступна только админу.")

    if not callable(_load_user_data) or not callable(_save_user_data):
        return await message.answer("⚠️ load_user_data/save_user_data не подключены.")

    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    if not arg:
        return await message.answer(
            "🧪 Использование:\n"
            "/bonus_test 2 = поставить 2 приглашённых (15⭐)\n"
            "/bonus_test 5 = поставить 5 приглашённых (50⭐)\n"
            "/bonus_test reset = сбросить бонусы"
        )

    data = _load_user_data() or {}
    uid = str(message.from_user.id)
    u = data.setdefault(uid, {})
    rb = _ensure_ref_bonus(u)

    if arg == "reset":
        rb["cycle_started_at"] = 0
        rb["qualified"] = 0
        rb["qualified_users"] = []
        rb["stars"] = 0

        rb["claim_status"] = "none"
        rb["pending_stars"] = 0
        rb["claim_requested_at"] = 0

        _save_user_data(data)

        await message.answer("✅ Сброшено. Теперь звёзды = 0⭐")
        return await bonuses_open(message, state)

    try:
        fake_q = int(arg)
    except Exception:
        return await message.answer("⚠️ Неверный аргумент. Пример: /bonus_test 2 или /bonus_test reset")

    # 💬 что делает эта часть: ставим фейковое кол-во qualified и пересчитываем звёзды по твоей же логике
    fake_q = max(0, min(fake_q, 5))
    rb["qualified"] = fake_q
    rb["stars"] = _calc_stars(fake_q)

    rb["claim_status"] = "none"       # 💬 тест должен открывать кнопку «Запросить подарок»
    rb["pending_stars"] = 0           # 💬 убираем зависшую заявку
    rb["claim_requested_at"] = 0      # 💬 очищаем таймстамп заявки


    # 💬 чтобы не сбрасывало цикл, если он пустой
    if int(rb.get("cycle_started_at", 0) or 0) == 0:
        rb["cycle_started_at"] = int(time.time())

    _save_user_data(data)

    await message.answer(f"✅ Тест выставлен: friends = {fake_q}, stars = {rb['stars']}⭐")
    return await bonuses_open(message, state)

@router.message(Command("bonus_reset"))
async def bonus_reset_cmd(message: Message, state: FSMContext):
    # 💬 что делает эта часть: админ может обнулить бонусы конкретного пользователя (сам пользователь не может)

    if _admin_chat_id is None:
        return await message.answer("⚠️ ADMIN_CHAT_ID не настроен.")

    # 💬 доступ только админу (как у /refstats и /bonus_test)
    if str(message.chat.id) != str(_admin_chat_id) and str(message.from_user.id) != str(_admin_chat_id):
        return await message.answer("⛔ Команда доступна только админу.")

    if not callable(_load_user_data) or not callable(_save_user_data):
        return await message.answer("⚠️ load_user_data/save_user_data не подключены.")

    parts = (message.text or "").split(maxsplit=1)
    target_uid = parts[1].strip() if len(parts) > 1 else ""

    if not target_uid or not target_uid.isdigit():
        return await message.answer("🧹 Использование:\n/bonus_reset <user_id>\nПример:\n/bonus_reset 123456789")

    data = _load_user_data() or {}
    u = data.setdefault(str(target_uid), {})
    rb = _ensure_ref_bonus(u)

    # 💬 что делает эта часть: полный сброс ref_bonus пользователя
    rb["cycle_started_at"] = 0
    rb["qualified"] = 0
    rb["qualified_users"] = []
    rb["stars"] = 0

    rb["claim_status"] = "none"
    rb["pending_stars"] = 0
    rb["claim_requested_at"] = 0

    _save_user_data(data)

    await message.answer(f"✅ Обнулено для user_id={target_uid}")

    # 💬 удобно сразу показать экран бонусов админу (если сбрасывал себя)
    if str(target_uid) == str(message.from_user.id):
        return await bonuses_open(message, state)


@router.message(Command("refstats"))
async def refstats_cmd(message: Message):

    # 💬 что делает эта часть: админ-команда статистики по рефералке

    if _admin_chat_id is None:
        return await message.answer("⚠️ ADMIN_CHAT_ID не настроен.")

    # 💬 защита: только админ (либо в админ-чате, либо от админ-юзера)
    if str(message.chat.id) != str(_admin_chat_id) and str(message.from_user.id) != str(_admin_chat_id):
        return await message.answer("⛔ Команда доступна только админу.")

    if not callable(_load_user_data):
        return await message.answer("⚠️ load_user_data не подключён.")

    data = _load_user_data() or {}

    # 💬 аргумент: /refstats <inviter_id>
    parts = (message.text or "").split(maxsplit=1)
    target_inviter = parts[1].strip() if len(parts) > 1 else ""

    # 💬 строим map inviter_id -> списки приглашённых
    inviter_map: dict[str, dict[str, list[str]]] = {}
    for uid, u in data.items():
        inviter = str(u.get("referred_by") or "").strip()
        if not inviter:
            continue

        st = (u.get("ref_status") or "clicked").strip()
        bucket = "clicked" if st != "qualified" else "qualified"

        inv = inviter_map.setdefault(inviter, {"clicked": [], "qualified": []})
        inv[bucket].append(str(uid))

    def _user_label(user_id: str) -> str:
        u = data.get(str(user_id), {}) or {}
        name = (u.get("name") or "").strip()
        tg = (u.get("tg_username") or "").strip()
        if tg:
            return f"{tg} ({user_id})"
        if name:
            return f"{name} ({user_id})"
        return f"{user_id}"

    # =========================
    # 1) ДЕТАЛЬНО ПО КОНКРЕТНОМУ
    # =========================
    if target_inviter:
        inv_id = target_inviter
        inv_data = inviter_map.get(inv_id, {"clicked": [], "qualified": []})

        inviter_u = data.get(inv_id, {}) or {}
        rb = _ensure_ref_bonus(inviter_u)
        _reset_cycle_if_expired(rb)

        qualified_cnt = int(rb.get("qualified", 0))
        stars = int(rb.get("stars", 0))
        days_left = _time_left_days(rb)
        pending = inviter_u.get("ref_pending", []) or []
        qualified_users = rb.get("qualified_users", []) or []

        text_out = (
            f"📊 <b>Реф-статистика</b>\n"
            f"Пригласивший = {_user_label(inv_id)}\n\n"
            f"👥 Засчитано = <b>{qualified_cnt}</b>\n"
            f"⭐ Звёзды = <b>{stars}</b>\n"
            f"⏳ До сброса = <b>{days_left}</b> дней\n\n"
            f"🟡 Нажали Start (clicked) = <b>{len(inv_data['clicked'])}</b>\n"
            f"🟢 Засчитаны (qualified) = <b>{len(inv_data['qualified'])}</b>\n\n"
            "🟡 Список clicked:\n"
        )

        if inv_data["clicked"]:
            text_out += "\n".join([f"• {_user_label(x)}" for x in inv_data["clicked"][:50]])
        else:
            text_out += "• нет"

        text_out += "\n\n🟢 Список qualified:\n"
        if inv_data["qualified"]:
            text_out += "\n".join([f"• {_user_label(x)}" for x in inv_data["qualified"][:50]])
        else:
            text_out += "• нет"

        # 💬 показываем внутренние списки (на случай расхождений)
        text_out += "\n\n(внутренние списки)\n"
        text_out += f"pending = {len(pending)}\n"
        text_out += f"qualified_users = {len(qualified_users)}\n"

        return await message.answer(text_out)

    # =========================
    # 2) ОБЩАЯ СВОДКА ПО ВСЕМ
    # =========================
    rows = []
    for inv_id, grp in inviter_map.items():
        inviter_u = data.get(inv_id, {}) or {}
        rb = _ensure_ref_bonus(inviter_u)
        _reset_cycle_if_expired(rb)

        rows.append({
            "inv_id": inv_id,
            "clicked": len(grp["clicked"]),
            "qualified": len(grp["qualified"]),
            "stars": int(rb.get("stars", 0)),
            "days_left": _time_left_days(rb),
        })

    # 💬 сортировка по засчитанным, затем по кликам
    rows.sort(key=lambda r: (r["qualified"], r["clicked"]), reverse=True)

    if not rows:
        return await message.answer("Пока нет реф-переходов.")

    lines = ["📊 <b>Реф-статистика (сводка)</b>\n"]
    for r in rows[:30]:
        lines.append(
            f"• {_user_label(r['inv_id'])}\n"
            f"  clicked={r['clicked']} | qualified={r['qualified']} | ⭐{r['stars']} | ⏳{r['days_left']}д\n"
            f"  /refstats {r['inv_id']}"
        )

    return await message.answer("\n".join(lines))








