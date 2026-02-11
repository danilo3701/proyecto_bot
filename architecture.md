# Architecture.md

## Overview

Telegram-бот на **aiogram 3.x** для обучения испанскому языку. Архитектура построена на модульной системе фич с чётким разделением слоёв: handlers → services → storage → utils. Основной принцип: **clean chat** (edit вместо send, удаление временных сообщений, минимизация спама).

**Deployment:** Railway с persistent storage в `/data/` volume.

---

## Core Principles

### Architectural Layers

```
┌─────────────────────────────────────┐
│   UI / Handlers / Routers           │  ← Обработка событий Telegram
├─────────────────────────────────────┤
│   Dialog / Scenario Logic           │  ← Диалоговые ветки и сценарии
├─────────────────────────────────────┤
│   Services / Business Logic         │  ← Бизнес-логика фич
├─────────────────────────────────────┤
│   Storage / Data Layer              │  ← JSON в /data/ volume
├─────────────────────────────────────┤
│   Utilities / Helpers               │  ← Clean chat, atomic save, etc.
└─────────────────────────────────────┘
```

### Clean Chat Standard

**Правило:** Telegram-чат должен быть чистым. Никаких дублей сообщений, никаких "висячих" промптов.

**Механики:**
- **edit вместо send:** всегда `bot.edit_message_text()` для обновления существующих сообщений
- **delete user input:** после получения ответа пользователя удаляем его сообщение (`_safe_delete_message(message.message_id)`)
- **answer() для callback:** всегда `cb.answer()` чтобы убрать "loading..." у кнопки
- **TTL deletion:** временные промпты удаляются через N секунд (`send_and_auto_delete_text(delay=3.0)`)
- **cleanup last bot message:** храним `lex_last_bot_msg_id` в state и удаляем перед отправкой нового

**Утилиты:**
- `_safe_delete_message(chat_id, message_id)` — безопасное удаление (не падает на ошибках)
- `send_and_auto_delete_text(bot, chat_id, text, delay=3.0)` — отправка + авто-удаление через delay
- `_delete_messages_after_delay(chat_id, message_ids, delay=10.0)` — массовое TTL удаление
- `_lex_cleanup_last_bot_message(chat_id, state)` — очистка прошлого сообщения бота в потоке "Учить слова"

### No False Success Rule

**Правило:** Если сервис/handler вернул "ok" пользователю, должно быть реальное сохранение в storage и ререндер UI.

**Точки проверки:**
- После добавления темы → `atomic_save_json()` → reload topics → обновить меню
- После прохождения урока → сохранить XP → обновить прогресс-бар
- После оплаты Premium → записать в `premium_users.json` → разблокировать контент

---

## File Map

### Core Files

#### `core8_1.py` (13,702 lines)
**Назначение:** Главный файл бота. Точка входа, регистрация роутеров, FSM, middleware.

**Импорты:**
- `aiogram` (Bot, Dispatcher, MemoryStorage)
- Feature routers: `battle_feature`, `bonuses_feature`, `referral_feature`, `podcasts_feature`, `grammar_feature`
- Admin router: `create_lesson_block`
- Scenario logic: `scenarios_estiloso8_1`, `scenario/*_block.py`

**Handlers (примеры):**
- `/start` → `start_handler()` — показ главного меню
- `menu:learn` callback → выбор категории (лексика/грамматика)
- Vocab/Exercise/Video flows (НЕ ВИЖУ В ФАЙЛАХ: полный список handlers, нужно увидеть все @dp.message/@dp.callback_query декораторы)

**Dependencies:**
- Read: `/data/topics/*.json` (темы уроков)
- Read/Write: `xp_data.json`, `user_data.json`, `premium_users.json` (НЕ ВИЖУ В ФАЙЛАХ: точные пути, предполагаю по аналогии с battle_data.json)
- Write: handler_history (для LoggingMiddleware)

**Storage keys in FSM:**
- `selected_topic` — ключ текущей темы
- `selected_phase_id` — ID фазы в vocab
- `lex_last_bot_msg_id` — ID последнего сообщения бота (для cleanup)
- `lex_session_vocab_list` — сессия раунда (ALL IN режим)
- НЕ ВИЖУ В ФАЙЛАХ: полный список FSM keys, нужно увидеть все `state.update_data()` вызовы

