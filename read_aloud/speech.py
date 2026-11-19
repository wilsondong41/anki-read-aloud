"""Making and playing speech, the same way on every platform.

Each press starts a background job: it makes the audio file (the neural
voice first, if chosen, then the system voices; each kept in a cache) and
plays it. Highlighting text starts the same job without playing, so the
audio is usually ready before the key is pressed.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
import traceback

from aqt import mw
from aqt.qt import QTimer
from aqt.utils import tooltip

from . import config as cfg
from . import text as textmod
from . import voices
from .config import COMPUTER, IS_LINUX, IS_MAC, IS_WIN

CACHE_DIR = os.path.join(cfg.USER_FILES, "edge_cache")  # neural voice clips
RENDER_DIR = os.path.join(cfg.LOCAL_DIR, "voice_cache")  # system voice clips
CACHE_LIMIT = 300e6  # per cache
NEURAL_TIMEOUT = 20  # a hung download (slow or captive network) gives up
NEURAL_PAUSE = 180  # after a failure, the system voice reads at once for this long

_current = None  # the job speaking now
_current_key = None  # (text, slow) it is saying
_prefetching: dict = {}  # audio file → job making it
_neural_paused_until = 0.0
_notices_shown: set = set()


def prepare(text: str, respell: bool = True) -> str:
    return textmod.prepare(text, cfg.pronunciations() if respell else {}, cfg.cleanup())


def _digest(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


# What to try, in order
##############################################################################


def _neural_candidate(spoken: str, slow: bool):
    config = cfg.get()
    if config.get("engine") != "edge" or not voices.NEURAL_OK:
        return None
    voice = config.get("edge_voice")
    voice = voice.strip() if isinstance(voice, str) and voice.strip() else voices.DEFAULT_EDGE
    # Neural voices honour --rate, so other speeds are real slower/faster speech.
    rate = f"{round((cfg.speed(slow) - 1) * 100):+d}%"
    path = os.path.join(CACHE_DIR, _digest(voice, rate, spoken) + ".mp3")
    if os.path.exists(path):
        return {"file": path, "neural": True}  # cached: no need to go online
    edge = voices.edge_command()
    if not edge or time.time() < _neural_paused_until:
        return None
    cmd, env = edge
    return {"file": path, "env": env, "speed": 1.0, "timeout": NEURAL_TIMEOUT, "neural": True,
            "make": [*cmd, "--voice", voice, f"--rate={rate}", f"--text={spoken}",
                     "--write-media", "{out}"]}


def _system_candidates(spoken: str, slow: bool) -> list:
    speed = cfg.speed(slow)
    out = []
    if IS_MAC:
        voice = cfg.get().get("voice")
        voice = voice.strip() if isinstance(voice, str) else "auto"
        rate = int(cfg.number("rate", 0))
        # The chosen (or best) voice, then the Mac's own default voice.
        for name in dict.fromkeys([voices.mac_voice(voice), None]):
            args = ["say"] + (["-v", name] if name else []) + (["-r", str(rate)] if rate else [])
            out.append({"file": os.path.join(RENDER_DIR, _digest("mac", name, rate, spoken) + ".aiff"),
                        "speed": speed, "make": [*args, "-o", "{out}", "-f", "{text}"]})
    elif IS_WIN:
        # The chosen voice, then the Windows defaults (OneCore sounds better).
        for kind, name in dict.fromkeys([voices.win_voice(), ("onecore", ""), ("sapi", "")]):
            out.append({"file": os.path.join(RENDER_DIR, _digest(kind, name, spoken) + ".wav"),
                        "env": {"RA_TEXT": spoken}, "speed": speed,
                        "make": voices.ps_command("-Kind", kind, "-Voice", name, "-Out", "{out}")})
    elif IS_LINUX:
        voice = cfg.get().get("voice")
        args = ["espeak"] + (["-v", voice] if isinstance(voice, str) and voice not in ("auto", "") else [])
        out.append({"file": os.path.join(RENDER_DIR, _digest("espeak", voice, spoken) + ".wav"),
                    "speed": speed, "make": [*args, "-w", "{out}", "-f", "{text}"]})
    return out


def _job(spoken: str, slow: bool, fetch_only: bool = False, lang: str = "en") -> dict:
    neural = _neural_candidate(spoken, slow)
    return {"candidates": ([neural] if neural else []) + _system_candidates(spoken, slow),
            "play": voices.player(), "fetch_only": fetch_only, "spoken": spoken, "lang": lang}


# Running it
##############################################################################


def _kill(child) -> None:
    if child and child.poll() is None:
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                               capture_output=True, timeout=5, creationflags=voices.NO_WINDOW)
            else:
                child.kill()
        except Exception:
            pass


class SpeechJob:
    """Make the audio if it isn't cached yet (trying each candidate in turn),
    then play it, on a background thread. Looks enough like a Popen (poll)
    for the rest of the add-on; stop() ends it at once."""

    def __init__(self, job: dict):
        self.job = job
        self._child = None
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def poll(self):
        return None if self._thread.is_alive() else 0

    def stop(self):
        self._stopped = True
        _kill(self._child)

    def first_file(self):
        candidates = self.job["candidates"]
        return candidates[0]["file"] if candidates else None

    def _call(self, cmd, env=None, timeout=None) -> tuple:
        """Run one program, remembering it so stop() can end it.
        Returns (exit code, error output); -1 when stopped or timed out."""
        if self._stopped:
            return -1, ""
        try:
            child = self._child = subprocess.Popen(
                cmd, env=voices.clean_env(**(env or {})), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=voices.NO_WINDOW)
        except Exception as e:
            return -1, str(e)
        if self._stopped:  # stop() landed between the check above and Popen
            _kill(child)
            return -1, ""
        try:
            _, err = child.communicate(timeout=timeout or 90)
            return child.returncode, (err or b"").decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            _kill(child)  # give up on this candidate only; the next one still runs
            try:
                child.communicate(timeout=5)
            except Exception:
                pass
            return -1, "timed out"

    def _make(self, candidate) -> bool:
        path = candidate["file"]
        # Pressed while the highlight prefetch is still making this same
        # file: wait for it rather than making it a second time.
        pending = _prefetching.get(path)
        while (pending is not None and pending is not self and pending.poll() is None
               and not self._stopped):
            time.sleep(0.05)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return True
        if not candidate.get("make"):
            return False
        base, ext = os.path.splitext(path)
        tmp = f"{base}.{threading.get_ident()}.tmp{ext}"  # `say -o` needs the extension
        text_file = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cmd = list(candidate["make"])
            if "{text}" in cmd:
                # A file, not an argument: "-lactamase" would be read as an option.
                text_file = tmp + ".txt"
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(self.job["spoken"])
            cmd = [tmp if a == "{out}" else text_file if a == "{text}" else a for a in cmd]
            code, err = self._call(cmd, candidate.get("env"), candidate.get("timeout"))
            if code == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, path)
                return True
            if not self._stopped:
                what = "neural voice" if candidate.get("neural") else os.path.basename(cmd[0])
                cfg.log(f"{what} failed ({'exit ' + str(code) if code != -1 else err or 'stopped'}): "
                        f"{err.strip()[-300:]}")
        except Exception:
            cfg.log("making audio failed:\n" + traceback.format_exc())
        finally:
            for f in (tmp, text_file):
                try:
                    if f:
                        os.remove(f)
                except OSError:
                    pass
        return False

    def _run(self):
        try:
            for candidate in self.job["candidates"]:
                if self._stopped:
                    return
                if self._make(candidate):
                    if not self.job["fetch_only"] and self.job["play"]:
                        self._call(self.job["play"](candidate["file"], candidate.get("speed", 1.0)),
                                   timeout=600)
                    return
                if candidate.get("neural") and not self._stopped:
                    _neural_failed(report=not self.job["fetch_only"], lang=self.job.get("lang"))
                if self.job["fetch_only"]:
                    return  # only prefetch the first choice
        except Exception:
            cfg.log("speech failed:\n" + traceback.format_exc())


def _neural_failed(report: bool, lang: str | None = None) -> None:
    """Offline, or edge-tts is out of date (Microsoft changes the service
    now and then): read with the system voice at once for a while."""
    global _neural_paused_until
    _neural_paused_until = time.time() + NEURAL_PAUSE
    if report:
        mw.taskman.run_on_main(lambda: notice("failed", lang))


def _speak_directly(spoken: str, slow: bool):
    """No player for audio files (Linux without mpv): speak directly."""
    if IS_WIN:
        kind, v = voices.win_voice()
        v = v if kind == "sapi" else ""
        sel = f"$s.SelectVoice('{v.replace(chr(39), chr(39) * 2)}'); " if v else ""
        rate = "$s.Rate = -4; " if slow else ""
        ps = (f"Add-Type -AssemblyName System.Speech; "
              f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"{sel}{rate}$s.Speak('{spoken.replace(chr(39), chr(39) * 2)}')")
        return subprocess.Popen([voices.powershell(), "-NoProfile", "-NonInteractive", "-Command", ps],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=voices.NO_WINDOW)
    voice = cfg.get().get("voice")
    cmd = ["espeak", "--stdin"] + (["-v", voice] if isinstance(voice, str) and voice not in ("auto", "") else [])
    if slow:
        cmd += ["-s", "110"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        proc.stdin.write(spoken.encode("utf-8"))
        proc.stdin.close()
    except Exception:
        pass
    return proc


# What the rest of the add-on calls
##############################################################################


def is_speaking() -> bool:
    return _current is not None and _current.poll() is None


def stop() -> None:
    global _current, _current_key
    proc, _current, _current_key = _current, None, None
    if proc is not None and proc.poll() is None:
        if isinstance(proc, SpeechJob):
            proc.stop()
        else:
            _kill(proc)


# Other add-ons (a background video, music) can turn down while Read Aloud
# speaks: the page gets a "read-aloud" event whose detail.speaking is true/false.
_told_page = False
_watching = False


def _watch_speaking() -> None:
    global _watching
    if not _watching:
        _watching = True
        _check_speaking()


def _check_speaking() -> None:
    global _told_page, _watching
    speaking = is_speaking()
    if speaking != _told_page:
        _told_page = speaking
        try:
            mw.web.eval("window.dispatchEvent(new CustomEvent('read-aloud', {detail: {speaking: %s}}))"
                        % ("true" if speaking else "false"))
        except Exception:
            pass
    _watching = speaking
    if speaking:
        QTimer.singleShot(200, _check_speaking)


def _settings(text: str, deck: str | None, context: str) -> dict:
    """The deck's voice (if one is set), then a voice for the text's script
    (Chinese, Japanese, …) if that voice can't read it."""
    values = cfg.deck_settings(deck)
    with cfg.overlay(values):
        return {**values, **voices.for_script(text, context)}


