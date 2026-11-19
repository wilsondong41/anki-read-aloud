"""Setting up a computer: a new one has neither edge-tts nor (on a Mac) a
Premium voice, so everything sounds robotic. The natural voice has its own
guided walkthrough (welcome_window), which opens at every start until it's
on. This window (Settings → Voice Downloads…) updates it and points to the
offline voices; it opens by itself once per computer when only those are
missing."""

from __future__ import annotations

import base64
import os
import shlex
import shutil
import subprocess
import time
import traceback

from aqt import mw
from aqt.qt import QCheckBox, QDialog, QEvent, QHBoxLayout, QLabel, QMenu, QPushButton, Qt, QVBoxLayout
from aqt.utils import showWarning, tooltip

from . import config as cfg
from . import speech, voices
from .config import COMPUTER, IS_MAC, IS_WIN

_VOICE_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.universalaccess?SpokenContent"

# Windows text-to-speech languages (Language.TextToSpeech capabilities).
_WIN_VOICE_PACKS = [
    ("en-US", "English (US)"), ("en-GB", "English (UK)"),
    ("en-AU", "English (Australia)"), ("en-CA", "English (Canada)"),
    ("en-IN", "English (India)"), ("en-IE", "English (Ireland)"),
    ("es-ES", "Spanish (Spain)"), ("es-MX", "Spanish (Mexico)"),
    ("fr-FR", "French"), ("de-DE", "German"), ("it-IT", "Italian"),
    ("pt-BR", "Portuguese (Brazil)"), ("zh-CN", "Chinese (Simplified)"),
    ("ja-JP", "Japanese"), ("ko-KR", "Korean"), ("ru-RU", "Russian"), ("ar-SA", "Arabic"),
    ("he-IL", "Hebrew"), ("th-TH", "Thai"), ("hi-IN", "Hindi"),
]


def status(quick: bool = False) -> dict:
    """Runs programs, so call it from a background thread. quick (at
    start-up): only look for edge-tts instead of starting it, and skip the
    slow Windows voice list."""
    voices.mac_voice_list.cache_clear()
    voices.win_voice_list.cache_clear()
    # Other languages read here that only have basic (or no) offline voices.
    weak = [] if quick else [lang for lang in cfg.local_state().get("languages", [])
                             if lang in voices.LANGUAGE_NAMES and not voices.has_good_voice(lang)]
    return {"edge": voices.edge_command() is not None if quick else voices.edge_works(),
            "mac_voice": IS_MAC and voices.mac_has_good_voice(),
            "win_voices": 0 if quick else len(voices.win_voice_list()),
            "weak_langs": weak}


def reasons(found: dict) -> set:
    """What this computer is missing: the natural voice (offered to every
    new computer, whichever voice is chosen, so new users hear of it), or,
    when it's installed but the robotic voice still reads, the choice of it;
    and on a Mac a high-quality offline voice."""
    if not voices.NEURAL_OK:
        missing = set()  # no way to play it here (Linux without mpv)
    elif not found["edge"]:
        missing = {"edge"}
    elif voices.NEURAL_OK and not _edge_in_use():
        missing = {"choose"}
    else:
        missing = set()
    if IS_MAC and not found["mac_voice"]:
        missing.add("mac_voice")
    return missing


def _edge_in_use() -> bool:
    return voices.NEURAL_OK and cfg.get().get("engine") == "edge"


def _use_edge() -> None:
    config = cfg.get()
    if config.get("engine") != "edge":
        config["engine"] = "edge"
        cfg.save(config)


