"""Finding voices and the programs that speak: macOS `say` voices, Windows
voices (win_tts.ps1), the optional neural voice (edge-tts) and a player."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from functools import lru_cache

from . import config as cfg
from . import text as textmod
from .config import IS_LINUX, IS_MAC, IS_WIN

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def clean_env(**extra) -> dict:
    """Environment for the programs we start: without Anki's own Python
    settings, which would confuse another Python."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env.update(extra)
    return env


def run(cmd, timeout=300, **extra_env):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          timeout=timeout, env=clean_env(**extra_env), creationflags=NO_WINDOW)


def tail(result) -> str:
    return (result.stderr or result.stdout or "").strip()[-400:]


# macOS
##############################################################################

_SAY_LINE = re.compile(r"^(.+?)\s+([a-z]{2,3}_[A-Za-z0-9]+)\s+#")


@lru_cache(maxsize=1)
def mac_voice_list():
    """((name, locale), …) of installed macOS voices. Cleared by Check Again."""
    if not IS_MAC:
        return ()
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ()
    return tuple((m.group(1).strip(), m.group(2))
                 for m in map(_SAY_LINE.match, out.splitlines()) if m)


def is_good_mac_voice(name: str) -> bool:
    return "(premium)" in name.lower() or "(enhanced)" in name.lower()


def mac_has_good_voice() -> bool:
    return any(loc.startswith("en_") and is_good_mac_voice(name) for name, loc in mac_voice_list())


def mac_best_voice():
    installed = {name.lower(): name for name, _ in mac_voice_list()}
    for name in ("Ava (Premium)", "Zoe (Premium)"):
        if name.lower() in installed:
            return installed[name.lower()]
    for name, loc in mac_voice_list():
        if loc.startswith("en_") and is_good_mac_voice(name):
            return name
    for name in ("Ava", "Samantha"):
        if name.lower() in installed:
            return installed[name.lower()]
    return None


def mac_voice(voice: str):
    """The voice to give `say`: the configured one if this Mac has it (the
    config is shared between computers), otherwise the best installed one.
    "default" (None) means the Mac's own Read & Speak voice (which can be a
    Siri voice, something `say -v` can't pick by name)."""
    if voice == "default":
        return None
    if voice not in ("auto", ""):
        installed = {name.lower(): name for name, _ in mac_voice_list()}
        if voice.lower() in installed or not installed:
            return voice
    return mac_best_voice()


# Windows
##############################################################################
# Two kinds: classic "sapi" desktop voices and the "onecore" ones Windows adds
# in Settings → Time & language → Speech. win_tts.ps1 lists them and renders
# speech to a .wav file.

WIN_PS1 = os.path.join(cfg.ADDON_DIR, "win_tts.ps1")


def powershell():
    root = os.environ.get("SystemRoot", r"C:\Windows")
    builtin = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return builtin if os.path.isfile(builtin) else (shutil.which("powershell") or "powershell")


