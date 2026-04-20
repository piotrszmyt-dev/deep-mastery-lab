"""
OpenRouter adapter. 
Routes LLM calls via OpenRouter's OpenAI-compatible API with native cost tracking.
"""

from openai import OpenAI

from src.config.constants import MAX_TOKENS_GENERATION


class OpenRouterAdapter:
    """Wraps OpenRouter's API using the OpenAI client. Returns a unified response dict
    compatible with all other adapters in this project."""
    def __init__(self, api_key: str):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.default_model = "deepseek/deepseek-chat"
    
    def generate(self, prompt: str, model: str = None, max_tokens: int = MAX_TOKENS_GENERATION) -> dict:
        """Non-streaming generation.
        Returns: {'content': str, 'usage': {'input': int, 'output': int, 'cost': float, 'model': str}}
        Cost is taken directly from OpenRouter's usage object (no local calculation needed).
        """
        model_to_use = model or self.default_model 
        try:
            response = self.client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            content = response.choices[0].message.content
            
            # --- OPENROUTER COST EXTRACTION ---
            # We convert the response to a dictionary to access custom fields
            # like 'cost' that OpenRouter injects into the 'usage' object.
            raw_data = response.model_dump() 
            usage_data = raw_data.get('usage', {})
            
            # OpenRouter provides total_cost directly in the usage object
            cost = usage_data.get('cost', 0.0) 
            
            # Token counts
            prompt_tokens = usage_data.get('prompt_tokens', 0)
            comp_tokens = usage_data.get('completion_tokens', 0)
            
            return {
                'content': content,
                'usage': {
                    'input': prompt_tokens,
                    'output': comp_tokens,
                    'cost': cost,           # <--- The exact cost from OpenRouter
                    'model': model_to_use
                }
            }
        except Exception as e:
            return {'content': f"❌ Error: {str(e)}", 'usage': None}

    def generate_stream(self, prompt: str, model: str = None, max_tokens: int = MAX_TOKENS_GENERATION, usage_callback=None):
        """Streaming generation. Yields text chunks, fires usage_callback on the final chunk.
        Args:
            usage_callback: optional callable receiving usage dict (prompt_tokens, completion_tokens, cost).
        """
        model_to_use = model if model else self.default_model
        
        try:
            stream = self.client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.7,
                stream=True,
                stream_options={"include_usage": True} # required to receive usage data in the final chunk
            )
            
            for chunk in stream:
                # 1. Yield Content
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                
                # 2. Capture Usage (Sent in the final chunk)
                if chunk.usage:
                    usage_data = chunk.usage.model_dump()
                    if usage_callback:
                        usage_callback(usage_data)
                    
        except Exception as e:
            yield f"❌ Error (Stream): {str(e)}"