from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List


@dataclass(frozen=True)
class ChangelogEntry:
    version: str
    date: str
    author: str
    description: str


_CHANGELOG: List[ChangelogEntry] = [
    ChangelogEntry(
        version="1.0.0",
        date="2026-02-09",
        author="unknown",
        description="Initial PySide6 GUI app with batch TPY->CSV conversion, JSON config, worker thread, and chunked output.",
    ),
]


def add_changelog_entry(version: str, date_: str, author: str, description: str) -> None:
    """
    Add a changelog entry in-memory.

    Note: This module is kept simple on purpose. If you want persistent changelog files,
    we can extend this to write to a CHANGELOG.md.
    """
    _CHANGELOG.append(
        ChangelogEntry(
            version=version,
            date=date_,
            author=author,
            description=description,
        )
    )


def get_changelog() -> List[ChangelogEntry]:
    return list(_CHANGELOG)


def get_latest_version() -> str:
    return _CHANGELOG[-1].version if _CHANGELOG else "0.0.0"


def get_today_iso() -> str:
    return date.today().isoformat()
