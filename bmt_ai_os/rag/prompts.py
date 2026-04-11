"""Prompt templates for the RAG pipeline."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. Use the following context to answer the "
    "question. If the context doesn't contain relevant information, say so. "
    "Always cite your sources."
)

DEFAULT_RAG_TEMPLATE = """{system}

Context:
{context}

Question: {question}"""

CODE_RAG_TEMPLATE = """{system}

You are answering a code-related question.  When referencing code, use
fenced code blocks with the appropriate language tag.

Context:
{context}

Question: {question}"""

# Suffix appended to a persona prompt when used in RAG context so the model
# still has clear instructions around citing retrieved sources.
_RAG_PERSONA_SUFFIX = (
    "\n\nUse the following retrieved context to answer the question. "
    "If the context does not contain relevant information, say so and "
    "answer from your own knowledge. Always cite the provided sources."
)


def get_rag_system_prompt(override: str | None = None) -> str:
    """Return the system prompt to use in RAG prompts.

    Priority:
    1. Explicit *override* argument — used by callers that supply their own text.
    2. Active persona assembled from SOUL.md (when persona module is available
       and ``BMT_PERSONA_ENABLED`` is not disabled).
    3. ``DEFAULT_SYSTEM_PROMPT`` constant.

    This function never raises; it falls back gracefully at each level.

    Parameters
    ----------
    override:
        Caller-supplied system prompt that takes absolute precedence.
    """
    if override:
        return override

    # Try persona-aware prompt
    if os.getenv("BMT_PERSONA_ENABLED", "1").lower() not in ("0", "false", "no"):
        try:
            from bmt_ai_os.persona.assembler import get_persona_assembler

            assembler = get_persona_assembler()
            persona_text = assembler.assemble()
            if persona_text:
                logger.debug("RAG using persona-aware system prompt")
                return persona_text + _RAG_PERSONA_SUFFIX
        except Exception as exc:
            logger.debug("Persona-aware RAG prompt unavailable: %s", exc)

    return DEFAULT_SYSTEM_PROMPT


def _format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a numbered context block.

    Each chunk dict is expected to have at least ``text`` and ``filename``
    keys.  An optional ``score`` key is included when available.
    """
    parts: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        filename = chunk.get("filename", "unknown")
        text = chunk.get("text", "")
        parts.append(f"[{idx}] (source: {filename})\n{text}")
    return "\n\n".join(parts)


def render_prompt(
    question: str,
    chunks: list[dict],
    *,
    system_prompt: str | None = None,
    code_mode: bool = False,
) -> str:
    """Render a full RAG prompt from a question and retrieved chunks.

    Parameters
    ----------
    question:
        The user's natural-language question.
    chunks:
        List of dicts with ``text``, ``filename``, and optionally ``score``.
    system_prompt:
        Override the default system prompt.  When ``None``, the persona-aware
        system prompt is used (see ``get_rag_system_prompt``).
    code_mode:
        Use the code-aware template variant.

    Returns
    -------
    str
        The fully rendered prompt ready for LLM submission.
    """
    system = get_rag_system_prompt(override=system_prompt)
    context = _format_context(chunks)
    template = CODE_RAG_TEMPLATE if code_mode else DEFAULT_RAG_TEMPLATE
    return template.format(system=system, context=context, question=question)
