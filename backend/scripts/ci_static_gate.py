"""Cheap repository invariants that do not require a database or model weights."""
from pathlib import Path
import subprocess
import re, sys
ROOT=Path(__file__).resolve().parents[2]
fail=[]
for base in (ROOT/'frontend'/'src', ROOT/'backend'/'app'):
    for path in base.rglob('*'):
        if path.suffix.lower() in {'.js','.jsx','.ts','.tsx','.py','.json','.css'}:
            text=path.read_text(encoding='utf-8')
            if '\ufffd' in text: fail.append(f'corrupt UTF-8 marker: {path}')
            if path.suffix.lower() in {'.js','.jsx'} and re.search(r'\balert\s*\(', text): fail.append(f'alert() remains: {path}')
tracked=subprocess.run(['git','ls-files','*.env','.env'],cwd=ROOT,text=True,capture_output=True,check=False).stdout.splitlines()
for path in tracked:
    fail.append(f'secret file tracked: {path}')
if fail:
    print('\n'.join(fail)); return_code=1
else:
    planner=(ROOT/'backend'/'app'/'api'/'planner.py').read_text(encoding='utf-8')
    verifier=(ROOT/'backend'/'app'/'planner'/'verifier.py').read_text(encoding='utf-8')
    for marker, source in (("variant_not_distinct", planner), ("lo_without_real_course", planner + verifier), ("rejected_variants", planner)):
        if marker not in source: fail.append(f'missing quality invariant: {marker}')
if fail:
    print('\n'.join(fail)); return_code=1
else:
    print('static quality gate passed'); return_code=0
sys.exit(return_code)