**Middlewares:**
- `LoggingMiddleware` — трекинг handler_history, отправка ошибок админу

**Special fixes:**
- `business_connection_id` wrapper — приведение int → str для aiogram Pydantic

---

#### `create_lesson_block.py` (5,426 lines)
**Назначение:** Админский интерфейс для создания/редактирования тем и уроков.

**Handlers:**
- НЕ ВИЖУ В ФАЙЛАХ: конкретные команды и callback, нужно увидеть @router.message/@router.callback_query

**Storage:**
- Read/Write: `/data/topics/*.json` (прямая работа через `atomic_save_json()`)

**FSM keys:**
- `ADMIN_INLINE_MSG_ID_KEY` — ID inline-меню (для edit)
- `ADMIN_TOPIC_MAP_KEY` — tid → filename stem
- `ADMIN_EDIT_MODE_KEY`, `ADMIN_EDIT_CATEGORY_KEY`, `ADMIN_EDIT_LEVEL_KEY` — фильтрованное редактирование
- `ADMIN_CURRENT_TID_KEY` — текущая открытая тема
- `ADMIN_EDIT_VIEW_KEY`, `ADMIN_EDIT_SCOPE_KEY`, `ADMIN_EDIT_PAGE_KEY` — навигация в админке
- `ADMIN_EDIT_PHASE_INDEX_KEY`, `ADMIN_EDIT_PACK_INDEX_KEY` — индексы фаз/паков
- `ADMIN_PENDING_ACTION_KEY`, `ADMIN_PENDING_INSERT_KIND_KEY` — pending операции (delete/move/insert)

**Utilities:**
- `atomic_save_json(path, data)` — атомарное сохранение JSON (tmp → replace)
- `_ikb(rows)` — конструктор InlineKeyboardMarkup
- `_inline_replace(cb, state, text, kb)` — edit inline-меню
- `_inline_open(message, state, text, kb)` — открыть новое inline-меню

**Clean chat:**
- Всегда edit существующего меню (`cb.message.edit_text()`)
- Fallback на `message.answer()` если edit невозможен
- Удаление старого меню при открытии нового

---

### Feature Modules

#### `battle_feature.py` (1,363 lines)
**Назначение:** Модуль "Битва" — соревнование пользователей по темам.

**Router:** `battle_router`

**FSM States:**
- `Battle.Future` — выбор темы битвы
- `Battle.Match` — загрузка соперника
- `Battle.Running` — бой идёт
- `Battle.Result` — результат + реванш/меню
- `BattleTopicsAdmin.*` — админка тем битвы

**Storage:**
- `/data/battle_data.json` — очки пользователей
- `/data/battle_topics.json` — темы для битв

**Functions:**
- `set_topics_ref(topics)` — передача ссылки на topics из core8_1 (избежание кругового импорта)
- `set_battle_links(contact_url, materials_url, bot_username)` — передача CONTACT_URL и т.д.
- `start_battle_from_lex_menu()` — НЕ ВИЖУ В ФАЙЛАХ: сигнатура, нужно увидеть
- `cancel_battle_if_running()` — НЕ ВИЖУ В ФАЙЛАХ: сигнатура
- `load_battle_data()` — чтение battle_data.json

**Constants:**
- `BATTLE_DURATION_S = 60`
- `BOT_SCORE_EVERY_S = 5`
- `POLL_TIME_S = 7`
- `MAX_QUESTIONS_PER_BATTLE` — кол-во раундов

**Handlers:**
- НЕ ВИЖУ В ФАЙЛАХ: полный список, нужно увидеть все @router.message/@router.callback_query

---

#### `bonuses_feature.py` (34K)
**Назначение:** Модуль "Бонусы" — реферальная система, достижения.

**Router:** `bonuses_router`

**Functions (экспортируемые):**
- `init_bonus_feature(...)` — НЕ ВИЖУ В ФАЙЛАХ: параметры
- `bonuses_open(...)` — НЕ ВИЖУ В ФАЙЛАХ: параметры
- `bonus_register_referral_from_start(...)` — НЕ ВИЖУ В ФАЙЛАХ: параметры
- `bonus_try_qualify_referral(...)` — НЕ ВИЖУ В ФАЙЛАХ: параметры