def ps_command(*args):
    return [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-File", WIN_PS1, *args]


@lru_cache(maxsize=1)
def win_voice_list():
    """((value, name, language, gender, kind), …) of installed Windows voices;
    value ("onecore:Microsoft Libby") is what the config stores."""
    if not IS_WIN:
        return ()
    try:
        out = subprocess.run(ps_command("-List"), capture_output=True, timeout=60,
                             creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    except Exception:
        return ()
    voices = []
    for line in out.splitlines():
        cols = line.strip().split("\t")
        if len(cols) == 4 and cols[0] in ("sapi", "onecore") and cols[1]:
            kind, name, lang, gender = cols
            voices.append((f"{kind}:{name}", name, lang, gender, kind))
    return tuple(voices)


_win_lister = None


def win_voices_if_listed():
    """The Windows voices if they're listed already; otherwise () and start
    listing them in the background, so the main thread never waits on it."""
    global _win_lister
    if win_voice_list.cache_info().currsize:
        return win_voice_list()
    if _win_lister is None or not _win_lister.is_alive():
        _win_lister = threading.Thread(target=win_voice_list, daemon=True)
        _win_lister.start()
    return ()


def win_voice():
    """(kind, name) for the configured Windows voice, or ("onecore", "") for
    the Windows default. Not checked against the installed voices (listing
    them is slow); if it's missing, the next choice reads instead."""
    value = cfg.get().get("windows_voice")
    if isinstance(value, str) and ":" in value:
        kind, name = value.split(":", 1)
        if kind in ("sapi", "onecore") and name:
            return kind, name
    return "onecore", ""


# The neural voice (edge-tts)
##############################################################################

EDGE_LIB = os.path.join(cfg.LOCAL_DIR, "edge-tts")
EDGE_WRAPPER = os.path.join(EDGE_LIB, "edge-tts")  # macOS/Linux: runs the pip copy


def anki_python(windowless: bool = False):
    """The Python Anki runs on (for pip). On Windows, windowless picks
    pythonw.exe so no console window flashes up."""
    if IS_WIN:
        names = (["pythonw.exe"] if windowless else []) + ["python.exe"]
        for folder in (os.path.join(sys.prefix, "Scripts"), sys.prefix,
                       os.path.dirname(sys.executable)):
            for name in names:
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    return p
        return None
    for p in (os.path.join(sys.prefix, "bin", "python3"), sys.executable):
        if p and os.path.isfile(p) and os.path.basename(p).startswith("python"):
            return p
    return None


def edge_path():
    custom = cfg.get().get("edge_tts_path")
    candidates = [custom if isinstance(custom, str) else None,
                  shutil.which("edge-tts"),
                  os.path.expanduser("~/.local/bin/edge-tts"),
                  os.path.expanduser(r"~\.local\bin\edge-tts.exe"),
                  EDGE_WRAPPER,
                  "/opt/homebrew/bin/edge-tts", "/usr/local/bin/edge-tts"]
    for p in candidates:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def edge_command():
    """(command, extra env) that runs edge-tts here, or None."""
    path = edge_path()
    if path:
        return [path], {}
    python = None if IS_WIN else anki_python()
    lib = os.path.join(EDGE_LIB, "lib")
    if python and os.path.isdir(os.path.join(lib, "edge_tts")):
        return [python, "-m", "edge_tts"], {"PYTHONPATH": lib}
    return None


def edge_works() -> bool:
    edge = edge_command()
    if not edge:
        return False
    cmd, extra = edge
    try:
        return run([*cmd, "--version"], timeout=60, **extra).returncode == 0
    except Exception:
        return False


RECOMMENDED_EDGE = [
    ("en-US-AvaNeural", "Female"), ("en-US-EmmaNeural", "Female"),
    ("en-US-JennyNeural", "Female"), ("en-US-AriaNeural", "Female"),
    ("en-US-AndrewNeural", "Male"), ("en-US-BrianNeural", "Male"),
    ("en-US-ChristopherNeural", "Male"),
]
DEFAULT_EDGE = "en-US-AvaNeural"

_REGIONS = {
    "US": "US", "GB": "UK", "AU": "Australia", "CA": "Canada", "IN": "India",
    "IE": "Ireland", "NZ": "New Zealand", "SG": "Singapore", "ZA": "South Africa",
    "PH": "Philippines", "KE": "Kenya", "NG": "Nigeria", "HK": "Hong Kong",
    "TZ": "Tanzania",
}

EDGE_VOICES_FILE = os.path.join(cfg.USER_FILES, "edge_voices.json")


def edge_label(voice_id: str, gender: str) -> str:
    """en-US-AvaMultilingualNeural → "Ava Multilingual — US, female"."""
    parts = voice_id.split("-", 2)
    if len(parts) < 3:
        return voice_id
    lang, region, name = parts
    name = re.sub(r"Neural$", "", name)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    where = _REGIONS.get(region, region) if lang == "en" else f"{lang}-{region}"
    star = "★ " if voice_id in dict(RECOMMENDED_EDGE) else ""
    return f"{star}{name} — {where}, {gender.lower()}" if gender else f"{star}{name} — {where}"


def edge_voice_list():
    """[(id, gender)] from edge-tts --list-voices, cached in user_files and
    refreshed monthly (Microsoft adds voices)."""
    cached = []
    try:
        with open(EDGE_VOICES_FILE, encoding="utf-8") as f:
            cached = [tuple(v) for v in json.load(f)]
        if cached and time.time() - os.path.getmtime(EDGE_VOICES_FILE) < 30 * 86400:
            return cached
    except Exception:
        pass
    edge = edge_command()
    if not edge:
        return cached
    try:
        out = run([*edge[0], "--list-voices"], timeout=60, **edge[1]).stdout
    except Exception:
        return cached
    voices = []
    for line in out.splitlines():
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) >= 2 and cols[0].endswith("Neural"):
            voices.append((cols[0], cols[1]))
    if voices:
        os.makedirs(os.path.dirname(EDGE_VOICES_FILE), exist_ok=True)
        with open(EDGE_VOICES_FILE, "w", encoding="utf-8") as f:
            json.dump(voices, f)
    return voices or cached


# Playing audio files
##############################################################################

_MPV_ARGS = ["--no-config", "--no-video", "--really-quiet", "--no-terminal",
             "--force-window=no", "--audio-display=no", "--keep-open=no", "--idle=no"]


@lru_cache(maxsize=1)
def _mpv():
    """Anki's own mpv (its Windows/macOS builds ship one), or one on PATH."""
    try:
        from aqt.sound import _packagedCmd
        path = _packagedCmd(["mpv"])[0][0]
        if os.path.isfile(path):
            return path
    except Exception:
        pass
    return shutil.which("mpv")


def player():
    """A function (file, speed) → command that plays an audio file at that
    speed (pitch kept), or None when there is nothing to play files with."""
    if IS_MAC:
        return lambda file, speed: ["afplay", "-q", "1", "-r", f"{speed:g}", file]
    mpv = _mpv()
    if mpv:
        return lambda file, speed: [mpv, *_MPV_ARGS, f"--speed={speed:g}", file]
    return None


NEURAL_OK = IS_MAC or IS_WIN or (IS_LINUX and _mpv() is not None)
# The config key for the system voice: a Mac voice name means nothing on
# Windows (the config is shared between computers), so each has its own.
VOICE_KEY = "windows_voice" if IS_WIN else "voice"


# A voice for text in another script
##############################################################################
# Highlighted Chinese (Japanese, Korean, Russian, Arabic, …) on a card read
# with an English voice comes out silent or garbled, so it is read with a
# voice of that language instead, without any setting.

EDGE_FOR = {"zh": "zh-CN-XiaoxiaoNeural", "ja": "ja-JP-NanamiNeural", "ko": "ko-KR-SunHiNeural",
            "ru": "ru-RU-SvetlanaNeural", "ar": "ar-SA-ZariyahNeural", "he": "he-IL-HilaNeural",
            "th": "th-TH-PremwadeeNeural", "hi": "hi-IN-SwaraNeural"}
LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German",
                  "it": "Italian", "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese",
                  "ko": "Korean", "ru": "Russian", "ar": "Arabic", "he": "Hebrew", "th": "Thai",
                  "hi": "Hindi"}


