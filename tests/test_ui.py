"""Test de fumée de l'interface.

Le scénario tourne dans un processus séparé : sous Windows, Qt en mode « offscreen »
peut planter à la fermeture du processus, après la fin du scénario. Le test est donc
jugé sur le marqueur UI-OK, affiché seulement si tout le scénario a réussi."""

import importlib.util
import os
import subprocess
import sys

import pytest

# Pas d'import de Qt dans ce processus : seulement vérifier qu'il est installé.
if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 non installé", allow_module_level=True)

HERE = os.path.dirname(os.path.abspath(__file__))


def test_full_ui(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, os.path.join(HERE, "ui_scenario.py"), str(tmp_path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=300)
    assert "UI-OK" in proc.stdout, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
