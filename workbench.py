"""
workbench.py — single-command launcher for the analytical workbench.

Usage::

    python workbench.py

What it does
─────────────
1. Pre-flight: confirms ``data/delivery_system.sqlite`` exists (warns if
   missing with the exact commands to populate it).
2. Pre-flight: if ``frontend/node_modules`` is absent, runs ``npm install``.
3. Launches the FastAPI backend (``uvicorn api.main:app`` on :8000) and
   the Vite dev server (``npm run dev`` on :5173) as child processes,
   tagging each subprocess's output with ``[api]`` / ``[web]`` so you
   can tell who is talking.
4. Opens ``http://localhost:5173`` in your default browser once Vite is
   likely warm (2.5 s delay).
5. Forwards Ctrl-C to both children for a clean shutdown.

Flags
─────
  --no-browser   don't auto-open the browser
  --db PATH      override DRONE_API_DB for this session (defaults to
                 data/delivery_system.sqlite)
  --reload       hot-reload the FastAPI backend on file changes
  --port-api N   override backend port (default 8000)
  --port-web N   override frontend port (default 5173)
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


ROOT       = Path(__file__).resolve().parent
DB_DEFAULT = ROOT / "data" / "delivery_system.sqlite"
FRONTEND   = ROOT / "frontend"

# ANSI colours — disabled gracefully when stdout isn't a TTY (CI logs, pipes).
_USE_COLOR = sys.stdout.isatty()


def _tag(name: str, ansi: str) -> str:
    if _USE_COLOR:
        return f"\x1b[{ansi}m[{name}]\x1b[0m "
    return f"[{name}] "


def _stream(proc: subprocess.Popen, tag: str) -> None:
    """Read a subprocess's combined stdout/stderr line-by-line and
    print each line with *tag* prefixed.  Runs on a daemon thread.
    Any decode/print failure is logged once and the loop continues —
    a single bad byte from a child must not kill the printer."""
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        try:
            line = raw.decode("utf-8", errors="replace").rstrip()
            print(tag + line, flush=True)
        except Exception as exc:  # pragma: no cover — defence in depth
            try:
                print(f"{tag}<stream error: {exc!r}>", flush=True)
            except Exception:
                pass


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """True if no listener is responding on *host*:*port*.

    Uses ``connect_ex`` rather than ``bind`` because on Windows
    ``SO_REUSEADDR`` lets a fresh ``bind`` succeed even when another
    process is already listening — a false negative we cannot afford.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        # connect_ex returns 0 iff something accepts the connection.
        return s.connect_ex((host, port)) != 0


def _check_ports(api_port: int, web_port: int) -> None:
    """Fail fast if either port is already in use, with a clear hint."""
    taken = [(name, p) for name, p in
             [("api", api_port), ("web", web_port)] if not _port_is_free(p)]
    if not taken:
        return
    msg = ["\n[preflight] required port(s) already in use:\n"]
    for name, p in taken:
        msg.append(f"  - {name:3s}  http://127.0.0.1:{p}\n")
    msg.append(
        "\nSomething is already listening there — usually a previous\n"
        "uvicorn or vite that didn't shut down cleanly.  To find and\n"
        "kill it on Windows:\n\n"
        "  netstat -ano | findstr :<port>\n"
        "  taskkill /F /PID <pid>\n\n"
        "Or pass --port-api / --port-web to use different ports.\n"
    )
    sys.stderr.write("".join(msg))
    sys.exit(1)


