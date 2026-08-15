"""Curated OpenAI-compatible LLM provider / model presets (updated Aug 2026)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label: str
    base_url: str
    models: tuple[str, ...]
    note: str = ""


# Display labels shown in the combo; values saved to settings.llm.provider
PROVIDERS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="OpenAI",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        models=(
            "gpt-5.6",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-5.4",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ),
        note="官方 Chat Completions / Responses",
    ),
    ProviderPreset(
        key="DeepSeek",
        label="DeepSeek（深度求索）",
        base_url="https://api.deepseek.com/v1",
        models=(
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ),
        note="旧别名 deepseek-chat / deepseek-reasoner 已弃用",
    ),
    ProviderPreset(
        key="Qwen",
        label="通义千问（阿里云百炼）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=(
            "qwen3.8-max",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen3.5-plus",
            "qwen3.5-flash",
            "qwen-plus",
            "qwen-flash",
            "qwen3-coder-plus",
            "qwen3-coder-flash",
        ),
        note="DashScope OpenAI 兼容模式",
    ),
    ProviderPreset(
        key="Moonshot",
        label="Kimi / 月之暗面",
        base_url="https://api.moonshot.cn/v1",
        models=(
            "kimi-k3",
            "kimi-k2.7-code",
            "kimi-k2.7-code-highspeed",
            "kimi-k2.6",
            "kimi-k2.5",
        ),
        note="国内常用 api.moonshot.cn；国际站多为 api.moonshot.ai",
    ),
    ProviderPreset(
        key="Zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=(
            "glm-4.5",
            "glm-4.5-air",
            "glm-4-flash",
            "glm-4-plus",
            "glm-4",
        ),
    ),
    ProviderPreset(
        key="Gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        models=(
            "gemini-3.5-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ),
        note="OpenAI 兼容端点",
    ),
    ProviderPreset(
        key="OpenRouter",
        label="OpenRouter（聚合）",
        base_url="https://openrouter.ai/api/v1",
        models=(
            "openai/gpt-5.6",
            "anthropic/claude-sonnet-5",
            "google/gemini-3.5-flash",
            "deepseek/deepseek-v4-pro",
            "qwen/qwen3.7-plus",
            "x-ai/grok-4.5",
        ),
        note="模型 ID 含厂商前缀，可在控制台复制后粘贴",
    ),
    ProviderPreset(
        key="SiliconFlow",
        label="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        models=(
            "deepseek-ai/DeepSeek-V3.2",
            "Qwen/Qwen3-235B-A22B",
            "moonshotai/Kimi-K2-Instruct",
            "THUDM/GLM-4.5",
        ),
        note="聚合国内开源/托管模型，建议点「拉取可用模型」",
    ),
    ProviderPreset(
        key="Ollama",
        label="Ollama（本地）",
        base_url="http://127.0.0.1:11434/v1",
        models=(
            "llama3.2",
            "qwen3",
            "deepseek-r1",
            "mistral",
        ),
        note="本地服务，无需 API Key；可用「拉取可用模型」同步",
    ),
    ProviderPreset(
        key="Custom",
        label="自定义 / 其他兼容接口",
        base_url="",
        models=(),
        note="任意 OpenAI 兼容网关，手动填 Base URL 与模型名",
    ),
)

_BY_KEY = {p.key: p for p in PROVIDERS}
_BY_LABEL = {p.label: p for p in PROVIDERS}


def provider_labels() -> list[str]:
    return [p.label for p in PROVIDERS]


def find_provider(text: str) -> ProviderPreset | None:
    text = (text or "").strip()
    if not text:
        return None
    if text in _BY_KEY:
        return _BY_KEY[text]
    if text in _BY_LABEL:
        return _BY_LABEL[text]
    for p in PROVIDERS:
        if p.key.lower() == text.lower() or p.label.lower() == text.lower():
            return p
    return None


def models_for_provider(text: str) -> list[str]:
    preset = find_provider(text)
    return list(preset.models) if preset else []


def provider_key_for_save(text: str) -> str:
    preset = find_provider(text)
    return preset.key if preset else (text.strip() or "Custom")
