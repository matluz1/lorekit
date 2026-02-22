"""Tests for rolldice.py."""


# -- Happy Path --

def test_d20_basic(run):
    r = run("rolldice.py", "d20")
    assert r.returncode == 0
    assert "ROLLS:" in r.stdout
    assert "KEPT:" in r.stdout
    assert "MODIFIER:" in r.stdout
    assert "TOTAL:" in r.stdout


def test_d20_range(run):
    for _ in range(100):
        r = run("rolldice.py", "d20")
        for line in r.stdout.splitlines():
            if line.startswith("TOTAL:"):
                total = int(line.split(":")[1].strip())
                assert 1 <= total <= 20, f"d20 total {total} out of range 1-20"


def test_3d6_shows_three_rolls(run):
    r = run("rolldice.py", "3d6")
    for line in r.stdout.splitlines():
        if line.startswith("ROLLS:"):
            rolls = line.split(":")[1].strip()
            assert rolls.count(",") == 2, "3d6 should produce 3 rolls"


def test_modifier_plus(run):
    r = run("rolldice.py", "1d4+5")
    assert "MODIFIER: +5" in r.stdout


def test_modifier_minus(run):
    r = run("rolldice.py", "1d4-2")
    assert "MODIFIER: -2" in r.stdout


def test_zero_modifier(run):
    r = run("rolldice.py", "d20")
    assert "MODIFIER: +0" in r.stdout


def test_keep_highest(run):
    r = run("rolldice.py", "4d6kh3")
    for line in r.stdout.splitlines():
        if line.startswith("KEPT:"):
            kept = line.split(":")[1].strip()
            assert kept.count(",") == 2, "4d6kh3 should keep 3"


# -- Error Cases --

def test_no_args_fails(run):
    r = run("rolldice.py")
    assert r.returncode == 1


def test_invalid_expression_fails(run):
    r = run("rolldice.py", "abc")
    assert r.returncode == 1
    assert "ERROR" in r.stderr


def test_zero_sides_fails(run):
    r = run("rolldice.py", "1d0")
    assert r.returncode == 1


def test_one_side_fails(run):
    r = run("rolldice.py", "1d1")
    assert r.returncode == 1


def test_keep_more_than_rolled_fails(run):
    r = run("rolldice.py", "2d6kh5")
    assert r.returncode == 1


def test_two_args_fails(run):
    r = run("rolldice.py", "d20", "d6")
    assert r.returncode == 1


# -- Edge Cases --

def test_d100_range(run):
    for _ in range(50):
        r = run("rolldice.py", "d100")
        for line in r.stdout.splitlines():
            if line.startswith("TOTAL:"):
                total = int(line.split(":")[1].strip())
                assert 1 <= total <= 100, f"d100 total {total} out of range"


def test_case_insensitive(run):
    r = run("rolldice.py", "D20")
    assert r.returncode == 0
    assert "TOTAL:" in r.stdout


def test_keep_one(run):
    r = run("rolldice.py", "3d6kh1")
    for line in r.stdout.splitlines():
        if line.startswith("KEPT:"):
            kept = line.split(":")[1].strip()
            assert kept.count(",") == 0, "kh1 keeps 1"
