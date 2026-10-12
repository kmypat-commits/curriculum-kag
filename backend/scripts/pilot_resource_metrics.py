"""Bounded read-only process-tree sampling; never stops an observed process."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def summarize_samples(samples):
    working, private, available = [], [], []
    for sample in samples:
        processes = {(p['pid'], p['created_at']): p for p in sample['processes']}
        working.append(sum(p['working_set_bytes'] for p in processes.values()))
        private.append(sum(p['private_bytes'] for p in processes.values()))
        available.append(sample['available_ram_bytes'])
    return {
        'sample_count': len(samples),
        'observation_seconds': (samples[-1]['monotonic_seconds'] - samples[0]['monotonic_seconds']) if samples else 0,
        'peak_working_set_bytes': max(working, default=0),
        'peak_private_bytes': max(private, default=0),
        'minimum_available_ram_bytes': min(available) if available else None,
        'generation_cost': None,
        'scope': 'Observed process trees only; not host-wide peak, throughput or generation cost',
    }


def host_snapshot(psutil):
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    processes, inaccessible = [], 0
    for process in psutil.process_iter(['pid', 'name', 'create_time', 'memory_info'], ad_value=None):
        info = process.info
        mem = info['memory_info']
        if mem is None:
            inaccessible += 1
            continue
        processes.append({'pid': info['pid'], 'name': info['name'],
                          'created_at': info['create_time'], 'working_set_bytes': mem.rss,
                          'private_bytes': getattr(mem, 'private', None)})
    return {'host_memory': {'total_ram_bytes': memory.total,
                            'available_ram_bytes': memory.available,
                            'swap_total_bytes': swap.total, 'swap_used_bytes': swap.used},
            'host_top_processes': sorted(processes, key=lambda p: p['working_set_bytes'], reverse=True)[:10],
            'host_inaccessible_processes': inaccessible}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', action='append', type=int, required=True)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--interval', type=float, default=1)
    parser.add_argument('--minimum-available-mib', type=float, default=1024)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.seconds <= 1800 or not .25 <= args.interval <= 10:
        parser.error('Require 0 < seconds <= 1800 and .25 <= interval <= 10')
    if args.output.exists():
        parser.error('Refusing to overwrite previous evidence')
    # Optional measurement dependency is isolated from the application venv.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '.runtime/pilot-metrics-lib'))
    import psutil

    roots = {pid: psutil.Process(pid).create_time() for pid in set(args.pid)}
    known = dict(roots)
    samples = []
    started = time.monotonic()
    report = {'sampler_pid': __import__('os').getpid(), 'psutil_version': psutil.__version__,
              'root_identities': roots, 'state': 'observing', 'samples': samples,
              'read_only': True, 'generation_load': False}
    # Exclusive creation also protects against two observers sharing a target.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream)
    while True:
        errors = []
        for pid, birth in roots.items():
            try:
                root = psutil.Process(pid)
                if root.create_time() != birth:
                    errors.append({'pid': pid, 'reason': 'root_pid_reused'})
                    continue
                for child in root.children(recursive=True):
                    known.setdefault(child.pid, child.create_time())
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                errors.append({'pid': pid, 'reason': type(exc).__name__})
        rows = []
        for pid, birth in known.items():
            try:
                process = psutil.Process(pid)
                if process.create_time() != birth:
                    errors.append({'pid': pid, 'reason': 'pid_reused'})
                    continue
                mem, cpu = process.memory_info(), process.cpu_times()
                rows.append({'pid': pid, 'created_at': birth,
                             'working_set_bytes': mem.rss,
                             'private_bytes': getattr(mem, 'private', mem.vms),
                             'private_measure': 'private' if hasattr(mem, 'private') else 'vms_fallback',
                             'cpu_seconds': cpu.user + cpu.system})
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                errors.append({'pid': pid, 'reason': type(exc).__name__})
        elapsed = time.monotonic() - started
        host = host_snapshot(psutil)
        free = host['host_memory']['available_ram_bytes']
        samples.append({'monotonic_seconds': elapsed, 'available_ram_bytes': free,
                        'processes': rows, 'observation_errors': errors, **host})
        if free < args.minimum_available_mib * 1024**2:
            report['state'] = 'memory_guard_triggered'
        elif elapsed >= args.seconds:
            report['state'] = 'observation_complete'
        report['summary'] = summarize_samples(samples)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        if report['state'] != 'observing':
            print(json.dumps({'state': report['state'], **report['summary']}))
            return 2 if report['state'] == 'memory_guard_triggered' else 0
        time.sleep(min(args.interval, args.seconds - elapsed))


if __name__ == '__main__':
    raise SystemExit(main())
