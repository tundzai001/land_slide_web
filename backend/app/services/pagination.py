"""Small helpers for additive list pagination while preserving legacy arrays."""
from typing import Optional

from fastapi import HTTPException, Response


def normalize_page(offset: Optional[int], limit: Optional[int], *, max_limit: int = 500):
    normalized_offset = 0 if offset is None else int(offset)
    normalized_limit = None if limit is None else int(limit)
    if normalized_offset < 0:
        raise HTTPException(status_code=422, detail="offset must be greater than or equal to 0")
    if normalized_limit is not None and not 1 <= normalized_limit <= max_limit:
        raise HTTPException(status_code=422, detail=f"limit must be between 1 and {max_limit}")
    return normalized_offset, normalized_limit


def set_pagination_headers(
    response: Response,
    *,
    total: int,
    offset: int,
    limit: Optional[int],
):
    response.headers["X-Total-Count"] = str(max(0, int(total)))
    response.headers["X-Offset"] = str(max(0, int(offset)))
    response.headers["X-Limit"] = str(max(0, int(total if limit is None else limit)))


def slice_rows(rows, offset: int, limit: Optional[int]):
    return rows[offset:] if limit is None else rows[offset:offset + limit]
