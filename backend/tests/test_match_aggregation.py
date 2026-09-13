from types import SimpleNamespace

from app.planner.match_aggregation import aggregate_match_scores


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return _Query(self.rows)


class _Field:
    def __eq__(self, _other):
        return True

    def asc(self):
        return self


class _Match:
    project_version_id = _Field()
    course_id = _Field()
    lo_id = _Field()


def test_aggregate_match_scores_keeps_expert_evidence_and_separates_goso():
    los = [
        SimpleNamespace(id=1, lo_code="LO1", weight=2.0),
        SimpleNamespace(id=2, lo_code="LO-GOSO-B1", weight=1.0),
    ]
    rows = [
        SimpleNamespace(course_id=10, lo_id=1, score=0.2, evidence_json={"epvo_expert_score": 0.8}),
        SimpleNamespace(course_id=10, lo_id=2, score=0.9, evidence_json={}),
    ]

    weights, codes, aggregate = aggregate_match_scores(_DB(rows), _Match, 7, los)

    assert weights == {1: 2.0, 2: 1.0}
    assert codes == {1: "LO1", 2: "LO-GOSO-B1"}
    item = aggregate[10]
    assert item["sum"] == 1.3
    assert item["max"] == 0.9
    assert item["credible_lo_codes"] == {"LO1", "LO-GOSO-B1"}
    assert item["professional_lo_codes"] == {"LO1"}
    assert item["lo_scores"] == {"LO1": 0.8, "LO-GOSO-B1": 0.9}
