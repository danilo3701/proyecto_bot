# MyWords latency benchmark (before/after)

Методика: синтетический тест (200 итераций на операцию), локальный FS, сравнение:
- **before**: наивный путь `load -> mutate -> save` (где применимо с дополнительным `load`),
- **after**: `MyWordsRepository` (валидация + `asyncio.Lock` + атомарная запись).

| Operation | Before median (ms) | After median (ms) | Before p95 (ms) | After p95 (ms) |
|---|---:|---:|---:|---:|
| add_word | 6.37 | 13.66 | 8.79 | 17.78 |
| start_lesson | 13.98 | 13.73 | 16.65 | 16.32 |
| text_answer | 13.85 | 14.70 | 18.17 | 16.63 |

Примечание: после изменений хвост распределения (p95) на `start_lesson` и `text_answer` стал стабильнее, но простая операция `add_word` стала дороже из-за централизованной валидации/блокировки.
