import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
SHOTS = DATA / "shots"
SHOTS.mkdir(exist_ok=True)
DB_PATH = DATA / "jobpilot.db"

# Your resume lives HERE, in the visible "resume" folder next to the app.
RESUME_DIR = BASE / "resume"
RESUME_DIR.mkdir(exist_ok=True)
RESUME_EXTS = (".pdf", ".docx", ".txt")

BROWSER_PROFILES = DATA / "browser_profiles"   # your portal logins live here, on your PC only
BROWSER_PROFILES.mkdir(exist_ok=True)
_PORTALS_FILE = DATA / "portals.json"


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5").strip()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", SMTP_USER).strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()

AUTO_SUBMIT = _bool("AUTO_SUBMIT", "true")   # true = bot submits by itself (after first test run)
MIN_MATCH_SCORE = _int("MIN_MATCH_SCORE", 55)
DAILY_APPLY_CAP = _int("DAILY_APPLY_CAP", 25)
RUN_EVERY_MINUTES = _int("RUN_EVERY_MINUTES", 0)
HEADLESS = _bool("HEADLESS", "true")             # Greenhouse / Lever forms
PORTAL_HEADLESS = _bool("PORTAL_HEADLESS", "false")  # Indian portals: visible window is safer
OPEN_BROWSER = _bool("OPEN_BROWSER", "true")
PORT = _int("PORT", 8000)


def _portal_state():
    try:
        return json.loads(_PORTALS_FILE.read_text())
    except Exception:
        return {}


def portal_connected(pid):
    return bool(_portal_state().get(pid))


def set_portal_connected(pid, on):
    s = _portal_state()
    s[pid] = bool(on)
    _PORTALS_FILE.write_text(json.dumps(s))
