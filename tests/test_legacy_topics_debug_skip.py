import asyncio
import unittest

from aiogram.dispatcher.event.bases import SkipHandler

import create_lesson_block as clb


class DummyUser:
    def __init__(self, user_id: int):
        self.id = int(user_id)


class DummyChat:
    def __init__(self, chat_id: int):
        self.id = int(chat_id)


class DummyMessage:
    def __init__(self, user_id: int, chat_id: int, text: str):
        self.from_user = DummyUser(user_id)
        self.chat = DummyChat(chat_id)
        self.text = text


class DummyState:
    async def get_data(self):
        return {"debug": True}

    async def get_state(self):
        return "dummy_state"


class TestLegacyTopicsDebugSkip(unittest.TestCase):
    def test_debug_handler_raises_skiphandler(self):
        msg = DummyMessage(user_id=1, chat_id=2, text="/payouts")
        state = DummyState()
        with self.assertRaises(SkipHandler):
            asyncio.run(clb._topics_router_debug_seen(msg, state))


if __name__ == "__main__":
    unittest.main()
