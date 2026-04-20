"""
Providers Registry
==================
Single source of truth for all supported API providers.

To add a new provider:
1. Create its adapter in src/api/ (must implement generate() and generate_stream())
2. Add an entry to PROVIDERS_REGISTRY below
3. Add its default models to PROVIDER_DEFAULT_MODELS below

The UI and model manager auto-discover everything from these two dicts.
"""

# --- Lazy imports to avoid circular dependencies and optional dependencies ---
def _get_openrouter_adapter():
    from src.api.openrouter_adapter import OpenRouterAdapter
    return OpenRouterAdapter

def _get_openai_adapter():
    from src.api.openai_adapter import OpenAIAdapter
    return OpenAIAdapter

def _get_anthropic_adapter():
    from src.api.anthropic_adapter import AnthropicAdapter
    return AnthropicAdapter

def _get_google_adapter():
    from src.api.google_adapter import GoogleAdapter
    return GoogleAdapter

def _get_deepseek_adapter():
    from src.api.deepseek_adapter import DeepSeekAdapter
    return DeepSeekAdapter


# =============================================================================
# PROVIDER REGISTRY
# =============================================================================
# Each entry defines everything the UI and adapter factory need.
# 'adapter_factory' is a callable that returns the adapter CLASS (lazy load).

PROVIDERS_REGISTRY = {
    "openrouter": {
        "display_name": "OpenRouter",
        "adapter_factory": _get_openrouter_adapter,
        "key_placeholder": "sk-or-...",
        "badge": "⭐ Recommended for full metrics and cost tracking",
        "base_url": "https://openrouter.ai/api/v1",   # OpenAI-compatible
    },
    "openai": {
        "display_name": "OpenAI",
        "adapter_factory": _get_openai_adapter,
        "key_placeholder": "sk-...",
        "badge": None,
        "base_url": None,   # OpenAI-compatible (native endpoint)
    },
    "anthropic": {
        "display_name": "Anthropic",
        "adapter_factory": _get_anthropic_adapter,
        "key_placeholder": "sk-ant-...",
        "badge": None,
        # no base_url — not OpenAI-compatible, unsupported by course generator
    },
    "google": {
        "display_name": "Google AI",
        "adapter_factory": _get_google_adapter,
        "key_placeholder": "AIza...",
        "badge": None,
        # no base_url — not OpenAI-compatible, unsupported by course generator
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "adapter_factory": _get_deepseek_adapter,
        "key_placeholder": "sk-...",
        "badge": None,
        "base_url": "https://api.deepseek.com",   # OpenAI-compatible
    },
}


# =============================================================================
# FACTORY DEFAULT MODELS
# =============================================================================

# Structure per model entry:
#   display_name : shown in selectboxes
#   model_id     : sent to the API
#   input_cost   : optional, USD per 1M tokens — omit for OpenRouter models
#   output_cost  : optional, USD per 1M tokens — omit for OpenRouter models
#                  OpenRouter returns cost directly from the server response

PROVIDER_DEFAULT_MODELS = {
    "openrouter": [
        {
            "display_name": "Deep Seek v3.2",
            "model_id": "deepseek/deepseek-v3.2",
        },
        {
            "display_name": "Grok 4.1 Fast",
            "model_id": "x-ai/grok-4.1-fast",
        },
        {
            "display_name": "GLM 5",
            "model_id": "z-ai/glm-5",
        },
        {
            "display_name": "GLM 4.7",
            "model_id": "z-ai/glm-4.7",
        },
        {
            "display_name": "Claude Haiku 4.5",
            "model_id": "anthropic/claude-haiku-4.5",
        },
        {
            "display_name": "Qwen 3.5 Plus",
            "model_id": "qwen/qwen3.5-plus-02-15",
        },
        {
            "display_name": "GPT OSS",
            "model_id": "openai/gpt-oss-120b",
        },
    ],
    "openai": [
        {
            "display_name": "GPT-4o",
            "model_id":     "gpt-4o",
            "input_cost":   2.50,
            "output_cost":  10.0,
        },
        {
            "display_name": "GPT-4o Mini",
            "model_id":     "gpt-4o-mini",
            "input_cost":   0.15,
            "output_cost":  0.60,
        },
        {
            "display_name": "o1 Mini",
            "model_id":     "o1-mini",
            "input_cost":   1.10,
            "output_cost":  4.40,
        },
    ],
    "anthropic": [
        {
            "display_name": "Claude Sonnet 4.5",
            "model_id":     "claude-sonnet-4-5",
            "input_cost":   3.0,
            "output_cost":  15.0,
        },
        {
            "display_name": "Claude Haiku 4.5",
            "model_id":     "claude-haiku-4-5-20251001",
            "input_cost":   0.80,
            "output_cost":  4.0,
        },
        {
            "display_name": "Claude Opus 4.6",
            "model_id":     "claude-opus-4-6",
            "input_cost":   15.0,
            "output_cost":  75.0,
        },
    ],
    "deepseek": [
        {
            "display_name": "DeepSeek Chat V3.2",
            "model_id":     "deepseek-chat",
            "input_cost":   0.28,
            "output_cost":  0.42,
        },
        {
            "display_name": "DeepSeek Reasoner V3.2",
            "model_id":     "deepseek-reasoner",
            "input_cost":   0.28,
            "output_cost":  0.42,
        },
    ],
    "google": [
        {
            "display_name": "Gemini 2.0 Flash",
            "model_id":     "gemini-2.0-flash",
            "input_cost":   0.10,
            "output_cost":  0.40,
        },
        {
            "display_name": "Gemini 2.5 Pro",
            "model_id":     "gemini-2.5-pro-preview-05-06",
            "input_cost":   1.25,
            "output_cost":  10.0,
        },
    ],
}


def get_provider_keys() -> list[str]:
    """Returns list of provider IDs in display order."""
    return list(PROVIDERS_REGISTRY.keys())


def get_provider_display_names() -> list[str]:
    """Returns display names in same order as get_provider_keys()."""
    return [v["display_name"] for v in PROVIDERS_REGISTRY.values()]


def get_registry_entry(provider_key: str) -> dict:
    """Returns the registry entry for a given provider key."""
    return PROVIDERS_REGISTRY.get(provider_key, {})


def get_default_models(provider_key: str) -> list[dict]:
    """Returns the factory default model list for a provider."""
    return PROVIDER_DEFAULT_MODELS.get(provider_key, [])


def build_adapter(provider_key: str, api_key: str):
    """
    Instantiates and returns the correct adapter for the given provider.
    
    Args:
        provider_key: Key from PROVIDERS_REGISTRY (e.g. 'openrouter')
        api_key: The user's API key for that provider
    
    Returns:
        Adapter instance, or None if provider not found.
    """
    entry = PROVIDERS_REGISTRY.get(provider_key)
    if not entry:
        return None
    
    try:
        adapter_class = entry["adapter_factory"]()
        return adapter_class(api_key=api_key)
    except ImportError as e:
        print(f"[WARN] Could not load adapter for '{provider_key}': {e}")
        return None
    
def get_model_pricing(model_id: str) -> tuple[float, float]:
    """
    Returns (input_cost, output_cost) per 1M tokens for a given model_id.
    Looks up across all providers. Returns (0.0, 0.0) if model not found.
    Cost fields are optional per entry — OpenRouter models have none.
    """
    for models in PROVIDER_DEFAULT_MODELS.values():
        for m in models:
            if m["model_id"] == model_id:
                return m.get("input_cost", 0.0), m.get("output_cost", 0.0)
    print(f"[WARN] No pricing data for model '{model_id}' -- cost will show $0.00")
    return 0.0, 0.0