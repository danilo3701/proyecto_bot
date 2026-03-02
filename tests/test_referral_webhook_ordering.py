import asyncio
import tempfile
import unittest
from pathlib import Path

import referral_feature as rf


class TestReferralWebhookOrdering(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        rf.REFERRALS_DATA_PATH = str(base / "referrals_data.json")
        rf.REFERRALS_BACKUP_PATH = str(base / "referrals_data.backup.json")
        rf.PAYOUTS_DB_PATH = str(base / "referral_payouts.sqlite3")
        rf.set_now_override(1_700_000_000)
        self.now_ts = 1_700_000_000
        self.user_id = 4101
        self.referrer_id = 3101

    def tearDown(self):
        rf.set_now_override(None)
        self.tmp.cleanup()

    def _accrued(self) -> int:
        data = rf._load_ref_data_sync()
        ref = (data.get("referrers", {}) or {}).get(str(self.referrer_id), {}) or {}
        return int(ref.get("accrued_total_cents", 0) or 0)

    def test_invoice_before_bind_then_replay_applies_once(self):
        exp = self.now_ts + 30 * 86400
        invoice = {"id": "inv_ordering_1", "amount_paid": 1000, "currency": "EUR"}

        # Webhook пришел до привязки пользователя к referrer: начисления быть не должно.
        self._run(
            rf.referrals_apply_invoice_paid(
                tg_user_id=self.user_id,
                invoice_obj=invoice,
                active_until=exp,
                payment_provider="stripe",
            )
        )
        self.assertEqual(self._accrued(), 0)

        # Позднее произошел первый /start по ref-ссылке.
        self._run(
            rf.referrals_try_bind_on_start(
                new_user_id=self.user_id,
                raw_payload=f"refpay_{self.referrer_id}",
                is_first_start=True,
                tg_username="u4101",
                full_name="User 4101",
            )
        )

        # Replay того же invoice должен начислить комиссию.
        self._run(
            rf.referrals_apply_invoice_paid(
                tg_user_id=self.user_id,
                invoice_obj=invoice,
                active_until=exp,
                payment_provider="stripe",
            )
        )
        accrued_once = self._accrued()
        self.assertGreater(accrued_once, 0)

        # Повторная доставка того же invoice не должна начислить второй раз.
        self._run(
            rf.referrals_apply_invoice_paid(
                tg_user_id=self.user_id,
                invoice_obj=invoice,
                active_until=exp,
                payment_provider="stripe",
            )
        )
        self.assertEqual(self._accrued(), accrued_once)


if __name__ == "__main__":
    unittest.main()