НЕ ВИЖУ В ФАЙЛАХ: нужно содержимое bonuses_feature.py для деталей

---

#### `referral_feature.py` (28K)
**Назначение:** Реферальная система.

**Router:** `referral_router`

**Functions (экспортируемые):**
- `referrals_try_bind_on_start(...)`
- `referrals_apply_invoice_paid(...)`
- `referrals_apply_subscription_status(...)`

НЕ ВИЖУ В ФАЙЛАХ: нужно содержимое referral_feature.py для деталей

---

#### `podcasts_feature.py` (97K)
**Назначение:** Модуль "Подкасты" — аудио/видео контент.

**Router:** `podcasts_router`

**Functions:**
- `init_podcasts_feature(...)`
- `podcasts_open(...)`

НЕ ВИЖУ В ФАЙЛАХ: нужно содержимое podcasts_feature.py для деталей

---

#### `grammar_feature.py` (95K)
**Назначение:** Модуль "Грамматика".

**Router:** `grammar_router`

**Functions:**
- `init_grammar_feature(...)`
- `set_topics_ref(topics)`
- `open_grammar_topic(...)`

НЕ ВИЖУ В ФАЙЛАХ: нужно содержимое grammar_feature.py для деталей

---

### Scenario Files

#### `scenarios_estiloso8_1.py` (749 lines)
**Назначение:** Диалоговые сценарии для обучения. Централизованное хранилище всех диалоговых веток.

**Структура сценария:**
```python
{
    "text": "Вопрос пользователю",
    "buttons": ["Кнопка 1", "Кнопка 2"],
    "replies": {
        "Кнопка 1": {"reaction": "Реакция", "next": "next_block_id"},
        "Кнопка 2": {"reaction": "Реакция", "next": "another_block_id"}
    }
}
```

**Экспортируемые сценарии:**
- `after_text` — после показа текстового блока (1 кнопка "Ага!")
- `after_photo` — после показа фото
- `after_quiz` — после quiz-блока
- `exercise_start_phrases` — вступительные фразы для упражнений
- `motivational_quotes` — мотивационные цитаты для главного меню
- `link_cta_phrases` — CTA для link-блоков
- `follow_up_phrases` — общие follow-up фразы
- `custom_progress_emojis` — эмоджи для прогресса
- `start_stickers`, `menu_study_phrases`, `difficulty_intro_phrases`
- `vocab_start_phrases`, `vocab_return_phrases`, `vocab_quiz_intro_phrases`, `vocab_quiz_progress_phrases`
- `go_next_phrases`
- `congrats_media`, `refusal_stickers` — стикеры/гифки

**Используется в:**
- `core8_1.py` — импортирует все списки фраз/сценариев
- Feature modules — импортируют `menu_study_phrases` и т.д.

---

#### `scenario/confirm_done_block.py`
**Назначение:** Сценарий подтверждения "Ты выполнил задание?"

**Экспорт:**
- `confirm_done` — список из ~17 вариантов

**Структура:**
- Вопрос + 2 кнопки (Да/Нет)
- Да → `{"next": "feedback_difficulty"}`
- Нет → `{"next": "refusal"}`

**Используется в:**
- `core8_1.py` — импортирует в `scenarios["confirm_done"]`

---

#### `scenario/feedback_difficulty_block.py`
**Назначение:** Сценарий обратной связи "Было легко?"

**Экспорт:**
- `feedback_difficulty` — список из ~12 вариантов

**Структура:**
- Вопрос + 2 кнопки (Легко/Сложно)
- Оба варианта → `{"next": "offer_continue"}`

---

#### `scenario/offer_continue_block.py`
**Назначение:** Сценарий "Продолжить или домой?"

**Экспорт:**
- `offer_continue` — список из ~13 вариантов

**Структура:**
- Вопрос + 2 кнопки (Дальше/Домой)
- Дальше → `{"next": "next_item"}`
- Домой → `{"next": "home"}`

---

