[33mcommit 6f4543a4c3cbc6d868b916ecdf9994f0f8670292[m[33m ([m[1;36mHEAD[m[33m -> [m[1;32mfeat/payouts-owner-bypass[m[33m)[m
Author: danilo3701 <galykin372004@gmail.com>
Date:   Tue Mar 3 22:32:55 2026 +0800

    bottom color

[1mdiff --git a/core8_1.py b/core8_1.py[m
[1mindex 45507a1..4eae198 100644[m
[1m--- a/core8_1.py[m
[1m+++ b/core8_1.py[m
[36m@@ -3363,28 +3363,28 @@[m [masync def start_handler(message: Message, state: FSMContext):[m
 [m
     # 💬 Главное меню теперь ИНЛАЙН — без ReplyKeyboard (ничего не «висит» внизу)[m
     inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[[m
[31m-            [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],[m
[32m+[m[32m            [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn", style="success")],[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL),[m
[31m-                InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords"),[m
[32m+[m[32m                InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL, style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords", style="primary"),[m
             ],[m
     [m
[31m-            [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts")],[m
[32m+[m[32m            [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts", style="primary")],[m
     [m
[31m-            [InlineKeyboardButton(text="🧠 Грамматика", callback_data="menu:grammar")],  # ← НОВАЯ СТРОКА[m
[32m+[m[32m            [InlineKeyboardButton(text="🧠 Грамматика", callback_data="menu:grammar", style="primary")],  # ← НОВАЯ СТРОКА[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle"),[m
[31m-                InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses"),[m
[32m+[m[32m                InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle", style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses", style="primary"),[m
             ],[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),[m
[31m-                InlineKeyboardButton(text="Статистика 📊", callback_data="menu:stats"),[m
[32m+[m[32m                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating", style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Статистика 📊", callback_data="menu:stats", style="primary"),[m
             ],[m
     [m
[31m-            [InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings")],[m
[32m+[m[32m            [InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings", style="danger")],[m
         ])  # 💬 выровненное главное меню (1,2,1,1,2,2,1)  ← ОБНОВИТЬ КОММЕНТАРИЙ[m
 [m
 [m
[36m@@ -4680,28 +4680,28 @@[m [masync def settings_back_cb(callback: CallbackQuery, state: FSMContext):[m
     )  # 💬 чистим режим ввода настроек[m
 [m
     inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[[m
[31m-            [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],[m
[32m+[m[32m            [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn", style="success")],[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL),[m
[31m-                InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords"),[m
[32m+[m[32m                InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL, style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords", style="primary"),[m
             ],[m
     [m
[31m-            [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts")],[m
[32m+[m[32m            [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts", style="primary")],[m
     [m
[31m-            [InlineKeyboardButton(text="🧠 Грамматика", callback_data="menu:grammar")],  # ← НОВАЯ СТРОКА[m
[32m+[m[32m            [InlineKeyboardButton(text="🧠 Грамматика", callback_data="menu:grammar", style="primary")],  # ← НОВАЯ СТРОКА[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle"),[m
[31m-                InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses"),[m
[32m+[m[32m                InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle", style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses", style="primary"),[m
             ],[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),[m
[31m-                InlineKeyboardButton(text="Статистика 📊", callback_data="menu:stats"),[m
[32m+[m[32m                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating", style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Статистика 📊", callback_data="menu:stats", style="primary"),[m
             ],[m
     [m
[31m-            [InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings")],[m
[32m+[m[32m            [InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings", style="danger")],[m
         ])  # 💬 выровненное главное меню (1,2,1,1,2,2,1)  ← ОБНОВИТЬ КОММЕНТАРИЙ[m
 [m
     menu_text = random.choice(menu_study_phrases) if menu_study_phrases else "Выбирай"  # 💬 рандомная фраза главного меню[m
[36m@@ -6761,28 +6761,28 @@[m [mdef _mywords_rename_category(data: dict, user_id: str, old_name: str, new_name:[m
 async def mywords_show_main_menu(message: Message, state: FSMContext):[m
     # 💬 возвращаемся в главное инлайн-меню без /start[m
     inline_kb_main = InlineKeyboardMarkup(inline_keyboard=[[m
[31m-            [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn")],[m
[32m+[m[32m            [InlineKeyboardButton(text="📚 УЧИТЬСЯ", callback_data="menu:learn", style="success")],[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL),[m
[31m-                InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords"),[m
[32m+[m[32m                InlineKeyboardButton(text="📎 Материалы", url=MATERIALS_POST_URL, style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Мои слова 🧩", callback_data="menu:mywords", style="primary"),[m
             ],[m
     [m
[31m-            [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts")],[m
[32m+[m[32m            [InlineKeyboardButton(text="🎧 Подкасты", callback_data="menu:podcasts", style="primary")],[m
     [m
[31m-            [InlineKeyboardButton(text="🧠 Грамматика", callback_data="menu:grammar")],  # ← НОВАЯ СТРОКА[m
[32m+[m[32m            [InlineKeyboardButton(text="🧠 Грамматика", callback_data="menu:grammar", style="primary")],  # ← НОВАЯ СТРОКА[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle"),[m
[31m-                InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses"),[m
[32m+[m[32m                InlineKeyboardButton(text="⚔️ Битва", callback_data="menu:battle", style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Бонусы 🎁", callback_data="menu:bonuses", style="primary"),[m
             ],[m
     [m
             [[m
[31m-                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating"),[m
[31m-                InlineKeyboardButton(text="Статистика 📊", callback_data="menu:stats"),[m
[32m+[m[32m                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating", style="primary"),[m
[32m+[m[32m                InlineKeyboardButton(text="Статистика 📊", callback_data="menu:stats", style="primary"),[m
             ],[m
     [m
[31m-            [InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings")],[m
[32m+[m[32m            [InlineKeyboardButton(text="Настройки ⚙️", callback_data="menu:settings", style="danger")],[m
         ])  # 💬 выровненное главное меню (1,2,1,1,2,2,1)  ← ОБНОВИТЬ КОММЕНТАРИЙ[m
     [m
 [m
