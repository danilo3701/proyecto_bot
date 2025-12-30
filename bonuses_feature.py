# bonuses_feature.py
# 💬 модуль «🎁 Бонусы» = рефералка + заявка на подарок (выдача вручную)

import time
import logging
from urllib.parse import quote

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.exceptions import TelegramBadRequest


router = Router()

# 💬 зависимости подставляем из core8_1.py через init_bonus_feature()
_load_user_data = None
_save_user_data = None
_load_subscription_channels = None
_LessonStates = None

_admin_chat_id: int | None = None
_friends_needed: int = 2

_materials_url: str = ""
_contact_url: str = ""

# 💬 если хочешь жёстко зафиксировать главный канал = поставь сюда "@espanolingooo"
_main_channel_override: str | None = None


def init_bonus_feature(
    *,
    load_user_data,
    save_user_data,
    load_subscription_channels,
    LessonStates,
    materials_url: str,
    contact_url: str,
    admin_chat_id: int,
    friends_needed: int = 2,
    main_channel_override: str | None = None
):
    # 💬 что делает эта часть: пробрасываем зависимости из core8_1.py, чтобы не было циклических импортов
    global _load_user_data, _save_user_data, _load_subscription_channels, _LessonStates
    global _admin_chat_id, _friends_needed, _materials_url, _contact_url, _main_channel_override

    _load_user_data = load_user_data
    _save_user_data = save_user_data
    _load_subscription_channels = load_subscription_channels
    _LessonStates = LessonStates

    _admin_chat_id = int(admin_chat_id)
    _friends_needed = int(friends_needed)

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


def _ensure_ref_bonus(u: dict) -> dict:
    # 💬 что делает эта часть: гарантируем структуру в user_data для реф-бонусов
    rb = u.setdefault("ref_bonus", {})
    rb.setdefault("qualified", 0)
    rb.setdefault("qualified_users", [])
    rb.setdefault("claim_status", "none")  # none | pending | issued | declined
    rb.setdefault("claim_requested_at", 0)
    rb.setdefault("claim_issued_at", 0)
    return rb


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
    💬 Засчитываем друга, когда он прошёл проверку подписки (в core8_1.py).
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

    qualified_users = rb.setdefault("qualified_users", [])
    if str(user_id) not in qualified_users:
        qualified_users.append(str(user_id))
        rb["qualified"] = int(rb.get("qualified", 0)) + 1

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

    q = int(rb.get("qualified", 0))
    can_claim = q >= _friends_needed and rb.get("claim_status") not in ("pending", "issued")

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📨 Пригласить друга", callback_data="bonuses:share")],
        [
            InlineKeyboardButton(text="🔗 Моя ссылка", callback_data="bonuses:link"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="bonuses:refresh"),
        ],
    ]

    if can_claim:
        rows.append([InlineKeyboardButton(text="🎁 Получить подарок", callback_data="bonuses:claim")])
    else:
        rows.append([InlineKeyboardButton(text="🔒 Получить подарок", callback_data="bonuses:locked")])

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
    _save_user_data(data)

    qualified = int(rb.get("qualified", 0))
    main_ch = _get_main_channel()

    text_out = (
        "🎁 <b>Бонусы</b>\n\n"
        f"Прогресс = <b>{qualified}/{_friends_needed}</b>\n\n"
        "Как засчитывается друг:\n"
        "1) Переходит по твоей ссылке\n"
        f"2) Подписывается на канал {main_ch}\n"
        "3) Заходит в тему и набирает минимум XP\n\n"
        "💬 На деле бот проверяет подписку, XP не считаем\n"
    )

    kb = _build_bonuses_kb(uid)

    try:
        await message.edit_text(text_out, reply_markup=kb)
    except TelegramBadRequest:
        await message.answer(text_out, reply_markup=kb)

    # 💬 остаёмся в choosing_category, чтобы главное меню продолжало работать
    if _LessonStates:
        try:
            await state.set_state(_LessonStates.choosing_category)
        except Exception:
            pass


@router.callback_query(F.data == "bonuses:refresh")
async def bonuses_refresh(callback: CallbackQuery, state):
    await callback.answer()
    return await bonuses_open(callback.message, state)  # 💬 перерисовываем экран


@router.callback_query(F.data == "bonuses:locked")
async def bonuses_locked(callback: CallbackQuery):
    # 💬 что делает эта часть: мягко объясняем, почему «получить» пока нельзя
    await callback.answer("Нужно 2/2 приглашённых, чтобы получить подарок.", show_alert=True)


