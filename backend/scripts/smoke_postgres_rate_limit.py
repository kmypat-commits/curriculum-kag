"""Verify the shared PostgreSQL rate-limit bucket across processes."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import RequestGuardMiddleware


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    bucket = f"smoke-{int(time.time())}"
    client_key = "smoke-client"
    local_results = [
        RequestGuardMiddleware._shared_bucket_allowed(bucket, client_key, args.limit, 60)
        for _ in range(args.limit + 1)
    ]
    if local_results != [True] * args.limit + [False]:
        print({"status": "failed", "local_results": local_results})
        return 1
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.main import RequestGuardMiddleware; "
            f"print(RequestGuardMiddleware._shared_bucket_allowed({bucket!r}, {client_key!r}, {args.limit}, 60))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    cross_process = (child.stdout or "").strip().lower().endswith("false")
    print({"status": "passed" if cross_process else "failed", "local_results": local_results, "cross_process": cross_process})
    return 0 if cross_process else 1


if __name__ == "__main__":
    raise SystemExit(main())
