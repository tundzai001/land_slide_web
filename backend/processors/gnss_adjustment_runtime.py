"""Compatibility alias for :mod:`processors.gnss_adjustment.runtime`."""
import sys

from .gnss_adjustment import runtime as _implementation

sys.modules[__name__] = _implementation
