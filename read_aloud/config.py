"""Settings (Anki's add-on config, shared between computers by tools like
Loadout), this computer's own state, and the log."""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager

from aqt import mw

ADDON = __name__.split(".")[0]
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILES = os.path.join(ADDON_DIR, "user_files")

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
COMPUTER = "Mac" if IS_MAC else "PC"

# Things for this computer only. Kept outside the add-on folder, because
# tools like Loadout copy user_files to the other computers.
if IS_WIN:
    LOCAL_DIR = os.path.join(os.environ.get("LOCALAPPDATA")
                             or os.path.expanduser(r"~\AppData\Local"), "Read Aloud for Anki")
elif IS_MAC:
    LOCAL_DIR = os.path.expanduser("~/Library/Application Support/Read Aloud for Anki")
else:
    LOCAL_DIR = os.path.expanduser("~/.local/share/read-aloud-for-anki")
LOCAL_STATE = os.path.join(LOCAL_DIR, "state.json")
LOG_PATH = os.path.join(LOCAL_DIR, "read_aloud.log")
LOG_LIMIT = 500_000

# The key that reads (Shift+key reads slowly). Not ones Anki's reviewer
# needs: e (edit), i (card info), o (options), r (replay).
SHORTCUT_KEYS = [c for c in "abcdfghjklmnpqstuvwxyz"]

# Unsaved settings (the settings window's Play buttons), then the settings
# of the deck being studied, on top of the saved ones.
_layers: list[dict] = []


def get() -> dict:
    try:
        config = dict(mw.addonManager.getConfig(ADDON) or {})
    except Exception:
        config = {}
    for layer in _layers:
        config.update(layer)
    return config


def save(config: dict) -> None:
    mw.addonManager.writeConfig(ADDON, config)


@contextmanager
def overlay(values: dict | None):
    """Settings that apply while speech is being set up."""
    if not values:
        yield
        return
    _layers.append(values)
    try:
        yield
    finally:
        _layers.remove(values)


def number(key: str, default: float) -> float:
    value = get().get(key)
    return value if isinstance(value, (int, float)) and value > 0 else default


def speed(slow: bool) -> float:
    """Playback speed: Shift+key uses slow_speed, the plain key speed."""
    if slow:
        return min(number("slow_speed", 0.65), 1.0)
    return min(number("speed", 1.0), 2.0)


def shortcut() -> str:
    key = get().get("shortcut")
    return key.lower() if isinstance(key, str) and key.lower() in SHORTCUT_KEYS else "v"


def cleanup() -> bool:
    """Read medical and science shorthand (K+, ↑, μg) as English words."""
    return get().get("cleanup", True) is not False


def pronunciations() -> dict:
    p = get().get("pronunciations")
    if not isinstance(p, dict):
        return {}
    return {k.strip(): v.strip() for k, v in p.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()}


def save_pronunciations(values: dict) -> None:
    config = get()
    config["pronunciations"] = dict(sorted(values.items(), key=lambda kv: kv[0].lower()))
    save(config)


# Voices for particular decks ("deck_voices": {deck name: {...}}); a deck's
# subdecks use them too.
DECK_KEYS = ("edge_voice", "voice", "windows_voice", "cleanup")


def deck_settings(deck_name: str | None) -> dict:
    if not deck_name:
        return {}
    decks = get().get("deck_voices")
    if not isinstance(decks, dict):
        return {}
    best = ""
    for name in decks:
        if (deck_name == name or deck_name.startswith(name + "::")) and len(name) > len(best):
            best = name
    found = decks.get(best) if best else None
    if not isinstance(found, dict):
        return {}
    return {k: v for k, v in found.items() if k in DECK_KEYS and v not in (None, "")}


# This computer's own state
##############################################################################


def local_state() -> dict:
    try:
        with open(LOCAL_STATE, encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def set_local_state(**values) -> None:
    # Read before opening for writing (that empties the file), and replace
    # the file in one step so a crash can't leave half of it.
    state = {**local_state(), **values}
    try:
        os.makedirs(LOCAL_DIR, exist_ok=True)
        tmp = LOCAL_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, LOCAL_STATE)
    except Exception:
        pass


def log(text: str) -> None:
    """A short log (for when something goes wrong; Settings → Open Log)."""
    try:
        os.makedirs(LOCAL_DIR, exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_LIMIT:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
    except Exception:
        pass
