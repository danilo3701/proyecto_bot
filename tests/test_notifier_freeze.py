import asyncio
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import extranjeria_notifier_bot as m


def test_event_delivery_decision_reasons(monkeypatch):
    now = 10_000
    user = {
        "enabled": False,
        "province": "Madrid",
        "office_id": "mad_poblados_51",
        "service_id": "ua_card",
    }

    ok, reason = m._event_delivery_decision(
        user,
        "Madrid",
        "mad_poblados_51",
        "ua_card",
        now,
        apply_random_skip=False,
    )
    assert ok is False
    assert reason == "disabled"

    user["enabled"] = True
    ok, reason = m._event_delivery_decision(
        user,
        "Valencia",
        "mad_poblados_51",
        "ua_card",
        now,
        apply_random_skip=False,
    )
    assert ok is False
    assert reason == "province_mismatch"

    user["province"] = "Madrid"
    user["last_alert_min"] = now - 5
    ok, reason = m._event_delivery_decision(
        user,
        "Madrid",
        "mad_poblados_51",
        "ua_card",
        now,
        apply_random_skip=False,
    )
    assert ok is False
    assert reason == "cooldown_lt_cfg"

    user["last_alert_min"] = now - 120
    monkeypatch.setattr(m.random, "random", lambda: 0.1)
    ok, reason = m._event_delivery_decision(
        user,
        "Madrid",
        "mad_poblados_51",
        "ua_card",
        now,
        apply_random_skip=True,
    )
    assert ok is False
    assert reason == "random_skip_15pct"


def test_send_alert_timeout(monkeypatch):
    class DummyBot:
        async def send_message(self, **kwargs):
            await asyncio.sleep(10)

    async def run():
        monkeypatch.setattr(m, "bot", DummyBot(), raising=False)
        monkeypatch.setattr(m, "SEND_TIMEOUT_SEC", 0.01)

        ok, err = await m._send_alert_result(123, "hi")
        assert ok is False
        assert err == "timeout"

    asyncio.run(run())


def test_notifier_loop_saves_once_per_tick(monkeypatch):
    async def run():
        fixed = m.dt.datetime(2026, 3, 2, 15, 0, tzinfo=m.MADRID_TZ)
        key = m._today_key(fixed)

        store = {
            "users": {
                "1": {
                    "enabled": True,
                    "province": "Madrid",
                    "office_id": "mad_poblados_51",
                    "service_id": "ua_card",
                }
            },
            "daily_events": {
                key: {
                    "events": [
                        {
                            "min": fixed.hour * 60 + fixed.minute,
                            "prov": "Madrid",
                            "office_id": "mad_poblados_51",
                            "service_id": "ua_card",
                        }
                    ],
                    "fired": [],
                }
            },
            "stats": {},
        }

        save_calls: list[str] = []

        monkeypatch.setattr(m, "_load_json", lambda _path: store)
        monkeypatch.setattr(m, "_save_json_atomic", lambda _path, _data: save_calls.append("saved"))

        class FixedDateTime(m.dt.datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed
                return fixed.astimezone(tz)

        monkeypatch.setattr(m.dt, "datetime", FixedDateTime)
        monkeypatch.setattr(m.random, "random", lambda: 0.9)

        class DummyTask:
            def cancel(self):
                return None

        def fake_create_task(coro):
            coro.close()
            return DummyTask()

        monkeypatch.setattr(m.asyncio, "create_task", fake_create_task)

        class StopLoop(Exception):
            pass

        async def fake_sleep(_seconds):
            raise StopLoop()

        monkeypatch.setattr(m.asyncio, "sleep", fake_sleep)

        with pytest.raises(StopLoop):
            await m.notifier_loop()

        assert len(save_calls) == 1
        fired = store["daily_events"][key]["fired"]
        assert fired

    asyncio.run(run())
