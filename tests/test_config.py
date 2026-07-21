from pathlib import Path

from dictate.config import Config, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg == Config()
    assert cfg.model == "small.en"
    assert cfg.language == "en"
    assert cfg.mic_source is None


def test_reads_overrides(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "medium.en"\nbeep = true\nmic_source = "Anker"\n')
    cfg = load_config(p)
    assert cfg.model == "medium.en"
    assert cfg.beep is True
    assert cfg.mic_source == "Anker"


def test_ignores_unknown_keys(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "small.en"\nnonsense = 42\n')
    cfg = load_config(p)
    assert cfg.model == "small.en"
