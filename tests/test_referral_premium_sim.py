import asyncio
import tempfile
import unittest
from pathlib import Path

import referral_feature as rf


class ReferralPremiumSim:
    def __init__(self, *, now_ts: int):
        self.now_ts = int(now_ts)
        self._started_users: set[int] = set()
        self.premium_users: dict[int, int] = {}
        rf.set_now_override(self.now_ts)

    def _run(self, coro):
        return asyncio.run(coro)

    def simulate_start_with_ref(self, user_id: int, referrer_id: int | str) -> None:
        is_first = user_id not in self._started_users
        self._started_users.add(user_id)
        self._run(
            rf.referrals_try_bind_on_start(
                new_user_id=int(user_id),
                raw_payload=f"refpay_{referrer_id}",
                is_first_start=is_first,
                tg_username=f"u{user_id}",
                full_name=f"User {user_id}",
            )
        )

    def simulate_payment_success(
        self,
        user_id: int,
        invoice_id: str,
        amount_cents: int,
        currency: str,
        subscription_expiration_date: int,
    ) -> None:
        self.premium_users[int(user_id)] = int(subscription_expiration_date)
        invoice_obj = {
            "id": str(invoice_id),
            "amount_paid": int(amount_cents),
            "currency": str(currency),
        }
        self._run(
            rf.referrals_apply_invoice_paid(
                tg_user_id=int(user_id),
                invoice_obj=invoice_obj,
                active_until=int(subscription_expiration_date),
            )
        )
        self._run(
            rf.referrals_apply_subscription_status(
                tg_user_id=int(user_id),
                status="paid",
                active_until=int(subscription_expiration_date),
            )
        )

    def simulate_month_passes(self, days: int = 31) -> None:
        self.now_ts += int(days) * 86400
        rf.set_now_override(self.now_ts)
        self._run(rf.referrals_recompute_expired(now_ts=self.now_ts))

    def simulate_cancel(self, user_id: int, active_until: int) -> None:
        self._run(
            rf.referrals_apply_subscription_status(
                tg_user_id=int(user_id),
                status="canceled",
                active_until=int(active_until),
            )
        )

    def is_premium_active(self, user_id: int) -> bool:
        return int(self.premium_users.get(int(user_id), 0)) > int(self.now_ts)


def _load_data() -> dict:
    return rf._load_ref_data_sync()


def _get_referrer(user_id: int):
    return _load_data().get("user_to_referrer", {}).get(str(user_id))


def _get_ref_info(referrer_id: int | str) -> dict:
    return (_load_data().get("referrers", {}).get(str(referrer_id)) or {})


def _active_paying_count(referrer_id: int | str, now_ts: int) -> int:
    return rf._active_paying_count(_get_ref_info(referrer_id), int(now_ts))


