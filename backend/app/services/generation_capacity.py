"""Connection-owned PostgreSQL slot for the entire heavy operation.

Callers must acquire before loading models, not only before MILP. A live
connection retains the slot even if job leases expire. Disconnect/crash
releases it in PostgreSQL; no timed lease may admit a second live owner.
"""
from contextlib import contextmanager
from threading import local
from sqlalchemy import text


_ownership = local()


class CapacityBusy(RuntimeError):
    pass


@contextmanager
def generation_slot(engine):
    """Synchronous, thread-owned scope; do not hold across an async await."""
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('Global generation capacity requires PostgreSQL')
    if getattr(_ownership, 'engine', None) is engine:
        yield
        return
    with engine.connect() as connection:
        acquired = connection.execute(
            text('SELECT pg_try_advisory_lock(:namespace, :slot)'),
            {'namespace': 1129005383, 'slot': 1},
        ).scalar()
        if not acquired:
            raise CapacityBusy('Heavy generation capacity is occupied')
        previous_engine = getattr(_ownership, 'engine', None)
        _ownership.engine = engine
        try:
            yield
        finally:
            _ownership.engine = previous_engine
            connection.execute(
                text('SELECT pg_advisory_unlock(:namespace, :slot)'),
                {'namespace': 1129005383, 'slot': 1},
            )
