"""Context engine with token budget management and message compaction.

The ContextEngine fits a list of ChatMessages into a token budget by:
  1. Always including all system messages (highest priority).
  2. Always including the most recent user/assistant turns.
  3. Summarising older messages when the budget would otherwise be exceeded.

Token counting uses a lightweight word-based estimator (words * 1.3) so that
the engine works fully offline without a separate tokenizer dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from bmt_ai_os.providers.base import ChatMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TOKEN_BUDGET = 4096
_WORDS_PER_TOKEN_RATIO = 1.3
# Reserve tokens for the compaction summary message itself
_SUMMARY_TOKEN_RESERVE = 200


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate token count for *text* using word count * 1.3.

    This is intentionally conservative (tends to over-estimate) to avoid
    exceeding real model context windows.
    """
    if not text:
        return 0
    words = len(text.split())
    if words == 0:
        return 0
    return max(1, round(words * _WORDS_PER_TOKEN_RATIO))


def message_tokens(msg: ChatMessage) -> int:
    """Estimate total tokens for a single ChatMessage (role + content)."""
    # ~4 tokens overhead per message (role label + formatting)
    return estimate_tokens(msg.content) + 4


# ---------------------------------------------------------------------------
# Compaction helpers
# ---------------------------------------------------------------------------


@dataclass
class CompactionResult:
    """Result of a compaction pass."""

    messages: list[ChatMessage]
    original_count: int
    compacted_count: int
    total_tokens: int
    was_compacted: bool


def _summarise_messages(messages: list[ChatMessage]) -> str:
    """Create a concise summary of *messages* for inclusion in context.

    This default implementation produces a structured digest.  In production
    you would wire a real LLM call here; the interface accepts an optional
    ``summariser`` callable so callers can inject one.
    """
    if not messages:
        return ""

    parts: list[str] = ["[Conversation summary]"]
    for msg in messages:
        role_label = msg.role.upper()
        # Truncate long messages to keep the summary compact
        snippet = msg.content[:200].replace("\n", " ")
        if len(msg.content) > 200:
            snippet += "..."
        parts.append(f"{role_label}: {snippet}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ContextEngine
# ---------------------------------------------------------------------------


class ContextEngine:
    """Manages a sliding-window conversation context within a token budget.

    Priority order when compaction is needed (highest → lowest):
      1. System messages  — always retained verbatim
      2. Recent messages  — kept as-is until budget allows
      3. Older messages   — replaced by a single summary message

    Parameters
    ----------
    token_budget:
        Maximum number of tokens the returned context may consume.
    recent_turns:
        Number of most-recent non-system message pairs to always retain
        verbatim before compaction kicks in.
    summariser:
        Optional callable ``(messages: list[ChatMessage]) -> str`` used to
        generate a summary of older messages.  Defaults to the built-in
        structured digest.
    """

    def __init__(
        self,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        recent_turns: int = 6,
        summariser: Callable[[list[ChatMessage]], str] | None = None,
    ) -> None:
        if token_budget < _SUMMARY_TOKEN_RESERVE + 10:
            raise ValueError(
                f"token_budget must be > {_SUMMARY_TOKEN_RESERVE + 10}; got {token_budget}"
            )
        self._budget = token_budget
        self._recent_turns = recent_turns
        self._summariser = summariser or _summarise_messages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def token_budget(self) -> int:
        """The configured maximum token budget."""
        return self._budget

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Return the total estimated token count for *messages*."""
        return sum(message_tokens(m) for m in messages)

    def build_context(
        self,
        messages: list[ChatMessage],
        max_tokens: int | None = None,
    ) -> list[ChatMessage]:
        """Return a pruned list of messages that fits within the token budget.

        Parameters
        ----------
        messages:
            Full conversation history in chronological order.
        max_tokens:
            Override the instance's token_budget for this call.

        Returns
        -------
        list[ChatMessage]
            A subset (or full set) of messages that fits within the budget,
            with older non-system messages replaced by a summary when needed.
        """
        budget = max_tokens if max_tokens is not None else self._budget

        if not messages:
            return []

        # Separate system messages from the rest
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        system_tokens = sum(message_tokens(m) for m in system_msgs)
        remaining_budget = budget - system_tokens

        if remaining_budget <= 0:
            # System messages alone exceed the budget — return them truncated
            logger.warning(
                "System messages (%d tokens) exceed the token budget (%d). "
                "Returning system messages only.",
                system_tokens,
                budget,
            )
            return system_msgs

        # Check whether all messages fit without compaction
        all_tokens = sum(message_tokens(m) for m in non_system)
        if all_tokens <= remaining_budget:
            return list(messages)

        # Apply compaction ---------------------------------------------------
        result = self._compact(non_system, remaining_budget)
        final_messages = system_msgs + result.messages

        logger.debug(
            "Context compaction: %d → %d messages, %d tokens (budget: %d)",
            result.original_count,
            result.compacted_count,
            result.total_tokens,
            budget,
        )

        return final_messages

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compact(self, messages: list[ChatMessage], budget: int) -> CompactionResult:
        """Compact *messages* so they fit within *budget* tokens.

        Strategy:
          - Keep the *recent_turns* most-recent messages verbatim.
          - Summarise older messages into a single ``system`` message.
          - If the recent messages alone exceed the budget, trim from the
            oldest recent message until they fit.
        """
        original_count = len(messages)

        # Split into recent and older
        recent_start = max(0, len(messages) - self._recent_turns)
        older = messages[:recent_start]
        recent = messages[recent_start:]

        # Budget allocation:
        #   summary_slot: tokens reserved for the compaction summary message
        summary_slot = min(_SUMMARY_TOKEN_RESERVE, budget // 3)

        # Build a summary of older messages; truncate if it overflows its slot
        summary_text = ""
        if older:
            raw_summary = self._summariser(older)
            # Truncate the summary text so that its token count fits in summary_slot
            words = raw_summary.split()
            max_words = max(1, int(summary_slot / _WORDS_PER_TOKEN_RATIO) - 4)
            if len(words) > max_words:
                raw_summary = " ".join(words[:max_words]) + "..."
            summary_text = raw_summary

        summary_tokens = (estimate_tokens(summary_text) + 4) if summary_text else 0
        recent_budget = budget - summary_tokens

        # Trim recent messages from the front if they still overflow
        recent_trimmed: list[ChatMessage] = list(recent)
        recent_token_total = sum(message_tokens(m) for m in recent_trimmed)

        while recent_token_total > recent_budget and recent_trimmed:
            dropped = recent_trimmed.pop(0)
            recent_token_total -= message_tokens(dropped)

        # Assemble final message list
        result_messages: list[ChatMessage] = []
        if summary_text:
            result_messages.append(ChatMessage(role="system", content=summary_text))
        result_messages.extend(recent_trimmed)

        total_tokens = sum(message_tokens(m) for m in result_messages)

        return CompactionResult(
            messages=result_messages,
            original_count=original_count,
            compacted_count=len(result_messages),
            total_tokens=total_tokens,
            was_compacted=len(older) > 0 or len(recent_trimmed) < len(recent),
        )
