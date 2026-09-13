class FakeQuery:
    def __init__(self, events):
        self.events = events

    def filter(self, *_args):
        return self

    def delete(self):
        self.events.append("delete-old")


class FakeSession:
    def __init__(self):
        self.events = []

    def query(self, *_args):
        return FakeQuery(self.events)

    def add_all(self, values):
        self.events.append(("add-new", list(values)))

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def test_scoring_publication_replaces_old_evidence_only_at_the_final_boundary():
    from app.kag.scoring import publish_match_scores

    db = FakeSession()
    pending = [object(), object()]
    publish_match_scores(db, 17, pending)

    assert db.events == ["delete-old", ("add-new", pending), "commit"]


def test_scoring_publication_rolls_back_if_replacement_cannot_be_written():
    from app.kag.scoring import publish_match_scores

    class BrokenSession(FakeSession):
        def add_all(self, _values):
            raise RuntimeError("simulated insert failure")

    db = BrokenSession()
    try:
        publish_match_scores(db, 17, [object()])
    except RuntimeError:
        pass
    else:
        raise AssertionError("publication failure must propagate to the caller")
    assert db.events == ["delete-old", "rollback"]
