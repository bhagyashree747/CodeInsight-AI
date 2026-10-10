"""Review module for CodeInsight AI."""

from app.review.llm_client import (
    LLMClient,
    MockLLMClient,
    OllamaLLMClient,
    OpenAICompatLLMClient,
    get_client,
)
from app.review.prompts import SYSTEM_PROMPT, build_user_prompt
from app.review.reviewer import review
from app.review.schema import Category, Finding, ReviewResult, Severity

__all__ = [
    "Category",
    "Finding",
    "LLMClient",
    "MockLLMClient",
    "OllamaLLMClient",
    "OpenAICompatLLMClient",
    "ReviewResult",
    "SYSTEM_PROMPT",
    "Severity",
    "build_user_prompt",
    "get_client",
    "review",
]
