import shutil
import subprocess

METHODS = ["wtype", "ydotool", "clipboard"]


def _command(method: str, text: str) -> list[str]:
    if method == "wtype":
        return ["wtype", text]
    if method == "ydotool":
        return ["ydotool", "type", text]
    if method == "clipboard":
        return ["wl-copy", text]
    raise ValueError(f"unknown method: {method}")


def detect_method() -> str:
    if shutil.which("wtype"):
        return "wtype"
    if shutil.which("ydotool"):
        return "ydotool"
    return "clipboard"


def inject(text: str, method: str | None = None, runner=subprocess.run) -> str:
    start = method or detect_method()
    order = METHODS[METHODS.index(start):]
    last_error: Exception | None = None
    for m in order:
        try:
            runner(_command(m, text), check=True)
            return m
        except Exception as exc:  # noqa: BLE001 - try next method
            last_error = exc
    raise RuntimeError(f"all injection methods failed: {last_error}")
