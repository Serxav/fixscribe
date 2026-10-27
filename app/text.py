"""Small English text helpers shared by the stages (one copy of each rule)."""

ARTICLES = frozenset({"a", "an", "the"})

_ES_ENDINGS = ("s", "x", "z", "ch", "sh")


def plural(noun: str, count: int = 2) -> str:
    """'screw' -> 'screws', 'glass' -> 'glasses', 'hose clamp' -> 'hose clamps'.

    The last word is pluralized; `count == 1` keeps the singular.
    """
    if count == 1 or not noun:
        return noun
    if noun.endswith(_ES_ENDINGS):
        return noun + "es"
    if noun.endswith("y") and len(noun) > 1 and noun[-2] not in "aeiou":
        return noun[:-1] + "ies"
    return noun + "s"


def drop_article(text: str) -> str:
    """Remove one leading 'a', 'an' or 'the'."""
    words = text.split()
    if words and words[0].lower() in ARTICLES:
        words = words[1:]
    return " ".join(words)
