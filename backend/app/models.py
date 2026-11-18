"""Domain model for a single Wikipedia change, plus parsing from the raw stream.

The Wikimedia `recentchange` stream carries many event types (edits, page
creations, log entries, categorisation changes) across every Wikimedia
project. We normalise only what the dashboard needs and drop the rest early,
so everything downstream works with one small, typed shape.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Literal
from urllib.parse import quote

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
    def byte_delta(self) -> int | None:
        """Size change in bytes, or None when the stream didn't report it.

        Unknown is not zero: treating a missing size as 0 would make an
        ordinary edit look like page blanking."""
        if self.length_new is None:
            return None
        if self.length_old is None:
            return self.length_new if self.type == "new" else None
        return self.length_new - self.length_old

    @property
    def page_url(self) -> str:
        return page_url(self.server_name, self.title)

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


def page_url(server_name: str, title: str) -> str:
    """Article URL. Titles may contain ?, # or %, which must be escaped or the
    browser treats them as a query string or fragment."""
    path = quote(title.replace(" ", "_"), safe="/:@!$()*,;'~")
    return f"https://{server_name}/wiki/{path}"


def is_wikipedia(server_name: str) -> bool:
    """True for Wikipedia language editions (en.wikipedia.org, ur.wikipedia.org, ...).

    Excludes sister projects. Wikidata alone is a large share of the stream,
    mostly bulk edits from tools like QuickStatements that aren't flagged as
    bots, and its items (Q141401630) mean nothing to a news reader."""
    return server_name.endswith(".wikipedia.org")


def is_anonymous(user: str) -> bool:
    """IP editors, plus temporary accounts (Wikimedia names these `~YYYY-...`)."""
    if user.startswith("~"):
        return True
    try:
        ipaddress.ip_address(user)
    except ValueError:
        return False
    return True


def parse_event(raw: Any) -> Edit | None:
    """Turn a raw stream event into an Edit, or None if we don't track it or
    the event is malformed.

    Every field is shape-checked before use, so one bad event is skipped
    instead of stopping ingestion. Booleans must be real booleans: a string
    like "false" is not silently read as True.
    """
    if not isinstance(raw, dict) or raw.get("type") not in TRACKED_TYPES:
        return None
    meta = raw.get("meta")
    # Wikimedia sends synthetic "canary" events to check the stream is alive.
    if isinstance(meta, dict) and meta.get("domain") == "canary":
        return None

    length = _dict_or_empty(raw.get("length"))
    revision = _dict_or_empty(raw.get("revision"))
    user = raw.get("user")
    comment = raw.get("comment")
    if length is None or revision is None or not isinstance(user, str):
        return None
    if comment is not None and not isinstance(comment, str):
        return None
    try:
        return Edit.model_validate(
            {
                "id": raw.get("id"),
                "wiki": raw.get("wiki"),
                "server_name": raw.get("server_name"),
                "title": raw.get("title"),
                "user": user,
                "bot": raw.get("bot", False),
                "anonymous": is_anonymous(user),
                "type": raw["type"],
                "namespace": raw.get("namespace", 0),
                "comment": comment or "",
                "minor": raw.get("minor", False),
                "timestamp": raw.get("timestamp"),
                "length_old": length.get("old"),
                "length_new": length.get("new"),
                "revision_old": revision.get("old"),
                "revision_new": revision.get("new"),
            },
            strict=True,  # no "false" -> True, no "12" -> 12
        )
    except ValidationError:
        return None


def _dict_or_empty(value: Any) -> dict[str, Any] | None:
    """Optional nested object: missing/null becomes {}, any other non-object is malformed."""
    if value is None:
        return {}
    return value if isinstance(value, dict) else None
