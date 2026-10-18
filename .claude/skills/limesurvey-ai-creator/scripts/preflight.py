#!/usr/bin/env python3
"""Pre-flight check for the limesurvey-ai-creator project. Standard library only.

Run from the project root (or set LIMESURVEY_CREATOR_HOME). Never prints secrets.
"""
import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path

home = Path(os.environ.get("LIMESURVEY_CREATOR_HOME", ".")).resolve()
ok = True


def line(flag, msg):
    global ok
    if flag is False:
        ok = False
    print(("[ OK ] " if flag else "[FAIL] ") + msg)


print(f"Project root: {home}")
line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (need 3.10+)")
line((home / "survey_creator").is_dir(), "survey_creator/ package")
line((home / "config" / "settings.yaml").is_file(), "config/settings.yaml")
line((home / "templates" / "blank.lss").is_file(), "templates/blank.lss (required by the builder)")
line((home / "requirements.txt").is_file(), "requirements.txt")

missing = [m for m in ("yaml", "lxml", "streamlit", "langgraph", "dotenv")
           if importlib.util.find_spec(m) is None]
line(not missing, "Python packages" + (f" missing: {', '.join(missing)}" if missing else ""))

env_file = home / ".env"
has_key = bool(os.environ.get("GROQ_API_KEY")) or (
    env_file.is_file() and "GROQ_API_KEY=" in env_file.read_text(errors="ignore")
    and "your_key_here" not in env_file.read_text(errors="ignore")
)
print(f"[INFO] GROQ_API_KEY set: {'yes' if has_key else 'no'}")
print(f"[INFO] LLM_PROVIDER env: {os.environ.get('LLM_PROVIDER', '(not set, project default is groq)')}")

base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
try:
    with urllib.request.urlopen(base + "/api/tags", timeout=3) as r:
        models = [m["name"] for m in json.load(r).get("models", [])]
    print(f"[ OK ] Ollama reachable at {base}; models: {', '.join(models) or '(none installed)'}")
except Exception as exc:  # noqa: BLE001
    print(f"[INFO] Ollama not reachable at {base} ({type(exc).__name__}). Start with: ollama serve")

print("\nRESULT:", "READY" if ok else "FIX THE [FAIL] ITEMS ABOVE")
sys.exit(0 if ok else 1)
