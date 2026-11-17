from seshka.format import format_bytes, format_limit, human_age


def test_format_bytes():
    assert format_bytes(0) == "–"
    assert format_bytes(500) == "<1 MB"
    assert format_bytes(5 * 1024 * 1024) == "5 MB"
    assert format_bytes(int(1.5 * 1024 * 1024 * 1024)) == "1.5 GB"


def test_human_age():
    assert human_age(12) == "12s"
    assert human_age(120) == "2m"
    assert human_age(7200) == "2h"
    assert human_age(90000) == "1d"


def test_format_limit():
    assert format_limit(45) == "45 min"
    assert format_limit(120) == "2 h"
    assert format_limit(150) == "2 h 30 min"
