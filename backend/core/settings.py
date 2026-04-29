"""
MiDM - Settings Manager
Persists user preferences to ~/.midm/settings.json
"""

import json
import logging
from pathlib import Path

log = logging.getLogger("MiDM.settings")

SETTINGS_FILE = Path.home() / ".midm" / "settings.json"

DEFAULTS = {
    "save_dir":                str(Path.home() / "Downloads"),
    "connections":             8,
    "max_simultaneous":        5,
    "theme":                   "dark",
    "auto_retry":              True,
    "max_retries":             3,
    "speed_limit_kbps":        0,        # 0 = unlimited
    "auto_start":              True,
    "notify_on_complete":      True,
    "auto_remove_hours":       0,        # 0 = never
}


class SettingsManager:

    def __init__(self):
        self._settings: dict = {}
        self.load()

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def load(self):
        """Load settings from disk, filling missing keys with defaults."""
        if SETTINGS_FILE.exists():
            try:
                saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                # Merge: saved values override defaults,
                # but any new default keys are added automatically
                self._settings = {**DEFAULTS, **saved}
                log.info("Settings loaded from disk")
            except Exception as e:
                log.error(f"Failed to load settings: {e} — using defaults")
                self._settings = dict(DEFAULTS)
        else:
            self._settings = dict(DEFAULTS)
            self.save()
            log.info("Settings file not found — created with defaults")

    def save(self):
        """Persist current settings to disk."""
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(self._settings, indent=2),
                encoding="utf-8"
            )
            log.info("Settings saved to disk")
        except Exception as e:
            log.error(f"Failed to save settings: {e}", exc_info=True)

    def get(self, key: str, fallback=None):
        return self._settings.get(key, fallback)

    def get_all(self) -> dict:
        return dict(self._settings)

    def update(self, data: dict) -> dict:
        """
        Merge incoming data into settings, validate, then save.
        Returns the final settings dict.
        """
        # Validate types before saving
        if "connections" in data:
            data["connections"] = max(1, min(16, int(data["connections"])))
        if "max_simultaneous" in data:
            data["max_simultaneous"] = max(1, min(10, int(data["max_simultaneous"])))
        if "speed_limit_kbps" in data:
            data["speed_limit_kbps"] = max(0, int(data["speed_limit_kbps"]))
        if "max_retries" in data:
            data["max_retries"] = max(1, min(10, int(data["max_retries"])))
        if "auto_remove_hours" in data:
            data["auto_remove_hours"] = max(0, int(data["auto_remove_hours"]))
        if "theme" in data:
            data["theme"] = data["theme"] if data["theme"] in ("dark", "light") else "dark"

        self._settings.update(data)
        self.save()
        log.info(f"Settings updated: {list(data.keys())}")
        return self.get_all()