import subprocess

import pytest

from dictate.inject import _command, inject


def test_command_shapes():
    assert _command("wtype", "hi") == ["wtype", "hi"]
    assert _command("ydotool", "hi") == ["ydotool", "type", "hi"]
    assert _command("clipboard", "hi") == ["wl-copy", "hi"]


def test_falls_back_on_failure():
    tried = []

    def runner(cmd, **kwargs):
        tried.append(cmd[0])
        if cmd[0] == "wtype":
            raise FileNotFoundError("no wtype")
        return subprocess.CompletedProcess(cmd, 0)

    used = inject("hello", method="wtype", runner=runner)
    assert used == "ydotool"
    assert tried == ["wtype", "ydotool"]


def test_raises_when_all_fail():
    def runner(cmd, **kwargs):
        raise FileNotFoundError("nope")

    with pytest.raises(RuntimeError):
        inject("hello", method="wtype", runner=runner)