#### `scenario/refusal_block.py`
**Назначение:** Сценарий отказа "Дать ещё шанс?"

**Экспорт:**
- `refusal` — список из 5 вариантов

**Структура:**
- Вопрос + 2 кнопки (Попробую ещё/Домой)
- Попробую ещё → `{"next": "repeat_current"}`
- Домой → `{"next": "home"}`

---

#### `scenario/quiz_reactions.py`
**Назначение:** Позитивные реакции на правильный ответ в квизе.

**Экспорт:**
- `vocab_quiz_success_phrases` — 33 фразы типа "Красава! 😎", "Вау! 🔥"

**Используется в:**
- НЕ ВИЖУ В ФАЙЛАХ: где именно используется, предполагаю в quiz handlers

---

### Config Files

#### `subscription_channels.json`
```json
{
  "channels": [
    "@espanolingooo",
    "@neispansky",
    "@espanolingooo_books"
  ]
}
```
**Назначение:** Список обязательных каналов для подписки.

НЕ ВИЖУ В ФАЙЛАХ: где используется, предполагаю в subscription check handler

---

#### `requirements.txt`
```
aiogram
stripe
Pillow
```

---

## Flow Map

### Main User Flows

#### Flow: Start → Menu → Action

**Вход:**
- `/start` command → `start_handler()`

**Действия:**
- Показ главного меню с категориями
- НЕ ВИЖУ В ФАЙЛАХ: полный список кнопок меню, вижу только упоминания в battle_feature (_battle_main_menu_kb)

**Выход:**
- Edit главного меню при возврате
- НЕ ВИЖУ В ФАЙЛАХ: где именно происходит edit, нужно увидеть menu callbacks

**State changes:**
- НЕ ВИЖУ В ФАЙЛАХ: какие FSM states используются

**Cleanup:**
- НЕ ВИЖУ В ФАЙЛАХ: какие ключи удаляются при выходе из flow

---

#### Flow: Vocab Learning

**Вход:**
- `menu:learn` → выбор темы → фаза → элемент

**Действия:**
1. Показ элемента (link/text/photo/quiz)
2. Сценарий `after_*` (вопрос + кнопки)
3. Переход к `confirm_done`
4. Если Да → `feedback_difficulty` → `offer_continue`
5. Если Нет → `refusal`

**State keys (из кода):**
- `selected_topic` — ключ темы
- `selected_phase_id` — ID фазы
- `lex_last_bot_msg_id` — последнее сообщение бота (для cleanup)
- `lex_session_vocab_list` — список элементов раунда (ALL IN режим)
- `lex_mode_active` — флаг активного режима

**Edit strategy:**
- При показе нового элемента: удалить `lex_last_bot_msg_id`, отправить новое, сохранить новый ID
- При переходе между сценариями: edit последнего сообщения

**Cleanup:**
- `_lex_cleanup_last_bot_message()` перед новым элементом
- Удаление промптов с TTL (`send_and_auto_delete_text`)

НЕ ВИЖУ В ФАЙЛАХ: точные handlers для каждого шага, нужно увидеть все is_confirm_done_vocab и подобные фильтры

---

#### Flow: Battle

**Вход:**
- `menu:battle` → выбор темы → `Battle.Future`

**Действия:**
1. Выбор темы битвы
2. `Battle.Match` — загрузка соперника
3. `Battle.Running` — раунды квизов (POLL_TIME_S каждый)
4. `Battle.Result` — итоги + реванш/меню

**State:**
- `Battle.*` states
- НЕ ВИЖУ В ФАЙЛАХ: какие данные хранятся в state

**Storage:**
- Write: `/data/battle_data.json` — очки после боя
- Read: `/data/battle_topics.json` — темы

**Cleanup:**
- НЕ ВИЖУ В ФАЙЛАХ: какие сообщения удаляются, где cleanup

---

#### Flow: Admin Topic Creation

**Вход:**
- НЕ ВИЖУ В ФАЙЛАХ: команда для входа в админку

**Действия:**
1. Inline-меню админки
2. Выбор действия (создать/редактировать/удалить)
3. Ввод данных (название, категория, level)
4. Сохранение через `atomic_save_json()`
5. Reload topics
6. Edit меню с обновлённым списком

