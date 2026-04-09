"""Prompt templates for the RAG pipeline."""

from __future__ import annotations

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
        Override the default system prompt.
    code_mode:
        Use the code-aware template variant.

    Returns
    -------
    str
        The fully rendered prompt ready for LLM submission.
    """
    system = system_prompt or DEFAULT_SYSTEM_PROMPT
    context = _format_context(chunks)
    template = CODE_RAG_TEMPLATE if code_mode else DEFAULT_RAG_TEMPLATE
    return template.format(system=system, context=context, question=question)
