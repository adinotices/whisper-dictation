import collections

import evdev

from dictate.ptt import (
    dispatch_events,
    event_to_command,
    key_name_to_code,
    select_keyboards,
)

FakeEvent = collections.namedtuple("FakeEvent", "type code value")


def test_event_to_command_maps_down_up_repeat():
    code = evdev.ecodes.KEY_RIGHTCTRL
    assert event_to_command(code, 1, code) == "start"
    assert event_to_command(code, 0, code) == "stop"
    assert event_to_command(code, 2, code) is None  # auto-repeat ignored


def test_event_to_command_ignores_other_keys():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    other = evdev.ecodes.KEY_A
    assert event_to_command(other, 1, ptt) is None
    assert event_to_command(other, 0, ptt) is None


def test_key_name_to_code_known_and_unknown():
    assert key_name_to_code("rightctrl") == evdev.ecodes.KEY_RIGHTCTRL
    assert key_name_to_code("RightAlt") == evdev.ecodes.KEY_RIGHTALT
    # unknown falls back to right ctrl
    assert key_name_to_code("nonsense") == evdev.ecodes.KEY_RIGHTCTRL


def test_dispatch_events_sends_mapped_commands():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    syn = evdev.ecodes.EV_SYN
    key = evdev.ecodes.EV_KEY
    events = [
        FakeEvent(key, ptt, 1),                  # down -> start
        FakeEvent(key, ptt, 2),                  # repeat -> nothing
        FakeEvent(syn, 0, 0),                    # non-key -> nothing
        FakeEvent(key, evdev.ecodes.KEY_A, 1),   # other key -> nothing
        FakeEvent(key, ptt, 0),                  # up -> stop
    ]
    sent = []
    dispatch_events(events, ptt, sent.append)
    assert sent == ["start", "stop"]


def test_dispatch_events_swallows_sender_oserror():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    events = [FakeEvent(evdev.ecodes.EV_KEY, ptt, 1)]

    def boom(cmd):
        raise OSError("daemon down")

    dispatch_events(events, ptt, boom)  # must not raise


class FakeDev:
    def __init__(self, keys):
        self._keys = keys

    def capabilities(self):
        return {evdev.ecodes.EV_KEY: self._keys}


def test_select_keyboards_picks_devices_with_ptt_key():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    devs = {
        "/dev/input/event0": FakeDev([ptt, evdev.ecodes.KEY_A]),  # keyboard
        "/dev/input/event1": FakeDev([evdev.ecodes.BTN_LEFT]),    # mouse
    }
    result = select_keyboards(ptt, list(devs), opener=lambda p: devs[p])
    assert len(result) == 1
    assert result[0] is devs["/dev/input/event0"]


def test_select_keyboards_skips_unopenable_devices():
    ptt = evdev.ecodes.KEY_RIGHTCTRL

    def opener(path):
        raise PermissionError("no access")

    assert select_keyboards(ptt, ["/dev/input/event0"], opener=opener) == []
