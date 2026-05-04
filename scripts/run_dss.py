from __future__ import annotations

import signal
import subprocess
import sys
import os
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    api_python = ROOT / ".venv/bin/python"
    if not api_python.exists():
        raise SystemExit("Missing .venv. Run: python3.12 -m venv .venv && .venv/bin/pip install -r apps/api/requirements.txt")

    api_cmd = [
        str(api_python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    web_cmd = ["npm", "--workspace", "apps/web", "run", "dev"]
    env = os.environ.copy()
    env["PYTHONPATH"] = "apps/api"
    env.setdefault("OPENALEX_DSS_DATA_DIR", str((ROOT.parent / "openalex-dss-data").resolve()))

    api = subprocess.Popen(api_cmd, cwd=ROOT, env=env)
    web = subprocess.Popen(web_cmd, cwd=ROOT, env=env)

    print("API:      http://127.0.0.1:8000/api/v1")
    print("Swagger:  http://127.0.0.1:8000/docs")
    print("UI:       http://127.0.0.1:5173")
    print(f"Data:     {env['OPENALEX_DSS_DATA_DIR']}")

    def stop(_sig: int, _frame: object) -> None:
        for proc in (web, api):
            if proc.poll() is None:
                proc.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while True:
        if api.poll() is not None:
            web.terminate()
            raise SystemExit(api.returncode)
        if web.poll() is not None:
            api.terminate()
            raise SystemExit(web.returncode)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
