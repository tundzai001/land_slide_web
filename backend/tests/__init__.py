"""Backend test package with stable import paths from any test runner."""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = BACKEND_DIR.parent
for directory in (BACKEND_DIR, REPOSITORY_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
