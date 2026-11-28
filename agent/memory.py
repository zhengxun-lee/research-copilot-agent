import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Memory:
    """Sliding-window conversation store for the OpenAI chat-completion format.

    Parameters
    ----------
    system_prompt:
        The system-level instruction placed at the start of every request.
    max_turns:
        Maximum number of user/assistant turn *pairs* to retain.  Older turns
        are evicted when the limit is exceeded.  The system prompt is always
        preserved.
    """

    def __init__(self, system_prompt: str, max_turns: int = 10):
        self.max_turns = max(1, max_turns)
        self.messages = [
            {"role": "system", "content": system_prompt}
        ]

    def add_user_message(self, content: str):
        """Append a ``role: "user"`` message and enforce the turn limit.

        If the previous message is also a ``user`` message (e.g. left over
        from a failed LLM call that never produced an assistant response),
        it is silently dropped to avoid consecutive user messages, which
        violate the chat completion format.
        """
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()
        self.messages.append({
            "role": "user",
            "content": content
        })
        self._enforce_limit()

    def pop_last_user_message(self) -> bool:
        """Remove the most recent user message **and all messages that follow
        it** — used to roll back a failed :meth:`Agent.run` so the next
        attempt doesn't see an unanswered user turn or orphaned assistant /
        tool messages.

        Returns ``True`` if a user message was removed, ``False`` otherwise.
        """
        if len(self.messages) <= 1:  # never pop the system prompt
            return False
        for index in range(len(self.messages) - 1, 0, -1):
            if self.messages[index]["role"] == "user":
                # Remove the user message and everything after it (assistant
                # tool-call messages, tool results, etc.) since those are all
                # part of the same failed turn.
                del self.messages[index:]
                return True
        return False

    def add_assistant_message(self, content: str = "", tool_calls: Optional[list] = None):
        """Append an ``role: "assistant"`` message, optionally with tool calls."""
        msg = {
            "role": "assistant",
            "content": content or ""
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self._enforce_limit()

    def add_tool_message(self, tool_call_id: str, content: str):
        """Append a ``role: "tool"`` message linked to *tool_call_id*."""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })
        self._enforce_limit()

    def append_to_last_assistant(self, extra_content: str):
        """Append *extra_content* to the most recent assistant message."""
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                msg["content"] = (msg.get("content", "") + "\n\n" + extra_content).strip()
                return
        logger.warning("append_to_last_assistant called but no assistant message exists")

    def _enforce_limit(self):
        system = self.messages[0]
        conversation = self.messages[1:]

        turns = []
        current_turn = []
        for msg in conversation:
            if msg["role"] == "user":
                if current_turn:
                    turns.append(current_turn)
                current_turn = [msg]
            else:
                current_turn.append(msg)

        if current_turn:
            turns.append(current_turn)

        self.messages = [system] + [
            msg for turn in turns[-self.max_turns:] for msg in turn
        ]

    def rollback_to(self, count: int) -> None:
        """Remove all messages from index *count* onwards.

        Used by :class:`~agent.core.Agent` to cleanly roll back a failed turn
        without directly mutating the internal message list.  *count* is
        typically the ``len(self.messages)`` value snapshotted before the
        user message was added.
        """
        del self.messages[count:]

    def get_messages(self) -> list:
        """Return a shallow copy of the current conversation history."""
        return list(self.messages)
