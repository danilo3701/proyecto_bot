# edit_topic_flow.py

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BotCommand
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram import Bot
from pathlib import Path
import json

router = Router()

# 💬 Универсальное меню действий внутри выбранного раздела
def section_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить блок"),     KeyboardButton(text="➖ Удалить блок")],
            [KeyboardButton(text="🔀 Поменять местами"),  KeyboardButton(text="🚫 Отмена")]
        ],
        resize_keyboard=True
    )



# ────────────────────────────────────────────────────────────────────
# 1. Определяем состояния для редактирования темы
# ────────────────────────────────────────────────────────────────────
class EditTopicStates(StatesGroup):
    # Выбор и основное меню
    choose_topic            = State()  # выбор темы

    waiting_section = State()   # выбор раздела: словарь/упражнения/видео/диалоги

    waiting_vocab_phase_choice = State()  # 💬 выбор фазы для редактирования словаря
    waiting_vocab_phase_name   = State()  # 💬 (опционально) создание новой фазы


    choose_action           = State()  # выбор действия
    choose_block_type       = State()
    insert_index            = State()  # позиция вставки блока
    swap_indexes            = State()   # ввод двух индексов для перестановки блоков

    # Словарь
    waiting_vocab_title     = State()
    waiting_vocab_link      = State()


    # Блок QUIZ
    waiting_quiz_block      = State()
    waiting_quiz_text      = State()   # 💬 ввод текста перед квизом или '-' для пропуска


    # Блок TEXTQUIZ — текстовый квиз (ввод ответа)
    waiting_vocab_textquiz_question = State()   # 💬 вопрос для текстового квиза в словаре
    waiting_vocab_textquiz_answer   = State()   # 💬 ответ для текстового квиза в словаре
    waiting_ex_textquiz_question    = State()   # 💬 вопрос для текстового квиза в упражнении
    waiting_ex_textquiz_answer      = State()   # 💬 ответ для текстового квиза в упражнении

    # Блок ТЕКСТ
    waiting_text_block      = State()
    # — после добавления текста — опциональный quiz
    waiting_vocab_text_quiz       = State()  # ввод всего квиза или '-' для пропуска
    waiting_vocab_text_quiz_block = State()  # парсинг и сохранение quiz внутри блока



    # ✅ Новые состояния для блока ФОТО
    waiting_vocab_photo_text = State()  # текст подписи для фото (словарь)
    waiting_vocab_photo_file = State()  # загрузка фото (словарь)


    # — после добавления фото — опциональный quiz
    waiting_vocab_photo_quiz       = State()  # ввод всего квиза или '-' для пропуска
    waiting_vocab_photo_quiz_block = State()  # парсинг и сохранение quiz внутри блока


    # Упражнение общее
    waiting_ex_title        = State()
    waiting_ex_instr        = State()
    waiting_ex_url          = State()


    # 💬 Фазы диалогов (новая структура как в CreateLessonBlock)
    waiting_dialog_phase_choice       = State()  # выбор фазы диалогов
    waiting_dialog_phase_name         = State()  # создание новой фазы диалогов
    waiting_dialog_block_markdown     = State()  # добавление мини-диалогов (RU+ES по 2 строки)
    waiting_dialog_block_delete_index = State()  # удаление мини-диалога по номеру


    waiting_ex_photo_text = State()     # текст подписи для фото (упражнение)
    waiting_ex_photo_file = State()     # загрузка фото (упражнение)

    # ✅ Новые состояния для блока ЛИНК в упражнениях
    waiting_ex_link_title = State()     # название ссылки (упражнение)
    waiting_ex_link_url   = State()     # ссылка (упражнение)

    # (остальные состояния без изменений...)
    waiting_video_title     = State()
    waiting_video_link      = State()
    waiting_dialog_title    = State()
    waiting_dialog_desc     = State()
    waiting_dialog_photo    = State()
    waiting_dialog_ex_title = State()
    waiting_dialog_ex_instr = State()
    waiting_dialog_ex_url   = State()




    # Удаление
    delete_choose_type      = State()
    delete_choose_index     = State()



# ────────────────────────────────────────────────────────────────────
# Вспомогательная функция: показать главное админ-меню
# ────────────────────────────────────────────────────────────────────
async def show_admin_menu(message: Message, state: FSMContext):
    """
    Показывает меню:
    «➕ Создать новую тему», «✏️ Редактировать тему», «🏠 Вернуться к урокам».
    Переводит в состояние ожидания NewTopicStates.waiting_admin_choice.
    """
    from create_lesson_block import NewTopicStates

    await state.clear()
    kb = section_menu()                # 💬 Показываем меню действий внутри раздела
    await message.answer("🏠 Админ-меню: выберите действие", reply_markup=kb)
    await state.set_state(NewTopicStates.waiting_admin_choice)


# ────────────────────────────────────────────────────────────────────
# 2. Команда /edittopic: показываем список JSON-файлов тем
# ────────────────────────────────────────────────────────────────────
@router.message(Command("edittopic"))
async def cmd_edittopic(message: Message, state: FSMContext):
    await state.clear()
    topics_dir = Path(__file__).parent / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    files = [p.stem for p in topics_dir.glob("*.json")]

    if not files:
        return await message.answer("⚠️ Нет доступных тем для редактирования.")

    buttons = [[KeyboardButton(text="🚫 Отмена")]] + [[KeyboardButton(text=name)] for name in files]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    await message.answer("✏️ Выберите тему для редактирования:", reply_markup=keyboard)
    await state.set_state(EditTopicStates.choose_topic)


# ────────────────────────────────────────────────────────────────────
# 3. Хендлер выбора темы или «🚫 Отмена»
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.choose_topic, lambda m: not m.text.startswith('/'))
async def choose_topic(message: Message, state: FSMContext):
    name = message.text.strip()
    if name == "🚫 Отмена":
        return await show_admin_menu(message, state)

    path = Path(__file__).parent / "topics" / f"{name}.json"
    if not path.exists():
        return await message.answer("⚠️ Тема не найдена. Пожалуйста, выберите из списка или нажмите «🚫 Отмена».")

    # Загружаем тему
    topic = json.loads(path.read_text(encoding="utf-8"))
    await state.update_data(topic=topic, topic_path=str(path), selected_topic=name)

    sections = [
        ("📚 Словарь",   "vocab"),
        ("🎲 Упражнения","exercises"),
        ("🎬 Видео",    "videos"),
        ("💬 Диалоги",  "dialogs")
    ]
    for label, key in sections:
        items = topic.get(key, [])
        if items:
            lines = []
            for i, blk in enumerate(items, start=1):
                # Определяем тип блока по полям, если нет blk.get("type")
                if blk.get("type") == "quiz" or "question" in blk:
                    preview = blk.get("question", "<без вопроса>")
                elif blk.get("type") == "text" or ("text" in blk and "photo" not in blk and "link" not in blk):
                    words = blk.get("text","").split()
                    preview = " ".join(words[:5]) + ("…" if len(words)>5 else "")
                elif blk.get("type") == "link" or ("link" in blk and "photo" not in blk):
                    title = blk.get("title","Без названия")
                    url   = blk.get("link","")
                    preview = f'{title} — <a href="{url}">ссылка</a>'
                elif blk.get("type") == "photo" or "photo" in blk:
                    preview = blk.get("text", "Фото")
                elif blk.get("type") == "video":
                    title = blk.get("title","Без названия")
                    url   = blk.get("link","")
                    preview = f'{title} — <a href="{url}">ссылка</a>'
                else:
                    # диалог
                    preview = blk.get("title","Без названия")
                lines.append(f"{i}. {preview}")
            await message.answer(
                f"<b>{label}:</b>\n" + "\n".join(lines),
                parse_mode="HTML", disable_web_page_preview=True
            )
        else:
            await message.answer(f"<b>{label}:</b>\nℹ️ Нет блоков", parse_mode="HTML")

    # 💬 И теперь меню действий
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Словарь"),   KeyboardButton(text="🎲 Упражнения")],
            [KeyboardButton(text="🎬 Видео"),     KeyboardButton(text="💬 Диалоги")],
            [KeyboardButton(text="🚫 Отмена"), KeyboardButton(text="Удалить")]
        ],
        resize_keyboard=True
    )
    await message.answer("Что хотите отредактировать в теме?", reply_markup=kb)
    await state.set_state(EditTopicStates.waiting_section)



