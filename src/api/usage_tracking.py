"""
Token usage and cost tracking for AI-generated content

Functions:
    update_course_metrics       — Foreground callback: saves usage data from streaming.py
                                  into the course metrics file via ProgressManager

Classes:
    ThreadSafeTrackingAdapter   — Wraps any API adapter for use in background threads.
                                  Tracks cost automatically after each .generate() call.

All cost data comes from the API adapter response and is provider-agnostic
(works with OpenRouter, Anthropic, OpenAI adapters).
"""

import streamlit as st
import threading
import time
from src.managers.progress_manager import ProgressManager
from src.config.constants import MAX_TOKENS_GENERATION

def update_course_metrics(course_filename, usage_data, pm_instance=None):
    """
    Save token usage and cost from a completed API call into the course metrics file.

    Called by handle_stream_response() in streaming.py after each streaming card
    generation. Delegates directly to ProgressManager.update_metrics() — only the
    course metrics file is touched, never the main progress file.

    Args:
        course_filename (str): Course filename used as the metrics key
                               (e.g. 'my_course.json').
        usage_data (dict):     Usage metrics from the API response. Accepts either
                               key format: 'prompt_tokens'/'completion_tokens'
                               or 'input'/'output', plus 'cost' (float).
        pm_instance:           Optional ProgressManager instance. If None, falls back
                               to st.session_state.progress_manager.

    Returns:
        None
    """
    if not usage_data or not course_filename:
        return
    
    # Get ProgressManager instance
    pm = pm_instance if pm_instance else st.session_state.progress_manager
    
    # Direct call to specialized method
    pm.update_metrics(course_filename, usage_data)


class ThreadSafeTrackingAdapter:
    """
    Wraps any API adapter for safe use in background threads.

    Background threads cannot access st.session_state, so this adapter
    creates a fresh ProgressManager instance per call and writes cost data
    to disk directly via a daemon thread, without touching session state.

    Used by:
        - generate_questions_background() — question generation in prefetch pipeline
        - generate_card_content()         — card prefetching
        - generate_final_card()           — FINAL_TEST congratulations card
    """
    
    def __init__(self, original_adapter, target_model, course_filename, element_id=None):
        """
        Initialize thread-safe adapter.

        Args:
            original_adapter: The underlying API adapter — any object exposing
                               .generate(prompt, model, max_tokens).
            target_model (str): Model ID passed to every .generate() call.
            course_filename (str): Course filename used as the metrics tracking key.
            element_id (str, optional): Label printed in terminal logs to identify
                                        which element triggered this generation.
                                        Default '?'.
        """
        self.origin = original_adapter
        self.model = target_model
        self.course_filename = course_filename
        self.element_id = element_id or '?'
        
    def generate(self, prompt, max_tokens=MAX_TOKENS_GENERATION, generation_type='Presentation'):
        """
        Generate content and automatically track cost to disk.

        Calls the underlying adapter, logs timing and token usage to the terminal,
        then fires a daemon thread to persist cost data via ProgressManager.

        Args:
            prompt (str):           The prompt to send to the API.
            max_tokens (int):       Maximum tokens for the response.
                                    Default MAX_TOKENS_GENERATION.
            generation_type (str):  Label used in terminal logs to identify the
                                    generation type (e.g. 'Presentation', 'FinalCard').
                                    Default 'Presentation'.

        Returns:
            dict: Full API response with 'content' and 'usage' keys if the adapter
                  returned usage data. Otherwise returns the raw adapter response
                  as-is (str or dict without 'usage').
        """
        print(f"[GEN] [{self.element_id}] {generation_type} | {self.model} | {len(prompt)} chars  |  Start")

        # A. Call API with timing
        start_time = time.time()
        result = self.origin.generate(prompt, model=self.model, max_tokens=max_tokens)
        elapsed = time.time() - start_time

        # B. Show results
        if isinstance(result, dict) and 'usage' in result:
            usage = result['usage']
            print(f"[OK] [{self.element_id}]  {generation_type} | {elapsed:.2f}s | "
                f"{usage.get('input',0)}in/{usage.get('output',0)}out | "
                f"${usage.get('cost',0):.6f} | Completed")

            # C. Save cost async (non-blocking)
            threading.Thread(
                target=self._save_cost_to_disk_threaded,
                args=(usage,),
                daemon=True
            ).start()

            # D. Return FULL dict (not just content) so callers can inspect it
        else:
            print(f"[OK] [{self.element_id}]  {generation_type} | {elapsed:.2f}s (no usage data) | Completed")

        return result

    def _save_cost_to_disk_threaded(self, usage_data):
        """
        Writes cost directly to disk in a background thread.
        
        This is called automatically after each API call to update the
        course metrics file with token usage and cost data from OpenRouter.
        
        Args:
            usage_data: Usage dictionary from API response
        """
        if not self.course_filename:
            return
        
        try:
            # Create a FRESH instance (avoids st.session_state in threads)
            pm = ProgressManager() 
            
            # This writes to 'course_metrics.pkl' and won't touch the main progress file
            pm.update_metrics(self.course_filename, usage_data)
            
        except Exception as e:
            print(f"[WARN] Cost tracking error: {e}")