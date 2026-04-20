"""
Anthropic Native Adapter
========================
Direct Anthropic API adapter. Implements the same interface as OpenRouterAdapter.

Key differences vs OpenAI/OpenRouter:
- Uses anthropic SDK (not openai-compatible)
- Streaming uses a context manager pattern (with client.messages.stream())
- Token counts come from message.usage (input_tokens / output_tokens)
- Cost calculated locally (Anthropic does not return cost)

Install: pip install anthropic
"""

import anthropic
from src.config.constants import MAX_TOKENS_GENERATION
from src.config.providers_registry import get_model_pricing


class AnthropicAdapter:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.default_model = "claude-haiku-4-5-20251001"

    def generate(self, prompt: str, model: str = None, max_tokens: int = MAX_TOKENS_GENERATION) -> dict:
        """Non-streaming generation.
        Returns: {'content': str, 'usage': {'input': int, 'output': int, 'cost': float, 'model': str}}
        """
        model_to_use = model or self.default_model

        try:
            message = self.client.messages.create(
                model=model_to_use,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = message.content[0].text
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            input_cost, output_cost = get_model_pricing(model_to_use)
            cost = (input_tokens * input_cost + output_tokens * output_cost) / 1_000_000

            return {
                "content": content,
                "usage": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "cost": cost,
                    "model": model_to_use,
                },
            }
        except Exception as e:
            return {"content": f"❌ Error: {str(e)}", "usage": None}

    def generate_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = MAX_TOKENS_GENERATION,
        usage_callback=None,
    ):
        """
        Streaming generation using Anthropic's streaming context manager.
        Yields content chunks, fires usage_callback at end.
        """
        model_to_use = model or self.default_model

        try:
            with self.client.messages.stream(
                model=model_to_use,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text_chunk in stream.text_stream:
                    yield text_chunk

                # After stream completes, get final message for usage
                final_message = stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens
                input_cost, output_cost = get_model_pricing(model_to_use)
                cost = (input_tokens * input_cost + output_tokens * output_cost) / 1_000_000

                usage_data = {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "cost": cost,
                    "model": model_to_use,
                }

                if usage_callback:
                    usage_callback(usage_data)

        except Exception as e:
            yield f"❌ Error (Stream): {str(e)}"