async def show_section_preview(message: Message, state: FSMContext):
    data  = await state.get_data()
    sec   = data.get("target_list")
    items = data.get("topic", {}).get(sec, [])
    if items:
        lines = []
        for i, blk in enumerate(items, start=1):
            if blk.get("type") == "quiz" or "question" in blk:
                preview = blk.get("question","<без вопроса>")
            elif blk.get("type") == "text" or ("text" in blk and "link" not in blk and "photo" not in blk):
                w = blk.get("text","").split()
                preview = " ".join(w[:5]) + ("…" if len(w)>5 else "")
            elif blk.get("type") == "link" or "link" in blk:
                title, url = blk.get("title","Без названия"), blk.get("link","")
                preview = f'{title} — <a href="{url}">ссылка</a>'
            elif blk.get("type") == "photo" or "photo" in blk:
                preview = blk.get("text","Фото")
            elif blk.get("type") == "video":
                t,u = blk.get("title","Без названия"), blk.get("link","")
                preview = f'{t} — <a href="{u}">ссылка</a>'
            else:
                preview = blk.get("title","Без названия")
            lines.append(f"{i}. {preview}")
        await message.answer("Текущие блоки в разделе:\n" + "\n".join(lines), 
                             parse_mode="HTML", disable_web_page_preview=True)
    else:
        await message.answer("ℹ️ В этом разделе ещё нет блоков.")


# ────────────────────────────────────────────────────────────────────
# Хендлер: выбор раздела (словарь/упражнения/видео/диалоги)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_section)
async def handle_waiting_section(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "Удалить":
        data = await state.get_data()
        # 💬 Удаляем JSON-файл темы
        Path(data["topic_path"]).unlink(missing_ok=True)
        await message.answer("✅ Тема удалена.", reply_markup=ReplyKeyboardRemove())
        # 💬 Показываем список тем заново
        topics_dir = Path(__file__).parent / "topics"
        files = [p.stem for p in topics_dir.glob("*.json")]
        buttons = [[KeyboardButton(text="🚫 Отмена")]] + [[KeyboardButton(text=name)] for name in files]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer("✏️ Выберите тему для редактирования:", reply_markup=keyboard)
        return await state.set_state(EditTopicStates.choose_topic)

    if text == "🚫 Отмена":
        # 💬 Вернуться к выбору темы при отмене
        topics_dir = Path(__file__).parent / "topics"
        files = [p.stem for p in topics_dir.glob("*.json")]
        # Клавиатура: сначала «Отмена», потом названия тем
        buttons = [[KeyboardButton(text="🚫 Отмена")]] + [[KeyboardButton(text=name)] for name in files]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer("✏️ Выберите тему для редактирования:", reply_markup=keyboard)
        return await state.set_state(EditTopicStates.choose_topic)


    # — Редактирование словаря: выбор фазы —
    if text == "📚 Словарь":
        data   = await state.get_data()
        topic  = data.get("topic", {})
        phases = topic.get("vocab", [])
        if not phases:
            # 💬 Фаз словаря нет — говорим об этом и ВОЗВРАЩАЕМ меню разделов
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📚 Словарь"),   KeyboardButton(text="🎲 Упражнения")],
                    [KeyboardButton(text="🎬 Видео"),     KeyboardButton(text="💬 Диалоги")],
                    [KeyboardButton(text="🚫 Отмена"),    KeyboardButton(text="Удалить")]
                ],
                resize_keyboard=True
            )
            await message.answer(
                "ℹ️ В теме нет фаз. Сначала добавьте их через основной поток создания тем.",
                reply_markup=kb
            )
            return await state.set_state(EditTopicStates.waiting_section)


        # строим клавиатуру из существующих фаз + кнопку "новая"
        buttons = [
            [KeyboardButton(text=f"{p['phase_id']}. {p['phase_name']}")]
            for p in phases
        ]
        buttons.append([KeyboardButton(text="➕ Новая фаза")])
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer("Выберите фазу для редактирования словаря:", reply_markup=kb)
        return await state.set_state(EditTopicStates.waiting_vocab_phase_choice)


    # — Редактирование диалогов: выбор фазы —
    if text == "💬 Диалоги":
        data   = await state.get_data()
        topic  = data.get("topic", {})
        phases = topic.get("dialogs", [])

        # 💬 Запоминаем, что сейчас работаем с разделом dialogs
        await state.update_data(target_list="dialogs")

        # Если фаз нет — сразу просим имя новой фазы
        if not phases:
            await message.answer(
                "ℹ️ В этой теме ещё нет фаз диалогов.\n"
                "Введите НАЗВАНИЕ новой фазы диалогов:",
                reply_markup=ReplyKeyboardRemove()
            )
            return await state.set_state(EditTopicStates.waiting_dialog_phase_name)

        # Если фазы есть — строим список кнопок по phase_id/phase_name
        buttons = [
            [KeyboardButton(
                text=f"{p.get('phase_id', i+1)}. {p.get('phase_name', 'Без названия')}"
            )]
            for i, p in enumerate(phases)
        ]
        buttons.append([KeyboardButton(text="➕ Новая фаза диалогов")])
        kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

        await message.answer(
            "Выберите фазу диалогов для редактирования или создайте новую:",
            reply_markup=kb
        )
        return await state.set_state(EditTopicStates.waiting_dialog_phase_choice)

    # — Остальные разделы (упражнения/видео) —
    mapping = {
        "🎲 Упражнения": "exercises",
        "🎬 Видео":      "videos",
    }
    target = mapping.get(text)
    if not target:
        return await message.answer("⚠️ Пожалуйста, выберите раздел из меню.")

    await state.update_data(target_list=target)

    # 💬 Превью: что уже есть в разделе
    data = await state.get_data()
    topic_data = data.get("topic", {})
    items = topic_data.get(target, [])
    if items:
        lines = []
        for i, block in enumerate(items, start=1):
            if block.get("type") == "quiz":
                preview = block.get("question", "<без вопроса>")
            elif block.get("type") == "text":
                txt = block.get("text", "")
                words = txt.split()
                preview = " ".join(words[:5]) + ("…" if len(words) > 5 else "")
            elif block.get("type") == "link":
                title = block.get("title") or "Без названия"
                url   = block.get("link", "")
                preview = f'{title} — <a href="{url}">ссылка</a>'
            else:
                preview = block.get("title", "Без названия")
            lines.append(f"{i}. {preview}")
        await message.answer(
            "<b>Текущие блоки в разделе:</b>\n" + "\n".join(lines),
            parse_mode="HTML", disable_web_page_preview=True
        )
    else:
        await message.answer("ℹ️ В этом разделе блоки ещё не добавлены.")

    # 💬 И теперь меню действий
    kb = section_menu()
    await message.answer(f"Что сделать в разделе «{text}»?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)








@router.message(EditTopicStates.waiting_vocab_phase_choice)
async def choose_edit_vocab_phase(message: Message, state: FSMContext):
    text = message.text.strip()
    # Новая фаза (если нужно)
    if text == "➕ Новая фаза":
        await message.answer("Введите НАЗВАНИЕ новой ФАЗЫ:", reply_markup=ReplyKeyboardRemove())
        return await state.set_state(EditTopicStates.waiting_vocab_phase_name)

    # Выбор существующей фазы
    phase_id = int(text.split(".",1)[0])
    await state.update_data(current_phase_id=phase_id, target_list="vocab")
    await message.answer(f"Фаза выбрана: {text}", reply_markup=ReplyKeyboardRemove())

    # Показываем текущие блоки этой фазы
    data   = await state.get_data()
    blocks = data["topic"]["vocab"][phase_id-1]["vocab"]
    if blocks:
        preview = "\n".join(f"{i+1}. {blk.get('title') or blk.get('question','...')}"
                            for i, blk in enumerate(blocks))
        await message.answer(f"<b>Блоки этой фазы:</b>\n{preview}", parse_mode="HTML")
    else:
        await message.answer("ℹ️ В этой фазе пока нет блоков.")

    # И отдаем меню действий
    await message.answer("Что хотите сделать?", reply_markup=section_menu())
    return await state.set_state(EditTopicStates.choose_action)


@router.message(EditTopicStates.waiting_vocab_phase_name)
async def create_edit_vocab_phase(message: Message, state: FSMContext):
    phase_name = message.text.strip()
    data       = await state.get_data()
    topic      = data["topic"]
    phases     = topic.setdefault("vocab", [])
    new_id     = len(phases) + 1
    # создаём новую фазу
    new_phase = {"phase_id": new_id, "phase_name": phase_name, "vocab": []}
    phases.append(new_phase)
    # сохраняем JSON
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)
    # обновляем состояние и сразу переходим к ней
    # 💬 запоминаем, что мы внутри раздела "vocab"
    await state.update_data(current_phase_id=new_id, target_list="vocab")
    await message.answer(f"Фаза «{phase_name}» создана и выбрана.", reply_markup=ReplyKeyboardRemove())
    # показываем меню действий внутри новой (пустой) фазы
    await message.answer("Что сделать в этой фазе?", reply_markup=section_menu())
    return await state.set_state(EditTopicStates.choose_action)