def _stop_card_audio() -> None:
    # The card's own sound would play over the voice (R replays it).
    try:
        from aqt.sound import av_player
        av_player.stop_and_clear_queue()
    except Exception:
        pass


_languages_noted: set = set()


def _remember_language(lang: str) -> None:
    """Languages read on this computer, so the setup window can suggest
    good offline voices for them."""
    if lang == "en" or lang in _languages_noted:
        return
    _languages_noted.add(lang)
    seen = cfg.local_state().get("languages", [])
    if lang not in seen:
        cfg.set_local_state(languages=sorted({*seen, lang}))


def speak(text: str, slow: bool = False, toggle: bool = False, respell: bool = True,
          deck: str | None = None, context: str = "") -> None:
    """Speak text (with the voice of that deck, if one is set). With toggle,
    pressing again while the same text is still being read stops it.
    context: the rest of the card, for telling Japanese kanji from Chinese."""
    global _current, _current_key
    text = (text or "").strip()
    if not text:
        return
    key = (text, slow)
    if toggle and is_speaking() and _current_key == key:
        stop()
        return
    stop()
    _stop_card_audio()
    with cfg.overlay(_settings(text, deck, context)):
        spoken = prepare(text, respell)
        if not spoken:
            return
        if cfg.get().get("engine") == "edge" and voices.NEURAL_OK and voices.edge_command() is None:
            notice("missing")
        lang = voices.reading_language(text, context)
        if deck:  # cards only, not the settings window's samples
            _remember_language(lang)
        job = _job(spoken, slow, lang=lang)
        try:
            proc = SpeechJob(job) if job["play"] else _speak_directly(spoken, slow)
        except FileNotFoundError:
            tooltip("Read Aloud: no voice found. On Linux, install espeak (and mpv for "
                    "the neural voice).", period=8000)
            return
    _current, _current_key = proc, key
    _watch_speaking()


