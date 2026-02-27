# Premium Architecture (core8_1.py + podcasts_feature.py + mywords_repository.py)

## 1) Что это за контур Premium

Этот документ собирает **полный контекст по Premium-подписке** в проекте на основе файлов:
- `core8_1.py`
- `podcasts_feature.py` (по смыслу это ваш «podcast.py»)
- `mywords_repository.py` (хранилище для «mywords»)

> Важно: по коду подключение оплаты сделано через **Stripe** (возможно, это то, что вы называете «трипл»).

---

## 2) Главная идея архитектуры

В проекте есть **единый источник истины Premium** — файл:
- `/data/premium_users.json`

В этом файле хранятся:
- срок действия (`active_until`),
- план (`plan`),
- связи `stripe_customer_id` и `stripe_subscription_id`.

Далее этот статус используется в 3 местах продукта:
1. **Лексика** (блокировка тем после free-лимита).
2. **Подкасты** (доступ к эпизодам сверх free-лимита и Premium-авторы).
3. **MyWords** (лимиты на количество категорий и слов в категории).

---

## 3) Компоненты и их роли

## 3.1 `core8_1.py` — центральный оркестратор

Отвечает за:
- загрузку/сохранение `premium_users.json`,
- функцию проверки `is_premium_active(user_id)`,
- Stripe webhook (`/stripe/webhook`),
- обновление Premium-статуса при событиях Stripe,
- paywall/кнопки проверки в интерфейсе,
- применение Premium-ограничений в лексике и MyWords,
- инициализацию модуля подкастов (`init_podcasts_feature(...)`).

## 3.2 `podcasts_feature.py` — модуль подкастов

Отвечает за:
- доступ к подкастам,
- свой paywall внутри подкастов,
- проверку Premium через `_premium_active(user_id)`,
- fallback-чтение разных premium-файлов (`premium_users.json`, `premium_access.json` и т.д.),
- показ кнопки «✅ Проверить Premium» и возврат в экран подкастов.

## 3.3 `mywords_repository.py` — хранилище данных MyWords

Сам по себе не знает про Premium, но обеспечивает:
- атомарные записи JSON,
- backup,
- lock (защита от гонок),
- нормализацию структуры данных.

Premium-правила для MyWords применяются в `core8_1.py`, а не в репозитории.

---

## 4) Данные и файлы (что где лежит)

## 4.1 Premium
- `/data/premium_users.json` — основной файл (истина для Premium).
- `/data/premium_users.backup.json` — резервная копия.
- `/data/premium_access.json` — дополнительный/fallback формат (используется в подкастах).

Поддерживаемые поля времени действия (в разных форматах):
- `active_until` (основной),
- `until_ts` (fallback),
- `premium_until` (legacy).

## 4.2 Подкасты
- `/data/podcasts_data.json` — данные авторов/эпизодов/фрагментов.
- `/data/podcast_notes/<user_id>.json` — заметки пользователя по подкастам.

## 4.3 MyWords
- путь к данным задается через `MY_WORDS_PATH` / `MY_WORDS_BACKUP_PATH` и работает через `MyWordsRepository`.

---

## 5) Подключение «через трипл/Stripe»: как идёт поток оплаты

## 5.1 Шаг 1. Пользователь открывает paywall

Paywall есть как минимум в:
- лексике (locked topics),
- настройках «💎 Моя подписка»,
- подкастах,
- mywords при превышении free-лимитов.

Пользователю показываются ссылки оплаты:
- `PREMIUM_PAYLINK_WEEK`
- `PREMIUM_PAYLINK_MONTH`
- `PREMIUM_PAYLINK_YEAR`

## 5.2 Шаг 2. Оплата в Stripe

В тексте paywall пользователю показывается его Telegram ID и просьба указать его при оплате.

Это критично, потому что потом в webhook бот должен понять, **какому Telegram user** выдать Premium.

## 5.3 Шаг 3. Stripe webhook приходит в `core8_1.py`

HTTP-сервер поднимает endpoint:
- `POST /stripe/webhook`

Дальше обработка `_stripe_process_event(event)`:

- `checkout.session.completed`
  - извлекается Telegram ID из `custom_fields`,
  - определяется `subscription_id`, `customer_id`,
  - вычисляется `active_until`,
  - вызывается `_set_premium_user(...)`.

