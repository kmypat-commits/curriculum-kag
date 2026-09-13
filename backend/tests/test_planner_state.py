from types import SimpleNamespace

from app.api import planner_state


class _Query:
    def __init__(self, row):
        self.row = row

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.row


class _SessionContext:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def query(self, _model):
        return _Query(self.row)

    def commit(self):
        pass


class _SessionFactory:
    def __init__(self, row):
        self.context = _SessionContext(row)

    def __call__(self):
        return self.context

    def begin(self):
        return self.context


def test_terminal_status_does_not_inherit_stale_lease_markers(monkeypatch):
    row = SimpleNamespace(
        state="running",
        stage="variant_A",
        progress=40,
        payload_json={
            "state": "running",
            "stage": "variant_A",
            "stale": True,
            "heartbeat_at": "2026-01-01T00:00:00+00:00",
            "lease_expires_at": "2026-01-01T00:00:01+00:00",
        },
        worker_id="planner-test",
        heartbeat_at=None,
        lease_expires_at=None,
        cancel_requested=0,
        idempotency_key="retry-key",
    )
    monkeypatch.setattr(planner_state, "SessionLocal", _SessionFactory(row))
    planner_state.plan_build_status.clear()

    result = planner_state.set_build_status(777, state="complete", stage="complete", progress=100)

    assert result["state"] == "complete"
    assert "stale" not in result
    assert "heartbeat_at" not in result
    assert "lease_expires_at" not in result
    assert row.state == "complete"
    assert row.heartbeat_at is None
    assert row.lease_expires_at is None


def test_cancel_request_does_not_extend_running_lease(monkeypatch):
    lease = "2099-01-01T00:00:01+00:00"
    row = SimpleNamespace(
        state="running",
        payload_json={
            "state": "running",
            "stage": "scoring",
            "lease_expires_at": lease,
            "heartbeat_at": "2098-12-31T23:59:00+00:00",
            "cancel_requested": 0,
        },
        cancel_requested=0,
        heartbeat_at=None,
        lease_expires_at=None,
    )
    monkeypatch.setattr(planner_state, "SessionLocal", _SessionFactory(row))
    planner_state.plan_build_status.clear()

    result = planner_state.request_build_cancel(778)

    assert result["cancel_requested"] == 1
    assert result["lease_expires_at"] == lease
    assert result["heartbeat_at"] == "2098-12-31T23:59:00+00:00"
    assert row.cancel_requested == 1
    assert row.payload_json["lease_expires_at"] == lease


def test_cancel_request_does_not_republish_terminal_row(monkeypatch):
    row = SimpleNamespace(
        state="complete",
        stage="complete",
        progress=100,
        payload_json={"state": "complete", "stage": "complete", "progress": 100},
        cancel_requested=0,
        heartbeat_at=None,
        lease_expires_at=None,
    )
    monkeypatch.setattr(planner_state, "SessionLocal", _SessionFactory(row))
    planner_state.plan_build_status.clear()

    result = planner_state.request_build_cancel(779)

    assert result["state"] == "complete"
    assert result["progress"] == 100
    assert result.get("cancel_requested", 0) == 0
    assert planner_state.plan_build_status[779]["state"] == "complete"


def test_queued_build_has_one_api_owner_and_gets_a_new_worker_owner(monkeypatch):
    from datetime import datetime, timedelta, timezone

    row = SimpleNamespace(
        state="queued",
        stage="queued",
        progress=0,
        payload_json={
            "state": "queued",
            "stage": "queued",
            "job_id": "build-stable-public-id",
            "request_hash": "a" * 64,
            "worker_id": "enqueue-owner",
        },
        job_id="build-stable-public-id",
        request_hash="a" * 64,
        worker_id="enqueue-owner",
        heartbeat_at=None,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempt_count=1,
        cancel_requested=0,
        idempotency_key="same-request",
    )
    monkeypatch.setattr(planner_state, "SessionLocal", _SessionFactory(row))
    planner_state.plan_build_status.clear()

    assert planner_state.claim_build_status(780, state="queued", stage="queued") is None
    claimed = planner_state.claim_build_status(780, state="running", stage="matching")

    assert claimed is not None
    assert claimed["state"] == "running"
    assert claimed["job_id"] == "build-stable-public-id"
    assert claimed["request_hash"] == "a" * 64
    assert claimed["worker_id"] != "enqueue-owner"
    assert claimed["attempt_count"] == 2
    assert claimed["lease_expires_at"]
    assert row.worker_id == claimed["worker_id"]
    assert row.job_id == "build-stable-public-id"


