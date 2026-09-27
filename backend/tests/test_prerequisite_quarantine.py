"""Reviewed corrections must preserve all unrelated mandatory edges."""
from sqlalchemy import create_engine, text
import pytest


def test_reviewed_quarantine_is_exact_and_rollback_is_idempotent():
    from scripts.quarantine_reviewed_prerequisites import change_edges
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE course_prerequisites (course_id INT, prerequisite_id INT)"))
        connection.execute(text("INSERT INTO course_prerequisites VALUES (517,724),(517,787),(734,517),(10,11)"))
        assert change_edges(connection, [(517,724),(517,787)], restore=False) == 2
        assert connection.execute(text("SELECT * FROM course_prerequisites ORDER BY course_id")).all() == [(10,11),(734,517)]
        assert change_edges(connection, [(517,724),(517,787)], restore=True) == 2
        assert change_edges(connection, [(517,724),(517,787)], restore=True) == 0
        assert connection.execute(text("SELECT COUNT(*) FROM course_prerequisites")).scalar() == 4


def test_missing_reviewed_edge_aborts_before_deleting_anything():
    from scripts.quarantine_reviewed_prerequisites import change_edges
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE course_prerequisites (course_id INT, prerequisite_id INT)"))
        connection.execute(text("INSERT INTO course_prerequisites VALUES (517,724)"))
        with pytest.raises(ValueError):
            change_edges(connection, [(517,724),(517,787)], restore=False)
        assert connection.execute(text("SELECT COUNT(*) FROM course_prerequisites")).scalar() == 1