**State keys:**
- `ADMIN_INLINE_MSG_ID_KEY` — ID меню
- `ADMIN_CURRENT_TID_KEY` — текущая тема
- `ADMIN_EDIT_*` — параметры редактирования

**Edit strategy:**
- Всегда `_inline_replace()` — edit существующего меню
- Fallback на `message.answer()` только если edit невозможен

**Cleanup:**
- Удаление старого меню при открытии нового (`_inline_open()`)
- НЕ ВИЖУ В ФАЙЛАХ: удаление ввода пользователя

---

### Special Flows

#### Flow: phrase_selector (ALL IN режим)

**Вход:**
- Vocab элемент с `type: "phrase_selector"`

**Действия:**
1. Показ списка фраз (es = ru)
2. Пользователь вводит номера известных фраз
3. Парсинг ввода → фильтрация фраз
4. Сборка квизов на неизвестные фразы
5. Сохранение в `lex_session_vocab_list`

**Функции (из кода):**
- `_lex_render_phrase_list(phrases)` — рендер списка фраз
- `get_vocab_list(data)` — логика сборки списка элементов

НЕ ВИЖУ В ФАЙЛАХ: полный handler для phrase_selector, нужно увидеть код

---

## Storage & Data Rules

### Storage Locations

**Railway Volume (`/data/`):**
- `/data/topics/*.json` — темы уроков (main content)
- `/data/battle_data.json` — очки битв
- `/data/battle_topics.json` — темы битв

**Предполагаемые (НЕ ВИЖУ В ФАЙЛАХ, но упоминаются):**
- `xp_data.json` — XP и аналитика пользователей
- `user_data.json` — настройки пользователей
- `premium_users.json` — Premium статусы

### Data Rules

**Atomic Save:**
- Всегда используем `atomic_save_json(path, data)`
- Механизм: запись в `.tmp` → `os.replace()` → гарантия целостности

**No False Success:**
- После каждого успешного действия пользователя → сохранение в storage
- После сохранения → reload данных → ререндер UI
- НЕ ВИЖУ В ФАЙЛАХ: где именно происходит reload topics после сохранения, предполагаю в create_lesson_block callbacks

**TTL Keys:**
- `lex_last_bot_msg_id` — удаляется при следующем элементе
- `ADMIN_INLINE_MSG_ID_KEY` — удаляется при новом меню
- НЕ ВИЖУ В ФАЙЛАХ: полный список временных ключей FSM

**Persistent Keys:**
- `selected_topic`, `selected_phase_id` — живут весь flow
- НЕ ВИЖУ В ФАЙЛАХ: когда именно очищаются

---

## Utilities & Helpers

### Clean Chat Utilities

```python
# Безопасное удаление (не падает)
async def _safe_delete_message(chat_id: int, message_id: int | None)

# Отправка + TTL удаление
async def send_and_auto_delete_text(bot, chat_id, text, delay=3.0)

# Массовое TTL удаление
async def _delete_messages_after_delay(chat_id: int, message_ids: list, delay=10.0)

# Cleanup последнего сообщения бота
async def _lex_cleanup_last_bot_message(chat_id: int, state: FSMContext)

# Рандомный текст + TTL удаление
async def send_and_auto_delete_random_text(bot, chat_id, texts=LINK_HINT_TEXTS, delay=3.0)
```

### Storage Utilities

```python
# Атомарное сохранение JSON
def atomic_save_json(path: str | Path, data: dict) -> bool

# Путь к topics
def get_topics_dir() -> Path  # -> /data/topics

# Загрузка topics
def load_topics_from_volume() -> dict

# Проверка что файл в Railway Volume
def _is_railway_topics_file(path: str | Path) -> bool
```

### Inline Menu Utilities (create_lesson_block)

```python
# Конструктор InlineKeyboardMarkup
def _ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup

# Edit inline-меню (clean chat)
async def _inline_replace(cb: CallbackQuery, state: FSMContext, text: str, kb: InlineKeyboardMarkup)

# Открыть новое inline-меню (удалить старое)
async def _inline_open(message: Message, state: FSMContext, text: str, kb: InlineKeyboardMarkup)

# Вставка в список по 1-based индексу
def _insert_or_append(target_list: list, item, insert_index)
```

