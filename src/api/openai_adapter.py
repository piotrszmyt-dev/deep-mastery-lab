"""
Non-streaming generation.
Returns same dict shape as OpenRouterAdapter:
{
    'content': str,
    'usage': {'input': int, 'output': int, 'cost': float, 'model': str}
}
"""

from openai import OpenAI
from src.config.constants import MAX_TOKENS_GENERATION
from src.config.providers_registry import get_model_pricing

class OpenAIAdapter:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.default_model = "gpt-4o-mini"

    def generate(self, prompt: str, model: str = None, max_tokens: int = MAX_TOKENS_GENERATION) -> dict:
        """
        Non-streaming generation.
        Returns same dict shape as OpenRouterAdapter:
        {
            'content': str,
            'usage': {'input': int, 'output': int, 'cost': float, 'model': str}
        }
        """
        model_to_use = model or self.default_model

        try:
            response = self.client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
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
        """Streaming generation. Yields text chunks, fires usage_callback on the final chunk.
        Args:
            usage_callback: optional callable receiving {'prompt_tokens', 'completion_tokens', 'cost', 'model'}.
        """
        model_to_use = model or self.default_model

        try:
            stream = self.client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )

            for chunk in stream:
                # Yield content
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

                # Capture usage from final chunk
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0
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