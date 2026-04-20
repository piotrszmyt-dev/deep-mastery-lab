"""
Keys Manager
============
Persists API keys to disk as a simple JSON file (data/keys.json by default).

Stores a flat dict of provider_key → api_key strings, e.g.:
    {"openrouter": "sk-or-...", "openai": "sk-..."}

Uses os.fsync() on save to guarantee the write reaches disk before returning.

Cloud mode (cloud_mode=True):
    All disk I/O is skipped. save() is a no-op and load() always returns {}.
    Keys live only in st.session_state for the duration of the user's session,
    preventing cross-user key leakage on shared-filesystem deployments such as
    Streamlit Community Cloud. Activated by setting IS_CLOUD = true in the
    app's Streamlit Secrets (Settings → Secrets in the Cloud dashboard).
"""

import json
import os 
from pathlib import Path

class KeysManager:
    def __init__(self, keys_path: str = "data/keys.json", cloud_mode: bool = False):
        """Creates the KeysManager and ensures the parent directory exists.

        In cloud_mode, all disk I/O is skipped — keys live only in st.session_state
        for the duration of the session, preventing cross-user key leakage on
        shared-filesystem deployments (e.g. Streamlit Community Cloud).
        """
        self.cloud_mode = cloud_mode
        if not cloud_mode:
            self.keys_path = Path(keys_path)
            self.keys_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, keys: dict) -> bool:
        """
        Write all keys to disk, flushing to the OS before returning.
        No-op in cloud_mode (keys are kept in st.session_state by the caller).

        Args:
            keys: Flat dict of provider_key → api_key strings.

        Returns:
            True on success, False if the write failed.
        """
        if self.cloud_mode:
            return True
        try:
            with open(self.keys_path, "w", encoding="utf-8") as f:
                json.dump(keys, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e:
            print(f"[ERROR] Keys save failed: {e}")
            return False

    def load(self) -> dict:
        """
        Load keys from disk.
        Returns {} in cloud_mode — each session starts clean.

        Returns:
            Dict of provider_key → api_key strings, or {} if the file
            doesn't exist, is unreadable, or cloud_mode is active.
        """
        if self.cloud_mode:
            return {}
        if not self.keys_path.exists():
            return {}
        try:
            with open(self.keys_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] Keys load failed: {e}")
            return {}