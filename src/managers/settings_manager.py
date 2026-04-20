"""
Settings Manager
================
Persists and loads global application settings (JSON) to/from disk.
Uses fsync to guarantee writes survive crashes or power loss.
"""

import json
import os 
from pathlib import Path
from typing import Dict, Any

class SettingsManager:
    def __init__(self, settings_path: str = "data/settings/settings.json", cloud_mode: bool = False):
        self.settings_path = Path(settings_path)
        self.cloud_mode = cloud_mode
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, config: Dict[str, Any]) -> bool:
        """Save global application settings to disk. Returns True on success."""
        if self.cloud_mode: return True
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
                f.flush()  
                os.fsync(f.fileno())  
            return True
        except Exception as e:
            print(f"[ERROR] Settings save failed: {e}")
            return False

    def load(self) -> Dict[str, Any]:
        """Load settings from disk. Returns empty dict if file missing or unreadable."""
        if not self.settings_path.exists():
            return {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] Settings load failed: {e}")
            return {}