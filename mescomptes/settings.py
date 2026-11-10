"""Préférences locales (non sensibles) : derniers dossiers ouverts, dossiers d'import."""

import json
import os
import sys


def _config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "MesComptes")
    return os.path.join(os.path.expanduser("~"), ".config", "mescomptes")


def default_data_dir():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"), "Mes Comptes")


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(_config_dir(), "preferences.json")
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def recent_files(self):
        return [p for p in self.get("recent", []) if os.path.exists(p)]

    def add_recent(self, path):
        path = os.path.abspath(path)
        recent = [p for p in self.get("recent", []) if os.path.abspath(p) != path]
        self.set("recent", [path] + recent[:9])
