"""
Progress Manager
================
Persists and loads per-course progress and metrics using the shared
path layout defined in course_paths.py.

Two separate files per course:
- *_progress.pkl  — critical state (current position, passed elements)
- *_metrics.pkl   — auxiliary stats (token usage, cost, time)

Writes are atomic (temp file + os.replace) to prevent corruption.
"""

import pickle
import os
import tempfile

import streamlit as st
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from src.managers.course_paths import get_progress_path, get_metrics_path
from src.utils.logger import get_logger

_log = get_logger("progress")

class ProgressManager:

    def __init__(self, cloud_mode: bool = False):
        self.cloud_mode = cloud_mode

    # --- PATH HELPERS ---
    def _get_progress_path(self, course_filename: str) -> Path:
        return get_progress_path(course_filename)

    def _get_metrics_path(self, course_filename: str) -> Path:
        return get_metrics_path(course_filename)

    # --- CORE METHODS ---
    def save(self, state: Dict, course_filename: str) -> bool:
        """
        Saves ONLY the critical course progress.
        Does NOT touch the metrics file.
        """
        if self.cloud_mode: return True
        if not course_filename: return False
        
        save_file = self._get_progress_path(course_filename)
        
        # Filter out metrics from the main state to keep this file pure
        data_to_save = {
            'current_id': state.get('current_id'),
            'tutor_state': state.get('tutor_state'),
            'passed_elements': state.get('passed_elements', []),
            'ignored_elements': state.get('ignored_elements', []), 
            'timestamp': datetime.now().isoformat(),
            'version': '1.0'
        }
        
        result = self._atomic_write(save_file, data_to_save)
        if not result:
            st.toast("Progress could not be saved.", icon=":material/warning:")
        return result

    def load(self, course_filename: str) -> Optional[Dict]:
        """
        Loads BOTH files and merges them into a single dictionary 
        so the App sees one unified state.
        """
        if not course_filename: return None
        
        progress_path = self._get_progress_path(course_filename)
        metrics_path = self._get_metrics_path(course_filename)
        
        # If the main progress file is missing, the course "doesn't exist" yet
        if not progress_path.exists(): return None
        
        final_state = {}
        
        # 1. Load Critical Progress
        try:
            with open(progress_path, 'rb') as f:
                progress_data = pickle.load(f)
                final_state.update(progress_data)
        except Exception as e:
            _log.error("load progress failed course=%s: %s", course_filename, e)
            st.toast("Progress could not be loaded.", icon=":material/warning:")
            return None
            
        # 2. Load Auxiliary Metrics (Optional)
        # If metrics file is missing or corrupt, we just return empty stats rather than crashing.
        default_metrics = {
            'total_input': 0, 
            'total_output': 0, 
            'total_cost': 0.0, 
            'total_time_seconds': 0.0
        }
        
        try:
            if metrics_path.exists():
                with open(metrics_path, 'rb') as f:
                    metrics_data = pickle.load(f)
                    final_state['metrics'] = metrics_data
            else:
                final_state['metrics'] = default_metrics
        except Exception as e:
            _log.warning("load metrics failed course=%s (using defaults): %s", course_filename, e)
            final_state['metrics'] = default_metrics
            
        return final_state

    def update_metrics(self, course_filename: str, usage_data: Dict = None, time_delta: float = 0.0) -> bool:
        """
        Updates the separate metrics file.
        Accepts Token Usage (usage_data) AND/OR Time Elapsed (time_delta).
        """
        if self.cloud_mode: return True
        if not course_filename: return False
        
        metrics_file = self._get_metrics_path(course_filename)
        
        # 1. Load existing metrics (safely)
        current_metrics = {
            'total_input': 0, 
            'total_output': 0, 
            'total_cost': 0.0, 
            'total_time_seconds': 0.0
        }
        
        if metrics_file.exists():
            try:
                with open(metrics_file, 'rb') as f:
                    loaded = pickle.load(f)
                    current_metrics.update(loaded)
            except (pickle.UnpicklingError, EOFError, OSError) as e:
                _log.warning("metrics file corrupt course=%s (resetting): %s", course_filename, e)

        # 2. Update Tokens/Cost (if provided)
        if usage_data:
            input_tokens = usage_data.get('input', 0) or usage_data.get('prompt_tokens', 0)
            output_tokens = usage_data.get('output', 0) or usage_data.get('completion_tokens', 0)
            cost = usage_data.get('cost', 0.0)

            current_metrics['total_input'] += input_tokens
            current_metrics['total_output'] += output_tokens
            current_metrics['total_cost'] += cost
        
        # 3. Update Time (if provided)
        if time_delta > 0:
            current_metrics['total_time_seconds'] = current_metrics.get('total_time_seconds', 0.0) + time_delta
        
        # 4. Save to Safe File
        return self._atomic_write(metrics_file, current_metrics)

    def exists(self, course_filename: str) -> bool:
        return self._get_progress_path(course_filename).exists()

    # --- INTERNAL HELPER ---
    def _atomic_write(self, filepath: Path, data: Dict) -> bool:
        """Helper to safely write a file using a temp file + rename."""
        try:
            # Write to temp
            fd, temp_path = tempfile.mkstemp(dir=filepath.parent, suffix='.tmp')

            with os.fdopen(fd, 'wb') as f:
                pickle.dump(data, f)
            
            # Atomic replace
            os.replace(temp_path, filepath)
            return True
        except Exception as e:
            _log.error("atomic write failed path=%s: %s", filepath, e)
            return False
        
# =============================================================================
# GRANULAR DELETE HELPERS
# Used by UI tabs for selective cache clearing (progress or metrics independently).
# =============================================================================
        
def clear_course_progress(course_filename: str) -> bool:
    """Delete only the progress file for a course."""
    path = get_progress_path(course_filename)
    if path.exists():
        path.unlink()
        return True
    return False

def clear_course_metrics(course_filename: str) -> bool:
    """Delete only the metrics file for a course."""
    path = get_metrics_path(course_filename)
    if path.exists():
        path.unlink()
        return True
    return False