"""Domain model for a single Wikipedia change, plus parsing from the raw stream.

The Wikimedia `recentchange` stream carries many event types (edits, page
creations, log entries, categorisation changes) across every Wikimedia
project. We normalise only what the dashboard needs and drop the rest early,
so everything downstream works with one small, typed shape.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

# Edits and page creations are what "editing activity" means to a reader.
# Log events (blocks, moves, uploads) and categorize events are noise here.
TRACKED_TYPES = frozenset({"edit", "new"})


class Edit(BaseModel):
    id: int
    wiki: str  # e.g. "enwiki"
    server_name: str  # e.g. "en.wikipedia.org"
    title: str
    user: str
    bot: bool
    anonymous: bool  # IP editor or temporary account
    type: Literal["edit", "new"]
    namespace: int
    comment: str
    minor: bool
    timestamp: int  # unix seconds, as reported by Wikimedia
    length_old: int | None
    length_new: int | None
    revision_old: int | None
    revision_new: int | None

    @property
    def byte_delta(self) -> int:
        return (self.length_new or 0) - (self.length_old or 0)

    @property
    def page_url(self) -> str:
        return f"https://{self.server_name}/wiki/{self.title.replace(' ', '_')}"

    @property
    def diff_url(self) -> str | None:
        if self.revision_new is None:
            return None
        url = f"https://{self.server_name}/w/index.php?diff={self.revision_new}"
        if self.revision_old:
            url += f"&oldid={self.revision_old}"
        return url

    def to_wire(self) -> dict[str, Any]:
        """Shape sent to the browser (kept flat and small on purpose)."""
        return {
            "id": self.id,
            "wiki": self.wiki,
            "title": self.title,
            "user": self.user,
            "bot": self.bot,
            "anonymous": self.anonymous,
            "type": self.type,
            "comment": self.comment,
            "minor": self.minor,
            "timestamp": self.timestamp,
            "byte_delta": self.byte_delta,
            "page_url": self.page_url,
            "diff_url": self.diff_url,
        }


def is_anonymous(user: str) -> bool:
    """IP editors, plus temporary accounts (Wikimedia names these `~YYYY-...`)."""
    if user.startswith("~"):
        return True
    try:
        ipaddress.ip_address(user)
    except ValueError:
        return False
    return True


def parse_event(raw: dict[str, Any]) -> Edit | None:
    """Turn a raw stream event into an Edit, or None if we don't track it.

    Never raises: one malformed event must not take down the pipeline.
    """
    if raw.get("type") not in TRACKED_TYPES:
        return None
    # Wikimedia sends synthetic "canary" events to check the stream is alive.
    if raw.get("meta", {}).get("domain") == "canary":
        return None

    length = raw.get("length") or {}
    revision = raw.get("revision") or {}
    user = raw.get("user") or ""
    try:
        return Edit(
            id=raw["id"],
            wiki=raw["wiki"],
            server_name=raw["server_name"],
            title=raw["title"],
            user=user,
            bot=bool(raw.get("bot", False)),
            anonymous=is_anonymous(user),
            type=raw["type"],
            namespace=raw.get("namespace", 0),
            comment=raw.get("comment") or "",
            minor=bool(raw.get("minor", False)),
            timestamp=raw["timestamp"],
            length_old=length.get("old"),
            length_new=length.get("new"),
            revision_old=revision.get("old"),
            revision_new=revision.get("new"),
        )
    except (KeyError, TypeError, ValidationError):
        return None
