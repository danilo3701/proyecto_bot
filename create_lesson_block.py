# === КОНСТРУКТОР УРОКОВ: СОХРАНЕНИЕ В STRUCTURE С TYPE ===

import json, random
import os
import uuid  # 💬 Для генерации уникальных имён файлов
import re

from pathlib import Path

from aiogram import Router, Bot
from aiogram import F
from aiogram.filters import StateFilter


from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand

from aiogram.filters.command import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

router = Router()

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]  # 💬 список уровней

#from core8_1 import load_ads_data, save_ads_data

ADS_DATA_PATH = "ads_data.json"

# 💬 Константа — ID вашего приватного канала для рекламы
AD_CHANNEL_ID = -1001398895326

def load_ads_data():
    if not os.path.exists(ADS_DATA_PATH):
        with open(ADS_DATA_PATH, "w", encoding="utf-8") as f:
            f.write("[]")
    with open(ADS_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_ads_data(data):
    with open(ADS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)



class NewTopicStates(StatesGroup):
    waiting_category = State()
    # ---------- БАЗОВЫЕ СОСТОЯНИЯ ------------
    adding_category         = State()  # 💬 состояние ожидания выбора уровня
    waiting_topic_name      = State()
    waiting_first_choice    = State()
    waiting_admin_choice    = State()
    waiting_post_action     = State()  # 💬 после сохранения словаря/упражнения/видео: создать еще или вернуться

    # ----------- БЛОК “СЛОВАРЬ” -------------
    waiting_vocab_title     = State()  # 💬 вводим заголовок словаря
    waiting_vocab_link      = State()  # 💬 вводим ссылку или текст словаря


    waiting_vocab_textquiz_question = State()  # 💬 ввод вопроса для текстового квиза в словаре
    waiting_vocab_textquiz_answer   = State()  # 💬 ввод правильного ответа для текстового квиза в словаре

    waiting_vocab_photo_text = State()  # 💬  необязательный текст перед фото
    waiting_vocab_photo     = State()

    waiting_vocab_quiz_block = State()   # ― для обычных quiz
    waiting_extra_quiz       = State()   # ― для EXTRA_QUIZ
    waiting_vocab_quiz_text = State()   # 💬 ввод опционального текста перед QUIZ словаря
    


    waiting_vocab_text     = State()


    # ------------ БЛОК “УПРАЖНЕНИЕ (ОБЩЕЕ)” ----------
    waiting_ex_title        = State()  # 💬 вводим название упражнения
    waiting_ex_instr        = State()  # 💬 вводим инструкцию
    waiting_ex_url          = State()  # 💬 вводим ссылку или контент упражнения

    waiting_ex_quiz_text    = State()   # 💬 ввод опционального текста перед QUIZ упражнения
    waiting_ex_quiz_block = State()  # 💬 Ожидание ввода QUIZ для упражнения 
    waiting_ex_text       = State()  # 💬 Ожидание ввода текст-блока для упражнения
    waiting_ex_photo_text = State()  # 💬 Ожидание подписи к фото упражнения

    waiting_ex_photo      = State()  # 💬 Ожидание фото или URL картинки для упражнения

    waiting_ex_textquiz_question    = State()  # 💬 ввод вопроса для текстового квиза в упражнении
    waiting_ex_textquiz_answer      = State()  # 💬 ввод правильного ответа для текстового квиза в упражнении

    # --------- БЛОК “ВИДЕО” -----------
    waiting_video_title     = State()  # 💬 вводим заголовок видео
    waiting_video_link      = State()  # 💬 вводим ссылку на видео



    waiting_channel = State()  # Новое состояние для канала

    # ——— БЛОК “РЕКЛАМА” ———
    waiting_ad_source = State()  # ждем пересланного сообщения из канала
    waiting_ad_buttons = State()   # ждем: вопрос|кнопка1|кнопка2|реакция1|реакция2




# 💬 Состояния для потока создания диалога с фото и упражнениями
class NewDialogStates(StatesGroup):
    waiting_dialog_title = State()
    waiting_dialog_description = State()
    waiting_dialog_photo = State()
    waiting_dialog_quiz_option_more = State()
    waiting_dialog_options = State()
    waiting_quiz_block = State()



# ✏️ Состояния для потока редактирования темы
class EditTopicStates(StatesGroup):
    choose_action           = State()   # ждем выбора действия: Добавить/Отмена
    # — Добавление словаря
    waiting_vocab_title     = State()
    waiting_vocab_link      = State()
    # — Добавление произвольного текста
    waiting_text_block      = State()
    # — Добавление QUIZ
    waiting_quiz_block      = State()
    # — Добавление упражнения
    waiting_ex_title        = State()
    waiting_ex_instr        = State()
    waiting_ex_url          = State()
    # — Добавление видео
    waiting_video_title     = State()
    waiting_video_link      = State()
    # — Добавление диалога
    waiting_dialog_title    = State()
    waiting_dialog_description = State()
    waiting_dialog_photo    = State()



def get_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Добавить словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
            [KeyboardButton(text="🎥 Добавить видео"),    KeyboardButton(text="💬 Добавить диалог")],
            [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")],
            [KeyboardButton(text="Добавить канал(ы)"),    KeyboardButton(text="Добавить рекламу")]
        ],
        resize_keyboard=True
    )

def get_edit_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить словарь"), KeyboardButton(text="➕ Добавить упражнение")],
            [KeyboardButton(text="➕ Добавить видео"),    KeyboardButton(text="➕ Добавить диалог")],
            [KeyboardButton(text="➕ Добавить QUIZ"),     KeyboardButton(text="📝 Добавить ТЕКСТ")],
            [KeyboardButton(text="➖ Удалить блок"),      KeyboardButton(text="🚫 Отмена")]
        ],
        resize_keyboard=True
    )


@router.message(Command("addtopic"))
async def start_adding_topic(message: Message, state: FSMContext):
    await state.clear()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Лексика"), KeyboardButton(text="🧠 Грамматика")]
        ],
        resize_keyboard=True
    )

    await message.answer("📂 Выбери КАТЕГОРИЮ темы:", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_category)

# === Шаг 1: выбор категории ===

@router.message(NewTopicStates.waiting_category)
async def get_category(message: Message, state: FSMContext):
    text = message.text.strip()
    if text not in ["📚 Лексика", "🧠 Грамматика"]:
        await message.answer("❗ Выбери одну из кнопок.")
        return

    category = "lex" if text == "📚 Лексика" else "gram"
    await state.update_data(topic={"category": category})

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=level) for level in ["A0", "A1", "A2"]],
            [KeyboardButton(text=level) for level in ["B1", "B2", "C1"]]
        ],
        resize_keyboard=True
    )
    await message.answer("Теперь выбери уровень темы:", reply_markup=keyboard)
    await state.set_state(NewTopicStates.adding_category)





