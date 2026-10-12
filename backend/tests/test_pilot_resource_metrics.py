import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_summary_deduplicates_process_identity_and_keeps_memory_measures_separate():
    path = Path(__file__).parents[1] / 'scripts/pilot_resource_metrics.py'
    assert path.exists(), 'Pilot sampler has not been implemented'
    spec = importlib.util.spec_from_file_location('pilot_metrics', path)
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    one = {'pid': 10, 'created_at': 100, 'working_set_bytes': 20,
           'private_bytes': 50, 'cpu_seconds': 2}
    two = {'pid': 11, 'created_at': 101, 'working_set_bytes': 30,
           'private_bytes': 70, 'cpu_seconds': 3}
    summary = metrics.summarize_samples([
        {'monotonic_seconds': 0, 'available_ram_bytes': 500, 'processes': [one, one, two]},
        {'monotonic_seconds': 2, 'available_ram_bytes': 400, 'processes': [one]},
    ])
    assert summary['peak_working_set_bytes'] == 50
    assert summary['peak_private_bytes'] == 120
    assert summary['minimum_available_ram_bytes'] == 400
    assert summary['observation_seconds'] == 2
    assert summary['generation_cost'] is None


@pytest.mark.parametrize('threshold, expected_state, exit_code', [
    ('0', 'observation_complete', 0),
    ('1000000000', 'memory_guard_triggered', 2),
])
def test_sampler_observes_real_process_and_reports_guard(tmp_path, threshold, expected_state, exit_code):
    root = Path(__file__).parents[2]
    if not (root / '.runtime/pilot-metrics-lib/psutil').exists():
        pytest.skip('Optional isolated measurement dependency not installed')
    target = tmp_path / 'samples.json'
    completed = subprocess.run([
        sys.executable, str(root / 'backend/scripts/pilot_resource_metrics.py'),
        '--pid', str(os.getpid()), '--seconds', '.1', '--interval', '.25',
        '--minimum-available-mib', threshold, '--output', str(target),
    ], capture_output=True, text=True, timeout=10)
    assert completed.returncode == exit_code, completed.stderr
    report = json.loads(target.read_text(encoding='utf-8'))
    assert report['state'] == expected_state
    assert report['generation_load'] is False
    observed = report['samples'][0]['processes']
    assert any(p['pid'] == os.getpid() and p['working_set_bytes'] > 0 for p in observed)
    assert report['summary']['generation_cost'] is None
    host = report['samples'][0]['host_memory']
    assert host['total_ram_bytes'] > 0
    assert host['available_ram_bytes'] <= host['total_ram_bytes']
    assert report['samples'][0]['host_top_processes']