@router.callback_query(F.data == "bonuses:link")
async def bonuses_send_link(callback: CallbackQuery):
    await callback.answer()
    me = await callback.bot.get_me()  # 💬 берём @username бота

    uid = str(callback.from_user.id)
    link = f"https://t.me/{me.username}?start=ref_{uid}"

    await callback.message.answer(
        f"🔗 Твоя ссылка:\n{link}\n\n"
        "Скопируй и отправь другу.",
        reply_markup=ReplyKeyboardRemove()
    )


@router.callback_query(F.data == "bonuses:share")
async def bonuses_share(callback: CallbackQuery):
    await callback.answer()
    me = await callback.bot.get_me()  # 💬 берём @username бота

    uid = str(callback.from_user.id)
    link = f"https://t.me/{me.username}?start=ref_{uid}"

    text_msg = (
        "Залетай в мой тренажёр по испанскому 😎\n"
        "Жми Start, подпишись на канал и начни учиться.\n"
    )

    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote(text_msg)}"
    await callback.message.answer(
        "📨 Нажми и поделись ссылкой:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Поделиться", url=share_url)]
        ])
    )


def _build_main_menu_kb() -> InlineKeyboardMarkup:
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
    await callback.answer()
    kb = _build_main_menu_kb()

    try:
        await callback.message.edit_text("Что изучаем?⭐", reply_markup=kb)  # 💬 возвращаем главное меню
    except TelegramBadRequest:
        await callback.message.answer("Что изучаем?⭐", reply_markup=kb)

    if _LessonStates:
        try:
            await state.set_state(_LessonStates.choosing_category)
        except Exception:
            pass


@router.callback_query(F.data == "bonuses:claim")
async def bonuses_claim(callback: CallbackQuery, state):
    await callback.answer()

    if _admin_chat_id is None:
        return await callback.message.answer("⚠️ Админ-чат не настроен.")

    uid = str(callback.from_user.id)

    data = _load_user_data()
    u = data.setdefault(uid, {})
    rb = _ensure_ref_bonus(u)

    qualified = int(rb.get("qualified", 0))
    if qualified < _friends_needed:
        return await callback.message.answer("🔒 Пока рано = нужно 2/2 приглашённых.")

    if rb.get("claim_status") in ("pending", "issued"):
        return await callback.message.answer("⏳ Заявка уже отправлена или отмечена как выданная.")

    rb["claim_status"] = "pending"
    rb["claim_requested_at"] = int(time.time())
    _save_user_data(data)

    # 💬 пишем админу заявку
    user_tag = callback.from_user.username
    user_tag = f"@{user_tag}" if user_tag else "(нет username)"

    admin_text = (
        "🎁 <b>Заявка на подарок</b>\n\n"
        f"Пользователь = {callback.from_user.full_name}\n"
        f"Username = {user_tag}\n"
        f"User ID = <code>{uid}</code>\n\n"
        f"Прогресс = {qualified}/{_friends_needed}\n"
        "После отправки подарка нажми «✅ Выдано»."
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выдано", callback_data=f"bonuses_admin:issued:{uid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"bonuses_admin:decline:{uid}"),
        ]
    ])

    await callback.bot.send_message(_admin_chat_id, admin_text, reply_markup=admin_kb)

    await callback.message.answer(
        "✅ Заявка отправлена админу.\n"
        "Жди = я пришлю тебе подарок вручную."
    )

    return await bonuses_open(callback.message, state)  # 💬 обновляем экран


@router.callback_query(F.data.startswith("bonuses_admin:"))
async def bonuses_admin_actions(callback: CallbackQuery):
    await callback.answer()

    if _admin_chat_id is None:
        return

    # 💬 разрешаем кнопки только админу
    if int(callback.from_user.id) != int(_admin_chat_id):
        return await callback.answer("⛔ Только админ.", show_alert=True)

    action, uid = callback.data.split(":", 2)[1], callback.data.split(":", 2)[2]

    data = _load_user_data()
    u = data.setdefault(str(uid), {})
    rb = _ensure_ref_bonus(u)

    if action == "issued":
        rb["claim_status"] = "issued"
        rb["claim_issued_at"] = int(time.time())
        _save_user_data(data)

        await callback.message.edit_text("✅ Отмечено как выдано.")  # 💬 закрываем заявку
        try:
            await callback.bot.send_message(int(uid), "🎉 Подарок отмечен как выданный. Спасибо!")
        except Exception:
            pass
        return

    if action == "decline":
        rb["claim_status"] = "declined"
        _save_user_data(data)

        await callback.message.edit_text("❌ Отклонено.")
        try:
            await callback.bot.send_message(int(uid), "❌ Заявка отклонена. Напиши админу, если считаешь что это ошибка.")
        except Exception:
            pass
        return
