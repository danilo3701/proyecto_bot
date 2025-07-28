# feedback_difficulty_block.py
# 💬 Список вариантов реакции на уровень сложности — “feedback_difficulty”

feedback_variants = [
    # (вопрос, кнопка1, кнопка2, реакция1, реакция2)
    ("Было легко? 😌", "Легко! 😃", "Сложно… 😓", "Вижу, звёзды тебе по плечу! ⭐️", "Скоро будет проще! 💪"),
    ("Справился без труда? 🚀", "Да! 🏆", "Нет, было тяжко… 😤", "Отлично! Вот это уровень! 🔝", "Главное — не сдаваться! 🫡"),
    ("Далеко ли до успеха? 🏁", "Почти там! 🤏", "Ой, далековато… 😅", "Уверенно двигаешься! ➡️", "Потихоньку, но верно! 🐢"),
    # ...добавляй новые строки...
]

feedback_difficulty = [
    {
        "text": text,             # 💬 Вопрос о сложности
        "buttons": [btn1, btn2],  # 💬 Короткие кнопки с эмоциями
        "replies": {
            btn1: {"reaction": reaction1, "next": "offer_continue"},  # 💬 Следующий шаг (например, к offer_continue)
            btn2: {"reaction": reaction2, "next": "offer_continue"}
        }
    }
    for text, btn1, btn2, reaction1, reaction2 in feedback_variants
]
