import subprocess


def notify(summary: str, body: str = "", runner=subprocess.run) -> None:
    try:
        runner(["notify-send", "-a", "dictate", summary, body], check=False)
    except Exception:  # noqa: BLE001 - notifications are best-effort
        pass