def _find_uv():
    exe = "uv.exe" if IS_WIN else "uv"
    home = os.path.expanduser("~")
    for p in (shutil.which("uv"), os.path.join(home, ".local", "bin", exe),
              os.path.join(home, ".cargo", "bin", exe), "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def install_edge_tts() -> str:
    """Install (or update to the newest) edge-tts for this computer. Tries,
    in order: uv if it's already there; pip with Anki's own Python into
    EDGE_LIB; and finally installing uv itself (from astral.sh) and using
    that. Returns "" when it works, else what went wrong."""
    problems = []

    def with_uv(uv):
        r = voices.run([uv, "tool", "install", "--force", "--upgrade", "edge-tts"])
        if r.returncode == 0 and voices.edge_works():
            return True
        problems.append(voices.tail(r))
        return False

    uv = _find_uv()
    if uv and with_uv(uv):
        return ""

    python = voices.anki_python()
    if python:
        lib = os.path.join(voices.EDGE_LIB, "lib")
        r = voices.run([python, "-m", "pip", "install", "--disable-pip-version-check",
                        "--no-input", "--upgrade", "--target", lib, "edge-tts"])
        if r.returncode == 0:
            if not IS_WIN:
                # One program to run (edge_path finds it).
                with open(voices.EDGE_WRAPPER, "w", encoding="utf-8") as f:
                    f.write("#!/bin/sh\n# Made by the Read Aloud Anki add-on.\n"
                            "unset PYTHONHOME\n"
                            f"PYTHONPATH={shlex.quote(lib)} exec {shlex.quote(python)} "
                            '-m edge_tts "$@"\n')
                os.chmod(voices.EDGE_WRAPPER, 0o755)
            if voices.edge_works():
                return ""
            problems.append("edge-tts was downloaded but doesn't start.")
        else:
            problems.append(voices.tail(r))

    if not uv:
        if IS_WIN:
            cmd = [voices.powershell(), "-NoProfile", "-ExecutionPolicy", "ByPass",
                   "-Command", "irm https://astral.sh/uv/install.ps1 | iex"]
        else:
            cmd = ["/bin/sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
        r = voices.run(cmd, UV_NO_MODIFY_PATH="1", INSTALLER_NO_MODIFY_PATH="1")
        uv = _find_uv()
        if uv and with_uv(uv):
            return ""
        if not uv:
            problems.append(voices.tail(r) or "Couldn't install uv.")
    return "\n\n".join(p for p in problems if p) or "Unknown error."


def install_win_voices(tags: list) -> bool:
    """Add Windows text-to-speech languages. Windows asks for permission
    (admin) once and then downloads them; this waits until it's done."""
    names = ",".join(f"'{tag}'" for tag in tags)  # tags come from _WIN_VOICE_PACKS
    inner = (f"try {{ foreach ($t in @({names})) {{ Add-WindowsCapability -Online -Name "
             "\"Language.TextToSpeech~~~$t~0.0.1.0\" -ErrorAction Stop | Out-Null }; "
             "exit 0 } catch { exit 1 }")
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    outer = ("$p = Start-Process -FilePath powershell -Verb RunAs -Wait -PassThru "
             f"-WindowStyle Hidden -ArgumentList '-NoProfile','-EncodedCommand','{encoded}'; "
             "exit $p.ExitCode")
    try:
        return voices.run([voices.powershell(), "-NoProfile", "-Command", outer],
                          timeout=1800).returncode == 0
    except Exception:
        return False


def _pack_for(lang: str):
    """The Windows voice pack for a language ("zh" → "zh-CN")."""
    return next((tag for tag, _ in _WIN_VOICE_PACKS if tag.split("-")[0] == lang), None)


def _names(langs) -> str:
    """["zh", "ja"] → "Chinese and Japanese"."""
    names = [voices.LANGUAGE_NAMES[lang] for lang in langs or []]
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


class SetupDialog(QDialog):
    def __init__(self, found: dict, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Read Aloud Setup")
        self.setMinimumWidth(540)
        self._updating = False

        intro = QLabel(f"<b>Choose how Read Aloud sounds on this {COMPUTER}</b><br>"
                       "The natural voice is recommended. It and the extras below are "
                       "free but don't come with the add-on, so each computer needs "
                       "them once.")
        intro.setWordWrap(True)

        self.edge_icon, self.edge_note, self.edge_btn, edge_row = self._row(
            "Natural neural voice (Ava and others)", "Install", self._install)
        # Asked here, where the neural voice is explained: fetching while
        # highlighting is faster, but sends highlighted text to Microsoft.
        self.prefetch = QCheckBox("Get audio ready as soon as I highlight text")
        self.prefetch.setChecked(bool(cfg.get().get("edge_prefetch", False)))
        self.prefetch.toggled.connect(self._prefetch_toggled)
        self.prefetch_note = QLabel("Plays faster, but sends what you highlight to Microsoft "
                                    "even if you don't play it.")
        self.prefetch_note.setWordWrap(True)
        self.prefetch_note.setStyleSheet("color: gray;")
        if IS_WIN:
            self.sys_icon, self.sys_note, self.sys_btn, sys_row = self._row(
                "More Windows voices (work offline)", "Add Voices", self._add_needed_voices)
            self._needed_packs: list = []
            menu = self._packs_menu = QMenu(self.sys_btn)
            self._pack_actions = {}
            for tag, language in _WIN_VOICE_PACKS:
                act = menu.addAction(language)
                act.triggered.connect(lambda _=False, t=tag, l=language: self._add_voices([t], l))
                self._pack_actions[tag] = (act, language)
            menu.addSeparator()
            menu.addAction("Open Windows Speech Settings…").triggered.connect(
                lambda: os.startfile("ms-settings:speech"))
            self.sys_btn.setMenu(menu)
        else:
            self.sys_icon, self.sys_note, self.sys_btn, sys_row = self._row(
                "High-quality voices for when you're offline", "Open Voice Settings…",
                self._open_voice_settings)

        close = self.close_btn = QPushButton("Done")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        self._checked_at = time.time()

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addLayout(edge_row)
        for widget in (self.prefetch, self.prefetch_note):
            row = QHBoxLayout()
            row.addSpacing(34 if widget is self.prefetch else 58)
            row.addWidget(widget, 1)
            layout.addLayout(row)
        if IS_MAC or IS_WIN:
            layout.addLayout(sys_row)
        layout.addSpacing(6)
        layout.addLayout(bottom)
        self._show_status(found)

    @staticmethod
    def _row(title, button_text, action):
        icon = QLabel()
        icon.setStyleSheet("font-size: 18px;")
        icon.setFixedWidth(28)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        name = QLabel(f"<b>{title}</b>")
        note = QLabel()
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        text = QVBoxLayout()
        text.addWidget(name)
        text.addWidget(note)
        button = QPushButton(button_text)
        if action:
            button.clicked.connect(action)
        row = QHBoxLayout()
        row.addWidget(icon)
        row.addLayout(text, 1)
        row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        return icon, note, button, row

    def _show_status(self, found):
        self.status = found
        privacy = ("It uses Microsoft's online Edge read-aloud service, not an official API: "
                   "the text you have read aloud is sent to Microsoft.")
        in_use = bool(found["edge"]) and _edge_in_use()
        if in_use:
            self.edge_icon.setText("✅")
            self.edge_note.setText("In use. If it ever stops working while you're online, "
                                   "click Update.")
            self.edge_btn.setText("Update")
        elif found["edge"]:
            self.edge_icon.setText("💡")
            self.edge_note.setText("Installed, but the system voice reads now. Click Use This "
                                   "Voice to hear it. " + privacy)
            self.edge_btn.setText("Use This Voice")
        else:
            self.edge_icon.setText("⚠️")
            self.edge_note.setText(
                "Not installed, so the robotic system voice reads instead. Install downloads "
                "the free edge-tts helper (about 10 MB, under a minute; if needed, also the uv "
                "installer from astral.sh). " + privacy)
            self.edge_btn.setText("Install")
        self.close_btn.setText("Done" if in_use else "Not Now")
        self.prefetch.setVisible(in_use)
        self.prefetch_note.setVisible(in_use)
        if IS_WIN:
            # Languages that already have voices can't be added again.
            have = {v[2].lower() for v in voices.win_voice_list()}
            for tag, (act, language) in self._pack_actions.items():
                installed = tag.lower() in have
                act.setText(f"{language} — installed" if installed else language)
                act.setEnabled(not installed)
            count = found["win_voices"]
            # Languages read here without a voice: one click adds them all.
            needed = [lang for lang in found.get("weak_langs") or [] if _pack_for(lang)]
            self._needed_packs = [_pack_for(lang) for lang in needed]
            self.sys_btn.setMenu(None if needed else self._packs_menu)
            self.sys_icon.setText("✅" if count and not needed else "⚠️")
            if needed:
                self.sys_btn.setText(f"Add {_names(needed)} Voices")
                one = len(needed) == 1
                self.sys_note.setText(
                    f"No offline voice yet for {_names(needed)}, so {'it' if one else 'they'} "
                    "can't be read when the natural voice can't be reached. Click the button: "
                    f"Windows asks for permission, then downloads {'it' if one else 'them'} in a "
                    f"few minutes. Read Aloud uses {'it' if one else 'them'} by itself.")
            else:
                self.sys_btn.setText("Add Voices")
                self.sys_note.setText(
                    f"{count} voices installed. Add Voices downloads Windows voices for another "
                    "accent or language (Windows asks for permission first). Read Aloud uses "
                    "them by itself for text in that language.")
        elif found["mac_voice"] and not found.get("weak_langs"):
            self.sys_icon.setText("✅")
            self.sys_note.setText(f"Installed ({voices.mac_best_voice()}).")
            self.sys_btn.setVisible(False)
        else:
            # Apple has no link to the voice downloads themselves, so: the
            # page (the button), then exactly what to click there.
            langs = (["en"] if not found["mac_voice"] else []) + list(found.get("weak_langs") or [])
            first, rest = voices.LANGUAGE_NAMES[langs[0]], langs[1:]
            again = f" Do the same for {_names(rest)}." if rest else ""
            self.sys_icon.setText("⚠️")
            self.sys_note.setText(
                f"{_names(langs)} only {'has' if len(langs) == 1 else 'have'} basic voices, so "
                f"{'it sounds' if len(langs) == 1 else 'they sound'} robotic when the natural "
                "voice can't be reached. To fix it:<br>"
                "1. Click Open Voice Settings.<br>"
                "2. Click ⓘ next to System voice.<br>"
                f"3. Click {first} in the list on the left, then the cloud download button next "
                f"to a voice marked Premium (best) or Enhanced.{again}<br>"
                "Then come back: this window notices, and Read Aloud uses the new voice by itself.")
            self.sys_btn.setVisible(True)
        self.adjustSize()  # texts above change length

    def _prefetch_toggled(self, on: bool):
        config = cfg.get()
        config["edge_prefetch"] = on
        cfg.save(config)

    def _install(self):
        if self.status.get("edge") and not _edge_in_use():
            # Installed but not chosen: switch to it, no download.
            _use_edge()
            speech.neural_reset()
            self._show_status(self.status)
            speech.speak("Read Aloud is ready.")
            return
        # In use: the button is Update (the newest edge-tts).
        self._updating = bool(self.status.get("edge"))
        self.edge_btn.setEnabled(False)
        self.edge_btn.setText("Updating…" if self._updating else "Installing…")
        mw.taskman.run_in_background(install_edge_tts, self._installed)

    def _installed(self, future):
        try:
            error = future.result()
        except Exception as e:
            error = str(e)
        what = "update" if self._updating else "install"
        cfg.log(f"neural voice {what}: {error or 'ok'}")
        try:
            self.edge_btn.setEnabled(True)
            self.edge_btn.setText("Try Again")
        except RuntimeError:
            return  # window already closed
        if error:
            showWarning(f"Read Aloud couldn't {what} the neural voice:\n\n" + error, parent=self)
            return
        if not self._updating:
            _use_edge()
        speech.neural_reset()
        self._show_status({**self.status, "edge": True})
        if self._updating:
            tooltip("Neural voice updated", parent=self)
        speech.speak("Read Aloud is ready.")

    def _add_needed_voices(self):
        if self._needed_packs and not self.sys_btn.menu():
            self._add_voices(self._needed_packs, _names(
                [tag.split("-")[0] for tag in self._needed_packs]))

    def _add_voices(self, tags, language):
        self.sys_btn.setEnabled(False)
        self.sys_btn.setText("Installing… (a few minutes)")

        def done(future):
            try:
                ok = future.result()
            except Exception:
                ok = False
            cfg.log(f"Windows voices {tags}: {'ok' if ok else 'failed'}")
            try:
                self.sys_btn.setEnabled(True)
                self.sys_btn.setText("Add Voices")
            except RuntimeError:
                return
            if ok:
                tooltip(f"Added {language} voices", parent=self)
                self._recheck()
            else:
                showWarning(f"Windows didn't add the {language} voices (or the permission request "
                            "was cancelled). You can also add them in Settings → Time & language "
                            "→ Speech → Add voices.", parent=self)

        mw.taskman.run_in_background(lambda: install_win_voices(tags), done)

    def _open_voice_settings(self):
        if subprocess.run(["open", _VOICE_SETTINGS_URL]).returncode != 0:
            subprocess.run(["open", "-b", "com.apple.systempreferences"])

    def _recheck(self):
        self._show_status(status())

    def changeEvent(self, event):
        # Coming back (e.g. from System Settings after downloading a voice):
        # check again, in the background.
        super().changeEvent(event)
        if (event.type() == QEvent.Type.ActivationChange and self.isActiveWindow()
                and time.time() - self._checked_at > 2):
            self._checked_at = time.time()

            def done(future):
                try:
                    self._show_status(future.result())
                except Exception:
                    pass  # window closed meanwhile

            mw.taskman.run_in_background(status, done)


_open_dialog = None  # keeps the start-up window alive while it's open


def open_setup(parent=None):
    SetupDialog(status(), parent).exec()


def startup_check():
    mw.taskman.run_in_background(speech.tidy_caches, lambda future: None)
    if cfg.local_state().get("skip_setup_check"):
        return

    def show(future):
        global _open_dialog
        try:
            _open_dialog = SetupDialog(future.result())
            _open_dialog.show()
        except Exception:
            pass

    def welcome(future):
        try:
            from . import welcome_window  # here: welcome_window imports this module
            welcome_window.show_at_startup(future.result())
        except Exception:
            cfg.log("walkthrough failed to open:\n" + traceback.format_exc())

    def done(future):
        try:
            missing = reasons(future.result())
        except Exception:
            cfg.log("start-up check failed:\n" + traceback.format_exc())
            return
        # The natural voice: the walkthrough at every start until it's on
        # (or "Don't show this again" sets skip_setup_check).
        if missing & {"edge", "choose"}:
            cfg.log(f"walkthrough offered: {sorted(missing)}")
            mw.taskman.run_in_background(status, welcome)
            return
        # Optional extras (a Mac offline voice): once per computer; after
        # that it's in Settings → Voice Downloads….
        shown = set(cfg.local_state().get("setup_shown", []))
        if missing - shown:
            cfg.set_local_state(setup_shown=sorted(shown | missing))
            cfg.log(f"setup offered: {sorted(missing)}")
            mw.taskman.run_in_background(status, show)

    mw.taskman.run_in_background(lambda: status(quick=True), done)