@router.message(EditTopicStates.waiting_dialog_phase_choice)
async def choose_edit_dialog_phase(message: Message, state: FSMContext):
    text = message.text.strip()

    # 💬 Создание новой фазы диалогов
    if text == "➕ Новая фаза диалогов":
        await message.answer(
            "Введите НАЗВАНИЕ новой фазы диалогов:",
            reply_markup=ReplyKeyboardRemove()
        )
        return await state.set_state(EditTopicStates.waiting_dialog_phase_name)

    # 💬 Выбор существующей фазы по формату "1. Имя фазы"
    try:
        phase_id = int(text.split(".", 1)[0])
    except ValueError:
        await message.answer("⚠️ Пожалуйста, выберите фазу из списка или нажмите «➕ Новая фаза диалогов».")
        return

    data    = await state.get_data()
    topic   = data.get("topic", {})
    dialogs = topic.get("dialogs", [])

    phase_index = None
    for i, ph in enumerate(dialogs):
        if ph.get("phase_id") == phase_id:
            phase_index = i
            break
    if phase_index is None:
        # fallback по порядку, если phase_id не найден
        if 1 <= phase_id <= len(dialogs):
            phase_index = phase_id - 1
        else:
            await message.answer("⚠️ Фаза диалогов не найдена. Выберите из списка.")
            return

    phase = dialogs[phase_index]
    await state.update_data(current_dialog_phase_id=phase.get("phase_id"))

    # 💬 Показываем мини-диалоги внутри фазы
    blocks = phase.get("blocks", [])
    if blocks:
        lines = []
        for i, blk in enumerate(blocks, start=1):
            first_line = ""
            if isinstance(blk, dict):
                lst = blk.get("lines") or []
                if isinstance(lst, list) and lst:
                    first_line = lst[0]
            if not first_line:
                first_line = "<пустая реплика>"
            if len(first_line) > 60:
                first_line = first_line[:57] + "…"
            lines.append(f"{i}. {first_line}")
        await message.answer(
            "<b>Мини-диалоги этой фазы:</b>\n" + "\n".join(lines),
            parse_mode="HTML"
        )
    else:
        await message.answer("ℹ️ В этой фазе пока нет мини-диалогов.")

    # 💬 Меню действий внутри выбранной фазы
    await message.answer("Что хотите сделать с этой фазой диалогов?", reply_markup=section_menu())
    return await state.set_state(EditTopicStates.choose_action)


