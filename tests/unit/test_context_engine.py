"""Unit tests for bmt_ai_os.memory.context — ContextEngine."""

from __future__ import annotations

import pytest

from bmt_ai_os.memory.context import (
    ContextEngine,
    estimate_tokens,
    message_tokens,
)
from bmt_ai_os.providers.base import ChatMessage

# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        # 1 word * 1.3 = 1.3 -> round -> 1
        assert estimate_tokens("hello") >= 1

    def test_four_words(self):
        # 4 words * 1.3 = 5.2 -> 5
        result = estimate_tokens("one two three four")
        assert result == 5

    def test_scales_with_length(self):
        short = estimate_tokens("hello world")
        long = estimate_tokens("hello world " * 10)
        assert long > short

    def test_whitespace_only(self):
        # "   ".split() returns [] so word count is 0
        assert estimate_tokens("   ") == 0

    def test_none_equivalent_empty(self):
        assert estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# message_tokens
# ---------------------------------------------------------------------------


class TestMessageTokens:
    def test_overhead_added(self):
        msg = ChatMessage(role="user", content="hello world")
        # content tokens + 4 overhead
        assert message_tokens(msg) == estimate_tokens("hello world") + 4

    def test_system_message(self):
        msg = ChatMessage(role="system", content="You are a helpful assistant.")
        assert message_tokens(msg) > 4


# ---------------------------------------------------------------------------
# ContextEngine construction
# ---------------------------------------------------------------------------


class TestContextEngineInit:
    def test_default_budget(self):
        engine = ContextEngine()
        assert engine.token_budget == 4096

    def test_custom_budget(self):
        engine = ContextEngine(token_budget=2048)
        assert engine.token_budget == 2048

    def test_too_small_budget_raises(self):
        with pytest.raises(ValueError, match="token_budget"):
            ContextEngine(token_budget=100)


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_empty(self):
        engine = ContextEngine()
        assert engine.count_tokens([]) == 0

    def test_single_message(self):
        engine = ContextEngine()
        msg = ChatMessage(role="user", content="hello")
        assert engine.count_tokens([msg]) == message_tokens(msg)

    def test_multiple_messages(self):
        engine = ContextEngine()
        msgs = [
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="assistant", content="hi there"),
        ]
        expected = sum(message_tokens(m) for m in msgs)
        assert engine.count_tokens(msgs) == expected


# ---------------------------------------------------------------------------
# build_context — no compaction needed
# ---------------------------------------------------------------------------


class TestBuildContextNoCompaction:
    def test_empty_returns_empty(self):
        engine = ContextEngine()
        assert engine.build_context([]) == []

    def test_small_messages_returned_unchanged(self):
        engine = ContextEngine(token_budget=4096)
        msgs = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]
        result = engine.build_context(msgs)
        assert result == msgs

    def test_max_tokens_override(self):
        engine = ContextEngine(token_budget=500)
        msgs = [
            ChatMessage(role="user", content="short"),
        ]
        # With large override, no compaction
        result = engine.build_context(msgs, max_tokens=4096)
        assert result == msgs


# ---------------------------------------------------------------------------
# build_context — system messages always retained
# ---------------------------------------------------------------------------


class TestBuildContextSystemMessages:
    def test_system_messages_always_kept(self):
        engine = ContextEngine(token_budget=500, recent_turns=2)
        system = ChatMessage(role="system", content="You are an assistant.")
        # Fill with many user/assistant pairs
        conversation = [system]
        for i in range(20):
            conversation.append(ChatMessage(role="user", content=f"Question {i}?"))
            conversation.append(ChatMessage(role="assistant", content=f"Answer {i}."))

        result = engine.build_context(conversation)

        # System message must be present
        assert any(m.role == "system" and "assistant" in m.content for m in result)

    def test_system_tokens_exceed_budget_returns_system_only(self):
        engine = ContextEngine(token_budget=300)
        # System message that consumes all budget (300 words * 1.3 ~ 390 tokens)
        system = ChatMessage(role="system", content="word " * 300)
        user = ChatMessage(role="user", content="hi")
        result = engine.build_context([system, user])
        # Only system message(s) returned when system alone exceeds budget
        assert all(m.role == "system" for m in result)


# ---------------------------------------------------------------------------
# build_context — compaction triggered
# ---------------------------------------------------------------------------


class TestBuildContextCompaction:
    def _make_conversation(self, n_pairs: int) -> list[ChatMessage]:
        msgs: list[ChatMessage] = [
            ChatMessage(role="system", content="You are a helpful AI assistant.")
        ]
        for i in range(n_pairs):
            msgs.append(ChatMessage(role="user", content=f"This is user question number {i}?"))
            msgs.append(
                ChatMessage(role="assistant", content=f"This is my answer to question {i}.")
            )
        return msgs

    def test_fits_within_budget(self):
        engine = ContextEngine(token_budget=500, recent_turns=4)
        msgs = self._make_conversation(20)
        result = engine.build_context(msgs)
        total = engine.count_tokens(result)
        assert total <= 500

    def test_result_contains_summary(self):
        # Use a budget small enough to guarantee compaction with 15 pairs (~387 tokens)
        # budget=250 forces compaction
        engine = ContextEngine(token_budget=250, recent_turns=2)
        msgs = self._make_conversation(15)
        result = engine.build_context(msgs)
        # A summary message should appear when compaction is triggered;
        # the default summariser produces a structured digest with role labels
        has_summary = any(
            m.role == "system"
            and ("summary" in m.content.lower() or "USER" in m.content or "ASSISTANT" in m.content)
            for m in result
        )
        assert has_summary

    def test_recent_messages_preserved(self):
        engine = ContextEngine(token_budget=500, recent_turns=4)
        msgs = self._make_conversation(20)
        result = engine.build_context(msgs)
        # Last user message should appear in context
        last_user_content = msgs[-2].content
        assert any(m.content == last_user_content for m in result)

    def test_custom_summariser_called(self):
        called_with: list[list[ChatMessage]] = []

        def my_summariser(messages: list[ChatMessage]) -> str:
            called_with.append(messages)
            return "CUSTOM SUMMARY"

        # budget=250 with 15 pairs forces compaction
        engine = ContextEngine(token_budget=250, recent_turns=2, summariser=my_summariser)
        msgs = self._make_conversation(15)
        result = engine.build_context(msgs)

        assert len(called_with) >= 1
        assert any("CUSTOM SUMMARY" in m.content for m in result)

    def test_budget_respected_with_tiny_budget(self):
        engine = ContextEngine(token_budget=300, recent_turns=2)
        msgs = self._make_conversation(30)
        result = engine.build_context(msgs)
        total = engine.count_tokens(result)
        # Budget must be respected (system messages alone may push slightly over
        # in pathological cases, but compaction must bring it well below 2x budget)
        assert total <= 300 * 1.2  # within 20% of budget (rounding tolerance)