- `invoice.paid` / `invoice.payment_succeeded`
  - продление подписки,
  - поиск пользователя по картам соответствия (`subscription/customer -> user_id`),
  - обновление `active_until`.

- `customer.subscription.updated`
  - синхронизация статуса,
  - при плохих статусах (`canceled`, `unpaid`, `past_due`, ...)
    Premium выключается (`active_until` в прошлое).

- `customer.subscription.deleted`
  - отключение Premium.

## 5.4 Шаг 4. Проверка Premium в интерфейсе

После оплаты пользователь жмёт «✅ Проверить Premium»:
- в лексике: callback `premium:check`,
- в подкастах: callback `pod:premium_check`,
- в настройках: `premium:check_settings`.

Если `is_premium_active == True`, замки снимаются.

---

## 6) Где именно Premium влияет на доступ

## 6.1 Лексика (`core8_1.py`)

В `show_topics_for_category_level(...)`:
- если категория `lex`,
- и Premium не активен,
- после `FREE_TOPICS_LIMIT` темы становятся locked,
- callback ведёт в `premium:topic:<key>` (paywall).

## 6.2 Подкасты (`podcasts_feature.py`)

В логике списка эпизодов:
- первые `FREE_PODCASTS_LIMIT` доступны бесплатно,
- дальше нужен Premium (`_premium_active(user_id)`).

Есть отдельный paywall и проверка через `pod:premium_check`.

## 6.3 MyWords (`core8_1.py` + `mywords_repository.py`)

Premium влияет на два лимита:
1. `FREE_MYWORDS_CATEGORIES_LIMIT` (по умолчанию 3 категории).
2. `FREE_MYWORDS_WORDS_PER_CAT_LIMIT` (по умолчанию 10 слов в категории).

Если лимит превышен и Premium не активен — показывается paywall.

`mywords_repository.py` здесь даёт безопасное хранение, но решение о доступе принимает `core8_1.py`.

---

## 7) Инициализация и связи между модулями

- `core8_1.py` подключает роутер подкастов: `dp.include_router(podcasts_router)`.
- Затем `core8_1.py` вызывает `init_podcasts_feature(...)` и передаёт зависимости:
  - `load_user_data`, `save_user_data`,
  - `load_subscription_channels`,
  - `LessonStates`,
  - `admin_chat_id`, `bot`.

Это означает: модуль подкастов не автономный, он **DI-подключён** к core.

---

## 8) Переменные окружения (важные для Premium)

Ключевые ENV:
- `PREMIUM_PAYLINK_WEEK`
- `PREMIUM_PAYLINK_MONTH`
- `PREMIUM_PAYLINK_YEAR`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PORTAL_RETURN_URL`
- `FREE_TOPICS_LIMIT`
- `FREE_PODCASTS_LIMIT`
- `FREE_MYWORDS_CATEGORIES_LIMIT`
- `FREE_MYWORDS_WORDS_PER_CAT_LIMIT`
- `PREMIUM_ACCESS_PATH` (в подкастах)

---

## 9) Точки отказа и что проверять в первую очередь

Если Premium «не срабатывает», сначала проверять:
1. Пришёл ли Stripe webhook на `/stripe/webhook`.
2. Записался ли user в `/data/premium_users.json`.
3. Есть ли `active_until > now` у нужного Telegram ID.
4. Передал ли пользователь правильный Telegram ID в checkout.
5. Не сломаны ли `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`.
6. Нажал ли пользователь кнопку «✅ Проверить Premium» после оплаты.

---

## 10) Краткая карта вызовов (для быстрого понимания)

1. Пользователь упирается в замок (лексика / подкасты / mywords).
2. Видит paywall + ссылки Stripe.
3. Оплачивает и указывает Telegram ID.
4. Stripe шлёт webhook в `core8_1.py`.
5. `core8_1.py` обновляет `/data/premium_users.json`.
6. Пользователь жмёт «Проверить Premium».
7. `is_premium_active(user_id)` возвращает `True`.
8. Ограничения снимаются во всех модулях.

---

## 11) Что уже сделано хорошо в текущем коде

- Единый Premium-файл с backup.
- Атомарная запись JSON.
- Поддержка нескольких webhook-событий Stripe (не только первичная покупка).
- Встроенный fallback в подкастах по нескольким premium-форматам.
- Проверка Premium в нескольких UI-точках.
- Распространение Premium на все ключевые разделы.

