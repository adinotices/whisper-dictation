import shutil
import subprocess

METHODS = ["wtype", "ydotool", "clipboard"]
# clipboard can't press keys, so key injection only tries the real backends.
KEY_METHODS = ["wtype", "ydotool"]

# evdev keycodes for ydotool.
_YDO_ENTER = "28"
_YDO_LSHIFT = "42"


def _command(method: str, text: str) -> list[str]:
    if method == "wtype":
        return ["wtype", text]
    if method == "ydotool":
        return ["ydotool", "type", text]
    if method == "clipboard":
        return ["wl-copy", text]
    raise ValueError(f"unknown method: {method}")


def _key_command(method: str, key: str) -> list[str]:
    if method == "wtype":
        if key == "enter":
            return ["wtype", "-k", "Return"]
        if key == "shift_enter":
            return ["wtype", "-M", "shift", "-k", "Return", "-m", "shift"]
    if method == "ydotool":
        if key == "enter":
            return ["ydotool", "key", f"{_YDO_ENTER}:1", f"{_YDO_ENTER}:0"]
        if key == "shift_enter":
            return [
                "ydotool", "key",
                f"{_YDO_LSHIFT}:1", f"{_YDO_ENTER}:1",
                f"{_YDO_ENTER}:0", f"{_YDO_LSHIFT}:0",
            ]
    raise ValueError(f"unknown key/method: {method}/{key}")


def inject_key(key: str, method: str | None = None, runner=subprocess.run) -> str:
    """Press a named key ("enter" | "shift_enter"). Tries wtype then ydotool;
    clipboard cannot press keys. Returns the method that succeeded.
    """
    order = KEY_METHODS
    if method in KEY_METHODS:
        order = KEY_METHODS[KEY_METHODS.index(method):]
    last_error: Exception | None = None
    for m in order:
        try:
            runner(_key_command(m, key), check=True)
            return m
        except Exception as exc:  # noqa: BLE001 - try next method
            last_error = exc
    raise RuntimeError(f"all key-injection methods failed: {last_error}")


def detect_method() -> str:
    if shutil.which("wtype"):
        return "wtype"
    if shutil.which("ydotool"):
        return "ydotool"
    return "clipboard"


def inject(text: str, method: str | None = None, runner=subprocess.run) -> str:
    start = method or detect_method()
    if start not in METHODS:
        raise RuntimeError(f"unknown injection method: {start}")
    order = METHODS[METHODS.index(start):]
    last_error: Exception | None = None
    for m in order:
        try:
            runner(_command(m, text), check=True)
            return m
        except Exception as exc:  # noqa: BLE001 - try next method
            last_error = exc
    raise RuntimeError(f"all injection methods failed: {last_error}")