@router.message(EditTopicStates.waiting_dialog_phase_name)
async def create_edit_dialog_phase(message: Message, state: FSMContext):
    phase_name = message.text.strip()
    data       = await state.get_data()
    topic      = data.get("topic", {})
    dialogs    = topic.setdefault("dialogs", [])

    # 💬 Считаем следующий phase_id, как в CreateLessonBlock
    existing_ids = [
        d.get("phase_id")
        for d in dialogs
        if isinstance(d, dict) and isinstance(d.get("phase_id"), int)
    ]
    next_id = max(existing_ids) + 1 if existing_ids else (len(dialogs) + 1 or 1)

    new_phase = {
        "phase_id":   next_id,
        "phase_name": phase_name,
        "blocks":     []  # 💬 сюда будем добавлять пары RU+ES
    }
    dialogs.append(new_phase)
    topic["dialogs"] = dialogs

    # 💾 Сохраняем JSON
    path = data.get("topic_path")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(topic, f, ensure_ascii=False, indent=2)

    # 💬 Обновляем state
    await state.update_data(topic=topic, current_dialog_phase_id=next_id, target_list="dialogs")

    await message.answer(
        f"Фаза диалогов «{phase_name}» создана и выбрана.",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Что сделать в этой фазе диалогов?", reply_markup=section_menu())
    return await state.set_state(EditTopicStates.choose_action)

@router.message(EditTopicStates.waiting_dialog_block_markdown)
async def add_dialog_blocks_markdown(message: Message, state: FSMContext):
    """
    💬 Добавляем в выбранную фазу диалогов новые мини-диалоги (RU+ES по 2 строки),
    по той же логике, как в CreateLessonBlock.
    """
    raw = (message.text or "").strip()

    # Срезаем ``` если прислали код-блок
    if raw.startswith("```"):
        raw = raw.lstrip("`").strip()
    if raw.endswith("```"):
        raw = raw.rstrip("`").strip()

    # Берём только непустые строки
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        await message.answer("❗ Не вижу строк в сообщении. Пришлите мини-диалоги ещё раз.")
        return

    if len(lines) % 2 != 0:
        await message.answer(
            f"❗ Количество НЕпустых строк должно делиться на 2.\n"
            f"Сейчас строк: {len(lines)}.\n"
            "Каждый мини-диалог должен быть из 2 строк (RU + ES)."
        )
        return

    # Собираем блоки по 2 строки
    new_blocks = []
    for i in range(0, len(lines), 2):
        pair = lines[i:i+2]
        new_blocks.append({"lines": pair})

    data    = await state.get_data()
    topic   = data.get("topic", {})
    path    = data.get("topic_path")
    phase_id = data.get("current_dialog_phase_id")
    dialogs = topic.setdefault("dialogs", [])

    if not phase_id or not dialogs:
        await message.answer("⚠️ Фаза диалогов не выбрана. Сначала выберите её в разделе «💬 Диалоги».")
        return await state.set_state(EditTopicStates.waiting_section)

    # Находим фазу по phase_id
    phase_index = None
    for i, ph in enumerate(dialogs):
        if ph.get("phase_id") == phase_id:
            phase_index = i
            break
    if phase_index is None:
        await message.answer("⚠️ Фаза диалогов не найдена. Попробуйте выбрать её снова.")
        return await state.set_state(EditTopicStates.waiting_section)

    phase = dialogs[phase_index]
    blocks = phase.get("blocks") or []
    blocks.extend(new_blocks)
    phase["blocks"] = blocks
    dialogs[phase_index] = phase
    topic["dialogs"] = dialogs

    # 💾 Сохраняем JSON
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)

    await message.answer(
        f"✅ Добавлено мини-диалогов: {len(new_blocks)}.",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Что дальше сделать с этой фазой диалогов?", reply_markup=section_menu())
    return await state.set_state(EditTopicStates.choose_action)


@router.message(EditTopicStates.choose_action)
async def choose_action(message: Message, state: FSMContext):
    text = message.text.strip()

    data = await state.get_data()
    target = data.get("target_list")  # раздел: "vocab", "exercises", "videos" или "dialogs"
    # 🚫 Отмена → вернуться в главное админ-меню
    # 🚫 Отмена → вернуться к выбору раздела внутри темы
    if text == "🚫 Отмена":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Словарь"),    KeyboardButton(text="🎲 Упражнения")],
                [KeyboardButton(text="🎬 Видео"),      KeyboardButton(text="💬 Диалоги")],
                [KeyboardButton(text="🚫 Отмена")]
            ],
            resize_keyboard=True
        )
        await message.answer("Отмена. Что хотите отредактировать в теме?", reply_markup=kb)
        return await state.set_state(EditTopicStates.waiting_section)



    # — Если раздел уже выбран, действуем внутри него:
    if target:
        # ➕ Добавить блок
        if text == "➕ Добавить блок":
            if target == "vocab":
                # 💬 Для СЛОВАРЯ при «Добавить блок» уходим в поток CreateLessonBlock
                from create_lesson_block import NewTopicStates, send_post_menu  # локальный импорт, чтобы не ловить циклы

                await state.update_data(last_block="vocab")
                await send_post_menu(message, state)
                return await state.set_state(NewTopicStates.waiting_post_action)

            elif target == "dialogs":
                # 💬 Для ДИАЛОГОВ — добавляем мини-диалоги в выбранную фазу
                data = await state.get_data()
                phase_id = data.get("current_dialog_phase_id")
                if not phase_id:
                    await message.answer("⚠️ Сначала выберите фазу диалогов для редактирования.")
                    return

                await message.answer(
                    "Пришлите мини-диалоги в Markdown.\n"
                    "Каждый блок — 2 строки подряд (RU + ES).\n"
                    "Пустые строки будут проигнорированы.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return await state.set_state(EditTopicStates.waiting_dialog_block_markdown)

            else:
                # 💬 Для упражнений и видео — выбираем тип блока (текст/фото/линк)
                kb = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="📝 Текст"), KeyboardButton(text="🖼 Фото")],
                        [KeyboardButton(text="📎 Линк"),  KeyboardButton(text="🚫 Отмена")]
                    ],
                    resize_keyboard=True
                )
                await message.answer("🔸 Выберите тип блока для добавления:", reply_markup=kb)
                await state.update_data(main_action=target)
                return await state.set_state(EditTopicStates.choose_block_type)

        # ➖ Удалить блок
        if text == "➖ Удалить блок":
            if target == "vocab":
                # 💬 В разделе СЛОВАРЬ «удалить блок» = удалить текущую фазу целиком
                topic = data.get("topic", {})
                phases = topic.get("vocab", [])
                cp = data.get("current_phase_id")

                if not phases:
                    return await message.answer("ℹ️ В теме нет фаз словаря для удаления.")
                if not cp or cp < 1 or cp > len(phases):
                    return await message.answer("⚠️ Фаза для удаления не выбрана. Сначала выберите фазу в списке.")

                removed_phase = phases.pop(cp - 1)

                for i, ph in enumerate(phases, start=1):
                    ph["phase_id"] = i
                topic["vocab"] = phases

                path = data.get("topic_path")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(topic, f, ensure_ascii=False, indent=2)

                await state.update_data(topic=topic, current_phase_id=None)

                await message.answer(
                    f"✅ Фаза «{removed_phase.get('phase_name', 'без имени')}» удалена.",
                    reply_markup=ReplyKeyboardRemove()
                )

                if phases:
                    buttons = [
                        [KeyboardButton(text=f"{p['phase_id']}. {p['phase_name']}")]
                        for p in phases
                    ]
                    buttons.append([KeyboardButton(text="➕ Новая фаза")])
                    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
                    await message.answer(
                        "Выберите фазу для редактирования словаря:",
                        reply_markup=kb
                    )
                    return await state.set_state(EditTopicStates.waiting_vocab_phase_choice)
                else:
                    kb = ReplyKeyboardMarkup(
                        keyboard=[
                            [KeyboardButton(text="📚 Словарь"), KeyboardButton(text="🎲 Упражнения")],
                            [KeyboardButton(text="🎬 Видео"),   KeyboardButton(text="💬 Диалоги")],
                            [KeyboardButton(text="🚫 Отмена")]
                        ],
                        resize_keyboard=True
                    )
                    await message.answer(
                        "ℹ️ В теме не осталось фаз словаря. Можете создать новую.",
                        reply_markup=kb
                    )
                    return await state.set_state(EditTopicStates.waiting_section)

            elif target == "dialogs":
                # 💬 В разделе ДИАЛОГИ — удаляем мини-диалог внутри выбранной фазы
                data    = await state.get_data()
                topic   = data.get("topic", {})
                phase_id = data.get("current_dialog_phase_id")
                dialogs = topic.get("dialogs", [])

                if not phase_id or not dialogs:
                    await message.answer("⚠️ Сначала выберите фазу диалогов для редактирования.")
                    return

                phase_index = None
                for i, ph in enumerate(dialogs):
                    if ph.get("phase_id") == phase_id:
                        phase_index = i
                        break
                if phase_index is None:
                    await message.answer("⚠️ Фаза диалогов не найдена. Выберите её ещё раз.")
                    return

                blocks = dialogs[phase_index].get("blocks", [])
                if not blocks:
                    await message.answer("ℹ️ В этой фазе пока нет мини-диалогов для удаления.")
                    return

                lines = []
                for i, blk in enumerate(blocks, start=1):
                    first_line = ""
                    if isinstance(blk, dict):
                        lst = blk.get("lines") or []
                        if isinstance(lst, list) and lst:
                            first_line = lst[0]
                    if not first_line:
                        first_line = "<пустая реплика>"
                    if len(first_line) > 60:
                        first_line = first_line[:57] + "…"
                    lines.append(f"{i}. {first_line}")

                await message.answer(
                    "🗑️ Введите номер мини-диалога для удаления:\n" + "\n".join(lines),
                    reply_markup=ReplyKeyboardRemove()
                )
                return await state.set_state(EditTopicStates.waiting_dialog_block_delete_index)

            else:
                # 💬 Для упражнений и видео — удаляем ОДИН блок по индексу
                topic = data.get("topic", {})
                if target == "exercises":
                    items = topic.get("exercises", [])
                elif target == "videos":
                    items = topic.get("videos", [])
                else:
                    items = []

                if not items:
                    return await message.answer("ℹ️ В разделе нет блоков для удаления.")

                lines = []
                for i, blk in enumerate(items, start=1):
                    title = blk.get("title") or blk.get("question", "Без названия")
                    lines.append(f"{i}. {title}")
                preview = "\n".join(lines)

                await state.update_data(delete_kind=target)
                await message.answer(
                    f"🗑️ Введите номер блока для удаления:\n{preview}",
                    reply_markup=ReplyKeyboardRemove()
                )
                return await state.set_state(EditTopicStates.delete_choose_index)

        # 🔀 Поменять местами (если потребуется в будущем)
        if text == "🔀 Поменять местами":
            await message.answer(
                "🔄 Введите два номера блоков через пробел (например: 1 2):",
                reply_markup=ReplyKeyboardRemove()
            )
            return await state.set_state(EditTopicStates.swap_indexes)

        # Любая другая кнопка внутри раздела
        return await message.answer("⚠️ Пожалуйста, выберите действие из меню.")

    # — Старая логика без раздела (оставляем только текст/фото/линк)
    if text in ["➕ Добавить словарь", "➕ Добавить упражнение"]:
        await state.update_data(main_action=text)
        kb = ReplyKeyboardMarkup(
            keyboard=[ 
                [KeyboardButton(text="📝 Текст"), KeyboardButton(text="🖼 Фото")],
                [KeyboardButton(text="📎 Линк"),  KeyboardButton(text="🚫 Отмена")]
            ],
            resize_keyboard=True
        )
        await message.answer("🔸 Выберите тип блока для добавления:", reply_markup=kb)
        return await state.set_state(EditTopicStates.choose_block_type)


    return await message.answer("⚠️ Пожалуйста, выберите одну из кнопок меню.")