class TestReferralPremiumSimulation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        rf.REFERRALS_DATA_PATH = str(base / "referrals_data.json")
        rf.REFERRALS_BACKUP_PATH = str(base / "referrals_data.backup.json")
        rf.PAYOUTS_DB_PATH = str(base / "referral_payouts.sqlite3")
        rf.set_now_override(1_700_000_000)
        self.sim = ReferralPremiumSim(now_ts=1_700_000_000)
        self.A = 1001

    def tearDown(self):
        rf.set_now_override(None)
        self.tmp.cleanup()

    def test_h1_first_ref_wins(self):
        self.sim.simulate_start_with_ref(2002, self.A)
        self.sim.simulate_start_with_ref(2002, 1002)
        self.assertEqual(_get_referrer(2002), str(self.A))

    def test_h2_no_referral_payment(self):
        self.sim.simulate_payment_success(2003, "inv_1", 1000, "XTR", self.sim.now_ts + 30 * 86400)
        self.assertEqual(_load_data().get("referrers", {}), {})

    def test_h3_accrual_once_per_invoice(self):
        self.sim.simulate_start_with_ref(2004, self.A)
        self.sim.simulate_payment_success(2004, "inv_2", 1000, "XTR", self.sim.now_ts + 30 * 86400)
        first_total = _get_ref_info(self.A).get("accrued_total_cents", 0)
        self.sim.simulate_payment_success(2004, "inv_2", 1000, "XTR", self.sim.now_ts + 30 * 86400)
        second_total = _get_ref_info(self.A).get("accrued_total_cents", 0)
        self.assertEqual(first_total, second_total)

    def test_h4_expiry_updates_status_and_active_count(self):
        u5 = 2005
        self.sim.simulate_start_with_ref(u5, self.A)
        exp = self.sim.now_ts + 30 * 86400
        self.sim.simulate_payment_success(u5, "inv_3", 1000, "XTR", exp)
        self.assertEqual(_active_paying_count(self.A, self.sim.now_ts), 1)

        self.sim.simulate_month_passes(days=31)
        referred = _get_ref_info(self.A).get("referred", {}).get(str(u5), {})
        self.assertFalse(self.sim.is_premium_active(u5))
        self.assertEqual(_active_paying_count(self.A, self.sim.now_ts), 0)
        self.assertEqual(referred.get("status"), "unpaid")

    def test_h5_renewal_extends_and_stays_active(self):
        u6 = 2006
        self.sim.simulate_start_with_ref(u6, self.A)
        exp_1 = self.sim.now_ts + 30 * 86400
        exp_2 = self.sim.now_ts + 60 * 86400
        self.sim.simulate_payment_success(u6, "inv_4", 1000, "XTR", exp_1)
        self.sim.simulate_payment_success(u6, "inv_5", 1000, "XTR", exp_2)
        referred = _get_ref_info(self.A).get("referred", {}).get(str(u6), {})
        self.assertEqual(int(referred.get("active_until", 0)), exp_2)
        self.assertEqual(_active_paying_count(self.A, self.sim.now_ts), 1)

    def test_h6_cancelled_removed_immediately_from_active_paying(self):
        u7 = 2007
        exp = self.sim.now_ts + 30 * 86400
        self.sim.simulate_start_with_ref(u7, self.A)
        self.sim.simulate_payment_success(u7, "inv_6", 1000, "XTR", exp)
        self.assertEqual(_active_paying_count(self.A, self.sim.now_ts), 1)

        self.sim.simulate_cancel(u7, exp)
        referred = _get_ref_info(self.A).get("referred", {}).get(str(u7), {})
        self.assertEqual(referred.get("status"), "canceled")
        self.assertEqual(_active_paying_count(self.A, self.sim.now_ts), 0)

    def test_h7_cabinet_stats_consistent(self):
        users = [2101, 2102, 2103]
        for u in users:
            self.sim.simulate_start_with_ref(u, self.A)
        self.sim.simulate_payment_success(2101, "inv_a", 1000, "XTR", self.sim.now_ts + 30 * 86400)
        self.sim.simulate_payment_success(2102, "inv_b", 1000, "XTR", self.sim.now_ts + 30 * 86400)
        self.sim.simulate_cancel(2102, self.sim.now_ts + 30 * 86400)

        ref = _get_ref_info(self.A)
        referred = ref.get("referred", {})
        active = sum(
            1
            for r in referred.values()
            if (r.get("status") == "paid") and int(r.get("active_until", 0)) > self.sim.now_ts
        )
        self.assertEqual(len(referred), 3)
        self.assertEqual(_active_paying_count(self.A, self.sim.now_ts), active)

    def test_h8_security_invariants(self):
        # self-referral ignored
        self.sim.simulate_start_with_ref(2201, 2201)
        self.assertIsNone(_get_referrer(2201))

        # invalid payload ignored
        asyncio.run(
            rf.referrals_try_bind_on_start(
                new_user_id=2202,
                raw_payload="refpay_abc",
                is_first_start=True,
                tg_username="u2202",
                full_name="U 2202",
            )
        )
        self.assertIsNone(_get_referrer(2202))

    def test_h9_payout_history_does_not_reduce_accrual(self):
        u9 = 2309
        self.sim.simulate_start_with_ref(u9, self.A)
        self.sim.simulate_payment_success(u9, "inv_9", 10000, "XTR", self.sim.now_ts + 30 * 86400)
        ref_before = _get_ref_info(self.A)
        accrued_before = int(ref_before.get("accrued_total_cents", 0))

        rf.add_payout(str(self.A), 500, admin_id=1, note="part")
        rf.add_payout(str(self.A), 700, admin_id=1, note="part2")

        data = _load_data()
        ref_after = data.get("referrers", {}).get(str(self.A), {})
        accrued_after = int(ref_after.get("accrued_total_cents", 0))
        paid_total = 500 + 700
        balance_due = max(0, accrued_after - paid_total)

        self.assertEqual(accrued_before, accrued_after)
        self.assertGreaterEqual(balance_due, 0)


if __name__ == "__main__":
    unittest.main()
