"""Shared model selection without importing either web service."""

import os
from agent.fake_llm import FastLLM, QualityLLM


def _build_llms(mode=None):
    mode = mode or os.getenv("AGENT_MODE", "improved")
    backend = os.getenv("LLM_BACKEND", "fake")
    if backend == "ollama":
        from agent.ollama_llm import OllamaFastLLM, OllamaQualityLLM

        if mode == "improved":
            from agent.runtime_llm import (
                InteractiveOllamaFastLLM,
                InteractiveOllamaQualityLLM,
            )

            OllamaFastLLM, OllamaQualityLLM = (
                InteractiveOllamaFastLLM,
                InteractiveOllamaQualityLLM,
            )
        return (
            backend,
            OllamaFastLLM(
                os.getenv("OLLAMA_FAST_MODEL", "qwen3:0.6b"), usd_per_1k_tokens=0.00015
            ),
            OllamaQualityLLM(
                os.getenv("OLLAMA_QUALITY_MODEL", "qwen3:8b"), usd_per_1k_tokens=0.005
            ),
        )
    if backend == "openai":
        from agent.openai_llm import OpenAIFastLLM, OpenAIQualityLLM

        if mode == "improved":
            from agent.runtime_llm import (
                InteractiveOpenAIFastLLM,
                InteractiveOpenAIQualityLLM,
            )

            OpenAIFastLLM, OpenAIQualityLLM = (
                InteractiveOpenAIFastLLM,
                InteractiveOpenAIQualityLLM,
            )
        return (
            backend,
            OpenAIFastLLM(
                os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini"), usd_per_1k_tokens=0.00015
            ),
            OpenAIQualityLLM(
                os.getenv("OPENAI_QUALITY_MODEL", "gpt-4o"), usd_per_1k_tokens=0.005
            ),
        )
    if backend != "fake":
        raise ValueError("Unknown LLM_BACKEND: " + backend)
    return (
        backend,
        FastLLM("fast-model-stub", 0.00015),
        QualityLLM("quality-model-stub", 0.005),
    )

