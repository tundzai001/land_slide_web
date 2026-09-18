"""Helpers for keeping long JSON payloads intact in tabular exports."""

from __future__ import annotations

import json
from typing import Any


def excel_chunks(value: Any, chunk_count: int = 8) -> list[str | None]:
    """Preserve large JSON/payload text across cells without truncation."""
    if value is None:
        return [None] * chunk_count
    text_value = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, default=str
    )
    chunk_size = 32760  # Excel cell limit is 32767 characters.
    chunks = [
        text_value[index:index + chunk_size]
        for index in range(0, len(text_value), chunk_size)
    ]
    if len(chunks) > chunk_count:
        raise ValueError(
            f"Export cell content is too large ({len(text_value)} characters)"
        )
    return chunks + [None] * (chunk_count - len(chunks))
