"""Shared GNSS classification-to-risk mapping."""


def map_gnss_daily_risk(classification: str) -> str:
    """Map the velocity classification emitted by the analyzer to API risk levels."""

    normalized = str(classification or "").upper()
    if any(label in normalized for label in ("EXTREMELY RAPID", "VERY RAPID", "RAPID")):
        return "CRITICAL"
    if "MODERATE" in normalized:
        return "HIGH"
    if "SLOW" in normalized:
        return "MEDIUM"
    return "LOW"
