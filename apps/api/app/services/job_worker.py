from __future__ import annotations

import sys

from app.services import jobs


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.services.job_worker <run_id>")
    jobs.execute_run_in_worker(sys.argv[1])


if __name__ == "__main__":
    main()
