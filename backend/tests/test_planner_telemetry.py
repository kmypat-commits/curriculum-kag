from app.api.planner_build import _percentile
from app.database import finish_sql_query_measurement, start_sql_query_measurement
from types import SimpleNamespace


def test_sql_query_measurement_is_scoped_and_restored():
    token = start_sql_query_measurement()
    assert finish_sql_query_measurement(token) == 0


def test_percentile_uses_interpolated_p50_and_p95():
    values = [10.0, 20.0, 30.0, 40.0]
    assert _percentile(values, 0.5) == 25.0
    assert _percentile(values, 0.95) == 38.5
    assert _percentile([], 0.95) is None


def test_build_telemetry_records_safe_embedding_runtime(monkeypatch):
    from app.api import planner_build

    captured = []

    class Db:
        def add(self, event):
            captured.append(event)

        def commit(self):
            pass

        def rollback(self):
            raise AssertionError("telemetry should be persisted")

    class Runtime:
        def get_status(self):
            return {
                "mode": "sentence_transformer",
                "runtime_profile": "sbert:test:device=cpu:dim=768",
                "configured_model": "test-model",
                "dimension": 768,
                "device": "cpu",
                "model_loaded": True,
                "load_error": "must not be copied",
            }

    import app.kag.embedding_service as embedding_module
    monkeypatch.setattr(embedding_module, "embedding_service", Runtime())
    planner_build._record_build_telemetry(
        Db(), current_user=SimpleNamespace(id=5), project_version_id=9,
        state="complete", elapsed_seconds=1.0, timings={}, sql_query_count=2,
        response_payload={"job_id": "build-telemetry"},
    )
    runtime = captured[0].details_json["embedding_runtime"]
    assert runtime["runtime_profile"].startswith("sbert:")
    assert "load_error" not in runtime


def test_build_performance_exposes_p95_budget_result(monkeypatch):
    from app.api import planner_build

    class Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return [SimpleNamespace(details_json={"duration_ms": value, "sql_query_count": 1, "response_bytes": 2, "cache_hit_rate": 1}) for value in (100, 200, 300, 400)]

    class Db:
        def query(self, *_args):
            return Query()

    monkeypatch.setattr(planner_build.settings, "PLANNER_P95_BUDGET_MS", 350)
    result = planner_build.get_build_performance(1, Db(), SimpleNamespace(id=1))

    assert result["duration_ms"]["p95"] == 385.0
    assert result["p95_budget_ms"] == 350
    assert result["p95_within_budget"] is False


def test_observability_summary_is_aggregate_and_respects_budget(monkeypatch):
    from app.api import planner_build
    from app.models.plan_build_status import PlanBuildStatus

    class StateQuery:
        def all(self):
            return [("complete",), ("failed",), ("timed_out",), ("running",)]

    class LeaseQuery:
        def filter(self, *_args):
            return self

        def count(self):
            return 1

    class TelemetryQuery:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return [( {"duration_ms": value},) for value in (100, 200, 300, 400)]

    class Db:
        def query(self, model):
            if model is PlanBuildStatus.state:
                return StateQuery()
            if model is PlanBuildStatus:
                return LeaseQuery()
            return TelemetryQuery()

    monkeypatch.setattr(planner_build.settings, "PLANNER_P95_BUDGET_MS", 350)
    result = planner_build.get_planner_observability_summary(Db(), SimpleNamespace(id=1))

    assert result["build_states"] == {"complete": 1, "failed": 1, "timed_out": 1, "running": 1}
    assert result["failed_or_timed_out"] == 2
    assert result["active_leases"] == 1
    assert result["telemetry_sample_size"] == 4
    assert result["duration_ms"]["p95"] == 385.0
    assert result["p95_within_budget"] is False
