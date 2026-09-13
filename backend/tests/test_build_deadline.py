from datetime import datetime, timedelta, timezone

import pytest

from app.api import planner_build


def test_deadline_rejects_late_publication(monkeypatch):
    monkeypatch.setattr(planner_build, "_cancellation_requested", lambda _version_id: False)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with pytest.raises(planner_build.BuildTimedOut):
        planner_build._assert_build_is_live(1, expired)


def test_deadline_is_not_cancel_and_future_deadline_is_live(monkeypatch):
    monkeypatch.setattr(planner_build, "_cancellation_requested", lambda _version_id: False)
    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert planner_build._assert_build_is_live(1, future) is None


def test_cancellation_wins_over_future_deadline(monkeypatch):
    monkeypatch.setattr(planner_build, "_cancellation_requested", lambda _version_id: True)
    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    with pytest.raises(planner_build.BuildCancelled):
        planner_build._assert_build_is_live(1, future)
