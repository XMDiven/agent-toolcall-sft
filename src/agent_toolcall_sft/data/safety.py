"""Format-based PII detection shared by contracts and dataset records."""

import re

PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"1[3-9]\d{9}"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"\b\d{17}[\dXx]\b"),
)


def contains_pii(text: str) -> bool:
    """Return True when the text matches any known real-PII pattern."""
    return any(pattern.search(text) for pattern in PII_PATTERNS)
