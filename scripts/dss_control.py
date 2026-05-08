from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
LOGS = RUNTIME / "logs"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


SERVICES = {
    "backend": {
        "port": BACKEND_PORT,
        "pid": RUNTIME / "backend.pid",
        "log": LOGS / "backend.log",
        "url": "http://127.0.0.1:8000/api/v1",
    },
    "frontend": {
        "port": FRONTEND_PORT,
        "pid": RUNTIME / "frontend.pid",
        "log": LOGS / "frontend.log",
        "url": "http://127.0.0.1:5173/",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAlex DSS local service manager")
    parser.add_argument("command", choices=["start", "stop", "restart", "status"])
    args = parser.parse_args()

    if args.command == "start":
        start()
    elif args.command == "stop":
        stop()
    elif args.command == "restart":
        stop()
        start()
    elif args.command == "status":
        status()


def start() -> None:
    ensure_runtime()
    start_backend()
    start_frontend()
    time.sleep(1.2)
    status()
    print()
    print("UI:      http://127.0.0.1:5173/")
    print("API:     http://127.0.0.1:8000/api/v1")
    print("Swagger: http://127.0.0.1:8000/docs")
    print(f"Logs:    {LOGS}")


def stop() -> None:
    ensure_runtime()
    for name in ("frontend", "backend"):
        stop_service(name)


def status() -> None:
    ensure_runtime()
    for name, service in SERVICES.items():
        port = int(service["port"])
        pid = service_pid(name) or port_pid(port)
        state = "running" if pid and pid_alive(pid) and port_open(port) else "stopped"
        suffix = f" pid={pid}" if pid else ""
        print(f"{name}: {state}{suffix} port={port} url={service['url']}")


def start_backend() -> None:
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit("Missing .venv. Run: python3.12 -m venv .venv && .venv/bin/pip install -r apps/api/requirements.txt")
    start_service(
        "backend",
        [
            str(python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=ROOT / "apps/api",
    )


def start_frontend() -> None:
    start_service(
        "frontend",
        ["npm", "run", "dev", "--workspace", "apps/web", "--", "--port", str(FRONTEND_PORT)],
        cwd=ROOT,
    )


def start_service(name: str, command: list[str], *, cwd: Path) -> None:
    service = SERVICES[name]
    port = int(service["port"])
    existing_pid = service_pid(name)
    if existing_pid and pid_alive(existing_pid):
        print(f"{name}: already running pid={existing_pid}")
        return
    port_owner = port_pid(port)
    if port_owner and pid_alive(port_owner):
        write_pid(name, port_owner)
        print(f"{name}: already listening on port {port} pid={port_owner}")
        return

    env = os.environ.copy()
    env.setdefault("OPENALEX_DSS_DATA_DIR", str((ROOT.parent / "openalex-dss-data").resolve()))
    log_path = Path(service["log"])
    log = log_path.open("ab")
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    write_pid(name, proc.pid)
    print(f"{name}: started pid={proc.pid} log={log_path}")


def stop_service(name: str) -> None:
    service = SERVICES[name]
    port = int(service["port"])
    candidates = [service_pid(name), port_pid(port)]
    seen: set[int] = set()
    stopped = False
    for raw_pid in candidates:
        if not raw_pid or raw_pid in seen or not pid_alive(raw_pid):
            continue
        seen.add(raw_pid)
        terminate_pid(raw_pid)
        stopped = True
        print(f"{name}: stopped pid={raw_pid}")
    Path(service["pid"]).unlink(missing_ok=True)
    if not stopped:
        print(f"{name}: stopped")


def terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise SystemExit(f"Cannot stop pid {pid}: {exc}") from exc
    deadline = time.time() + 4
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.15)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def ensure_runtime() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)


def service_pid(name: str) -> int | None:
    path = Path(SERVICES[name]["pid"])
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError):
        return None


def write_pid(name: str, pid: int) -> None:
    Path(SERVICES[name]["pid"]).write_text(f"{pid}\n", encoding="utf-8")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def port_pid(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
