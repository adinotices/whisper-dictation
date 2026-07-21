import select as _select
import sys

import evdev

from .client import send_command
from .config import load_config


def event_to_command(code: int, value: int, ptt_code: int) -> str | None:
    """Map a key event to a daemon command. Only the PTT key matters:
    down (1) -> start, up (0) -> stop, auto-repeat (2) / anything else -> None.
    """
    if code != ptt_code:
        return None
    if value == 1:
        return "start"
    if value == 0:
        return "stop"
    return None


def key_name_to_code(name: str) -> int:
    """Resolve a config key name like 'rightctrl' to an evdev key code.
    Unknown names fall back to Right Ctrl with a warning.
    """
    attr = "KEY_" + name.strip().upper()
    code = getattr(evdev.ecodes, attr, None)
    if code is None:
        print(
            f"dictate-ptt: unknown ptt_key {name!r}, using rightctrl",
            file=sys.stderr,
        )
        return evdev.ecodes.KEY_RIGHTCTRL
    return code


def dispatch_events(events, ptt_code, sender) -> None:
    """Feed an iterable of evdev events; send the mapped command for each PTT
    key edge. A sender OSError (daemon momentarily down) is logged, not raised.
    """
    for event in events:
        if event.type != evdev.ecodes.EV_KEY:
            continue
        command = event_to_command(event.code, event.value, ptt_code)
        if command is None:
            continue
        try:
            sender(command)
        except OSError as exc:
            print(f"dictate-ptt: {command} failed: {exc}", file=sys.stderr)


def select_keyboards(ptt_code, paths, opener=evdev.InputDevice):
    """Return opened devices whose EV_KEY capabilities include the PTT key.
    Devices that cannot be opened (permissions/hotplug races) are skipped.
    """
    keyboards = []
    for path in paths:
        try:
            device = opener(path)
        except (PermissionError, OSError):
            continue
        keys = device.capabilities().get(evdev.ecodes.EV_KEY, [])
        if ptt_code in keys:
            keyboards.append(device)
    return keyboards


def event_stream(devices):
    """Yield events from several devices at once via select()."""
    fd_to_device = {device.fd: device for device in devices}
    while True:
        readable, _, _ = _select.select(fd_to_device, [], [])
        for fd in readable:
            yield from fd_to_device[fd].read()


def main() -> None:
    config = load_config()
    ptt_code = key_name_to_code(config.ptt_key)
    devices = select_keyboards(ptt_code, evdev.list_devices())
    if not devices:
        print(
            "dictate-ptt: no keyboard exposing the PTT key found "
            "(is your user in the 'input' group?)",
            file=sys.stderr,
        )
        sys.exit(1)
    # Clear any stale recording state left by a previous run.
    try:
        send_command("stop")
    except OSError:
        pass
    names = ", ".join(d.name for d in devices)
    print(f"dictate-ptt: listening on {names}", file=sys.stderr)
    dispatch_events(event_stream(devices), ptt_code, send_command)