def _lang(locale) -> str:
    """"zh_CN" / "zh-CN" / "zh-CN-XiaoxiaoNeural" → "zh"."""
    return (locale or "").replace("_", "-").split("-")[0].lower()


def _pick(options, lang: str):
    """The best of [(value, locale, quality)] for that language: the main
    region (zh-CN, not zh-TW), then the higher quality."""
    main = EDGE_FOR[lang][:5].lower()
    found = [o for o in options if _lang(o[1]) == lang]
    best = max(found, key=lambda o: (o[1].replace("_", "-").lower() == main, o[2]), default=None)
    return best[0] if best else None


def reading_language(text: str, context: str = "") -> str:
    """The language the text is read in: its script's, else the neural
    voice's (a Spanish deck's voice, say)."""
    found = textmod.script_language(text, context)
    edge = cfg.get().get("edge_voice")
    return found[0] if found else _lang(edge if isinstance(edge, str) and edge.strip() else DEFAULT_EDGE)


def has_good_voice(lang: str, wait: bool = True) -> bool:
    """Whether this computer can read the language naturally offline: a
    Premium or Enhanced Mac voice, or any Windows voice (they're decent).
    Without wait, Windows voices not listed yet count as fine."""
    if IS_MAC:
        return any(_lang(loc) == lang and is_good_mac_voice(n) for n, loc in mac_voice_list())
    if IS_WIN:
        installed = win_voice_list() if wait else win_voices_if_listed()
        return not installed or any(_lang(v[2]) == lang for v in installed)
    return True


def for_script(text: str, context: str = "") -> dict:
    """Settings that read text in another script with a voice of its
    language, when the chosen voices can't ({} for ordinary text). The
    English clean-up (K+ → potassium) is off for it either way."""
    found = textmod.script_language(text, context)
    if not found:
        return {}
    lang, langs = found
    config = cfg.get()
    out = {"cleanup": False}
    edge = config.get("edge_voice") if isinstance(config.get("edge_voice"), str) else ""
    edge = edge.strip() or DEFAULT_EDGE
    if _lang(edge) not in langs and "Multilingual" not in edge:
        out["edge_voice"] = EDGE_FOR[lang]
    # A system voice of that language only if one is installed; otherwise
    # the chosen one still reads (as before).
    if IS_MAC:
        voice = config.get("voice") if isinstance(config.get("voice"), str) else "auto"
        if _lang(dict(mac_voice_list()).get(mac_voice(voice.strip()))) not in langs:
            # Premium/Enhanced first, then plain names (Tingting) over the novelty ones (Eddy (…)).
            pick = _pick([(n, loc, (is_good_mac_voice(n), "(" not in n))
                          for n, loc in mac_voice_list()], lang)
            if pick:
                out["voice"] = pick
    elif IS_WIN:
        installed = win_voices_if_listed()  # slow to list: the next press has them
        if installed and _lang({v[0]: v[2] for v in installed}.get(config.get("windows_voice"))) not in langs:
            pick = _pick([(v[0], v[2], v[4] == "onecore") for v in installed], lang)
            if pick:
                out["windows_voice"] = pick
    return out
