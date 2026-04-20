"""
Streaming response handler for AI-generated card content.

Provides handle_stream_response(), the single entry point for all streaming
card generation in the LMS layer. Renders the stream directly into the
Streamlit UI via st.write_stream(), captures token usage from the final
chunk, and fires update_course_metrics() to persist cost data.
"""

import streamlit as st
import time
from pathlib import Path
from src.utils.logger import get_logger

_log = get_logger("cards")

def handle_stream_response(
    adapter,
    prompt: str,
    model: str,
    course_path: str = None,
    update_metrics_callback=None,
    element_id: str = "?",
    generation_type: str = "Presentation",
) -> str:
    """
    Stream a card generation response into the Streamlit UI and track cost.

    Calls adapter.generate_stream(), renders chunks live via st.write_stream(),
    then fires update_metrics_callback with the captured usage data once the
    stream completes. Cost is only saved if all three are present: a non-empty
    usage container, course_path, and update_metrics_callback.

    Args:
        adapter:                   Any adapter exposing .generate_stream(prompt, model,
                                   usage_callback). Not OpenRouter-specific.
        prompt (str):              The fully-built prompt to send to the API.
        model (str):               Model identifier string.
        course_path (str, optional): Full path to the course file. The filename is
                                     extracted and passed to update_metrics_callback.
                                     If None, cost tracking is skipped.
        update_metrics_callback:   Optional callable(filename, usage_data) invoked
                                   after a successful stream to persist cost data.
                                   Typically update_course_metrics from usage_tracking.py.

    Returns:
        str: The complete generated response as a single string.
        None: If the stream returns no content or an error. Cost tracking
              is skipped and the caller is responsible for showing an error UI.
    """

    # Cost capture container
    stream_usage_container = {}
    
    def stream_usage_callback(usage_data):
        """Internal callback to capture usage metrics"""
        stream_usage_container.update(usage_data)
    
    print(f"[STREAM] [{element_id}] {generation_type} | {model} | {len(prompt)} chars  |  Start")

    stream_start_time = time.time()

    # Generate stream with usage tracking
    stream_generator = adapter.generate_stream(
        prompt,
        model=model,
        usage_callback=stream_usage_callback
    )

    # Render the stream in Streamlit
    try:
        full_response = st.write_stream(stream_generator)
    except Exception as e:
        _log.error("st.write_stream failed model=%s: %s", model, e)
        stream_elapsed = time.time() - stream_start_time
        print(f"[ERROR] [STREAM] [{element_id}] stream interrupted after {stream_elapsed:.2f}s: {e}")
        return None

    stream_elapsed = time.time() - stream_start_time

    if not full_response:
        print(f"[WARN] [STREAM] [{element_id}] stream returned no content")
        return None

    if "\u274c Error" in full_response:
        print(f"[WARN] [STREAM] [{element_id}] stream returned an error")
        return None

    if stream_usage_container and course_path and update_metrics_callback:
        filename = Path(course_path).name
        update_metrics_callback(filename, stream_usage_container)

    print(f"[OK] [STREAM] [{element_id}]  {generation_type} | {stream_elapsed:.2f}s | "
          f"{stream_usage_container.get('prompt_tokens', 0)}in/"
          f"{stream_usage_container.get('completion_tokens', 0)}out | "
          f"${stream_usage_container.get('cost', 0):.6f} | Completed")

    return full_response