"""Faz A: the daily KAP/corporate-action refresh gate."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bist_bot.services.kap_service import KapSyncJob

TR = ZoneInfo("Europe/Istanbul")


class _Settings:
    KAP_SYNC_ENABLED = True
    KAP_SYNC_HOUR_TR = 18


class _FakeKap:
    def __init__(self, report=None) -> None:
        self.report = report or {"fetched": 3, "mapped": 2}
        self.calls = 0

    def sync(self):
        self.calls += 1
        return self.report


class _FakeActions:
    def __init__(self) -> None:
        self.calls = 0

    def sync(self):
        self.calls += 1
        return {"fetched": 10, "written": 10}


def _job(kap=None, actions=None, settings=None) -> KapSyncJob:
    return KapSyncJob(kap or _FakeKap(), actions or _FakeActions(), settings or _Settings())


def test_disabled_job_does_nothing() -> None:
    class Disabled(_Settings):
        KAP_SYNC_ENABLED = False

    kap, actions = _FakeKap(), _FakeActions()
    job = KapSyncJob(kap, actions, Disabled())
    assert job.run_if_due(datetime(2026, 10, 23, 19, 0, tzinfo=TR)) is False
    assert kap.calls == 0 and actions.calls == 0


def test_job_waits_until_the_evening_hour() -> None:
    kap = _FakeKap()
    job = _job(kap)
    assert job.run_if_due(datetime(2026, 10, 23, 17, 59, tzinfo=TR)) is False
    assert kap.calls == 0
    assert job.run_if_due(datetime(2026, 10, 23, 18, 0, tzinfo=TR)) is True
    assert kap.calls == 1


def test_job_runs_once_per_day_and_skips_holidays() -> None:
    kap, actions = _FakeKap(), _FakeActions()
    job = _job(kap, actions)

    # 2026-01-01 is a BIST holiday.
    assert job.run_if_due(datetime(2026, 1, 1, 19, 0, tzinfo=TR)) is False
    assert kap.calls == 0

    assert job.run_if_due(datetime(2026, 10, 23, 18, 30, tzinfo=TR)) is True
    assert job.run_if_due(datetime(2026, 10, 23, 21, 30, tzinfo=TR)) is False
    assert kap.calls == 1 and actions.calls == 1

    # A new day runs again.
    assert job.run_if_due(datetime(2026, 10, 26, 18, 30, tzinfo=TR)) is True
    assert kap.calls == 2


def test_empty_report_still_marks_the_day_done() -> None:
    kap = _FakeKap({"fetched": 0, "mapped": 0})
    job = _job(kap)
    assert job.run_if_due(datetime(2026, 10, 23, 19, 0, tzinfo=TR)) is True
    assert job.run_if_due(datetime(2026, 10, 23, 20, 0, tzinfo=TR)) is False
