"""
Server pre-flight check — run before starting Route-Time to detect ghost processes.

Usage:
  python -m pytest route_time/tests/test_server.py -v
  python route_time/tests/test_server.py        # standalone, prints result

The test PASSES when no process is holding port 5050.
The test FAILS (with PID list) when the port is occupied, which is the signal
to kill the old server before starting a new one.
"""
import socket
import subprocess
import sys

PORT = 5050


def _pids_on_port(port: int) -> list[int]:
    """Return PIDs listening on *port* using lsof (macOS/Linux)."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f":{port}"], stderr=subprocess.DEVNULL, text=True
        )
        return [int(p) for p in out.split() if p.strip()]
    except subprocess.CalledProcessError:
        return []          # lsof returns exit 1 when nothing found
    except FileNotFoundError:
        return []          # lsof not available (shouldn't happen on macOS)


def _port_open(port: int) -> bool:
    """Quick TCP connect check — true if something is accepting on *port*."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# pytest test
# ---------------------------------------------------------------------------

def test_port_5050_is_free():
    """
    Fail loudly if Route-Time server is already running (or some other process
    has grabbed port 5050).  Provides the PID so the user knows exactly what
    to kill.

    To kill the old server:
        kill $(lsof -ti :5050)
    Or use the restart script:
        bash route_time/runserver.sh
    """
    pids = _pids_on_port(PORT)
    if pids:
        pid_str = ", ".join(str(p) for p in pids)
        raise AssertionError(
            f"Port {PORT} is already in use by PID(s): {pid_str}\n"
            f"  Kill with:  kill {pid_str}\n"
            f"  Or restart: bash route_time/runserver.sh"
        )


def test_server_responds_if_running():
    """
    If the server IS running, verify it responds with HTTP 200 on /.
    Skipped when nothing is on port 5050.

    This is the liveness check — run after startup to confirm the server
    is healthy, not just occupying the port.
    """
    import pytest
    if not _port_open(PORT):
        pytest.skip("No server on port 5050 — start with: python -m route_time.gui")

    import urllib.request
    import urllib.error
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=3)
        assert resp.status == 200, f"Server returned HTTP {resp.status}"
    except urllib.error.URLError as exc:
        raise AssertionError(f"Server on port {PORT} did not respond: {exc}") from exc


# ---------------------------------------------------------------------------
# Standalone runner (no pytest required)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pids = _pids_on_port(PORT)
    accepting = _port_open(PORT)

    if not pids and not accepting:
        print(f"[OK] Port {PORT} is free — safe to start the server.")
        sys.exit(0)

    if pids:
        print(f"[!!] Port {PORT} is held by PID(s): {', '.join(str(p) for p in pids)}")
        print(f"     Kill with:  kill {' '.join(str(p) for p in pids)}")
        print(f"     Or restart: bash route_time/runserver.sh")
    if accepting and not pids:
        # Port accepting but lsof found nothing (e.g., permission issue)
        print(f"[!!] Port {PORT} is accepting connections but lsof found no PID.")
        print(f"     Try:  sudo lsof -ti :{PORT} | xargs kill -9")
    sys.exit(1)
