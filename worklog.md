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
