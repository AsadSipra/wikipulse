from typing import Any

from app.llm import LLMError
from app.models import Edit


class FakeLLM:
    """Returns queued replies in order; an Exception in the queue is raised."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.prompts.append((system, user))
        if not self.replies:
            raise LLMError("no reply queued")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def aclose(self) -> None:
        pass


def make_edit(**overrides: Any) -> Edit:
    fields: dict[str, Any] = dict(
        id=1, wiki="enwiki", server_name="en.wikipedia.org", title="Lahore", user="Alice",
        bot=False, anonymous=False, type="edit", namespace=0, comment="copyedit", minor=False,
        timestamp=0, length_old=5000, length_new=5100, revision_old=10, revision_new=11,
    )
    fields.update(overrides)
    return Edit(**fields)