@router.message(NewTopicStates.adding_category)
async def get_level_for_topic(message: Message, state: FSMContext):
    level = message.text.strip()
    if level not in LEVELS:
        await message.answer("❗ Выбери корректный уровень.")
        return

    await state.update_data(topic_level=level)
    await message.answer("Уровень выбран. Теперь введи НАЗВАНИЕ новой темы:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(NewTopicStates.waiting_topic_name)
    # 💬 После выбора уровня переходим к вводу названия темы.



# === Шаг 2: название темы ===

@router.message(NewTopicStates.waiting_topic_name)
async def get_topic_name(message: Message, state: FSMContext):
    import os, re, json

    raw = message.text.strip()
    clean = re.sub(r"[^\w\s]", "", raw).lower().replace(" ", "_")
    filename = f"topics/{clean}.json"

    # 💬 Собираем базовую структуру темы
    data = await state.get_data()
    category = data["topic"]["category"]
    topic = {
        "title": clean,
        "visible_title": raw,
        "category": category,
        "level": data.get("topic_level"),  # 💬 добавляем выбранный уровень
        "vocab": [],
        "exercises": [],
        "videos": [],
        "dialogs": []
    }

    # 💾 Сохраняем в файл
    os.makedirs("topics", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # 💬 Обновляем состояние
    await state.update_data(topic=topic, topic_path=filename)

    # ⌨️ Главное меню — добавление блоков
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
            [KeyboardButton(text="🎥 Добавить видео"),    KeyboardButton(text="💬 Добавить диалог")],
            [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")],
            [KeyboardButton(text="Добавить канал(ы)"),    KeyboardButton(text="Добавить рекламу")]
        ],
        resize_keyboard=True
    )

    await message.answer("🧩 С чего начнём?", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_first_choice)







# === Шаг 2: выбор действия
# === Главное меню: обработка выбора блока или просмотр/сохранение ===
@router.message(NewTopicStates.waiting_first_choice)
async def handle_main_menu(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    tp = data.get("topic")
    path = data.get("topic_path")

    # ----------------------- Добавить словарь -----------------------
    if text == "📚 словарь":
        # 💬 Запоминаем, что сейчас последний блок – «vocab» (словари)
        await state.update_data(last_block="vocab")
        # Просим ввести заголовок словаря
        await message.answer("Введите ЗАГОЛОВОК словаря:")
        # Переходим в состояние, где ждём title словаря
        await state.set_state(NewTopicStates.waiting_vocab_title)
        return

    # ----------------------- Добавить упражнение -----------------------
    if text == "✏️ Добавить упражнение":
        # 💬 Последний блок – «exercise» (общие упражнения)
        await state.update_data(last_block="exercise")
        # Просим ввести название упражнения
        await message.answer("Введите НАЗВАНИЕ упражнения:")
        # Переходим в состояние, где ждём title упражнения
        await state.set_state(NewTopicStates.waiting_ex_title)
        return

    # ----------------------- Добавить видео -----------------------
    if text == "🎥 Добавить видео":
        # 💬 Последний блок – «video»
        await state.update_data(last_block="video")
        # Просим ввести заголовок видео
        await message.answer("Введите ЗАГОЛОВОК видео:")
        # Переходим в состояние, где ждём title видео
        await state.set_state(NewTopicStates.waiting_video_title)
        return

    # ----------------------- Добавить диалог -----------------------
    if text == "💬 Добавить диалог":
        # Запускаем поток создания диалога
        await message.answer("Введите заголовок диалога:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(NewDialogStates.waiting_dialog_title)


    # ----------------------- Добавить рекламу -----------------------
    if text == "Добавить рекламу":
        await message.answer(
            "📌 Перешлите мне сообщение из вашего *приватного канала*,\n"
            "из которого нужно брать рекламу."
        )
        await state.set_state(NewTopicStates.waiting_ad_source)
        return



    # ----------------------- Просмотреть то, что уже создали -----------------------

    if text == "👁 Просмотреть":
        # 💬 Читаем текущий JSON-файл
        if topic_path and os.path.exists(topic_path):
            with open(topic_path, "r", encoding="utf-8") as f:
                topic_data = json.load(f)

            lines = []

            # 1) Словари (quiz/text/link)
            vocab_list = topic_data.get("vocab", [])
            if vocab_list:
                lines.append("🗂 <b>Словари:</b>")
                for idx, block in enumerate(vocab_list, start=1):
                    # Quiz-блок
                    if block.get("type") == "quiz":
                        preview = block.get("question", "<без вопроса>")
                    # Text-блок
                    elif block.get("type") == "text":
                        txt = block.get("text", "")
                        words = txt.split()
                        preview = " ".join(words[:5]) + ("…" if len(words) > 5 else "")
                    # Link-блок
                    else:
                        title = block.get("title") or "Без названия"
                        url   = block.get("link", "")
                        preview = f'{title} — <a href="{url}">ссылка</a> ({url})'
                    lines.append(f"  {idx}) {preview}")
                lines.append("")

            # 2) Общие упражнения (quiz/text/link)
            ex_list = topic_data.get("exercises", [])
            if ex_list:
                lines.append("✏️ <b>Упражнения:</b>")
                for idx, block in enumerate(ex_list, start=1):
                    if block.get("type") == "quiz":
                        preview = block.get("question", "<без вопроса>")
                    elif block.get("type") == "text":
                        txt = block.get("text", "")
                        words = txt.split()
                        preview = " ".join(words[:5]) + ("…" if len(words) > 5 else "")
                    else:
                        title = block.get("title") or "Без названия"
                        url   = block.get("link", "")
                        preview = f'{title} — <a href="{url}">ссылка</a> ({url})'
                    lines.append(f"  {idx}) {preview}")
                lines.append("")

            # 3) Видео (link)
            vid_list = topic_data.get("videos", [])
            if vid_list:
                lines.append("🎥 <b>Видео:</b>")
                for idx, vid in enumerate(vid_list, start=1):
                    title = vid.get("title") or "Без названия"
                    url   = vid.get("link", "")
                    lines.append(f'  {idx}) <a href="{url}">{title}</a>')
                lines.append("")

            # 4) Диалоги и упражнения внутри них
            dlg_list = topic_data.get("dialogs", [])
            if dlg_list:
                lines.append("💬 <b>Диалоги:</b>")
                for d_idx, dlg in enumerate(dlg_list, start=1):
                    # Заголовок диалога
                    lines.append(f"  {d_idx}) 💬 <b>{dlg.get('title','Без названия')}</b>")
                    # Упражнения по диалогу
                    for ex_idx, block in enumerate(dlg.get("exercises", []), start=1):
                        if block.get("type") == "quiz":
                            preview = block.get("question", "<без вопроса>")
                        elif block.get("type") == "text":
                            txt = block.get("text", "")
                            words = txt.split()
                            preview = " ".join(words[:5]) + ("…" if len(words) > 5 else "")
                        else:
                            title = block.get("title") or "Без названия"
                            url   = block.get("link", "")
                            preview = f'{title} — <a href="{url}">ссылка</a> ({url})'
                        lines.append(f"      {d_idx}.{ex_idx}) {preview}")
                lines.append("")

            # Если ничего не добавлено
            if not lines:
                await message.answer(
                    "Пока нет добавленных блоков.",
                    disable_web_page_preview=True
                )
            else:
                # Отправляем всё одним сообщением
                preview_text = "\n".join(lines)
                await message.answer(
                    preview_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
        else:
            await message.answer(
                "Ошибка: файл темы не найден.",
                disable_web_page_preview=True
            )

        # 💡 Восстанавливаем главное меню кнопок и состояние
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
                [KeyboardButton(text="🎥 Добавить видео"),    KeyboardButton(text="💬 Добавить диалог")],
                [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")],
                [KeyboardButton(text="Добавить канал(ы)"),    KeyboardButton(text="Добавить рекламу")]
            ],
            resize_keyboard=True
        )
        await message.answer("С чего начнём?", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return



    # ----------------------- Редактировать тему -----------------------
    if text == "✏️ Редактировать":
        data = await state.get_data()
        topic = data.get("topic")
        topic_path = data.get("topic_path")
        if not topic or not topic_path:
            await message.answer("❗ Ошибка: тема не загружена. Пожалуйста, создайте или откройте тему заново.")
            return

        # 🔧 Расширенное меню редактирования:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Добавить словарь"),           KeyboardButton(text="➕ Добавить упражнение")],
                [KeyboardButton(text="➕ Добавить диалог"),            KeyboardButton(text="➕ Добавить видео")],
                [KeyboardButton(text="➕ Добавить QUIZ"),              KeyboardButton(text="📝 Добавить ТЕКСТ")],
                [KeyboardButton(text="➖ Удалить блок"),               KeyboardButton(text="🚫 Отмена")]
            ],
            resize_keyboard=True
        )
        await message.answer("✏️ Режим редактирования. Что вы хотите сделать с этой темой?", reply_markup=kb)
        from edit_topic_flow import EditTopicStates
        await state.set_state(EditTopicStates.choose_action)
        return

        # ----------------------- Добавить канал(ы)
    if text == "Добавить канал(ы)":
        # 💬 Запрашиваем у админа username канала(ов)
        await message.answer(
            "Введи ссылку (https://t.me/username) или имя канала (@username).\n"
            "Если несколько — раздели через запятую."
        )
        await state.set_state(NewTopicStates.waiting_channel)
        return


    # ----------------------- Обработка ввода не из списка -----------------------
    # Если сообщение не соответствует ни одной кнопке, просим выбрать ещё раз
    await message.answer("❗ Выберите, пожалуйста, одну из кнопок Главного меню.")



# 💬 Хендлер для добавления каналов: принимает URL (https://t.me/username) или @username
@router.message(
    F.text == "Добавить канал(ы)",
    StateFilter(NewTopicStates.waiting_first_choice, NewTopicStates.waiting_post_action)
)
async def handle_add_channel(message: Message, state: FSMContext):
    await message.answer(
        "Введи ссылку (https://t.me/username) или имя канала (@username).\n"
        "Если несколько — раздели через запятую."
    )
    await state.set_state(NewTopicStates.waiting_channel)





@router.message(StateFilter(NewTopicStates.waiting_channel))
async def save_channel_to_topic(message: Message, state: FSMContext):
    raw = message.text.strip()
    # 💬 Распарсим URL или username
    inputs = [c.strip() for c in raw.split(",") if c.strip()]
    parsed = []
    for ch in inputs:
        m = re.search(r"(?:https?://)?t\.me/(@?[\w\d_]+)", ch)
        if m:
            uname = m.group(1)
        else:
            uname = ch.lstrip("@")
        if not uname.startswith("@"):
            uname = "@" + uname
        parsed.append(uname)

    data = await state.get_data()
    topic = data.get("topic", {})
    # 💬 Обновляем поля в памяти
    if len(parsed) == 1:
        topic["required_channel"] = parsed[0]
        topic.pop("required_channels", None)
    else:
        topic["required_channels"] = parsed
        topic.pop("required_channel", None)

    # 💾 Сохраняем в файл JSON
    path = data.get("topic_path")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)
    await message.answer(f"✅ Канал(ы) добавлены: {', '.join(parsed)}")
    # 💬 Возвращаем Главное меню
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
            [KeyboardButton(text="🎥 Добавить видео"), KeyboardButton(text="💬 Добавить диалог")],
            [KeyboardButton(text="👁 Просмотреть"), KeyboardButton(text="✏️ Редактировать")],
            [KeyboardButton(text="Добавить канал(ы)"),    KeyboardButton(text="Добавить рекламу")]
        ], resize_keyboard=True
    )
    await message.answer("С чего начнём?", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_first_choice)




