"""Format-based PII detection shared by contracts and dataset records."""

import re

PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?![\dXx])"),
)


def contains_pii(text: str) -> bool:
    """Return True when the text matches any known real-PII pattern."""
    return any(pattern.search(text) for pattern in PII_PATTERNS)
