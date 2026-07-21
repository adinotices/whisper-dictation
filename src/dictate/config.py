import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "dictate" / "config.toml"


@dataclass
class Config:
    model: str = "small.en"
    language: str = "en"
    mic_source: str | None = None
    inject_method: str | None = None
    beep: bool = False
    ptt_key: str = "rightctrl"
    smart_spacing: bool = True
    smart_spacing_reset_seconds: int = 30
    voice_commands: bool = True


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    known = {f.name for f in fields(Config)}
    filtered = {k: v for k, v in data.items() if k in known}
    return Config(**filtered)
