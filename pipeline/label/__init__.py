"""LLM text labeling. The ONLY LLM use in NAZAR (PROTOCOL R5): labels/clusters text, never lifecycle judgments."""

from pipeline.label.llm_client import MissingLLMKey

__all__ = ["MissingLLMKey"]
