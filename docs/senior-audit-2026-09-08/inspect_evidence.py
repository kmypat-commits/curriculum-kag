"""Read-only source/artifact audit; never imports the application or opens a DB.

The Windows process probe runs ONLY in a disposable child and targets its own
PID. No PID read from project files is passed to os.kill. Output is generated
only in this audit directory. This is evidence collection, not a product fix.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def pure_function(relative, name, extra=None, constants=(), helpers=()):
    tree = ast.parse(read(relative))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    body.extend(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets))
    body.extend(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in helpers)
    body.append(function)
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    env = dict(extra or {})
    exec(compile(module, relative, "exec"), env)
    return env[name]


def main():
    policy_path = "backend/app/planner/bridge_policy.py"
    limit = pure_function(policy_path, "bridge_module_limit", {"settings": SimpleNamespace(MAX_BRIDGE_MODULES=5)})
    policy_results = []
    for requested in (0, 1, 3, 5, 7):
        project = SimpleNamespace(constraints_json={"program_type": "interdisciplinary", "max_new_courses": requested})
        policy_results.append({"requested": requested, "actual": limit(SimpleNamespace(project=project))})
    match_domain = pure_function(
        "backend/app/planner/domain_evidence.py",
        "domain_label_matches",
        extra={"re": re},
        constants=("_DOMAIN_ALIASES",),
        helpers=("_label_contains",),
    )
    domain_results = {label: match_domain(label, ["Information and communication technologies"])
                      for label in ("Literature", "Hospitality", "Agriculture", "Computer science")}
    cases = pure_function("backend/scripts/audit_quality_cohort.py", "build_cohort_cases")(30, "breadth")
    semantic_cases = {(r["level"], r["profile"], r["focus"].split(" — контрольный контекст")[0]) for r in cases}
    signature = pure_function(
        "backend/app/planner/invariant_ledger.py",
        "schedule_fingerprint",
        extra={"hashlib": hashlib, "json": json},
    )
    items = [{"course_id": 100, "credits": 5}, {"course_id": 200, "credits": 5}]
    order_sensitive = signature({1: items}) != signature({1: list(reversed(items))})

    # The repository helper is executed only on the disposable interpreter's
    # own PID, NEVER on an existing app, cohort runner or shell process.
    windows_probe = {"performed": False, "reason": "Windows-only behavior"}
    if os.name == "nt":
        tree = ast.parse(read("backend/scripts/audit_quality_cohort.py"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_is_alive")
        child_code = "import os, signal\n" + ast.unparse(node) + '\nprint("BEFORE", flush=True)\nprint("LIVE_SELF_RESULT", process_is_alive(os.getpid()), flush=True)\nprint("CTRL_C_EVENT", signal.CTRL_C_EVENT, flush=True)\nprint("AFTER", flush=True)\n'
        child = subprocess.run([sys.executable, "-c", child_code], capture_output=True, text=True, timeout=15)
        windows_probe = {"performed": True, "python_version": sys.version, "target": "disposable child own PID only",
                         "returncode": child.returncode, "stdout": child.stdout.strip(),
                         "after_marker_present": "AFTER" in child.stdout}

    cohort_path = ".runtime/quality-cohort-acceptance-20260907.json"
    cohort = json.loads(read(cohort_path))
    reports = cohort.get("reports", [])
    durations = [r["elapsed_seconds"] for r in reports if isinstance(r.get("elapsed_seconds"), (int, float))]
    rows = []
    for index, report in enumerate(reports, 1):
        variants = {}
        for key, value in (report.get("variants") or {}).items():
            variants[key] = {k: value.get(k) for k in ("credits", "hard_violations", "credit_violations", "quality_passed", "goso_compliant", "real_courses", "bridges", "bridge_titles", "prerequisite_graph")}
            variants[key]["prerequisite_pairs"] = [{k: p.get(k) for k in ("prerequisite_title", "course_title", "prerequisite_semester", "course_semester")}
                                                       for p in value.get("prerequisite_pairs", [])]
        rows.append({"case": index, "level": report.get("level"), "profile": report.get("profile"),
                     "passed": report.get("passed"), "elapsed_seconds": report.get("elapsed_seconds"),
                     "attempts": report.get("process_attempts"), "returncode": report.get("process_returncode"), "variants": variants})
    migration_path = ".runtime/sqlite-postgres-acceptance-20260906-final2.json"
    migration = json.loads(read(migration_path))
    tracked_paths = [policy_path, "backend/app/api/epvo.py", "backend/scripts/audit_quality_cohort.py",
                     "backend/tests/test_quality_cohort_manifest.py", "backend/app/planner/domain_evidence.py",
                     "backend/app/api/planner_build.py", "backend/app/api/planner_state.py",
                     "backend/app/kag/embedding_service.py", "backend/app/kag/scoring.py",
                     "backend/app/services/planner_stage_cache.py", "backend/app/planner/scheduler.py",
                     "backend/app/planner/verifier.py", "backend/app/planner/variant_strategy.py",
                     "backend/app/kag/bridge_generator.py", "backend/app/config.py",
                     "backend/app/services/program_profiles.py", "backend/app/planner/scheduler_prerequisites.py",
                     "backend/app/planner/prerequisite_inference.py", "frontend/src/pages/PlanBuilder.jsx",
                     cohort_path, migration_path]
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in tracked_paths}
    large_files = []
    for base in (ROOT / "backend/app", ROOT / "frontend/src"):
        for path in base.rglob("*"):
            if path.suffix not in (".py", ".js", ".jsx", ".ts", ".tsx"):
                continue
            content = path.read_text(encoding="utf-8-sig")
            largest = None
            if path.suffix == ".py":
                try:
                    functions = [n for n in ast.walk(ast.parse(content)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    if functions:
                        fun = max(functions, key=lambda n: n.end_lineno - n.lineno)
                        largest = {"function": fun.name, "start": fun.lineno, "lines": fun.end_lineno - fun.lineno + 1}
                except SyntaxError:
                    pass
            large_files.append({"path": path.relative_to(ROOT).as_posix(), "physical_lines": len(content.splitlines()), "largest_function": largest})
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
    result = {
        "audit_utc": datetime.now(timezone.utc).isoformat(), "git_head": git.stdout.strip(),
        "scope": "dirty working tree; no application imports, database writes, services or generation",
        "probes": {"bridge_budget": policy_results, "domain_aliases": domain_results,
                   "breadth_raw_cases": len(cases), "breadth_semantic_contexts": len(semantic_cases),
                   "variant_signature_changes_on_intrasemester_reordering": order_sensitive,
                   "windows_pid_check": windows_probe},
        "cohort": {"source": cohort_path, "stored_status": cohort.get("status"),
                   "completed": cohort.get("completed"), "requested": cohort.get("requested"),
                   "passed_records": sum(r.get("passed") is True for r in reports),
                   "failed_records": sum(r.get("passed") is False for r in reports),
                   "elapsed_seconds": {"min": min(durations), "median": statistics.median(durations), "max": max(durations)},
                   "duration_caveat": "child audit only, not end-to-end; previous failed attempts not included", "records": rows},
        "migration": {"source": migration_path, "passed": migration.get("passed"),
                      "tables": len(migration.get("tables", [])),
                      "failed_tables": [r["table"] for r in migration.get("tables", []) if not r.get("passed")],
                      "foreign_key_violations": migration.get("foreign_key_violations"),
                      "discard_manifest_entries": len(migration.get("discard_manifest", []))},
        "largest_files": sorted(large_files, key=lambda r: r["physical_lines"], reverse=True)[:20],
        "source_sha256": hashes,
    }
    destination = HERE / "evidence.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source = HERE / "04_PROGRAMS_20_RU.md"
    brief_text = source.read_text(encoding="utf-8")
    parts = re.split(r"^## (P\d{2})\. (.+)$", brief_text, flags=re.M)
    briefs = []
    for index in range(1, len(parts), 3):
        case_id, title, section = parts[index:index + 3]
        profile = re.search(r"^Профиль: (.+)$", section, flags=re.M).group(1)
        goal = re.search(r"^(?:Цель|Мақсат|Goal): (.+)$", section, flags=re.M).group(1)
        los = re.findall(r"^LO([1-5])\. (.+)$", section, flags=re.M)
        assert [code for code, _ in los] == ["1", "2", "3", "4", "5"], case_id
        credits, semesters = re.search(r"\b(\d{2,3})(?: кредитов)?\s*/\s*(\d+)", profile).groups()
        level = next(level for level in ("bachelor", "master", "doctorate") if level in profile)
        language = re.search(r"язык (RU|KK|EN)", profile).group(1).lower()
        track = "standard" if level == "bachelor" else "professional" if ", professional," in profile else "scientific_pedagogical"
        briefs.append({"case_id": case_id, "title": title, "goal": goal,
                       "learning_outcomes": [{"code": f"LO{code}", "text": text, "weight": 1.0, "critical": True} for code, text in los],
                       "profile_verbatim": profile, "education_level": level, "track": track,
                       "jurisdiction": "KZ", "target_language": language,
                       "credits": int(credits), "semesters": int(semesters),
                       "max_generated_modules": int(re.search(r"Максимум новых модулей: (\d+)", profile).group(1)),
                       "required_blocks": re.search(r"^(?:Обязательные блоки|Блоки): (.+)$", section, flags=re.M).group(1),
                       "prerequisite_expectations": re.search(r"^(?:Ожидаемая цепочка|Цепочка): (.+)$", section, flags=re.M).group(1),
                       "unacceptable_substitutions": re.search(r"^Не принимать: (.+)$", section, flags=re.M).group(1),
                       "requested_variants": ["A", "B", "C"], "execution_status": "not_run",
                       "catalog_scope_status": "resolve_from_catalog_before_run", "expert_review_status": "not_requested"})
    assert [b["case_id"] for b in briefs] == [f"P{i:02d}" for i in range(1, 21)]
    assert len({b["goal"] for b in briefs}) == 20
    brief_manifest = {"status": "prepared_not_executed", "not_api_payload": True,
                      "scope_warning": "Resolve real level-appropriate EPVO codes; never substitute ICT for unsupported scopes.",
                      "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "cases": briefs}
    (HERE / "program_briefs_20.json").write_text(json.dumps(brief_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(destination), "probes": result["probes"],
                      "prepared_program_briefs": len(briefs), "professional_los": sum(len(b["learning_outcomes"]) for b in briefs),
                      "cohort_counts": {k: result["cohort"][k] for k in ("completed", "requested", "passed_records", "failed_records", "elapsed_seconds")},
                      "migration": result["migration"], "largest_files": result["largest_files"][:8]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