# ——— Хелпер: отправляет общее пост-меню для vocab/exercise/video ———

async def send_post_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    last = data.get("last_block")

    # Составляем кнопки под тип последнего блока
    if last == "vocab":
        rows = [
             
            [KeyboardButton(text="🔄 Создать ещё словарь"),
             KeyboardButton(text="🔤 Добавить TEXT_QUIZ"),
             KeyboardButton(text="➕ Добавить QUIZ")],
            [KeyboardButton(text="➕ Добавить EXTRA_QUIZ"),
             KeyboardButton(text="📝 Добавить ТЕКСТ"),
             KeyboardButton(text="🖼 Добавить фото")],
            [KeyboardButton(text="Добавить канал(ы)"),
             KeyboardButton(text="Добавить рекламу")],
        ]
    elif last == "exercise":
        rows = [
            [KeyboardButton(text="🔄 Создать ещё упражнение"),
             KeyboardButton(text="🔤 Добавить TEXT_QUIZ"),
             KeyboardButton(text="➕ Добавить QUIZ")],
            [KeyboardButton(text="📝 Добавить ТЕКСТ"),
             KeyboardButton(text="🖼 Добавить фото")],
        ]
    elif last == "video":
        rows = [
            [KeyboardButton(text="🔄 Создать ещё видео")]
        ]
    else:
        rows = []

    # Внизу общий «Вернуться»
    rows.append([KeyboardButton(text="↩️ Вернуться в Главное меню")])

    kb = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
    await message.answer("Что дальше?", reply_markup=kb)
    await state.set_state(NewTopicStates.waiting_post_action)









# === БЛОК “СЛОВАРЬ” ===
# Создание Потока "Учить слова"