def prefetch(text: str, deck: str | None = None, context: str = "") -> None:
    """Get the audio ready while the text is only highlighted, so the key
    plays at once. The neural voice only does this with edge_prefetch on
    (it sends the text to Microsoft); system voices are made locally."""
    with cfg.overlay(_settings(text or "", deck, context)):
        spoken = prepare((text or "").strip())
        config = cfg.get()
        if not spoken or not voices.player():
            return
        if config.get("engine") == "edge" and not config.get("edge_prefetch", False):
            return
        for path in [p for p, job in _prefetching.items() if job.poll() is not None]:
            del _prefetching[path]
        if len(_prefetching) >= 3:
            return
        job = _job(spoken, slow=False, fetch_only=True)
    first = job["candidates"][0]["file"] if job["candidates"] else None
    if not first or os.path.exists(first) or first in _prefetching:
        return
    if isinstance(_current, SpeechJob) and _current.poll() is None and _current.first_file() == first:
        return  # the key got there first and is already making it
    _prefetching[first] = SpeechJob(job)


def notice(kind: str, lang: str | None = None) -> None:
    """Say (once per session) why the system voice read instead of the
    neural one: "missing" (not set up on this computer) or "failed" (and
    how to get a better offline voice, when the one that read is basic)."""
    if kind in _notices_shown:
        return
    _notices_shown.add(kind)
    if kind == "missing":
        text = (f"Read Aloud: the neural voice isn't set up on this {COMPUTER} yet, "
                "so the robotic system voice read it.<br><b>Click here to install it (one click).</b>")
    else:
        text = ("Read Aloud: the neural voice couldn't be reached, so the offline voice read it "
                "(it tries again in a few minutes).")
        name = voices.LANGUAGE_NAMES.get(lang or "en")
        if name and not voices.has_good_voice(lang or "en", wait=False):
            text += f"<br><b>Click here to make {name} sound natural offline too.</b>"
        else:
            text += "<br>If you're online and this keeps happening, <b>click here to update it.</b>"
    cfg.log(f"notice: {kind}")
    tooltip(text, period=12000)
    _open_setup_on_click(walkthrough=kind == "missing")


