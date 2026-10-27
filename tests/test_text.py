import pytest

from app.text import drop_article, plural


@pytest.mark.parametrize(
    ("noun", "expected"),
    [
        ("screw", "screws"),
        ("glass", "glasses"),
        ("hose clamp", "hose clamps"),
        ("compression nut", "compression nuts"),
        ("battery", "batteries"),
        ("key", "keys"),
        ("box", "boxes"),
        ("latch", "latches"),
    ],
)
def test_plural(noun, expected):
    assert plural(noun) == expected


def test_plural_of_one_and_empty():
    assert plural("bolt", 1) == "bolt"
    assert plural("") == ""


def test_drop_article():
    assert drop_article("The back cover") == "back cover"
    assert drop_article("an o-ring") == "o-ring"
    assert drop_article("theme panel") == "theme panel"