#Создание extra_quiz
@router.message(NewTopicStates.waiting_post_action, F.text=="➕ Добавить EXTRA_QUIZ")
async def start_add_extra_quiz(message: Message, state: FSMContext):
    await message.answer("Отправь EXTRA_QUIZ в формате:\nВопрос|Правильный|Неправильный1|Неправильный2|Пояснение")
    await state.set_state(NewTopicStates.waiting_extra_quiz)


@router.message(NewTopicStates.waiting_extra_quiz)
async def save_extra_quiz(message: Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) != 5:
        return await message.answer("❌ Формат неправильный, нужно 5 частей!")

    question, correct, wrong1, wrong2, explanation = [p.strip() for p in parts]

    new_quiz = {
        "question": question,
        "options": [correct, wrong1, wrong2],
        "correct_answer": correct,
        "explanation_correct": explanation
    }

    data = await state.get_data()
    topic = data["topic"]
    topic.setdefault("extra_quiz", []).append(new_quiz)

    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await message.answer("✅ EXTRA_QUIZ добавлен!", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)
    #........конец Создание extra_quiz..........................



# ——— Добавить TextQuiz for VOCAB and EXERCISE ———
@router.message(NewTopicStates.waiting_post_action, F.text == "🔤 Добавить TEXT_QUIZ")
async def start_textquiz(message: Message, state: FSMContext):
    data = await state.get_data()
    last_block = data.get("last_block")

    if last_block == "vocab":
        # 💬 спрашиваем вопрос для текстового квиза в словаре
        await message.answer("📝 Введите ВОПРОС для текстового квиза словаря:")
        await state.set_state(NewTopicStates.waiting_vocab_textquiz_question)
    elif last_block == "exercise":
        # 💬 спрашиваем вопрос для текстового квиза в упражнении
        await message.answer("📝 Введите ВОПРОС для текстового квиза упражнения:")
        await state.set_state(NewTopicStates.waiting_ex_textquiz_question)
    else:
        # 💬 защита на случай неправильного контекста
        await message.answer("❗ Текстовый квиз недоступен для этого типа блока.")



@router.message(NewTopicStates.waiting_vocab_textquiz_question)
async def ask_vocab_textquiz_answer(message: Message, state: FSMContext):
    # 💬 Сохраняем вопрос
    await state.update_data(current_textquiz_question=message.text.strip())
    await message.answer("✔️ Теперь введите ПРАВИЛЬНЫЙ ОТВЕТ:")
    await state.set_state(NewTopicStates.waiting_vocab_textquiz_answer)

