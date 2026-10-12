"""Opt-in isolated database check; no model loads or catalogue writes."""
import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.services.generation_capacity import generation_slot, CapacityBusy


@pytest.mark.skipif(os.environ.get('RUN_CAPACITY_PG') != '1', reason='isolated PostgreSQL opt-in')
def test_four_connections_admit_only_one_and_release_allows_next():
    from app.config import settings
    source = urlparse(settings.DATABASE_URL)
    assert source.port == 5433 and source.path == '/curriculum_kag_shadow'
    database = 'curriculum_kag_restore_pilot_20261010'
    engine = create_engine(source._replace(path='/' + database).geturl(), poolclass=NullPool)
    with engine.connect() as connection:
        assert connection.execute(text('select current_database()')).scalar() == database
    barrier, release, outcomes = Barrier(4), Event(), Queue()

    def attempt():
        barrier.wait(timeout=10)
        try:
            with generation_slot(engine):
                outcomes.put('admitted')
                assert release.wait(timeout=15)
        except CapacityBusy:
            outcomes.put('busy')

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(attempt) for _ in range(4)]
            try:
                observed = [outcomes.get(timeout=10) for _ in range(4)]
                assert observed.count('admitted') == 1
                assert observed.count('busy') == 3
            finally:
                release.set()
            for future in futures:
                future.result(timeout=10)
        with generation_slot(engine):
            pass
        # A worker owns the whole build; scoring re-enters its same slot.
        with generation_slot(engine):
            with generation_slot(engine):
                pass
            def competing_worker():
                with pytest.raises(CapacityBusy):
                    with generation_slot(engine):
                        pytest.fail('Nested exit released the outer slot')
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(competing_worker).result(timeout=10)
    finally:
        release.set()
        engine.dispose()


@pytest.mark.skipif(os.environ.get('RUN_CAPACITY_PG') != '1', reason='isolated PostgreSQL opt-in')
def test_disconnected_owner_releases_slot_without_lease_repair():
    from app.config import settings
    source = urlparse(settings.DATABASE_URL)
    assert source.port == 5433 and source.path == '/curriculum_kag_shadow'
    engine = create_engine(source._replace(path='/curriculum_kag_restore_pilot_20261010').geturl(), poolclass=NullPool)
    try:
        with engine.connect() as owner:
            assert owner.execute(text('SELECT pg_try_advisory_lock(1129005383, 1)')).scalar()
            with pytest.raises(CapacityBusy):
                with generation_slot(engine):
                    pytest.fail('Another live owner was admitted')
            # NullPool closes the physical connection, matching an owner loss.
        with generation_slot(engine):
            pass
    finally:
        engine.dispose()
