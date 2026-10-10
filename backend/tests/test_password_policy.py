import pytest

from app.schemas import password_rule_failures


@pytest.mark.parametrize("pw", ["Abcdef1!", "Zz9$aaaa", "Hello.World7", "Sup3r*Safe?", "Ab1#xxxx"])
def test_accepts_valid_passwords(pw):
    assert password_rule_failures(pw) == []


@pytest.mark.parametrize("pw,missing", [
    ("Abc1!", "at least 8"),        # too short
    ("abcdefg1!", "capital"),       # no capital
    ("Abcdefgh!", "number"),        # no digit
    ("Abcdefg12", "special"),       # no special
    ("Abcdefg1-", "special"),       # '-' is not one of ! @ # $ * . ?
])
def test_rejects_with_reason(pw, missing):
    assert any(missing in f for f in password_rule_failures(pw))
