import asyncio
import tempfile
import unittest
from pathlib import Path

import referral_feature as rf


class DummyUser:
    def __init__(self, user_id: int):
        self.id = int(user_id)


class DummyMessage:
    def __init__(self, user_id: int, text: str = ""):
        self.from_user = DummyUser(user_id)
        self.text = text
        self.answers: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append((text, kwargs))

    async def delete(self):
        return


class TestReferralAdminPayouts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        rf.REFERRALS_DATA_PATH = str(base / "referrals_data.json")
        rf.REFERRALS_BACKUP_PATH = str(base / "referrals_data.backup.json")
        rf.PAYOUTS_DB_PATH = str(base / "referral_payouts.sqlite3")
        rf.set_now_override(1_700_000_000)
        self.admin_id = 9001

    def tearDown(self):
        rf.set_now_override(None)
        self.tmp.cleanup()

    def _save_referrer(self, referrer_id: str, accrued_total: int, paid_total: int) -> None:
        data = rf._load_ref_data_sync()
        referrers = data.get("referrers", {}) or {}
        referrers[str(referrer_id)] = {
            "accrued_total_cents": int(accrued_total),
            "paid_total_cents": int(paid_total),
            "paid_out_cents": int(paid_total),
            "referred": {},
        }
        data["referrers"] = referrers
        rf._save_ref_data_sync(data)

    def test_admin_menu_empty_list_shows_hint(self):
        msg = DummyMessage(self.admin_id, text="/payouts")
        asyncio.run(rf.cmd_payouts(msg))
        self.assertTrue(msg.answers)
        text = msg.answers[-1][0]
        self.assertIn("Рефералов пока нет", text)

    def test_admin_kb_list_pager_buttons(self):
        kb = rf._kb_admin_ref_list(prefix="refadm:list", page=0, total_pages=1, back_cb="refadm:close")
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "refadm:edge:first")
        self.assertEqual(kb.inline_keyboard[0][1].callback_data, "refadm:noop")
        self.assertEqual(kb.inline_keyboard[0][2].callback_data, "refadm:edge:last")
        self.assertEqual(kb.inline_keyboard[1][0].callback_data, "refadm:close")

    def test_admin_kb_card_buttons(self):
        kb = rf._kb_admin_ref_card("123")
        row1 = kb.inline_keyboard[0]
        row2 = kb.inline_keyboard[1]
        row3 = kb.inline_keyboard[2]
        self.assertEqual(row1[0].callback_data, "refadm:pay:123")
        self.assertEqual(row1[1].callback_data, "refadm:rollback:123")
        self.assertEqual(row2[0].callback_data, "refadm:history:123")
        self.assertEqual(row3[0].callback_data, "refadm:list:0")

    def test_payout_apply_and_rollback_updates_totals(self):
        self._save_referrer("100", accrued_total=10000, paid_total=2000)
        msg = DummyMessage(self.admin_id)

        asyncio.run(rf._apply_owner_payout(msg, referrer_id="100", amount_cents=3000))
        data = rf._load_ref_data_sync()
        ref = data.get("referrers", {}).get("100", {})
        self.assertEqual(int(ref.get("paid_total_cents", 0)), 5000)
        self.assertEqual(int(ref.get("paid_out_cents", 0)), 5000)

        asyncio.run(rf._apply_owner_payout_rollback(msg, referrer_id="100", amount_cents=1500))
        data = rf._load_ref_data_sync()
        ref = data.get("referrers", {}).get("100", {})
        self.assertEqual(int(ref.get("paid_total_cents", 0)), 3500)
        self.assertEqual(int(ref.get("paid_out_cents", 0)), 3500)

        payouts = rf.get_payouts(referrer_id="100", limit=10)
        amounts = {int(p["amount_cents"]) for p in payouts}
        self.assertIn(3000, amounts)
        self.assertIn(-1500, amounts)

    def test_payout_rejects_over_balance(self):
        self._save_referrer("200", accrued_total=1000, paid_total=0)
        msg = DummyMessage(self.admin_id)

        asyncio.run(rf._apply_owner_payout(msg, referrer_id="200", amount_cents=2000))
        data = rf._load_ref_data_sync()
        ref = data.get("referrers", {}).get("200", {})
        self.assertEqual(int(ref.get("paid_total_cents", 0)), 0)
        self.assertTrue(msg.answers)
        self.assertIn("Сумма больше баланса", msg.answers[-1][0])


if __name__ == "__main__":
    unittest.main()