def test_enqueue_does_not_count_as_an_executed_worker_attempt(monkeypatch):
    class EmptyQuery(_Query):
        def first(self):
            return None

    class EmptySession(_SessionContext):
        def query(self, _model):
            return EmptyQuery(None)

        def add(self, row):
            self.row = row

    class EmptyFactory:
        def __init__(self):
            self.context = EmptySession(None)

        def begin(self):
            return self.context

    factory = EmptyFactory()
    monkeypatch.setattr(planner_state, "SessionLocal", factory)
    planner_state.plan_build_status.clear()

    queued = planner_state.claim_build_status(781, state="queued", stage="queued")

    assert queued is not None
    assert queued["attempt_count"] == 0


def test_queued_cancel_is_terminal_and_old_worker_cannot_claim_it(monkeypatch):
    from datetime import datetime, timedelta, timezone

    row = SimpleNamespace(
        state="queued",
        stage="queued",
        progress=0,
        payload_json={
            "state": "queued", "stage": "queued", "progress": 0,
            "job_id": "build-cancelled", "request_hash": "c" * 64,
        },
        job_id="build-cancelled",
        request_hash="c" * 64,
        worker_id="enqueue-owner",
        heartbeat_at=None,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempt_count=0,
        cancel_requested=0,
        idempotency_key=None,
    )
    monkeypatch.setattr(planner_state, "SessionLocal", _SessionFactory(row))
    planner_state.plan_build_status.clear()

    cancelled = planner_state.request_build_cancel(782)
    assert cancelled["state"] == "cancelled"
    assert row.state == "cancelled"
    assert row.lease_expires_at is None
    assert planner_state.claim_build_status(
        782, state="running", stage="matching", _expected_job_id="build-cancelled"
    ) is None


def test_job_deadline_is_independent_from_renewable_worker_lease(monkeypatch):
    from datetime import datetime

    class EmptyQuery(_Query):
        def first(self):
            return None

    class EmptySession(_SessionContext):
        def query(self, _model):
            return EmptyQuery(None)

        def add(self, row):
            self.row = row

    class EmptyFactory:
        def __init__(self):
            self.context = EmptySession(None)

        def begin(self):
            return self.context

    monkeypatch.setattr(planner_state, "SessionLocal", EmptyFactory())
    monkeypatch.setattr(planner_state.settings, "BUILD_LEASE_SECONDS", 30)
    monkeypatch.setattr(planner_state.settings, "BUILD_DEADLINE_SECONDS", 120)
    claimed = planner_state.claim_build_status(
        783, state="running", stage="matching", job_id="build-deadline", request_hash="d" * 64
    )
    assert claimed is not None
    lease = datetime.fromisoformat(claimed["lease_expires_at"])
    deadline = datetime.fromisoformat(claimed["deadline_at"])
    assert deadline > lease


def test_retry_refreshes_expired_job_deadline(monkeypatch):
    from datetime import datetime, timezone

    class ExistingSession(_SessionContext):
        def add(self, row):
            self.row = row

    class ExistingFactory:
        def __init__(self, row):
            self.context = ExistingSession(row)

        def begin(self):
            return self.context

    old_deadline = "2020-01-01T00:00:00+00:00"
    row = SimpleNamespace(
        state="timed_out", stage="timed_out", progress=0,
        payload_json={"state": "timed_out", "deadline_at": old_deadline,
                      "job_id": "build-retry", "request_hash": "r" * 64},
        job_id="build-retry", request_hash="r" * 64,
        worker_id=None, heartbeat_at=None, lease_expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        attempt_count=1, cancel_requested=0, idempotency_key=None,
    )
    monkeypatch.setattr(planner_state, "SessionLocal", ExistingFactory(row))
    monkeypatch.setattr(planner_state.settings, "BUILD_DEADLINE_SECONDS", 120)

    claimed = planner_state.claim_build_status(784, state="running", stage="matching")

    assert claimed is not None
    assert datetime.fromisoformat(claimed["deadline_at"]) > datetime.now(timezone.utc)
    assert claimed["deadline_at"] != old_deadline
