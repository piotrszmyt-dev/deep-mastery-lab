"""
Course Generator Adapter
------------------------
API support layer exclusively for the course generation pipeline.

Contains:
    PipelineAbortError       — raised on unrecoverable pipeline failure
    ParseCircuitBreaker      — trips on repeated server/parse failures in a 30s window
    CourseGeneratorAdapter   — async API client with token/cost tracking for the
                               generator completion screen (get_stats())

Supported providers: all providers in PROVIDERS_REGISTRY.
- OpenAI-compatible (openrouter, openai, deepseek): openai.AsyncOpenAI with base_url
- Anthropic: anthropic.AsyncAnthropic
- Google: google.generativeai generate_content_async
"""

import time
import openai
from src.config.providers_registry import PROVIDERS_REGISTRY, get_model_pricing

class PipelineAbortError(Exception):
    """Raised when a phase fails all retry attempts or the circuit breaker trips."""
    pass


class ParseCircuitBreaker:
    """
    Shared within a single orchestrator run.
    Trips open if too many failures appear in a 30-second rolling window,
    signalling either a degraded provider or a model that cannot produce JSON.
    """
    _WINDOW = 30
    _SERVER_LIMIT = 3
    _PARSE_LIMIT  = 4

    def __init__(self):
        self._parse_fails  = []
        self._server_fails = []
        self.state        = 'CLOSED'
        self.trip_reason  = None

    def record_parse_failure(self, label: str):
        self._parse_fails.append((time.time(), label))
        self._evaluate()

    def record_server_failure(self, label: str):
        self._server_fails.append((time.time(), label))
        self._evaluate()

    def _evaluate(self):
        if self.state == 'OPEN':
            return
        cutoff = time.time() - self._WINDOW
        recent_server = [l for t, l in self._server_fails if t >= cutoff]
        if len(recent_server) >= self._SERVER_LIMIT:
            self.state = 'OPEN'
            self.trip_reason = 'server_down'
            return
        recent_parse = [(t, l) for t, l in self._parse_fails if t >= cutoff]
        if len(recent_parse) >= self._PARSE_LIMIT:
            unique_tasks = len(set(l for _, l in recent_parse))
            if unique_tasks >= 3:
                self.state = 'OPEN'
                self.trip_reason = 'model_json'

    @property
    def is_open(self) -> bool:
        return self.state == 'OPEN'


class CourseGeneratorAdapter:
    """
    Async API client for the course generation pipeline.

    Supports all providers in PROVIDERS_REGISTRY:
    - OpenAI-compatible (openrouter, openai, deepseek): uses openai.AsyncOpenAI
    - anthropic: uses anthropic.AsyncAnthropic
    - google: uses google.generativeai generate_content_async

    Tracks cumulative token usage and cost so the generator completion screen
    can display stats via get_stats().

    Used exclusively by ProductionCourseGenerator and course_generator_render.py.
    Concurrency is controlled entirely by the semaphore in phase_3_name_lessons.
    """

    def __init__(self, api_key: str, provider: str = "openrouter"):
        self.api_key  = api_key
        self.provider = provider

        entry = PROVIDERS_REGISTRY.get(provider, {})

        if 'base_url' in entry:
            # OpenAI-compatible provider
            base_url = entry['base_url']
            kwargs = dict(api_key=api_key, timeout=60.0)
            if base_url:
                kwargs["base_url"] = base_url
            self.client = openai.AsyncOpenAI(**kwargs)

        elif provider == 'anthropic':
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=api_key)

        elif provider == 'google':
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.client = genai   # module-level client; model instantiated per call

        else:
            raise ValueError(f"Unsupported provider for course generation: '{provider}'")

        self.total_input_tokens  = 0
        self.total_output_tokens = 0
        self.total_cost          = 0.0

    async def generate_async(self, prompt: str, model: str,
                              temperature: float = 0.7,
                              max_tokens: int = 4000) -> str:
        """
        Single async LLM call. No retry logic — retries are handled by
        _parse_with_retry in ProductionCourseGenerator.

        Returns:
            str: Raw text response from the model.
        """
        if 'base_url' in PROVIDERS_REGISTRY.get(self.provider, {}):
            return await self._generate_openai(prompt, model, temperature, max_tokens)
        elif self.provider == 'anthropic':
            return await self._generate_anthropic(prompt, model, max_tokens)
        elif self.provider == 'google':
            return await self._generate_google(prompt, model, max_tokens)

    async def _generate_openai(self, prompt, model, temperature, max_tokens):
        response = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        if hasattr(response, 'usage') and response.usage:
            self.total_input_tokens  += response.usage.prompt_tokens
            self.total_output_tokens += response.usage.completion_tokens
            if self.provider == "openrouter":
                cost = response.model_dump().get('usage', {}).get('cost', 0.0)
                if cost:
                    self.total_cost += cost
            else:
                in_cost, out_cost = get_model_pricing(model)
                self.total_cost += (response.usage.prompt_tokens     / 1_000_000) * in_cost
                self.total_cost += (response.usage.completion_tokens / 1_000_000) * out_cost
        return response.choices[0].message.content

    async def _generate_anthropic(self, prompt, model, max_tokens):
        message = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        self.total_input_tokens  += message.usage.input_tokens
        self.total_output_tokens += message.usage.output_tokens
        in_cost, out_cost = get_model_pricing(model)
        self.total_cost += (message.usage.input_tokens  / 1_000_000) * in_cost
        self.total_cost += (message.usage.output_tokens / 1_000_000) * out_cost
        return message.content[0].text

    async def _generate_google(self, prompt, model, max_tokens):
        import google.generativeai as genai
        gemini_model = genai.GenerativeModel(model)
        response = await gemini_model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(max_output_tokens=max_tokens)
        )
        in_tok  = response.usage_metadata.prompt_token_count or 0
        out_tok = response.usage_metadata.candidates_token_count or 0
        self.total_input_tokens  += in_tok
        self.total_output_tokens += out_tok
        in_cost, out_cost = get_model_pricing(model)
        self.total_cost += (in_tok  / 1_000_000) * in_cost
        self.total_cost += (out_tok / 1_000_000) * out_cost
        return response.text

    def get_stats(self) -> dict:
        """
        Returns cumulative token and cost stats for the completion screen.
        OpenRouter cost comes from the API response directly.
        All other providers compute cost from get_model_pricing() × token counts.
        Shows N/A only when no pricing data is available for the model.
        """
        cost_str = f"${self.total_cost:.4f}" if self.total_cost > 0 else "N/A"
        return {
            "input_tokens":   self.total_input_tokens,
            "output_tokens":  self.total_output_tokens,
            "total_tokens":   self.total_input_tokens + self.total_output_tokens,
            "cost":           self.total_cost,
            "cost_formatted": cost_str
        }
