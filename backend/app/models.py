"""The Edit model and parsing of raw stream events."""

from __future__ import annotations

import ipaddress
import time
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

# Log and categorize events are not editing activity.
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
    timestamp: int  # unix seconds
    length_old: int | None
    length_new: int | None
    revision_old: int | None
    revision_new: int | None

    @property
    def byte_delta(self) -> int | None:
        """Size change in bytes, or None if unknown (not 0, which would look like blanking)."""
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
        """Shape sent to the browser."""
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
    """Article URL, with ?, # and % in titles escaped."""
    path = quote(title.replace(" ", "_"), safe="/:@!$()*,;'~")
    return f"https://{server_name}/wiki/{path}"


def is_wikipedia(server_name: str) -> bool:
    """True for Wikipedia language editions; excludes Wikidata, Commons and other sister projects."""
    return server_name.endswith(".wikipedia.org")


def is_anonymous(user: str) -> bool:
    """IP editors and temporary accounts (`~YYYY-...`)."""
    if user.startswith("~"):
        return True
    try:
        ipaddress.ip_address(user)
    except ValueError:
        return False
    return True


# Larger than any seconds value until the year 5138, so it must be milliseconds.
_MS_THRESHOLD = 100_000_000_000


def normalize_timestamp(value: Any) -> int | None:
    """Unix seconds, converting milliseconds; None if not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = value / 1000 if value >= _MS_THRESHOLD else value
    return int(seconds)


def parse_event(raw: Any) -> Edit | None:
    """An Edit, or None for untracked or malformed events (never raises)."""
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
    raw_ts = raw.get("timestamp")
    timestamp = normalize_timestamp(raw_ts)
    if timestamp is None:
        if raw_ts is not None:
            return None
        # Missing: keep the edit; stats use arrival time anyway.
        timestamp = int(time.time())
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
                "timestamp": timestamp,
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
