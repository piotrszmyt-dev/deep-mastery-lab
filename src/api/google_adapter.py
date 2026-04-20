"""
Google AI Native Adapter
========================
Direct Google AI (Gemini) adapter. Implements the same interface as OpenRouterAdapter.

Install: pip install google-generativeai
"""

import google.generativeai as genai
from src.config.constants import MAX_TOKENS_GENERATION
from src.config.providers_registry import get_model_pricing

class GoogleAdapter:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.default_model = "gemini-2.0-flash"

    def _get_model(self, model_id: str):
        """Creates a GenerativeModel instance for the given model_id."""
        return genai.GenerativeModel(model_id)

    def generate(self, prompt: str, model: str = None, max_tokens: int = MAX_TOKENS_GENERATION) -> dict:
        """Non-streaming generation.
        Returns: {'content': str, 'usage': {'input': int, 'output': int, 'cost': float, 'model': str}}
        """
        model_to_use = model or self.default_model

        try:
            gemini_model = self._get_model(model_to_use)
            response = gemini_model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=max_tokens,
                ),
            )

            content = response.text
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
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
        Streaming generation using Google's streaming API.
        Yields content chunks, fires usage_callback at end.
        """
        model_to_use = model or self.default_model

        try:
            gemini_model = self._get_model(model_to_use)
            stream = gemini_model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=max_tokens,
                ),
                stream=True,
            )

            input_tokens = 0
            output_tokens = 0

            for chunk in stream:
                if chunk.text:
                    yield chunk.text
                # Accumulate usage from each chunk (Google sends it per-chunk)
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.prompt_token_count or 0
                    output_tokens = chunk.usage_metadata.candidates_token_count or 0

            # Fire callback after stream completes
            if usage_callback:
                input_cost, output_cost = get_model_pricing(model_to_use)
                cost = (input_tokens * input_cost + output_tokens * output_cost) / 1_000_000
                usage_callback({
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "cost": cost,
                    "model": model_to_use,
                })

        except Exception as e:
            yield f"❌ Error (Stream): {str(e)}"