def _open_setup_on_click(walkthrough: bool = False) -> None:
    """Clicking the notice opens the natural voice walkthrough (not set up
    yet) or the setup window, instead of a trip through the menus."""
    try:
        from aqt import utils
        from . import setup_window, welcome_window  # here: they import this module
        label = utils._tooltipLabel

        def clicked(event, label=label):
            label.hide()
            if walkthrough:
                welcome_window.open_welcome()
            else:
                setup_window.open_setup()

        label.mousePressEvent = clicked
    except Exception:
        pass


def neural_reset() -> None:
    """After installing or updating the neural voice: try it again at once."""
    global _neural_paused_until
    _neural_paused_until = 0.0
    _notices_shown.discard("failed")


# Caches
##############################################################################


def cache_files() -> list:
    files = []
    for folder in (CACHE_DIR, RENDER_DIR):
        try:
            files += [os.path.join(folder, n) for n in os.listdir(folder)
                      if n.endswith((".mp3", ".wav", ".aiff"))]
        except Exception:
            pass
    return files


def tidy_caches() -> None:
    """Remove leftovers from interrupted downloads, and keep each audio cache
    under CACHE_LIMIT by deleting the clips that were used longest ago."""
    for folder in (CACHE_DIR, RENDER_DIR):
        try:
            files = [os.path.join(folder, n) for n in os.listdir(folder)]
        except Exception:
            continue
        kept = []
        for f in files:
            try:
                if ".tmp" in os.path.basename(f):
                    os.remove(f)
                else:
                    st = os.stat(f)
                    kept.append((max(st.st_atime, st.st_mtime), st.st_size, f))
            except Exception:
                pass
        total = sum(size for _, size, _ in kept)
        for _, size, f in sorted(kept):
            if total <= CACHE_LIMIT:
                break
            try:
                os.remove(f)
                total -= size
            except Exception:
                pass
