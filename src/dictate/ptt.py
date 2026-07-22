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


# How often (seconds) the listen loop wakes to re-scan /dev/input for keyboards
# that were docked/undocked after startup. A keyboard becomes live within ~this
# long; small enough to feel instant, large enough to avoid a busy loop.
POLL_INTERVAL = 1.0


def reconcile_devices(current, ptt_code, list_devices=evdev.list_devices,
                      opener=evdev.InputDevice):
    """Bring the ``{path: device}`` map `current` in line with the devices now
    present in /dev/input. Opens newly-appeared keyboards (those exposing the PTT
    key), closes ones that were unplugged. Returns ``(added_names, removed_names)``
    so the caller can log changes. Mutates `current` in place.
    """
    present = set(list_devices())
    removed = []
    for path in list(current):
        if path not in present:
            device = current.pop(path)
            removed.append(device.name)
            try:
                device.close()
            except OSError:
                pass
    added = []
    for path in present:
        if path in current:
            continue
        try:
            device = opener(path)
        except (PermissionError, OSError):
            continue  # permission gap or a hotplug race — try again next scan
        keys = device.capabilities().get(evdev.ecodes.EV_KEY, [])
        if ptt_code in keys:
            current[path] = device
            added.append(device.name)
        else:
            try:
                device.close()  # not a keyboard; don't hold it open
            except OSError:
                pass
    return added, removed


def run_listener(ptt_code, sender, list_devices=evdev.list_devices,
                 opener=evdev.InputDevice, poll_interval=POLL_INTERVAL,
                 selector=_select.select):
    """Watch all PTT-capable keyboards, re-scanning every `poll_interval` seconds
    so keyboards docked after startup are picked up automatically. Blocks forever.
    """
    devices: dict = {}
    reconcile_devices(devices, ptt_code, list_devices, opener)
    while True:
        fd_map = {d.fd: (path, d) for path, d in devices.items()}
        readable, _, _ = selector(list(fd_map), [], [], poll_interval)
        for fd in readable:
            path, device = fd_map[fd]
            try:
                dispatch_events(device.read(), ptt_code, sender)
            except OSError:
                # Device yanked between select() and read(): drop it now; the
                # reconcile below also handles the steady-state case.
                devices.pop(path, None)
                try:
                    device.close()
                except OSError:
                    pass
        added, removed = reconcile_devices(devices, ptt_code, list_devices, opener)
        for name in added:
            print(f"dictate-ptt: keyboard connected: {name}", file=sys.stderr)
        for name in removed:
            print(f"dictate-ptt: keyboard disconnected: {name}", file=sys.stderr)


def main() -> None:
    config = load_config()
    ptt_code = key_name_to_code(config.ptt_key)
    devices: dict = {}
    reconcile_devices(devices, ptt_code)
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
    names = ", ".join(d.name for d in devices.values())
    print(f"dictate-ptt: listening on {names} (hotplug-aware)", file=sys.stderr)
    run_listener(ptt_code, send_command)
