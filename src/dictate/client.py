import socket
import subprocess
import sys
import time

from .daemon import socket_path


def socket_connect():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(socket_path()))
    return sock


def send_command(command, connect=socket_connect) -> str:
    conn = connect()
    try:
        conn.sendall(command.encode())
        return conn.recv(1024).decode().strip()
    finally:
        conn.close()


def send_toggle(connect=socket_connect) -> str:
    return send_command("toggle", connect=connect)


def _start_daemon_and_wait() -> None:
    subprocess.Popen(["dictate-daemon"])
    for _ in range(100):  # wait up to ~10s for model load + socket bind
        if socket_path().exists():
            return
        time.sleep(0.1)


def main() -> None:
    try:
        print(send_toggle())
        sys.exit(0)
    except (ConnectionRefusedError, FileNotFoundError):
        _start_daemon_and_wait()
    try:
        print(send_toggle())
        sys.exit(0)
    except OSError as exc:
        print(f"dictate: could not reach daemon: {exc}", file=sys.stderr)
        sys.exit(1)
