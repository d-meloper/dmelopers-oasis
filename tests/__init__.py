"""Offline contracts and real disposable Git fixtures."""

from pathlib import Path
import tempfile

from oasis_harness.common import contained

def fixture_project(checkout):
    """Retained snapshots share their owning checkout's short scratch path."""
    checkout = Path(checkout).resolve()
    if (checkout / ".git").exists():
        return checkout
    for ancestor in checkout.parents:
        if checkout.is_relative_to(ancestor / ".oasis/local") and (ancestor / ".git").exists():
            return ancestor
    return checkout


# Every TemporaryDirectory still owns and removes only its unique fixture.
# Avoid nesting scratch inside snapshots: native Windows tools need short paths.
FIXTURE_ROOT = contained(fixture_project(Path(__file__).resolve().parents[1]), ".oasis/local/tmp")
FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(FIXTURE_ROOT)