@router.message(NewTopicStates.waiting_vocab_textquiz_answer)
async def save_vocab_textquiz_block(message: Message, state: FSMContext):
    answer = message.text.strip()
    data = await state.get_data()
    new_block = {
        "type": "textquiz",                # 💬 новый тип
        "question": data["current_textquiz_question"],
        "correct_answer": answer
    }
    topic = data["topic"]
    topic.setdefault("vocab", []).append(new_block)
    # 💾 Сохраняем в файл
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    await state.update_data(current_textquiz_question=None)
    await message.answer("✅ Текстовый квиз сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)

@router.message(NewTopicStates.waiting_ex_textquiz_question)
async def ask_ex_textquiz_answer(message: Message, state: FSMContext):
    await state.update_data(current_ex_textquiz_question=message.text.strip())
    await message.answer("✔️ Теперь введите ПРАВИЛЬНЫЙ ОТВЕТ для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_textquiz_answer)

@router.message(NewTopicStates.waiting_ex_textquiz_answer)
async def save_ex_textquiz_block(message: Message, state: FSMContext):
    answer = message.text.strip()
    data = await state.get_data()
    new_block = {
        "type": "textquiz",                # 💬 новый тип
        "question": data["current_ex_textquiz_question"],
        "correct_answer": answer
    }
    topic = data["topic"]
    topic.setdefault("exercises", []).append(new_block)
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    await state.update_data(current_ex_textquiz_question=None)
    await message.answer("✅ Текстовый квиз упражнения сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)
# ——— FINISH TextQuiz ———




# ——— 📚 словарь ———
# 1) Запрашиваем заголовок словаря
@router.message(NewTopicStates.waiting_vocab_title)
async def get_vocab_title(message: Message, state: FSMContext):
    # Сохраняем title словаря
    vocab_title = message.text.strip()
    await state.update_data(current_vocab_title=vocab_title)
    # Переходим к запросу ссылки/текста словаря
    await message.answer("Введите ССЫЛКУ или ТЕКСТ словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_link)

# 2) Запрашиваем ссылку или текст словаря
@router.message(NewTopicStates.waiting_vocab_link)
async def get_vocab_link(message: Message, state: FSMContext):
    raw_input = message.text.strip()

    # Если в тексте есть <iframe>, то вытягиваем значение src="..."
    if "<iframe" in raw_input:
        src_index = raw_input.find('src="')
        if src_index != -1:
            # начало содержимого ссылки (после src=")
            start = src_index + len('src="')
            end = raw_input.find('"', start)
            if end != -1:
                vocab_link = raw_input[start:end]
            else:
                # Если закрывающая кавычка не найдена, просто сохраняем как есть
                vocab_link = raw_input
        else:
            # Не нашли src, сохраняем как есть
            vocab_link = raw_input
    else:
        vocab_link = raw_input

    data = await state.get_data()
    topic_data = data["topic"]
    topic_path = data["topic_path"]

    # Собираем новый блок словаря
    new_block = {
        "title": data.get("current_vocab_title"),
        "link": vocab_link
    }

    # Обновляем в памяти и в JSON-файле
    topic_data["vocab"].append(new_block)
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

       # … после записи в JSON и очистки current_vocab_title …
    await state.update_data(current_vocab_title=None, last_block="vocab")

    await message.answer("Словарь сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)



# 3) Пост-блоковое меню для всех блоков (часть 1)
@router.message(NewTopicStates.waiting_post_action)
async def handle_post_action(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    last_block = data.get("last_block")

    # ─── БЛОК «СЛОВАРЬ» ───
    if last_block == "vocab":
        if text == "🔄 Создать ещё словарь":
            # Снова запрашиваем заголовок
            await message.answer("Введите ЗАГОЛОВОК словаря:")
            await state.set_state(NewTopicStates.waiting_vocab_title)
            return
        if text == "➕ Добавить QUIZ":
            # 💬 Сначала ввод опционального текста или '-' для пропуска
            await message.answer("📝 Введите текст перед квизом или '-' для пропуска:")
            return await state.set_state(NewTopicStates.waiting_vocab_quiz_text)

        # 💬 Обработка TextQuiz для словаря
        if text == "🔤 Добавить TEXT_QUIZ":
            await message.answer("📝 Введите ВОПРОС для текстового квиза словаря:")
            return await state.set_state(NewTopicStates.waiting_vocab_textquiz_question)

        # — Добавить ТЕКСТ
        if text == "📝 Добавить ТЕКСТ":
            await message.answer("📝 Введите произвольный текст-блок для словаря:")
            await state.set_state(NewTopicStates.waiting_vocab_text)
            return
        # ——— Добавить фото словаря ———
        if text == "🖼 Добавить фото" and last_block == "vocab":
            await message.answer("Введите подпись к фото словаря или '-' для пропуска:", reply_markup=ReplyKeyboardRemove())
            await state.set_state(NewTopicStates.waiting_vocab_photo_text)
            return



    # ─── БЛОК «УПРАЖНЕНИЕ» ───
    if last_block == "exercise":
        if text == "🔄 Создать ещё упражнение":
            await message.answer("Введите НАЗВАНИЕ упражнения:")
            return await state.set_state(NewTopicStates.waiting_ex_title)
        if text == "➕ Добавить QUIZ":
            # 💬 Сначала ввод опционального текста или '-' для пропуска
            await message.answer("📝 Введите текст перед квизом или '-' для пропуска:")
            return await state.set_state(NewTopicStates.waiting_ex_quiz_text)
        if text == "📝 Добавить ТЕКСТ":
            await message.answer("📝 Введите текст для упражнения:")
            return await state.set_state(NewTopicStates.waiting_ex_text)
        if text == "🖼 Добавить фото":
            await message.answer("Введите подпись к фото упражнения или '-' для пропуска:")
            return await state.set_state(NewTopicStates.waiting_ex_photo_text)
    # ─── БЛОК «ВИДЕО» ───
    if last_block == "video" and text == "🔄 Создать ещё видео":
        await message.answer("Введите ЗАГОЛОВОК видео:")
        await state.set_state(NewTopicStates.waiting_video_title)
        return

    # ─── Вернуться в Главное меню ───
    if text == "↩️ Вернуться в Главное меню":
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
                [KeyboardButton(text="🎥 Добавить видео"),     KeyboardButton(text="💬 Добавить диалог")],
                [KeyboardButton(text="👁 Просмотреть"),       KeyboardButton(text="✏️ Редактировать")]
            ],
            resize_keyboard=True
        )
        await message.answer("Возвращаемся в Главное меню.", reply_markup=keyboard)
        await state.set_state(NewTopicStates.waiting_first_choice)
        return

    # ─── Некорректный ввод ───
    await message.answer(
        "❗ Пожалуйста, нажми одну из кнопок: «🔄 Создать ещё словарь», «➕ Добавить QUIZ» или «↩️ Вернуться в Главное меню»."
    )









# === БЛОК “УПРАЖНЕНИЕ (ОБЩЕЕ)” ===


# 1) Сохраняем название упражнения
@router.message(NewTopicStates.waiting_ex_title)
async def get_ex_title(message: Message, state: FSMContext):
    await state.update_data(current_ex_title=message.text.strip())
    await message.answer("Введите ИНСТРУКЦИЮ для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_instr)

# 2) Запрашиваем инструкцию к упражнению
@router.message(NewTopicStates.waiting_ex_instr)
async def get_ex_instr(message: Message, state: FSMContext):
    instr = message.text.strip()
    await state.update_data(current_ex_instr=instr)
    # 💬 Как в словаре: сразу просим ссылку или iframe
    await message.answer("Введите ССЫЛКУ или iframe для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_url)



# 3) Сохраняем упражнение (title + instr + link) и возвращаем Главное меню
@router.message(NewTopicStates.waiting_ex_url)
async def get_ex_link(message: Message, state: FSMContext):
    raw = message.text.strip()
    # — вытягиваем src из iframe, если нужно
    if "<iframe" in raw and 'src="' in raw:
        link = raw.split('src="',1)[1].split('"',1)[0]
    else:
        link = raw

    data = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]

    # — прямо как в словаре, но добавляем инструкцию
    new_block = {
        "title":       data["current_ex_title"],
        "instruction": data["current_ex_instr"],
        "link":        link
    }
    topic.setdefault("exercises", []).append(new_block)
    # 🔄 Перезаписываем JSON
    import json
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # очищаем временные поля
    await state.update_data(current_ex_title=None, current_ex_instr=None)

    # — подтвердим и вернём Главное меню темы
    await message.answer("✅ Упражнение сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)






# ——— Добавить квиз ———
# 💬 Сохраняем опциональный текст перед quiz для упражнения
@router.message(NewTopicStates.waiting_ex_quiz_text)
async def handle_ex_quiz_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "-":
        text = None
    await state.update_data(current_quiz_text=text)
    # Запрашиваем сам квиз-блок
    await message.answer(
        "📝 Пришлите викторину через '|':\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного"
    )
    await state.set_state(NewTopicStates.waiting_ex_quiz_block)
    

# 💬 4) Обработка квиза в блоке «УПРАЖНЕНИЕ» и сохранение вместе с текстом
@router.message(NewTopicStates.waiting_ex_quiz_block)
async def save_ex_quiz_block(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 6:
        return await message.answer("❗ Формат неверный — нужно 6 частей через `|`. Попробуй снова.")
    question, correct, w1, w2, exp_corr, exp_wrong = parts
    options = [correct, w1, w2]
    import random; random.shuffle(options)

    data = await state.get_data()
    new_quiz = {
        "type": "quiz",
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation_correct": exp_corr,
        "explanation_wrong": exp_wrong
    }
    quiz_text = data.get("current_quiz_text")
    if quiz_text:
        new_quiz["text"] = quiz_text
    await state.update_data(current_quiz_text=None)

    topic = data["topic"]
    topic.setdefault("exercises", []).append(new_quiz)
    path = data["topic_path"]
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await message.answer("✅ Викторина сохранена.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)



# ——— Добавить текст ———
@router.message(NewTopicStates.waiting_ex_text)
async def save_ex_text(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    topic = data["topic"]
    topic.setdefault("exercises", []).append({"type": "text", "text": text})
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    await message.answer("Текст упражнения сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)







@router.message(NewTopicStates.waiting_ex_photo_text, F.text)
async def handle_ex_photo_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == '-':
        await state.update_data(ex_photo_caption=None)
    else:
        await state.update_data(ex_photo_caption=text)
    await message.answer("🖼 Пришлите фото, GIF/MP4 или стикер для упражнения:")
    await state.set_state(NewTopicStates.waiting_ex_photo)


# ——— Добавить фото/гиф/стикер к упражнению ———
@router.message(NewTopicStates.waiting_ex_photo, F.content_type.in_(["photo", "video", "animation", "sticker", "text"]))
async def save_ex_photo(message: Message, state: FSMContext):
    import time
    from pathlib import Path

    data = await state.get_data()
    topic = data["topic"]
    path = data["topic_path"]

    # создаём папку для медиа
    theme_dir = Path("exercise_images") / topic["title"]
    theme_dir.mkdir(parents=True, exist_ok=True)

    entry = {"type": "photo"}  # общий блок

    # 1) Если это стикер — сохраняем file_id
    if message.sticker:
        entry["media_type"] = "sticker"
        entry["photo"] = message.sticker.file_id

    # 2) Если видео/GIF
    elif message.animation or message.video:
        media = message.animation or message.video
        entry["media_type"] = "animation"
        stamp = int(time.time())
        fname = f"ex_{stamp}_{media.file_id[-5:]}.mp4"
        dest = theme_dir / fname
        file = await message.bot.get_file(media.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 3) Если фото (jpg/png)
    elif message.photo:
        ph = message.photo[-1]
        entry["media_type"] = "photo"
        stamp = int(time.time())
        fname = f"ex_{stamp}_{ph.file_id[-5:]}.jpg"
        dest = theme_dir / fname
        file = await message.bot.get_file(ph.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 4) Если прислан текст (URL или sticker_id)
    else:
        url = message.text.strip()
        lower = url.lower()
        if lower.endswith((".mp4", ".gif")):
            entry["media_type"] = "animation"
        elif lower.endswith((".jpg", ".jpeg", ".png")):
            entry["media_type"] = "photo"
        else:
            entry["media_type"] = "sticker"
        entry["photo"] = url


    # 💬 Сохраняем подпись, если она была добавлена на предыдущем шаге
    if data.get("ex_photo_caption"):
        entry["text"] = data["ex_photo_caption"]
        await state.update_data(ex_photo_caption=None)


    topic.setdefault("exercises", []).append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await message.answer("Медиа упражнения сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)












#------БЛОКИ ДЛЯ "➕ Добавить QUIZ" для VOCAB----------

# 💬 Сохраняем опциональный текст перед quiz для словаря
@router.message(NewTopicStates.waiting_vocab_quiz_text)
async def handle_vocab_quiz_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "-":
        text = None
    await state.update_data(current_quiz_text=text)
    # Запрашиваем сам квиз-блок
    await message.answer(
        "📝 Пришлите квиз через '|':\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного"
    )
    await state.set_state(NewTopicStates.waiting_vocab_quiz_block)



# 💬 2) Обработка квиза в блоке «СЛОВАРЬ» и сохранение вместе с текстом
@router.message(NewTopicStates.waiting_vocab_quiz_block)
async def save_vocab_quiz_block(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 6:
        return await message.answer("❗ Формат неверный — нужно 6 частей через `|`. Попробуй снова.")
    question, correct, w1, w2, exp_corr, exp_wrong = parts
    options = [correct, w1, w2]
    import random; random.shuffle(options)

    # собираем новый квиз-блок
    data = await state.get_data()
    new_quiz = {
        "type": "quiz",
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation_correct": exp_corr,
        "explanation_wrong": exp_wrong
    }
    # добавляем опциональный текст, если был
    quiz_text = data.get("current_quiz_text")
    if quiz_text:
        new_quiz["text"] = quiz_text
    # очищаем временный текст
    await state.update_data(current_quiz_text=None)

    # сохраняем в JSON
    topic = data["topic"]
    topic["vocab"].append(new_quiz)
    path = data["topic_path"]
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await message.answer("✅ Викторина сохранена.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)





#------БЛОКИ ДЛЯ "📝 Добавить ТЕКСТ"----------


@router.message(NewTopicStates.waiting_post_action, F.text == "📝 Добавить ТЕКСТ")
async def ask_vocab_text(message: Message, state: FSMContext):
    await message.answer("📝 Введите произвольный ТЕКСТ-блок для словаря:")
    await state.set_state(NewTopicStates.waiting_vocab_text)



@router.message(NewTopicStates.waiting_vocab_text)
async def save_vocab_text(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    topic = data["topic"]
    # вставляем сразу после последнего словаря
    topic["vocab"].append({
      "type": "text",
      "text": text
    })
    # перезапись файла
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    # возвращаемся в то же пост-меню
    await message.answer("Текст сохранён.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)





#------БЛОКИ ДЛЯ "📝 Добавить ФОТО / PHOTO"----------

# ------ БЛОКИ ДЛЯ "🖼 Добавить ФОТО / PHOTO"----------
@router.message(NewTopicStates.waiting_post_action, F.text=="🖼 Добавить фото")
async def ask_vocab_caption(message: Message, state: FSMContext):
    # 💬 Спросить подпись или '-' для пропуска
    await message.answer(
        "Введите подпись к фото словаря или '-' для пропуска:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(NewTopicStates.waiting_vocab_photo_text)

@router.message(NewTopicStates.waiting_vocab_photo_text)
async def handle_vocab_text(message: Message, state: FSMContext):
    text = message.text.strip()
    # 💬 Сохраняем подпись или None
    if text == '-':
        await state.update_data(vocab_caption=None)
    else:
        await state.update_data(vocab_caption=text)

    # 💬 Теперь запрашиваем само фото или URL
    await message.answer(
        "🖼 Пришлите фотографию (JPG/PNG) или URL картинки для словаря:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(NewTopicStates.waiting_vocab_photo)



# === БЛОК ДЛЯ "🖼 Добавить ФОТО / PHOTO" — расширенный вариант с GIF и стикерами ===

from pathlib import Path
import time

@router.message(NewTopicStates.waiting_vocab_photo, F.content_type.in_(["photo","video","animation","sticker","text"]))
async def receive_vocab_media(message: Message, state: FSMContext):
    """
    Сохраняем в тему либо:
      • JPG/PNG → media_type="photo"
      • MP4/GIF → media_type="animation"
      • Стикер → media_type="sticker"
      • URL (текст) — по расширению решаем, что это за медиа
    """
    data       = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]

    # создаём папку темы внутри vocab_images:
    theme_dir = Path("vocab_images") / topic["title"]
    theme_dir.mkdir(parents=True, exist_ok=True)

    entry = {"type": "photo"}  # общий «photo»-блок, но с уточнением media_type

    # 1) Если это стикер — просто сохраняем file_id
    if message.sticker:
        entry["media_type"] = "sticker"
        entry["photo"]      = message.sticker.file_id

    # 2) Если видео/GIF (Telegram animation или video)
    elif message.animation or message.video:
        media = message.animation or message.video
        entry["media_type"] = "animation"
        stamp = int(time.time())
        fname = f"vocab_{stamp}_{media.file_id[-5:]}.mp4"
        dest  = theme_dir / fname
        file  = await message.bot.get_file(media.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 3) Если фото — сохраняем JPG
    elif message.photo:
        ph    = message.photo[-1]
        entry["media_type"] = "photo"
        stamp = int(time.time())
        fname = f"vocab_{stamp}_{ph.file_id[-5:]}.jpg"
        dest  = theme_dir / fname
        file  = await message.bot.get_file(ph.file_id)
        await message.bot.download_file(file.file_path, dest)
        entry["photo"] = str(dest).replace("\\", "/")

    # 4) Если пользователь прислал текст — считаем URL или sticker_id
    else:
        url = message.text.strip()
        # очень простой детектор: mp4 → animation, .jpg/.png → photo, иначе sticker
        lower = url.lower()
        if lower.endswith((".mp4", ".gif")):
            entry["media_type"] = "animation"
        elif lower.endswith((".jpg", ".jpeg", ".png")):
            entry["media_type"] = "photo"
        else:
            entry["media_type"] = "sticker"
        entry["photo"] = url

    # если была подпись, сохраняем её
    if data.get("vocab_caption"):
        entry["text"] = data["vocab_caption"]
        # очистим её, чтобы не дублировать
        await state.update_data(vocab_caption=None)

    # добавляем в JSON-тему и сохраняем
    topic.setdefault("vocab", []).append(entry)
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # подтверждаем и возвращаем в меню
    await message.answer("Фото/медиа сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)

















# === БЛОК “ВИДЕО” ===

# 1) Запрашиваем заголовок видео
@router.message(NewTopicStates.waiting_video_title)
async def get_video_title(message: Message, state: FSMContext):
    video_title = message.text.strip()
    await state.update_data(current_video_title=video_title)
    # Переходим к запросу ссылки на видео
    await message.answer("Введите ССЫЛКУ на видео:")
    await state.set_state(NewTopicStates.waiting_video_link)

# 2) Запрашиваем ссылку на видео, сохраняем и пост-меню
@router.message(NewTopicStates.waiting_video_link)
async def get_video_link(message: Message, state: FSMContext):
    raw_input = message.text.strip()

    # Если передан iframe, извлекаем src
    if "<iframe" in raw_input:
        src_index = raw_input.find('src="')
        if src_index != -1:
            start = src_index + len('src="')
            end = raw_input.find('"', start)
            if end != -1:
                video_link = raw_input[start:end]
            else:
                video_link = raw_input
        else:
            video_link = raw_input
    else:
        video_link = raw_input

    data = await state.get_data()
    topic_data = data["topic"]
    topic_path = data["topic_path"]

    new_video = {
        "title": data.get("current_video_title"),
        "link": video_link
    }

    # Сохраняем в памяти и сразу в файл
    topic_data["videos"].append(new_video)
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Удаляем временную переменную
    await state.update_data(current_video_title=None)

    # Показываем пост-блоковое меню
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Создать ещё видео"), KeyboardButton(text="↩️ Вернуться в Главное меню")]
        ],
        resize_keyboard=True
    )
    await message.answer("Видео сохранено.", reply_markup=ReplyKeyboardRemove())
    await send_post_menu(message, state)










# ─────────────── DIALOG CREATION FLOW ───────────────
# ========================================================================
#Создание потока "Читать диалог" + упражнения внутри telegram bot 
#ПОТОК "Читать диалог"
# ========================================================================

# === Шаг 1: Заголовок диалога ===зщ
@router.message(F.text == "💬 Добавить диалог")
async def start_dialog_add(message: Message, state: FSMContext):
    await message.answer("💬 Введите ЗАГОЛОВОК диалога:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(NewDialogStates.waiting_dialog_title)

@router.message(NewDialogStates.waiting_dialog_title)
async def get_dialog_title(message: Message, state: FSMContext):
    await state.update_data(current_dialog_title=message.text.strip())
    await message.answer("📝 Введите ОПИСАНИЕ диалога:")
    await state.set_state(NewDialogStates.waiting_dialog_description)

@router.message(NewDialogStates.waiting_dialog_description)
async def get_dialog_description(message: Message, state: FSMContext):
    data = await state.get_data()
    topic = data["topic"]

    new_dialog = {
        "title": data["current_dialog_title"],
        "description": message.text.strip(),
        "photo": "",
        "exercises": []
    }
    topic["dialogs"].append(new_dialog)

    await state.update_data(topic=topic)
    await message.answer("📎 Прикрепите фото или пришлите ссылку на изображение:")
    await state.set_state(NewDialogStates.waiting_dialog_photo)




from pathlib import Path
import time  # 💬 для метки времени

# === Получаем фото для диалога ===
@router.message(NewDialogStates.waiting_dialog_photo)
async def receive_dialog_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_data = data["topic"]
    topic_path = data["topic_path"]

    # 💬 Получаем последний диалог в списке
    dialog = topic_data["dialogs"][-1]

    # 📂 Куда сохраняем фото
    images_dir = Path("dialogo") / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    if message.photo:
        photo: types.PhotoSize = message.photo[-1]
        file_id = photo.file_id
        timestamp = int(time.time())
        unique_filename = f"dialog_{timestamp}_{file_id[-5:]}.jpg"
        full_path = images_dir / unique_filename

        file = await message.bot.get_file(file_id)
        await message.bot.download_file(file.file_path, full_path)

        dialog["photo"] = str(full_path).replace("\\", "/")  # 💾 Сохраняем путь к фото

    else:
        await message.answer("❗ Пришлите фото (JPG/PNG).")
        return

    # 💾 Сохраняем JSON
    with open(topic_path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # 📲 Предлагаем добавить упражнения
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить упражнение")],
            [KeyboardButton(text="💾 Сохранить и вернуться")]
        ],
        resize_keyboard=True
    )
    await message.answer("📷 Фото сохранено. Что дальше?", reply_markup=keyboard)
    await state.set_state(NewDialogStates.waiting_dialog_quiz_option_more)



# === Добавляем сожержание по quiz ===
@router.message(NewDialogStates.waiting_dialog_quiz_option_more, F.text == "Добавить упражнение")
async def ask_quiz_block(message: Message, state: FSMContext):
    # 💬 просим всю строку: Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного
    await message.answer(
        "📝 Пришли весь квиз одним сообщением через `|`:\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного"
    )
    await state.set_state(NewDialogStates.waiting_quiz_block)



@router.message(NewDialogStates.waiting_quiz_block)
async def get_quiz_block(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 6:
        return await message.answer(
            "❗ Формат неверный. Нужны 6 частей через `|`. Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного"
        )

    question, correct, w1, w2, exp_corr, exp_wrong = parts

    # 🔀 перемешиваем варианты
    options = [correct, w1, w2]
    import random; random.shuffle(options)

    # 💾 собираем новый блок
    new_ex = {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation_correct": exp_corr,
        "explanation_wrong": exp_wrong
    }

    # 📂 сохраняем в JSON последнего диалога
    data = await state.get_data()
    topic = data["topic"]
    dialog = topic["dialogs"][-1]
    dialog.setdefault("exercises", []).append(new_ex)

    # перезапись файла
    path = data["topic_path"]
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    await message.answer("✅ Квиз добавлен в диалог!", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Добавить упражнение")],
                  [KeyboardButton(text="💾 Сохранить и вернуться")]],
        resize_keyboard=True
    ))
    # возвращаемся к прежнему состоянию
    await state.set_state(NewDialogStates.waiting_dialog_quiz_option_more)




@router.message(NewDialogStates.waiting_dialog_quiz_option_more, F.text == "💾 Сохранить и вернуться")
async def save_and_back(message: Message, state: FSMContext):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Добавить словарь"), KeyboardButton(text="✏️ Добавить упражнение")],
            [KeyboardButton(text="🎥 Добавить видео"), KeyboardButton(text="💬 Добавить диалог")],
            [KeyboardButton(text="👁 Просмотреть"), KeyboardButton(text="✏️ Редактировать")]
        ], resize_keyboard=True
    )
    await message.answer("📚 Главное меню темы:", reply_markup=keyboard)
    await state.set_state(NewTopicStates.waiting_first_choice)









# 🎨 Утилита: меню действий в режиме редактирования
async def send_edit_menu(chat_id: int, bot: Bot, state: FSMContext):
    kb = make_kb([
        ["➕ Добавить словарь",    "➕ Добавить упражнение"],
        ["➕ Добавить видео",      "➕ Добавить диалог"],
        ["➕ Добавить QUIZ",       "📝 Добавить ТЕКСТ"],
        ["↩️ Вернуться в Главное меню"]
    ])
    await bot.send_message(chat_id, "✏️ Режим редактирования. Что вы хотите сделать?", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)

# 🎨 Хендлер: выбор действия в режиме редактирования
@router.message(EditTopicStates.choose_action)
async def handle_edit_action(message: Message, state: FSMContext):
    text = message.text.strip()
    # Каждая кнопка переводит в своё состояние и просит данные
    if text == "➕ Добавить словарь":
        await message.answer("Введите ЗАГОЛОВОК словаря:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_vocab_title)
    if text == "➕ Добавить упражнение":
        await message.answer("Введите НАЗВАНИЕ упражнения:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_ex_title)
    if text == "➕ Добавить видео":
        await message.answer("Введите ЗАГОЛОВОК видео:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_video_title)
    if text == "➕ Добавить диалог":
        await message.answer("Введите ЗАГОЛОВОК диалога:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_dialog_title)
    if text == "➕ Добавить QUIZ":
        await message.answer(
            "📝 Пришлите quiz в формате:\n"
            "Вопрос|Правильный|Неправ1|Неправ2|ОбъяснениеПравильного|ОбъяснениеНеправильного",
            reply_markup=ReplyKeyboardRemove()
        )
        return await state.set_state(EditTopicStates.waiting_quiz_block)
    if text == "📝 Добавить ТЕКСТ":
        await message.answer("📝 Введите произвольный текст:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_text_block)
    if text.startswith("↩️"):
        # Возврат в основное меню создания/просмотра
        await send_post_menu(message.chat.id, message.bot)
        return
    await message.answer("❗ Пожалуйста, выберите один из пунктов меню.")



# — Добавить словарь —
@router.message(EditTopicStates.waiting_vocab_title)
async def edit_vocab_title(message: Message, state: FSMContext):
    await state.update_data(current_vocab_title=message.text.strip())
    await message.answer("🖇️ Введите ссылку или текст словаря:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(EditTopicStates.waiting_vocab_link)

@router.message(EditTopicStates.waiting_vocab_link, F.content_type=="text")
async def edit_vocab_link(message: Message, state: FSMContext):
    data       = await state.get_data()
    topic      = data["topic"]
    topic_path = data["topic_path"]
    title      = data.get("current_vocab_title")
    raw        = message.text.strip()
    link       = extract_src(raw) if "<iframe" in raw else raw

    add_block_and_save(topic, topic_path, {"title": title, "link": link}, "vocab")
    await state.update_data(current_vocab_title=None)

    await message.answer("✅ Словарь добавлен.", reply_markup=ReplyKeyboardRemove())
    await send_edit_menu(message.chat.id, message.bot, state)







# ——— Новый поток: Добавление рекламы ———

# … ваш импорт load_ads_data, save_ads_data из core8_1.py

# 1) После того, как получили forwarded from_chat + message_id:

@router.message(StateFilter(NewTopicStates.waiting_ad_source), F.forward_from_chat)
async def receive_ad_source(message: Message, state: FSMContext):
    # Сохраняем ID канала и ID сообщения
    ch = message.forward_from_chat.id
    mid = message.forward_from_message_id
    logging.info(f"[receive_ad_source] ad_channel={ch}, ad_message_id={mid}")

    await state.update_data(ad_channel=ch, ad_message_id=mid)
    # Переходим к сбору текста вопроса и кнопок
    await message.answer(
        "➡️ Теперь введите через `|`:\n"
        "вопрос|текст кнопки1|текст кнопки2|реакция1|реакция2"
    )
    # ← переключаемся в состояние, где будем ждать текст с кнопками
    await state.update_data(
        ad_channel=ch,
        ad_message_id=mid,
        ad_fwd_chat_id=message.chat.id,
        ad_fwd_message_id=message.message_id
    )




# 2) Обработка самого текста с вопросом и кнопками
@router.message(NewTopicStates.waiting_ad_buttons)
async def save_ad_block(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 5:
        return await message.answer(
            "❌ Неверный формат! Нужно ровно 5 частей через `|`: "
            "`вопрос|кнопка1|кнопка2|реакция1|реакция2`",
            parse_mode="Markdown"
        )
    q, bt1, bt2, r1, r2 = parts
    data = await state.get_data()
    new_ad = {
        "channel_id":    data["ad_channel"],
        "message_id":    data["ad_message_id"],
        "fwd_chat_id":   data["ad_fwd_chat_id"],
        "fwd_message_id":data["ad_fwd_message_id"],
        "question":      q,
        "btns": [
          {"text": bt1, "reaction": r1},
          {"text": bt2, "reaction": r2},
        ]
    }
    logging.info(f"[save_ad_block] new_ad={new_ad}")

    ads = load_ads_data()
    ads.append(new_ad)
    save_ads_data(ads)

    # 4) Чистим временные поля FSM и возвращаемся в меню
    await state.update_data(ad_channel=None, ad_message_id=None)
    await message.answer("✅ Реклама добавлена!", reply_markup=ReplyKeyboardRemove())

    # и возвращаемся в основное меню:
    await send_post_menu(message, state)





