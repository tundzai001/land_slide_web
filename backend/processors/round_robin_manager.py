"""Compatibility alias for the GNSS adjustment round-robin implementation.

New code should import :mod:`processors.gnss_adjustment.round_robin` directly.
"""
import sys

from .gnss_adjustment import round_robin as _implementation

sys.modules[__name__] = _implementation
