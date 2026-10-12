from contextlib import contextmanager
import pytest
from app.services.generation_capacity import generation_slot, CapacityBusy


class Connection:
    def __init__(self, available=True):
        self.available = available
        self.locked = False

    def execute(self, statement, parameters):
        if 'try_advisory_lock' in str(statement):
            self.locked = self.available
            return self
        self.locked = False
        return self

    def scalar(self):
        return self.locked


class Engine:
    def __init__(self, connection):
        self.connection = connection
        self.dialect = type('Dialect', (), {'name': 'postgresql'})()

    @contextmanager
    def connect(self):
        yield self.connection


def test_busy_slot_never_enters_heavy_work():
    entered = []
    with pytest.raises(CapacityBusy):
        with generation_slot(Engine(Connection(False))):
            entered.append('model')
    assert entered == []


def test_slot_is_released_after_heavy_work_fails():
    connection = Connection()
    with pytest.raises(ValueError):
        with generation_slot(Engine(connection)):
            assert connection.locked
            raise ValueError('model failed')
    assert not connection.locked
