# grammar_quiz_reactions.py
import random
import asyncio

grammar_quiz_success_phrases: list[str] = [
    "Отлично!",
    "Молодец!",
    "Так держать!",
    "Идеально!",
    "Грамматика под контролем!",
]

GRAMMAR_REACTION_EMOJI_PROB: float = 0.30

# 💬 оставил placeholders как в ТЗ — вставишь свои эмоджи
GRAMMAR_CORRECT_EMOJI: str = "CAACAgIAAxkBAAIYx2mSr8mRcS19H96svKTl57ps9Qv5AAL6EwACp_IxSjdGLEsDu-S3OgQ"
GRAMMAR_WRONG_EMOJI: str = "CAACAgIAAxkBAAIYxWmSr5PF-JHpQLK0L9CW2dJeGpTDAAIrEAACIfiYSfeadbBgPmtmOgQ"


async def _maybe_send_grammar_emoji(bot, chat_id: int, emoji: str) -> None:
    if not emoji:
        return

    if random.random() >= GRAMMAR_REACTION_EMOJI_PROB:
        return

    # Если это похоже на file_id — шлём как sticker
    try:
        if emoji.startswith("CAAC"):
            msg = await bot.send_sticker(chat_id, emoji)
        else:
            msg = await bot.send_message(chat_id, emoji)
    except Exception:
        return

    async def _auto_delete():
        await asyncio.sleep(1.5)
        try:
            await bot.delete_message(chat_id, msg.message_id)
        except Exception:
            pass

    asyncio.create_task(_auto_delete())
