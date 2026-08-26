from app.api.planner_build import _percentile
from app.database import finish_sql_query_measurement, start_sql_query_measurement


def test_sql_query_measurement_is_scoped_and_restored():
    token = start_sql_query_measurement()
    assert finish_sql_query_measurement(token) == 0


def test_percentile_uses_interpolated_p50_and_p95():
    values = [10.0, 20.0, 30.0, 40.0]
    assert _percentile(values, 0.5) == 25.0
    assert _percentile(values, 0.95) == 38.5
    assert _percentile([], 0.95) is None
