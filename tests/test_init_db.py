"""Tests for init_db.py."""

import os
import sqlite3
import subprocess
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")


def test_creates_database_file(tmp_path):
    db = str(tmp_path / "game.db")
    env = os.environ.copy()
    env["LOREKIT_DB_DIR"] = str(tmp_path)
    env["LOREKIT_DB"] = db
    subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, "init_db.py")], env=env, check=True, capture_output=True)
    assert os.path.isfile(db)


def test_creates_data_directory(tmp_path):
    data_dir = str(tmp_path / "subdir")
    db = str(tmp_path / "subdir" / "game.db")
    env = os.environ.copy()
    env["LOREKIT_DB_DIR"] = data_dir
    env["LOREKIT_DB"] = db
    subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, "init_db.py")], env=env, check=True, capture_output=True)
    assert os.path.isdir(data_dir)


def test_creates_all_nine_tables(db_path):
    conn = sqlite3.connect(db_path)
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    conn.close()
    expected = ["character_abilities", "character_attributes", "character_inventory", "characters", "dialogues", "journal", "regions", "session_meta", "sessions"]
    for t in expected:
        assert t in tables, f"table {t} missing"


def test_idempotent_reinit(db_path):
    env = os.environ.copy()
    env["LOREKIT_DB"] = db_path
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, "init_db.py")], env=env, capture_output=True, text=True)
    assert r.returncode == 0
    assert "Database initialized" in r.stdout


def test_characters_has_type_column(db_path):
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(characters)").fetchall()]
    conn.close()
    assert "type" in cols


def test_characters_has_region_id_column(db_path):
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(characters)").fetchall()]
    conn.close()
    assert "region_id" in cols