@router.message(EditTopicStates.choose_block_type)
async def handle_choose_block_type(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    main_action = data["main_action"]  # ключ раздела: "vocab" или "exercises"

    # 🚫 Отмена → назад в меню действий
    if text == "🚫 Отмена":
        await message.answer("Добавление отменено.", reply_markup=ReplyKeyboardRemove())
        await message.answer("Что дальше?", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # 💬 Оставляем только типы: текст / фото / линк
    block_types = {
        "📝 Текст": "text",
        "🖼 Фото": "photo",
        "📎 Линк": "link",
    }

    if text in block_types:
        await state.update_data(action=block_types[text], main_action=main_action)
        data = await state.get_data()
        topic = data["topic"]

        # main_action уже хранит "vocab" или "exercises"
        target_list = main_action

        if target_list == "vocab":
            cp      = data["current_phase_id"]
            max_pos = len(topic["vocab"][cp-1]["vocab"]) + 1
        else:
            max_pos = len(topic.get(target_list, [])) + 1

        await message.answer(
            f"✏️ На какую позицию (1–{max_pos}) вставить новый блок? 🚫 Отмена",
            reply_markup=ReplyKeyboardRemove()
        )
        return await state.set_state(EditTopicStates.insert_index)

    # Если выбрана неправильная кнопка
    return await message.answer("⚠️ Выберите одну из предложенных кнопок.")



# ────────────────────────────────────────────────────────────────────
# 📝 Handler: пользователь вводит позицию, куда вставить выбранный тип блока
# Обработка введенного числа и выбор следующего шага
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.insert_index)
async def handle_insert_index(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()

    # 💬 Теперь action может быть только: "text", "photo", "link"
    action      = data["action"]
    main_action = data["main_action"]     # ключ раздела: "vocab" или "exercises"
    topic       = data["topic"]

    # main_action уже хранит ключ раздела ("vocab" или "exercises")
    target_list = main_action

    if target_list == "vocab":
        cp      = data["current_phase_id"]
        max_pos = len(topic["vocab"][cp-1]["vocab"]) + 1
    else:
        max_pos = len(topic.get(target_list, [])) + 1

    # 🚫 Если пользователь нажал «Отмена»
    if text == "🚫 Отмена":
        await message.answer("Добавление отменено.", reply_markup=ReplyKeyboardRemove())
        await message.answer("Что дальше?", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # ⚠️ Проверка, что пользователь ввёл корректную позицию (число)
    if not text.isdigit() or not (1 <= int(text) <= max_pos):
        await message.answer(f"⚠️ Введите число от 1 до {max_pos} или нажмите «🚫 Отмена».")
        return

    # ✅ Сохраняем выбранную позицию в state (0-based)
    await state.update_data(insert_index=int(text) - 1)

    # 💬 Определяем, что спросить дальше (следующее состояние FSM)
    if action == "text":
        await message.answer("Введите текст для текстового блока:")
        return await state.set_state(EditTopicStates.waiting_text_block)

    elif action == "photo":
        if target_list == "vocab":
            await message.answer(
                "📝 Введите подпись к фото (или '-' для пустой подписи):",
                reply_markup=ReplyKeyboardRemove()
            )
            return await state.set_state(EditTopicStates.waiting_vocab_photo_text)
        else:
            await message.answer(
                "📝 Введите подпись к фото упражнения (или '-' для пустой подписи):",
                reply_markup=ReplyKeyboardRemove()
            )
            return await state.set_state(EditTopicStates.waiting_ex_photo_text)

    elif action == "link":
        await message.answer("Введите название ссылки:")
        # 💬 Состояние зависит от раздела (словарь или упражнение)
        if target_list == "vocab":
            return await state.set_state(EditTopicStates.waiting_vocab_title)
        else:
            return await state.set_state(EditTopicStates.waiting_ex_title)

    else:
        # На всякий случай fallback, если вдруг action старый
        await message.answer("⚠️ Ошибка, тип блока неизвестен.", reply_markup=ReplyKeyboardRemove())
        await message.answer("Что дальше?", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)


# ────────────────────────────────────────────────────────────────────
# 6. Добавление словаря: ввод заголовка
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_vocab_title)
async def handle_vocab_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(vocab_title=title)
    await message.answer("🖇️ Введите ССЫЛКУ или ТЕКСТ словаря:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_vocab_link)


# ────────────────────────────────────────────────────────────────────
# 7. Добавление словаря: ввод ссылки/текста, сохранение
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_vocab_link)
async def handle_vocab_link(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    # — если вставили <iframe ... src="URL" ...>, достаём URL
    import re
    m = re.search(r'src="([^"]+)"', raw_input)
    url = m.group(1) if m else raw_input

    data = await state.get_data()
    topic_data = data.get("topic", {})
    path = data.get("topic_path")
    idx = data.get("insert_index", 0)

    # 💬 Сохраняем новый link-блок в словаре
    new_block = {
        "type":  "link",                    # тип блока
        "title": data.get("vocab_title"),   # заголовок ссылки
        "link":  url                        # чистый URL
    }



    # 💬 вставляем link-блок в выбранную фазу
    cp         = data["current_phase_id"]
    phase_list = topic_data["vocab"][cp-1]["vocab"]
    phase_list.insert(idx, new_block)
    topic_data["vocab"][cp-1]["vocab"] = phase_list


    # Сохраняем JSON-файл
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Удаляем временные поля
    await state.update_data(vocab_title=None, insert_index=None)

    # Сообщаем об успешном добавлении и возвращаем в меню действий
    await message.answer("✅ Словарь добавлен.", reply_markup=ReplyKeyboardRemove())
    await show_section_preview(message, state)
    kb = section_menu()                # 💬 Показываем меню действий внутри раздела
    await message.answer("Что дальше?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)


# ────────────────────────────────────────────────────────────────────
# 8. Добавление упражнения: ввод названия
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_title)
async def handle_ex_title(message: Message, state: FSMContext):
    ex_title = message.text.strip()
    await state.update_data(ex_title=ex_title)
    await message.answer("🖋️ Введите ИНСТРУКЦИЮ для упражнения:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_ex_instr)


# ────────────────────────────────────────────────────────────────────
# 9. Добавление упражнения: ввод инструкции
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_instr)
async def handle_ex_instr(message: Message, state: FSMContext):
    ex_instr = message.text.strip()
    await state.update_data(ex_instr=ex_instr)
    await message.answer("🖇️ Введите ССЫЛКУ или КОНТЕНТ упражнения:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_ex_url)


# ────────────────────────────────────────────────────────────────────
# 10. Добавление упражнения: ввод ссылки/контента, сохранение
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_url)
async def handle_ex_url(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    data = await state.get_data()
    topic_data = data.get("topic", {})
    path = data.get("topic_path")
    idx = data.get("insert_index", 0)

    new_block = {
        "type": "link",
        "title": data.get("ex_title"),
        "instruction": data.get("ex_instr"),
        "url": raw_input
    }

    ex_list = topic_data.get("exercises", [])
    if idx < 0:
        idx = 0
    if idx > len(ex_list):
        idx = len(ex_list)
    ex_list.insert(idx, new_block)
    topic_data["exercises"] = ex_list

    # Сохраняем JSON-файл
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    await state.update_data(ex_title=None, ex_instr=None, insert_index=None)

    await message.answer("✅ Упражнение добавлено.", reply_markup=ReplyKeyboardRemove())
    kb = section_menu()                # 💬 Показываем меню действий внутри раздела
    await message.answer("Что дальше?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)


# ────────────────────────────────────────────────────────────────────
# 11. Добавление видео: ввод заголовка
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_video_title)
async def handle_video_title(message: Message, state: FSMContext):
    video_title = message.text.strip()
    await state.update_data(video_title=video_title)
    await message.answer("🖇️ Введите ССЫЛКУ на видео:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_video_link)


# ────────────────────────────────────────────────────────────────────
# 12. Добавление видео: ввод ссылки, сохранение
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_video_link)
async def handle_video_link(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    data = await state.get_data()
    topic_data = data.get("topic", {})
    path = data.get("topic_path")
    idx = data.get("insert_index", 0)

    # 💬 Сохраняем новый video-блок
    new_block = {
        "type":  "video",                     # указываем тип блока
        "title": data.get("video_title"),     # заголовок видео
        "link":  raw_input                    # чистый URL
    }


    vid_list = topic_data.get("videos", [])
    if idx < 0:
        idx = 0
    if idx > len(vid_list):
        idx = len(vid_list)
    vid_list.insert(idx, new_block)
    topic_data["videos"] = vid_list

    # Сохраняем JSON-файл
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    await state.update_data(video_title=None, insert_index=None)

    await message.answer("✅ Видео добавлено.", reply_markup=ReplyKeyboardRemove())
    kb = section_menu()                # 💬 Показываем меню действий внутри раздела
    await message.answer("Что дальше?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)


# ────────────────────────────────────────────────────────────────────
# 13. Добавление диалога: ввод заголовка
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_dialog_title)
async def handle_dialog_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(dialog_title=title)
    await message.answer("📝 Введите ОПИСАНИЕ диалога:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_dialog_desc)


# ────────────────────────────────────────────────────────────────────
# 14. Добавление диалога: ввод описания
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_dialog_desc)
async def handle_dialog_desc(message: Message, state: FSMContext):
    desc = message.text.strip()
    await state.update_data(dialog_desc=desc)
    await message.answer("🖼 Введите ССЫЛКУ на фото или загрузите файл изображения для диалога:")
    return await state.set_state(EditTopicStates.waiting_dialog_photo)


# ────────────────────────────────────────────────────────────────────
# 15. Добавление диалога: ввод фото/ссылки, сохранение и возможность добавить упражнение
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_dialog_photo, lambda m: m.photo or m.text)
async def handle_dialog_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_data = data.get("topic", {})
    path = data.get("topic_path")
    idx = data.get("insert_index", 0)

    # Получаем файл или URL
    if message.photo:
        photo_id = message.photo[-1].file_id
        photo_url = photo_id
    else:
        photo_url = message.text.strip()

    # Формируем новый диалог
    new_dialog = {
        "title": data.get("dialog_title"),
        "description": data.get("dialog_desc"),
        "photos": [photo_url],
        "exercises": []
    }
    dlg_list = topic_data.get("dialogs", [])
    if idx < 0:
        idx = 0
    if idx > len(dlg_list):
        idx = len(dlg_list)
    dlg_list.insert(idx, new_dialog)
    topic_data["dialogs"] = dlg_list

    # Сохраняем JSON
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Удаляем временные поля, кроме insert_index (он хранит позицию для exercise)
    await state.update_data(dialog_title=None, dialog_desc=None)

    # Предложить добавить упражнение к только что добавленному диалогу
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔤 Добавить упражнение к этому диалогу")],
            [KeyboardButton(text="↩️ Вернуться в меню редактирования")]
        ],
        resize_keyboard=True
    )
    await message.answer("✅ Диалог добавлен.", reply_markup=ReplyKeyboardRemove())
    await message.answer("Что дальше с этим диалогом?", reply_markup=kb)
    return await state.set_state(EditTopicStates.waiting_dialog_ex_title)


# ────────────────────────────────────────────────────────────────────
# 16. Добавление упражнения к диалогу: ввод названия
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_dialog_ex_title)
async def handle_dialog_ex_title(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "↩️ Вернуться в меню редактирования":
        # Сразу возврат к главному меню редактирования темы
        data = await state.get_data()
        topic = data.get("topic", {})
        kb = section_menu()
        await message.answer("Возвращаемся в меню редактирования темы.", reply_markup=kb)
        return await state.set_state(EditTopicStates.choose_action)

    ex_title = text
    await state.update_data(dialog_ex_title=ex_title)
    await message.answer("🖋️ Введите ИНСТРУКЦИЮ для упражнения этого диалога:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_dialog_ex_instr)


# ────────────────────────────────────────────────────────────────────
# 17. Добавление упражнения к диалогу: ввод инструкции
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_dialog_ex_instr)
async def handle_dialog_ex_instr(message: Message, state: FSMContext):
    ex_instr = message.text.strip()
    await state.update_data(dialog_ex_instr=ex_instr)
    await message.answer("🖇️ Введите ССЫЛКУ или КОНТЕНТ упражнения для диалога:", reply_markup=ReplyKeyboardRemove())
    return await state.set_state(EditTopicStates.waiting_dialog_ex_url)


# ────────────────────────────────────────────────────────────────────
# 18. Добавление упражнения к диалогу: ввод ссылки/контента и сохранение
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_dialog_ex_url)
async def handle_dialog_ex_url(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    data = await state.get_data()
    topic_data = data.get("topic", {})
    path = data.get("topic_path")
    idx = data.get("insert_index", 0)

    # Формируем новую запись упражнения
    new_ex = {
        "type": "link",
        "title": data.get("dialog_ex_title"),
        "instruction": data.get("dialog_ex_instr"),
        "url": raw_input
    }

    dlg_list = topic_data.get("dialogs", [])
    # Если индекс выходит за границы, корректируем
    if idx < 0:
        idx = 0
    if idx >= len(dlg_list):
        idx = len(dlg_list) - 1
    # Добавляем в нужный диалог
    dlg_list[idx].setdefault("exercises", []).append(new_ex)
    topic_data["dialogs"] = dlg_list

    # Сохраняем JSON
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Удаляем временные поля
    await state.update_data(dialog_ex_title=None, dialog_ex_instr=None, insert_index=None)

    # Сообщаем об успешном добавлении и возвращаемся к меню редактирования темы
    await message.answer("✅ Упражнение добавлено к диалогу.", reply_markup=ReplyKeyboardRemove())
    kb = section_menu()
    await message.answer("Что дальше?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)


# ────────────────────────────────────────────────────────────────────
# 19. Удаление блока: выбор типа блока
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.delete_choose_type)
async def handle_delete_choose_type(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    data = await state.get_data()
    topic = data.get("topic", {})

    # 🚫 Отмена → вернуться к меню редактирования темы
    if text == "🚫 отмена":
        kb = section_menu()

        await message.answer("Удаление отменено.", reply_markup=kb)
        return await state.set_state(EditTopicStates.choose_action)

    if "слов" in text:
        items = topic.get("vocab", [])
        label = "Словарь"
        kind = "vocab"
    elif "упражн" in text:
        items = topic.get("exercises", [])
        label = "Упражнение"
        kind = "exercise"
    elif "диал" in text:
        items = topic.get("dialogs", [])
        label = "Диалог"
        kind = "dialog"
    elif "видео" in text:
        items = topic.get("videos", [])
        label = "Видео"
        kind = "video"
    else:
        return await message.answer("⚠️ Пожалуйста, выберите «Словарь», «Упражнение», «Диалог» или «Видео», либо «🚫 Отмена».")
    if not items:
        return await message.answer(f"ℹ️ В теме нет блоков типа «{label}» для удаления.")

    # Формируем список элементов с их заголовками
    # ─── Формируем превью для каждого блока ───
    lines = []
    for idx, block in enumerate(items, start=1):
        # 1) Quiz-блок: показываем сам вопрос
        if block.get("type") == "quiz":
            preview = block.get("question", "<без вопроса>")
        # 2) Text-блок: первые 5 слов или 20 символов
        elif block.get("type") == "text":
            txt = block.get("text", "")
            words = txt.split()
            if len(words) > 5:
                preview = " ".join(words[:5]) + "…"
        else:
            # Ссылка — показываем заголовок и оборачиваем URL в слово «ссылка»
            title = block.get("title") or "Без названия"
            url   = block.get("link", "")
            preview = f'{title} — <a href="{url}">ссылка</a>'

        lines.append(f"{idx}. {preview}")

    preview = (
        f"<b>Блоки «{label}»:</b>\n"
        + "\n".join(lines)
        + f"\n\n<i>Введите номер (1–{len(items)}) для удаления или «🚫 Отмена»</i>"
    )
    await message.answer(preview, parse_mode="HTML", disable_web_page_preview=True)


    # Сохраняем, что будем удалять
    await state.update_data(delete_kind=kind)
    return await state.set_state(EditTopicStates.delete_choose_index)





# ────────────────────────────────────────────────────────────────────
# 20. Удаление блока: ввод номера и удаление
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.delete_choose_index)
async def handle_delete_choose_index(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    kind = data.get("delete_kind")
    topic_data = data.get("topic", {})
    path = data.get("topic_path")

    # 🚫 Отмена → вернуться к меню редактирования темы
    if text == "🚫 Отмена":
        await message.answer("Удаление отменено.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    if not text.isdigit():
        return await message.answer("⚠️ Введите номер блока или «🚫 Отмена».")

    idx = int(text) - 1

    # Выбираем список для удаления
    if kind == "vocab":
        # 💬 удаляем из выбранной фазы
        cp = data["current_phase_id"]
        lst = topic_data["vocab"][cp - 1]["vocab"]
    elif kind == "exercise":
        lst = topic_data.get("exercises", [])
    elif kind == "dialog":
        lst = topic_data.get("dialogs", [])
    else:  # kind == "video"
        lst = topic_data.get("videos", [])

    if not (0 <= idx < len(lst)):
        return await message.answer(
            f"⚠️ Номер вне диапазона. Введите от 1 до {len(lst)} или «🚫 Отмена»."
        )

    removed = lst.pop(idx)

    # Сохраняем изменения обратно в topic_data
    if kind == "vocab":
        topic_data["vocab"][cp - 1]["vocab"] = lst
    elif kind == "exercise":
        topic_data["exercises"] = lst
    elif kind == "dialog":
        topic_data["dialogs"] = lst
    else:
        topic_data["videos"] = lst

    # Записываем JSON
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    await message.answer(
        f"✅ Блок «{removed.get('title', removed.get('question','Без названия'))}» удалён.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Возвращаемся к меню редактирования темы
    await message.answer("Что дальше?", reply_markup=section_menu())
    return await state.set_state(EditTopicStates.choose_action)



@router.message(EditTopicStates.waiting_dialog_block_delete_index)
async def handle_dialog_block_delete_index(message: Message, state: FSMContext):
    """
    # 💬 Удаляем один мини-диалог в выбранной фазе диалогов и возвращаемся в меню действий
    """
    text = message.text.strip()
    data = await state.get_data()
    topic = data.get("topic", {})
    path = data.get("topic_path")
    phase_id = data.get("current_dialog_phase_id")
    dialogs = topic.get("dialogs", [])

    # 🚫 Отмена → назад в меню действий внутри фазы
    if text == "🚫 Отмена":
        kb = section_menu()
        await message.answer("Удаление мини-диалога отменено.", reply_markup=kb)
        return await state.set_state(EditTopicStates.choose_action)

    # Проверяем, что введено число
    if not text.isdigit():
        await message.answer("⚠️ Введите номер мини-диалога или «🚫 Отмена».")
        return

    idx = int(text) - 1

    # Проверяем, что фаза выбрана и есть диалоги
    if not phase_id or not dialogs:
        await message.answer("⚠️ Фаза диалогов не выбрана. Сначала выберите её в разделе «💬 Диалоги».")
        return await state.set_state(EditTopicStates.waiting_section)

    # Находим индекс фазы по phase_id (как в choose_edit_dialog_phase)
    phase_index = None
    for i, ph in enumerate(dialogs):
        if ph.get("phase_id") == phase_id:
            phase_index = i
            break

    if phase_index is None:
        await message.answer("⚠️ Фаза диалогов не найдена. Выберите её ещё раз.")
        return await state.set_state(EditTopicStates.waiting_section)

    phase = dialogs[phase_index]
    blocks = phase.get("blocks") or []

    if not blocks:
        kb = section_menu()
        await message.answer("ℹ️ В этой фазе нет мини-диалогов для удаления.", reply_markup=kb)
        return await state.set_state(EditTopicStates.choose_action)

    # Проверяем диапазон номера
    if not (0 <= idx < len(blocks)):
        await message.answer(
            f"⚠️ Номер вне диапазона. Введите от 1 до {len(blocks)} или «🚫 Отмена»."
        )
        return

    removed = blocks.pop(idx)
    phase["blocks"] = blocks
    dialogs[phase_index] = phase
    topic["dialogs"] = dialogs

    # 💾 Сохраняем JSON, если путь есть
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(topic, f, ensure_ascii=False, indent=2)

    await state.update_data(topic=topic)

    # Короткий текст для подтверждения
    first_line = ""
    if isinstance(removed, dict):
        lst = removed.get("lines") or []
        if isinstance(lst, list) and lst:
            first_line = lst[0]
    if not first_line:
        first_line = "мини-диалог"

    await message.answer(
        f"✅ Мини-диалог «{first_line[:50]}» удалён.",
        reply_markup=ReplyKeyboardRemove()
    )

    # 💬 Возвращаемся в меню действий по фазе диалогов
    kb = section_menu()
    await message.answer("Что дальше сделать с этой фазой диалогов?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)




# ────────────────────────────────────────────────────────────────────
# 🖼 Handler: текст подписи фото (для раздела словарь)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_vocab_photo_text)
async def handle_vocab_photo_text(message: Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(vocab_photo_text=None if text == "-" else text)
    await message.answer("📸 Теперь отправьте само фото:")
    await state.set_state(EditTopicStates.waiting_vocab_photo_file)


# ────────────────────────────────────────────────────────────────────
# 🖼 Handler: обработка загрузки фото (для раздела словарь)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_vocab_photo_file, lambda m: m.photo)
async def handle_vocab_photo_file(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_data = data["topic"]
    idx = data["insert_index"]

    photo_id = message.photo[-1].file_id
    caption = data.get("vocab_photo_text")

    new_block = {
        "type": "photo",
        "text": caption,
        "photo": photo_id
    }

    # 💬 вставляем фото-блок в выбранную фазу
    cp         = data["current_phase_id"]
    phase_list = topic_data["vocab"][cp-1]["vocab"]
    phase_list.insert(idx, new_block)
    topic_data["vocab"][cp-1]["vocab"] = phase_list


    # Сохраняем изменения в JSON
    path = data["topic_path"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # 💬 Запросим опциональный quiz
    await state.update_data(vocab_photo_text=None, current_quiz_text=None)
    await message.answer(
        "📝 Пришлите опциональный quiz одним сообщением через `|` или '-' для пропуска:\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ПояснениеПравильного|ПояснениеНеправильно",
        reply_markup=ReplyKeyboardRemove()
    )
    return await state.set_state(EditTopicStates.waiting_vocab_photo_quiz)



# 💬 Если пользователь отправил не фото
@router.message(EditTopicStates.waiting_vocab_photo_file)
async def handle_wrong_vocab_photo(message: Message):
    await message.answer("⚠️ Это не фото. Пожалуйста, отправьте изображение.")


# ────────────────────────────────────────────────────────────────────
# 🖼 Handler: текст подписи фото (для раздела упражнения)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_photo_text)
async def handle_ex_photo_text(message: Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(ex_photo_text=None if text == "-" else text)
    await message.answer("📸 Теперь отправьте само фото:")
    await state.set_state(EditTopicStates.waiting_ex_photo_file)


# ────────────────────────────────────────────────────────────────────
# 🖼 Handler: обработка загрузки фото (для раздела упражнения)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_photo_file, lambda m: m.photo)
async def handle_ex_photo_file(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_data = data["topic"]
    idx = data["insert_index"]

    photo_id = message.photo[-1].file_id
    caption = data.get("ex_photo_text")

    new_block = {
        "type": "photo",
        "text": caption,
        "photo": photo_id
    }

    ex_list = topic_data.setdefault("exercises", [])
    ex_list.insert(idx, new_block)

    # Сохраняем JSON
    path = data["topic_path"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    await state.update_data(ex_photo_text=None, insert_index=None)

    kb = section_menu()
    await message.answer("✅ Фото добавлено в упражнения!", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)


# 💬 Если пользователь отправил не фото
@router.message(EditTopicStates.waiting_ex_photo_file)
async def handle_wrong_ex_photo(message: Message):
    await message.answer("⚠️ Это не фото. Пожалуйста, отправьте изображение.")



# ────────────────────────────────────────────────────────────────────
# 📎 Handler: заголовок ссылки (упражнение)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_title)
async def handle_ex_link_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(ex_link_title=title)
    await message.answer("🔗 Введите саму ссылку:")
    await state.set_state(EditTopicStates.waiting_ex_link_url)


# ────────────────────────────────────────────────────────────────────
# 📎 Handler: сам линк и вставка в JSON (упражнение)
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.waiting_ex_link_url)
async def handle_ex_link_url(message: Message, state: FSMContext):
    url = message.text.strip()
    data = await state.get_data()
    topic_data = data["topic"]
    idx = data["insert_index"]

    new_block = {
        "type": "link",
        "title": data.get("ex_link_title"),
        "link": url
    }

    ex_list = topic_data.setdefault("exercises", [])
    ex_list.insert(idx, new_block)

    # Сохраняем JSON
    path = data["topic_path"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    await state.update_data(ex_link_title=None, insert_index=None)

    kb = section_menu()
    await message.answer("✅ Ссылка добавлена в упражнения!", reply_markup=kb)
    await state.set_state(EditTopicStates.choose_action)


# ────────────────────────────────────────────────────────────────────
# 🔀 Handler: перестановка двух блоков внутри раздела
# ────────────────────────────────────────────────────────────────────
@router.message(EditTopicStates.swap_indexes)
async def handle_swap_indexes(message: Message, state: FSMContext):
    text = message.text.strip()
    parts = text.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return await message.answer("⚠️ Введите два номера через пробел, например: 1 2")
    i1, i2 = [int(p) - 1 for p in parts]
    if i1 == i2:
        return await message.answer("⚠️ Номера должны быть разными.")

    data  = await state.get_data()
    kind  = data.get("target_list")       # "vocab"/"exercises"/"videos"/"dialogs"
    topic = data.get("topic", {})

    # — выбираем нужный список для swap —
    if kind == "vocab":
        cp  = data.get("current_phase_id")
        lst = topic["vocab"][cp-1]["vocab"]
    else:
        lst = topic.get(kind, [])

    max_n = len(lst)
    if not (0 <= i1 < max_n and 0 <= i2 < max_n):
        return await message.answer(f"⚠️ Номера вне диапазона: от 1 до {max_n}.")

    # Меняем местами
    lst[i1], lst[i2] = lst[i2], lst[i1]

    # Сохраняем обратно в структуру
    if kind == "vocab":
        topic["vocab"][cp-1]["vocab"] = lst
    else:
        topic[kind] = lst

    # Записываем в файл
    path = data.get("topic_path")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic, f, ensure_ascii=False, indent=2)

    # Отвечаем и возвращаем меню
    await message.answer("✅ Блоки поменяны местами.", reply_markup=ReplyKeyboardRemove())
    kb = section_menu()
    await message.answer("Что дальше?", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)






# ——— TextQuiz для разделов «Словарь» и «Упражнения» ———


@router.message(EditTopicStates.waiting_text_block)
async def handle_text_block(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    topic_data = data["topic"]
    idx = data["insert_index"]
    new_block = {"type": "text", "text": text}

    # Вставляем текст-блок
    cp = data["current_phase_id"]
    phase_list = topic_data["vocab"][cp-1]["vocab"]
    phase_list.insert(idx, new_block)
    topic_data["vocab"][cp-1]["vocab"] = phase_list

    # Сохраняем JSON
    path = data["topic_path"]
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    # Теперь запрашиваем опциональный quiz
    await state.update_data(current_quiz_text=None)
    await message.answer(
        "📝 Пришлите опциональный quiz одним сообщением через `|` или `-` для пропуска:\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ПояснениеПравильного|ПояснениеНеправильного",
        reply_markup=ReplyKeyboardRemove()
    )
    return await state.set_state(EditTopicStates.waiting_vocab_text_quiz)




@router.message(EditTopicStates.waiting_vocab_text_quiz)
async def handle_add_vocab_text_quiz(message: Message, state: FSMContext):
    raw = message.text.strip()
    parts = [p.strip() for p in raw.split("|")]

    # 1) Если сразу прислали полноценный quiz (6 частей) — обрабатываем inline
    if len(parts) == 6:
        question, correct, w1, w2, exp_corr, exp_wrong = parts
        import random; options = [correct, w1, w2]; random.shuffle(options)
        data = await state.get_data()
        cp = data["current_phase_id"]
        idx = data["insert_index"]
        topic_data = data["topic"]
        # Встраиваем quiz внутрь добавленного текст-блока
        block = topic_data["vocab"][cp-1]["vocab"][idx]
        block["quiz"] = {
            "question":           question,
            "options":            options,
            "correct_answer":     correct,
            "explanation_correct": exp_corr,
            "explanation_wrong":  exp_wrong
        }
        # Сохраняем и очищаем state
        import json
        with open(data["topic_path"], "w", encoding="utf-8") as f:
            json.dump(topic_data, f, ensure_ascii=False, indent=2)
        await state.update_data(current_quiz_text=None, insert_index=None)
        await message.answer("✅ Quiz к тексту сохранён.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # 2) Если прислали '-' — пропускаем quiz
    if raw == "-":
        await state.update_data(current_quiz_text=None, insert_index=None)
        await message.answer("✅ Пропускаем опциональный quiz.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # 3) Иначе — сохраняем подпись и запрашиваем сам quiz
    await state.update_data(current_quiz_text=raw)
    await message.answer(
        "📝 Теперь введите quiz одним сообщением через `|`:\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ПояснениеПравильного|ПояснениеНеправильно",
        reply_markup=ReplyKeyboardRemove()
    )
    return await state.set_state(EditTopicStates.waiting_vocab_text_quiz_block)


async def handle_add_vocab_text_quiz(message: Message, state: FSMContext):
    raw = message.text.strip()
    # 💬 Если пользователь прислал "-" — пропускаем опциональный quiz
    if raw == "-":
        await state.update_data(current_quiz_text=None, insert_index=None)
        await message.answer("✅ Пропускаем опциональный quiz.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # иначе — сохраняем текст перед quiz и запрашиваем сам quiz
    await state.update_data(current_quiz_text=raw)
    await message.answer(
        "📝 Теперь введите quiz одним сообщением через `|`:\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ПояснениеПравильного|ПояснениеНеправильно",
        reply_markup=ReplyKeyboardRemove()
    )
    return await state.set_state(EditTopicStates.waiting_vocab_text_quiz_block)

@router.message(EditTopicStates.waiting_vocab_text_quiz_block)
async def save_add_vocab_text_quiz_block(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 6:
        return await message.answer("❗ Формат неверный. Нужно 6 частей через `|`. Попробуйте снова.")
    question, correct, w1, w2, exp_corr, exp_wrong = parts
    import random; options = [correct, w1, w2]; random.shuffle(options)

    data = await state.get_data()
    cp = data["current_phase_id"]
    idx = data["insert_index"]
    topic_data = data["topic"]

    # 💬 Встраиваем quiz внутрь добавленного текст-блока
    block = topic_data["vocab"][cp-1]["vocab"][idx]
    block["quiz"] = {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation_correct": exp_corr,
        "explanation_wrong": exp_wrong
    }

    # 💬 Сохраняем в JSON и очищаем state
    await state.update_data(current_quiz_text=None, insert_index=None)
    import json
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    kb = section_menu()
    await message.answer("✅ Quiz к тексту сохранён.", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)



@router.message(EditTopicStates.waiting_vocab_photo_quiz)
async def handle_add_vocab_photo_quiz(message: Message, state: FSMContext):
    raw = message.text.strip()
    parts = [p.strip() for p in raw.split("|")]

    # 1) Inline-обработка полного quiz (6 частей)
    if len(parts) == 6:
        question, correct, w1, w2, exp_corr, exp_wrong = parts
        import random; options = [correct, w1, w2]; random.shuffle(options)
        data = await state.get_data()
        cp = data["current_phase_id"]
        idx = data["insert_index"]
        topic_data = data["topic"]
        # Встраиваем quiz внутрь добавленного photo-блока
        block = topic_data["vocab"][cp-1]["vocab"][idx]
        block["quiz"] = {
            "question":           question,
            "options":            options,
            "correct_answer":     correct,
            "explanation_correct": exp_corr,
            "explanation_wrong":  exp_wrong
        }
        # Сохраняем и очищаем state
        import json
        with open(data["topic_path"], "w", encoding="utf-8") as f:
            json.dump(topic_data, f, ensure_ascii=False, indent=2)
        await state.update_data(current_quiz_text=None, insert_index=None)
        await message.answer("✅ Quiz к фото сохранён.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # 2) Пропуск quiz
    if raw == "-":
        await state.update_data(current_quiz_text=None, insert_index=None)
        await message.answer("✅ Пропускаем опциональный quiz.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    # 3) Иначе — сохраняем подпись и запрашиваем сам quiz
    await state.update_data(current_quiz_text=raw)
    await message.answer(
        "📝 Теперь введите quiz одним сообщением через `|`:\n"
        "Вопрос|Правильный|Неправ1|Неправ2|ПояснениеПравильного|ПояснениеНеправильно",
        reply_markup=ReplyKeyboardRemove()
    )
    return await state.set_state(EditTopicStates.waiting_vocab_photo_quiz_block)





@router.message(EditTopicStates.waiting_vocab_photo_quiz_block)
async def save_add_vocab_photo_quiz_block(message: Message, state: FSMContext):
    raw = message.text.strip()
    if raw == "-":
        await message.answer("✅ Пропускаем опциональный quiz.", reply_markup=section_menu())
        return await state.set_state(EditTopicStates.choose_action)

    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 6:
        return await message.answer("❗ Формат неверный. Нужно 6 частей через `|`. Попробуйте снова.")
    question, correct, w1, w2, exp_corr, exp_wrong = parts
    import random; options = [correct, w1, w2]; random.shuffle(options)

    data = await state.get_data()
    cp = data["current_phase_id"]
    idx = data["insert_index"]
    topic_data = data["topic"]

    block = topic_data["vocab"][cp-1]["vocab"][idx]
    block["quiz"] = {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation_correct": exp_corr,
        "explanation_wrong": exp_wrong
    }

    await state.update_data(insert_index=None, current_quiz_text=None)
    import json
    with open(data["topic_path"], "w", encoding="utf-8") as f:
        json.dump(topic_data, f, ensure_ascii=False, indent=2)

    kb = section_menu()
    await message.answer("✅ Quiz к фото сохранён.", reply_markup=kb)
    return await state.set_state(EditTopicStates.choose_action)
