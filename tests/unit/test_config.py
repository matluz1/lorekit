"""Tests for configuration loading."""

from pathlib import Path

from lorekit.config import LoreKitConfig, config_path, load_config


def test_default_config():
    cfg = LoreKitConfig()
    assert cfg.provider is None
    assert cfg.model is None
    assert cfg.port == 8765


def test_config_path_returns_path():
    p = config_path()
    assert isinstance(p, Path)
    assert p.name == "config.toml"
    assert "lorekit" in str(p)


def test_load_config_missing_file(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.provider is None
    assert cfg.model is None
    assert cfg.port == 8765


def test_load_config_full(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[agent]\nprovider = "claude"\nmodel = "opus"\n\n[server]\nport = 9000\n')
    cfg = load_config(p)
    assert cfg.provider == "claude"
    assert cfg.model == "opus"
    assert cfg.port == 9000


def test_load_config_partial(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[agent]\nprovider = "codex"\n')
    cfg = load_config(p)
    assert cfg.provider == "codex"
    assert cfg.model is None
    assert cfg.port == 8765