def _preflight(args: argparse.Namespace) -> None:
    db = Path(args.db) if args.db else DB_DEFAULT
    if not db.exists():
        sys.stderr.write(
            f"\n[preflight] WARNING: database not found at {db}\n"
            f"            The workbench will load but pages will show empty\n"
            f"            states.  To populate:\n\n"
            f"              python run_scenarios.py --scenarios urban_dense "
            f"suburban_standard rural_extended --trips 100 --seed 42\n"
            f"              python run_transforms.py --all-runs --all-delivery-domains\n"
            f"              python run_transforms.py --all-runs --all-scale-models\n"
            f"              python run_visualizations.py --db {db} "
            f"--out outputs/charts\n\n"
        )

    if not (FRONTEND / "node_modules").exists():
        print("[preflight] frontend/node_modules missing — running `npm install`...",
              flush=True)
        rc = subprocess.call(
            ["npm", "install"], cwd=FRONTEND,
            shell=(os.name == "nt"),     # npm is a .cmd on Windows
        )
        if rc != 0:
            sys.stderr.write("[preflight] npm install failed — aborting\n")
            sys.exit(rc)


def main() -> None:
    # On Windows the default stdout codec is cp1252, which chokes on the
    # arrows / box-drawing glyphs Vite emits.  Switch stdout/stderr to
    # UTF-8 with replacement so a stray glyph never tears down a thread.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="Launch the FastAPI + React workbench in one terminal.",
    )
    ap.add_argument("--no-browser", action="store_true",
                    help="don't auto-open http://localhost:<port-web>")
    ap.add_argument("--db",        default=None,
                    help=f"override DRONE_API_DB (default: {DB_DEFAULT})")
    ap.add_argument("--reload",    action="store_true",
                    help="enable uvicorn --reload (hot-reload on .py edits)")
    ap.add_argument("--port-api",  type=int, default=8000)
    ap.add_argument("--port-web",  type=int, default=5173)
    args = ap.parse_args()

    _check_ports(args.port_api, args.port_web)
    _preflight(args)

    env = os.environ.copy()
    if args.db:
        env["DRONE_API_DB"] = args.db

    # ── Backend ────────────────────────────────────────────────────────────
    uvicorn_cmd = [
        sys.executable, "-m", "uvicorn", "api.main:app",
        "--host", "127.0.0.1",
        "--port", str(args.port_api),
    ]
    if args.reload:
        uvicorn_cmd.append("--reload")
    api_proc = subprocess.Popen(
        uvicorn_cmd, cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    # ── Frontend ───────────────────────────────────────────────────────────
    # --strictPort fails fast if the port slipped between _check_ports
    # and Vite's actual bind (a tight race in theory, never in practice).
    web_proc = subprocess.Popen(
        ["npm", "run", "dev", "--",
         "--port", str(args.port_web), "--strictPort"],
        cwd=FRONTEND,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        shell=(os.name == "nt"),
    )

    threading.Thread(target=_stream, args=(api_proc, _tag("api", "36")),
                     daemon=True).start()
    threading.Thread(target=_stream, args=(web_proc, _tag("web", "35")),
                     daemon=True).start()

    if not args.no_browser:
        def _open_browser() -> None:
            time.sleep(2.5)  # let Vite finish its first build
            webbrowser.open(f"http://localhost:{args.port_web}")
        threading.Thread(target=_open_browser, daemon=True).start()

    print(_tag("workbench", "32") + "started.  Ctrl-C to stop.", flush=True)
    print(_tag("workbench", "32") +
          f"frontend  http://localhost:{args.port_web}", flush=True)
    print(_tag("workbench", "32") +
          f"api       http://localhost:{args.port_api}/docs", flush=True)

    # ── Lifecycle: forward Ctrl-C, watch for unexpected child death ────────
    shutting_down = threading.Event()

    def _shutdown(*_args) -> None:
        if shutting_down.is_set():
            return
        shutting_down.set()
        print("\n" + _tag("workbench", "33") + "shutting down…", flush=True)
        for p in (web_proc, api_proc):
            try:
                p.terminate()
            except Exception:
                pass
        for p in (web_proc, api_proc):
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    try:
        while not shutting_down.is_set():
            if api_proc.poll() is not None:
                print(_tag("workbench", "31") +
                      f"api exited unexpectedly (rc={api_proc.returncode})",
                      flush=True)
                _shutdown()
            if web_proc.poll() is not None:
                print(_tag("workbench", "31") +
                      f"web exited unexpectedly (rc={web_proc.returncode})",
                      flush=True)
                _shutdown()
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
