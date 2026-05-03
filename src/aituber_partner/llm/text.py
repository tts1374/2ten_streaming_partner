"""LLM text post-processing utilities."""

from __future__ import annotations

import re

_THINKING_BLOCK_RE = re.compile(r"<(?:think|thinking)>.*?</(?:think|thinking)>", re.DOTALL | re.I)
_THINKING_LINE_RE = re.compile(
    r"^\s*(?:thinking|reasoning|思考|内部分析)\s*[:：].*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_thinking_text(text: str) -> str:
    """Remove thinking-like text before subtitles or TTS can receive it."""

    without_blocks = _THINKING_BLOCK_RE.sub("", text)
    without_lines = _THINKING_LINE_RE.sub("", without_blocks)
    return "\n".join(line.rstrip() for line in without_lines.splitlines() if line.strip()).strip()

