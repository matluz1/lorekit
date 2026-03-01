"""Tests for dice rolling."""

from mcp_server import roll_dice


# -- Happy Path --


def test_d20_basic():
    result = roll_dice(expression="d20")
    assert "ROLLS:" in result
    assert "KEPT:" in result
    assert "MODIFIER:" in result
    assert "TOTAL:" in result


def test_d20_range():
    for _ in range(100):
        result = roll_dice(expression="d20")
        for line in result.splitlines():
            if line.startswith("TOTAL:"):
                total = int(line.split(":")[1].strip())
                assert 1 <= total <= 20, f"d20 total {total} out of range 1-20"


def test_3d6_shows_three_rolls():
    result = roll_dice(expression="3d6")
    for line in result.splitlines():
        if line.startswith("ROLLS:"):
            rolls = line.split(":")[1].strip()
            assert rolls.count(",") == 2, "3d6 should produce 3 rolls"


def test_modifier_plus():
    result = roll_dice(expression="1d4+5")
    assert "MODIFIER: +5" in result


def test_modifier_minus():
    result = roll_dice(expression="1d4-2")
    assert "MODIFIER: -2" in result


def test_zero_modifier():
    result = roll_dice(expression="d20")
    assert "MODIFIER: +0" in result


def test_keep_highest():
    result = roll_dice(expression="4d6kh3")
    for line in result.splitlines():
        if line.startswith("KEPT:"):
            kept = line.split(":")[1].strip()
            assert kept.count(",") == 2, "4d6kh3 should keep 3"


# -- Multiple Expressions --


def test_two_expressions():
    result = roll_dice(expression="d20 d6")
    assert "--- d20 ---" in result
    assert "--- d6 ---" in result


def test_multiple_expressions():
    result = roll_dice(expression="d20 2d6+3 4d6kh3")
    blocks = result.split("---")
    headers = [b.strip() for b in blocks if b.strip() in ("d20", "2d6+3", "4d6kh3")]
    assert len(headers) == 3
    assert result.count("TOTAL:") == 3


def test_single_expression_unchanged():
    result = roll_dice(expression="d20")
    assert "---" not in result
    assert result.startswith("ROLLS:")


# -- Error Cases --


def test_invalid_expression_fails():
    result = roll_dice(expression="abc")
    assert "ERROR" in result


def test_zero_sides_fails():
    result = roll_dice(expression="1d0")
    assert "ERROR" in result


def test_one_side_fails():
    result = roll_dice(expression="1d1")
    assert "ERROR" in result


def test_keep_more_than_rolled_fails():
    result = roll_dice(expression="2d6kh5")
    assert "ERROR" in result


# -- Edge Cases --


def test_d100_range():
    for _ in range(50):
        result = roll_dice(expression="d100")
        for line in result.splitlines():
            if line.startswith("TOTAL:"):
                total = int(line.split(":")[1].strip())
                assert 1 <= total <= 100, f"d100 total {total} out of range"


def test_case_insensitive():
    result = roll_dice(expression="D20")
    assert "TOTAL:" in result


def test_keep_one():
    result = roll_dice(expression="3d6kh1")
    for line in result.splitlines():
        if line.startswith("KEPT:"):
            kept = line.split(":")[1].strip()
            assert kept.count(",") == 0, "kh1 keeps 1"