### Vocab/Phase Utilities

```python
# Получить список элементов vocab для фазы
def get_vocab_list(data: dict) -> list

# Получить выбранную фазу
def _lex_get_selected_phase(data: dict) -> dict | None

# Рендер списка фраз для phrase_selector
def _lex_render_phrase_list(phrases: list) -> str

# Получить фазу по topic_key + phase_id
def _get_vocab_phase(topic_key: str, phase_id: str) -> dict

# Фильтрация активных фраз (без hidden)
def _get_active_phrase_indexes(phrases: list, hidden: set) -> list
```

### Premium/Stripe Utilities

НЕ ВИЖУ В ФАЙЛАХ: полный список, вижу только упоминания:
- `_premium_paywall_text(user_id)` — текст Premium экрана
- `_premium_paywall_kb(back_cb)` — клавиатура с кнопками оплаты
- `_stripe_get_subscription_period_end(subscription_id)` — получить срок подписки
- `_stripe_guess_plan_from_subscription(subscription_id)` — определить тариф

---

## Risk Map

### Типовые риски и точки проверки

#### Risk: Дубли handlers
**Где смотреть:**
- `core8_1.py` — все `@dp.message`, `@dp.callback_query`
- Feature routers — все `@router.message`, `@router.callback_query`

**Проверка:**
- Нет ли двух handlers на один и тот же callback_data?
- Нет ли двух handlers на одно и то же состояние?

НЕ ВИЖУ В ФАЙЛАХ: полный список handlers, нужно увидеть весь код

---

#### Risk: Несоответствие state
**Где смотреть:**
- FSM states в feature modules (Battle, BattleTopicsAdmin, etc.)
- НЕ ВИЖУ В ФАЙЛАХ: основные FSM states в core8_1

**Проверка:**
- Все ли переходы между states корректны?
- Нет ли зависших states без выхода?

---

#### Risk: Callback без answer()
**Где смотреть:**
- Все callback handlers

**Проверка:**
- Каждый `@dp.callback_query` должен вызывать `cb.answer()`
- Проверить наличие в `try/except` блоках

НЕ ВИЖУ В ФАЙЛАХ: примеры callback handlers, нужно увидеть код

---

#### Risk: Несохранение данных
**Где смотреть:**
- Все места где пользователь получает "успех" (feedback, поздравления)
- create_lesson_block — после редактирования темы

**Проверка:**
- После успешного действия должен быть `atomic_save_json()`
- После save должен быть reload данных
- После reload должен быть ререндер UI (edit меню)

**Точки проверки (примеры):**
- После завершения урока → сохранить XP → обновить статистику
- После добавления темы → `atomic_save_json()` → `topics = load_topics_from_volume()` → edit меню
- НЕ ВИЖУ В ФАЙЛАХ: точные handlers, нужно увидеть код

---

#### Risk: Неочищенные временные ключи FSM
**Где смотреть:**
- Все `state.update_data()` с временными ключами

**Проверка:**
- Все `*_last_bot_msg_id` должны очищаться при выходе из flow
- Все `ADMIN_PENDING_*` должны очищаться после завершения операции
- НЕ ВИЖУ В ФАЙЛАХ: где именно происходит cleanup, нужно увидеть код

**Потенциальные утечки:**
- `lex_last_bot_msg_id` — если не вызвать `_lex_cleanup_last_bot_message()`
- `ADMIN_INLINE_MSG_ID_KEY` — если не вызвать `_inline_open()` при новом меню

---

#### Risk: Спам сообщений (нарушение clean chat)
**Где смотреть:**
- Все места где отправляются новые сообщения вместо edit

**Проверка:**
- Все обновления UI должны идти через `bot.edit_message_text()`
- Исключения: первое сообщение flow, fallback если edit невозможен
- НЕ ВИЖУ В ФАЙЛАХ: все места send vs edit, нужно увидеть код

**Bad pattern:**
```python
await message.answer("Обновление")  # спам!
```

**Good pattern:**
```python
await bot.edit_message_text(chat_id=..., message_id=msg_id, text="Обновление")
```

