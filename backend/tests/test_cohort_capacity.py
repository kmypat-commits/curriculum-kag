import json
from contextlib import contextmanager
import pytest
from app.services.generation_capacity import CapacityBusy


def test_busy_cli_exits_retryable_before_creating_temporary_project(monkeypatch, tmp_path):
    from scripts import audit_cross_level_generation as cli
    observed = {'created': False, 'closed': False}
    class DB:
        def get_bind(self): return object()
        def execute(self, *args): pass
        def add(self, *args):
            observed['created'] = True
            raise SystemExit(99)
        def rollback(self): pass
        def close(self): observed['closed'] = True
    @contextmanager
    def busy(_engine):
        raise CapacityBusy('occupied')
        yield
    report = tmp_path / 'busy.json'
    monkeypatch.setattr(cli, 'SessionLocal', DB)
    monkeypatch.setattr(cli, 'generation_slot', busy, raising=False)
    monkeypatch.setattr(cli.sys, 'argv', ['audit', '--level', 'bachelor',
                                        '--variants', 'A', '--output', str(report)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 75
    assert observed == {'created': False, 'closed': True}
    assert json.loads(report.read_text(encoding='utf-8'))['status'] == 'capacity_busy'
