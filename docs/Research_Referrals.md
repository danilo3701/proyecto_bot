# Research Referrals: `/payouts` Reachability

## 1. Контекст и цель
- Цель: выяснить, почему команда `/payouts` в реферальном модуле иногда "молчит" (без ответа и без ошибки), и внести безопасный фикс.
- Ограничение: не менять основную команду (`/payouts` остается основной точкой входа).

## 2. Текущая архитектура рефералок и выплат
- Основная логика рефералок и выплат: `referral_feature.py`.
- Подключение роутера: `core8_1.py` через `dp.include_router(referral_router)`.
- Точки вызова реферальной логики из core:
  - `referrals_try_bind_on_start(...)`
  - `referrals_apply_invoice_paid(...)`
  - `referrals_apply_subscription_status(...)`
  - `render_ref_cabinet(...)` (прокси `/ref` в core).
- Команды выплат в `referral_feature.py`:
  - `/payout` (ручная фиксация выплаты),
  - `/payouts` (админ-меню/история),
  - `/payouts_summary` (сводка выплат).

## 3. Route flow для `/payouts`
- Сообщение попадает в Dispatcher.
- Роутеры подключены в порядке:
  1) `legacy_topics_router` (из `create_lesson_block.py`, если импорт успешен),
  2) `grammar_router`,
  3) `battle_router`,
  4) `bonuses_router`,
  5) `referral_router`,
  6) `podcasts_router`.
- В `create_lesson_block.py` был глобальный debug handler: `@router.message(StateFilter("*"))`.

## 4. Подтвержденная причина "тишины"
- В aiogram 3.26 действует first-match propagation: при первом совпавшем handler дальнейшая цепочка не продолжается, если не выброшен `SkipHandler`.
- Debug-catch-all в `create_lesson_block.py` совпадал с любым сообщением и завершался `return`, из-за чего событие не доходило до `referral_router` и `/payouts` мог "молчать".
- Дополнительный edge-case: near-miss формат (например `'/payouts`) не является командой Telegram и попадал в текстовый handler, что выглядело как "команда не работает".

## 5. Альтернативные гипотезы и статус
- Дубликат `/payouts` в `core8_1.py`: не подтвержден.
- Перекрытие `referral_router` роутером `podcasts_router`: низкий риск для корректного `/payouts`, так как `podcasts_router` подключен после `referral_router`.
- Неверный формат ввода пользователя (лишние символы): подтвержден как отдельный UX edge-case.

## 6. Что изменено
- `create_lesson_block.py`:
  - debug-catch-all теперь завершает обработку через `raise SkipHandler`, чтобы событие продолжало propagation в следующие роутеры.
- `referral_feature.py`:
  - добавлены диагностические логи для `/payouts`:
    - вход в `cmd_payouts`,
    - открытие админ-меню,
    - вывод истории выплат,
    - невалидный формат.
  - добавлены логи ранних выходов в `cmd_payout_input` (reason=`not_owner`/`not_waiting`) для payout-like сообщений.
  - добавлен warning для near-miss ввода (например `'/payouts`) с подсказкой корректного формата.

## 7. Checklist ручной проверки
1. Отправить `/payouts`:
   - ожидается открытие списка рефералов (админ-меню выплат).
2. Отправить `/payouts <referrer_id>`:
   - ожидается история выплат по referrer.
3. Отправить `'/payouts`:
   - команда не выполняется (это не валидная Telegram-команда), но в логах есть warning `ref.payouts.near_miss`.
4. Проверить, что не сломались:
   - `/ref`,
   - `/payout`,
   - callback `settings:referrals`.
5. Проверить startup/runtime логи:
   - есть записи `ref.payouts.cmd`,
   - есть записи `ref.payout.input.skip` при ранних выходах.

## 8. Вывод
- Причина проблемы локализована в перехвате событий debug-catch-all handler-ом legacy router.
- Фикс сделан локально и безопасно: порядок роутеров не менялся, поведение `/payouts` сохранено.
