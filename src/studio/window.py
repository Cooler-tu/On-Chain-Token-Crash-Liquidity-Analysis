"""Block-window helpers for the local analysis studio."""
from __future__ import annotations

BLOCKS_PER_DAY = 7_200  # ~12s post-merge blocks
ALLOWED_DAYS = (7, 30)


def span_blocks(days: int) -> int:
    if int(days) not in ALLOWED_DAYS:
        raise ValueError("duration must be 7 or 30 days")
    return int(days) * BLOCKS_PER_DAY


def window_from_start(from_block: int, days: int) -> tuple[int, int]:
    """Return [from_block, from_block + span - 1]."""
    start = int(from_block)
    if start <= 0:
        raise ValueError("from_block must be a positive integer")
    span = span_blocks(days)
    return start, start + span - 1


def window_ending_at(to_block: int, days: int) -> tuple[int, int]:
    """Return a duration window that ends at ``to_block`` (inclusive)."""
    end = int(to_block)
    if end <= 0:
        raise ValueError("to_block must be a positive integer")
    span = span_blocks(days)
    start = max(1, end - span + 1)
    return start, end


def chart_span_for_days(days: int) -> str:
    return "month" if int(days) >= 30 else "week"


def output_dir_name(token: str, days: int, from_block: int) -> str:
    raw = (token or "").strip()
    if raw.lower().startswith("0x") and len(raw) >= 10:
        slug = raw[:10]
    else:
        slug = raw
    slug = "".join(ch if ch.isalnum() else "-" for ch in slug).strip("-").lower()
    slug = slug[:24] or "token"
    return "output-{}-{}d-{}".format(slug, int(days), int(from_block))
