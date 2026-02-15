# WORKLOG проекта

## Правило
- Каждая попытка фикса = новая запись
- В записи: симптом → что сделали → результат
- Если ❌ не сработало: пишем почему/что увидели в логах

---

## Записи

### 2026-02-14 · SlotFlow/Grammar · grammar-branch · P
Контекст: /grammar_admin + menu:grammar + legacy create_lesson_block
Симптом: Смешивание новой грамматики с legacy-конструктором тем из-за общего хранилища /data/topics и неясных роутер-подключений
Сделали:
- Развели хранилища: grammar_future теперь читает/пишет темы грамматики в /data/grammar_topics вместо /data/topics
- Убрали дубль подключения grammar_router в core8_1 (dp.include_router был дважды)
- Переименовали алиас роутера legacy create_lesson_block в core8_1 для ясности (legacy_topics_router)
Файлы:
- core8_1.py
- grammar_future.py
Коммит: PENDING
Результат: Грамматика больше не попадает в список тем/редактор legacy-конструктора; роутер грамматики подключён ровно 1 раз
Следующий шаг: Протестировать 1) menu:grammar 2) /grammar_admin 3) /addtopic и “Редактировать темы” = там не должно быть грамматических тем

### 2026-02-14 · grammar · branch_grammar · P
Контекст: core8_1.py → подключение роутеров (dp.include_router) + /grammar_admin unhandled
Симптом: /grammar_admin и/или grammar callbacks не обрабатываются; бот падает на импорте create_lesson_block из-за SyntaxError.
Сделали:
- Обернули импорт legacy_topics_router в try/except, чтобы SyntaxError в create_lesson_block не ронял весь бот.
- Подключили grammar_router в dp.include_router, чтобы грамматика и /grammar_admin были достижимы.
- Подключение legacy_topics_router сделали условным (только если импорт успешен).
Файлы:
- core8_1.py
Коммит: (заполни сам)
Результат: бот стартует даже при сломанном create_lesson_block; grammar_router активен → /grammar_admin не должен быть unhandled.
Следующий шаг: 1) проверить /grammar_admin; 2) нажать “Грамматика” из меню; 3) убедиться что legacy create_lesson_block не влияет на грамматику.

### 2026-02-15 · grammar_future1 · grammar-branch · P
Контекст: Открытие темы грамматики / рендер страниц + админ bulk pages
Симптом: TelegramBadRequest: can't parse entities из-за unsupported start tag "br"
Сделали:
- Убрали генерацию <br> в mdish_to_html (оставили \n)
- Добавили санитайзер страниц: <br>/<br/>/<br /> -> \n
- Санитизируем pages при загрузке тем и перед рендером страницы
- Санитизируем pages при bulk-вставке страниц в админке
Файлы:
- grammar_future1.py
Коммит: <hash или сообщение>
Результат: Страницы больше не содержат <br> в HTML parse_mode, старые сохранённые страницы автоматически чинятся при загрузке/рендере
Следующий шаг: Открыть тему с ранее сохранёнными страницами и проверить, что рендер не падает; затем добавить новые страницы bulk и проверить отображение переносов строк


### 2026-02-16 · grammar_future1 · grammar · P
Контекст: Quiz Flow (poll) внутри грамматики
Симптом: Опрос “мигает” и быстро удаляется, ответ не успевает обработаться
Сделали:
- В _run_quiz_flow заменили получение poll_id на poll_msg.poll.id
- Добавили guard на poll_id is None, чтобы не было ложного совпадения last_poll_id==None и мгновенной очистки/удаления
Файлы:
- grammar_future1.py
Коммит: PENDING
Результат: poll_id корректно сопоставляется с PollAnswer, квиз не “флэш-удаляется”
Следующий шаг: Протестировать квиз: ответить на poll и дождаться корректной проверки + перехода к следующему вопросу
