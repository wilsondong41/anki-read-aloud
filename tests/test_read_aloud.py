"""Tests for Read Aloud. Needs Anki's own Python (the add-on imports aqt):

    QT_QPA_PLATFORM=offscreen <Anki's python> -m unittest discover -s tests

On a Mac that's ~/Library/Application Support/AnkiProgramFiles/.venv/bin/python.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aqt.qt import QApplication, QCoreApplication, Qt  # noqa: E402
from aqt.qt import QWebEngineView  # noqa: E402,F401  (must load before the app starts)

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
_app = QApplication.instance() or QApplication(["read-aloud-tests"])

import read_aloud  # noqa: E402
from read_aloud import config as cfg  # noqa: E402
from read_aloud import card_text, setup_window, speech, text, voices, welcome_window  # noqa: E402
from read_aloud import settings_window  # noqa: E402,F401  (loads the windows)


class TextTest(unittest.TestCase):
    CASES = [
        ("IL-1β ↑ in sepsis", "IL-1 beta increased in sepsis"),
        ("5 μg/kg", "5 micrograms per kg"),
        ("β-lactamase", "beta-lactamase"),
        ("-lactamase", "-lactamase"),
        ("↑K+ → peaked T waves", "increased potassium leads to peaked T waves"),
        ("Na+/K+ ATPase", "sodium-potassium ATPase"),
        ("Ca2+ and Ca++", "calcium and calcium"),
        ("Cl- and HCO3−", "chloride and bicarbonate"),
        ("Cl- channel", "chloride channel"),
        ("Fe2+ vs Fe3+", "ferrous iron vs ferric iron"),
        ("H+ ions", "hydrogen ions"),
        ("H+ secretion", "hydrogen ion secretion"),
        ("K+-sparing", "potassium-sparing"),
        ("pH < 7.35", "pH less than 7.35"),
        ("x <= 3", "x less than or equal to 3"),
        ("HbA1c ≥ 6.5%", "HbA1c greater than or equal to 6.5%"),
        ("CD4+ T cells", "CD4 positive T cells"),
        ("CD8- cells", "CD8 negative cells"),
        ("Gram+ cocci, Gram- rods", "Gram positive cocci, Gram negative rods"),
        ("HER2+ breast cancer", "HER2 positive breast cancer"),
        ("ANA +ve", "ANA positive"),
        ("mg/dL", "mg per dL"),
        ("10 mL/kg/hr", "10 mL per kg per hr"),
        ("IV -> PO", "IV leads to PO"),
        ("+/- 2", "plus or minus 2"),
        ("37°C", "37 degrees Celsius"),
        ("250 mcg", "250 micrograms"),
        ("~5 mg", "about 5 mg"),
        # Left alone
        ("ER-positive", "ER-positive"),
        ("vitamin K-dependent", "vitamin K-dependent"),
        ("Na-K pump", "Na-K pump"),
        ("MHC I-", "MHC I-"),
        ("1/2 tab", "1/2 tab"),
        ("and/or", "and/or"),
        ("S. aureus", "S. aureus"),
        ("C++", "C++"),
    ]

    def test_card_text_is_read_naturally(self) -> None:
        for raw, spoken in self.CASES:
            self.assertEqual(text.prepare(raw), spoken, raw)

    def test_respellings_win_and_cleanup_can_be_off(self) -> None:
        self.assertEqual(text.prepare("MRSA and K+", {"mrsa": "mursa"}), "mursa and potassium")
        self.assertEqual(text.prepare("¿Dónde está? 5 > 3", cleanup=False), "¿Dónde está? 5 > 3")

    def test_chinese_respellings_match_inside_phrases(self) -> None:
        self.assertEqual(text.respell("银行很大", {"行": "航"}), "银航很大")
        self.assertEqual(text.respell("mrsa MRSAs", {"mrsa": "mursa"}), "mursa MRSAs")

    def test_script_language(self) -> None:
        self.assertEqual(text.script_language("β-lactamase K+"), None)
        self.assertEqual(text.script_language("Hola, ¿qué tal?"), None)
        self.assertEqual(text.script_language("银行")[0], "zh")
        self.assertEqual(text.script_language("学生", context="学生です")[0], "ja")
        self.assertEqual(text.script_language("ありがとう")[0], "ja")
        self.assertEqual(text.script_language("학생")[0], "ko")
        self.assertEqual(text.script_language("спасибо")[0], "ru")


class Sandbox(unittest.TestCase):
    """Settings, local state, caches and Anki's window, all stand-ins."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="read-aloud-test-")
        self.config: dict = {}
        self.tips: list = []
        self.saved = [(mod, name, getattr(mod, name)) for mod, name in [
            (cfg, "mw"), (cfg, "LOCAL_DIR"), (cfg, "LOCAL_STATE"), (cfg, "LOG_PATH"),
            (speech, "mw"), (speech, "tooltip"), (speech, "CACHE_DIR"), (speech, "RENDER_DIR"),
            (voices, "edge_command"), (voices, "player"), (voices, "EDGE_VOICES_FILE"),
            (setup_window, "mw"), (setup_window, "status"), (setup_window, "SetupDialog"),
            (setup_window, "install_edge_tts"), (welcome_window, "mw"),
            (welcome_window, "show_at_startup"), (welcome_window, "tooltip"), (speech, "speak"),
            (settings_window, "mw"), (settings_window, "tooltip"), (voices, "NEURAL_OK"),
        ]]
        fake_mw = types.SimpleNamespace(
            addonManager=types.SimpleNamespace(getConfig=lambda name: dict(self.config),
                                               writeConfig=lambda name, c: self.config.update(c)),
            taskman=types.SimpleNamespace(
                run_on_main=lambda f: f(),
                run_in_background=lambda fn, done=None: done(types.SimpleNamespace(result=fn))
                if done else fn()))
        cfg.mw = speech.mw = setup_window.mw = welcome_window.mw = settings_window.mw = fake_mw
        cfg.LOCAL_DIR = self.tmp
        cfg.LOCAL_STATE = os.path.join(self.tmp, "state.json")
        cfg.LOG_PATH = os.path.join(self.tmp, "read_aloud.log")
        speech.tooltip = lambda message, **kw: self.tips.append(message)
        speech.CACHE_DIR = os.path.join(self.tmp, "neural")
        speech.RENDER_DIR = os.path.join(self.tmp, "system")
        speech._notices_shown.clear()
        speech._prefetching.clear()
        speech._neural_paused_until = 0.0
        speech._languages_noted.clear()
        self.played: list = []
        voices.player = lambda: (lambda file, speed: ["/bin/sh", "-c", f'echo "{file}" >> "{self.tmp}/played"'])

    def tearDown(self) -> None:
        speech.stop()
        for mod, name, value in self.saved:
            setattr(mod, name, value)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def played_files(self) -> list:
        try:
            with open(os.path.join(self.tmp, "played")) as f:
                return f.read().split()
        except OSError:
            return []

    @staticmethod
    def wait(job) -> None:
        job._thread.join(15)


class ConfigTest(Sandbox):
    def test_deck_voice_applies_to_its_subdecks(self) -> None:
        self.config = {"edge_voice": "en-US-AvaNeural", "deck_voices": {
            "Spanish": {"edge_voice": "es-MX-DaliaNeural", "cleanup": False},
            "Spanish::Grammar": {"edge_voice": "es-ES-ElviraNeural"}}}
        self.assertEqual(cfg.deck_settings("Spanish::Vocab")["edge_voice"], "es-MX-DaliaNeural")
        self.assertEqual(cfg.deck_settings("Spanish::Grammar::Verbs")["edge_voice"], "es-ES-ElviraNeural")
        self.assertEqual(cfg.deck_settings("Spanishish"), {})
        with cfg.overlay(cfg.deck_settings("Spanish")):
            self.assertEqual(cfg.get()["edge_voice"], "es-MX-DaliaNeural")
            self.assertFalse(cfg.cleanup())
        self.assertEqual(cfg.get()["edge_voice"], "en-US-AvaNeural")

    def test_local_state_keeps_earlier_values(self) -> None:
        cfg.set_local_state(setup_shown=["edge"])
        cfg.set_local_state(hint_shown=True)
        self.assertEqual(cfg.local_state(), {"setup_shown": ["edge"], "hint_shown": True})

    def test_shortcut_falls_back_to_v(self) -> None:
        for value, key in (("B", "b"), ("e", "v"), ("ctrl+x", "v"), (None, "v")):
            self.config = {"shortcut": value}
            self.assertEqual(cfg.shortcut(), key)


class SetupPromptTest(Sandbox):
    def _watch(self, found):
        """Start-up windows opened: ("walkthrough" | "setup", status)."""
        shown = []
        setup_window.status = lambda quick=False: found
        welcome_window.show_at_startup = lambda s: shown.append(("walkthrough", s))
        setup_window.SetupDialog = lambda s: types.SimpleNamespace(
            show=lambda: shown.append(("setup", s)))
        return shown

    def test_walkthrough_every_start_until_natural_voice_installed(self) -> None:
        shown = self._watch({"edge": False, "mac_voice": True, "win_voices": 0})
        self.config = {"engine": "system"}  # a new user
        for _ in range(3):
            setup_window.startup_check()
        self.assertEqual([kind for kind, _ in shown], ["walkthrough"] * 3)

    def test_dont_show_again_stops_it(self) -> None:
        shown = self._watch({"edge": False, "mac_voice": True, "win_voices": 0})
        cfg.set_local_state(skip_setup_check=True)
        setup_window.startup_check()
        self.assertEqual(shown, [])

    def test_installed_natural_voice_not_in_use_is_offered_every_start(self) -> None:
        # e.g. a reinstall: edge-tts is still there, but the default is the system voice.
        shown = self._watch({"edge": True, "mac_voice": True, "win_voices": 0})
        self.config = {"engine": "system"}
        setup_window.startup_check()
        setup_window.startup_check()
        self.assertEqual([kind for kind, _ in shown], ["walkthrough"] * 2)
        self.config = {"engine": "edge"}  # turned on: no more
        setup_window.startup_check()
        self.assertEqual(len(shown), 2)

    def test_offline_voice_alone_is_offered_once(self) -> None:
        if not cfg.IS_MAC:
            self.skipTest("Mac only")
        shown = self._watch({"edge": True, "mac_voice": False, "win_voices": 0})
        self.config = {"engine": "edge"}
        setup_window.startup_check()
        setup_window.startup_check()
        self.assertEqual([kind for kind, _ in shown], ["setup"])

    def test_no_walkthrough_where_the_natural_voice_cannot_play(self) -> None:
        voices.NEURAL_OK = False  # e.g. Linux without mpv
        self.config = {"engine": "system"}
        self.assertNotIn("edge", setup_window.reasons({"edge": False, "mac_voice": True}))

    def test_nothing_offered_when_set_up(self) -> None:
        self.config = {"engine": "edge"}
        self.assertEqual(setup_window.reasons({"edge": True, "mac_voice": True, "win_voices": 0}), set())


class WalkthroughTest(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.spoken = []
        speech.speak = lambda text, **kw: self.spoken.append(text)
        welcome_window.tooltip = lambda *a, **kw: None
        self.config = {"engine": "system"}

    def _dialog(self, edge=False, startup=True):
        from aqt.qt import QWidget
        self.host = QWidget()  # stands in for Anki's main window
        d = welcome_window.WelcomeDialog({"edge": edge, "mac_voice": True, "win_voices": 0},
                                         self.host, startup=startup)
        d.show()
        return d

    def test_dont_show_again_is_saved_on_close(self) -> None:
        d = self._dialog()
        d.never.setChecked(True)
        d.reject()  # Not Now, or the window's X
        self.assertTrue(cfg.local_state().get("skip_setup_check"))

    def test_not_now_without_the_box_asks_again(self) -> None:
        self._dialog().reject()
        self.assertFalse(cfg.local_state().get("skip_setup_check"))

    def test_no_dont_show_again_when_opened_from_settings(self) -> None:
        d = self._dialog(startup=False)
        self.assertFalse(d.never.isVisible())

    def test_install_turns_it_on_and_says_how_to_use_it(self) -> None:
        setup_window.install_edge_tts = lambda: ""
        d = self._dialog()
        self.assertEqual(d.go_btn.text(), "Install Natural Voice")
        d.go_btn.click()
        self.assertEqual(d.pages.currentIndex(), d.DONE)
        self.assertEqual(self.config.get("engine"), "edge")
        self.assertEqual(self.spoken, [welcome_window.READY])
        self.assertEqual(d.close_btn.text(), "Done")
        d.never.setChecked(True)  # hidden by now; must not count
        d.accept()
        self.assertFalse(cfg.local_state().get("skip_setup_check"))

    def test_failed_install_offers_try_again(self) -> None:
        setup_window.install_edge_tts = lambda: "pip: network unreachable"
        d = self._dialog()
        d.go_btn.click()
        self.assertEqual(d.pages.currentIndex(), d.INSTALLING)
        self.assertTrue(d.error_row.isVisible())
        self.assertFalse(d.details.isVisible())
        self.assertIn("network unreachable", d.details.toPlainText())
        self.assertEqual(self.config.get("engine"), "system")
        setup_window.install_edge_tts = lambda: ""
        d.retry_btn.click()
        self.assertEqual(d.pages.currentIndex(), d.DONE)

    def test_offline_voice_offered_on_last_page_not_again_at_start(self) -> None:
        setup_window.install_edge_tts = lambda: ""
        from aqt.qt import QWidget
        self.host = QWidget()
        d = welcome_window.WelcomeDialog({"edge": False, "mac_voice": False}, self.host)
        d.show()
        d.go_btn.click()
        if cfg.IS_MAC:
            self.assertIn("mac_voice", cfg.local_state().get("setup_shown", []))

    def test_already_downloaded_is_one_click(self) -> None:
        setup_window.install_edge_tts = lambda: self.fail("should not download")
        d = self._dialog(edge=True)
        self.assertEqual(d.go_btn.text(), "Turn On Natural Voice")
        d.go_btn.click()
        self.assertEqual(d.pages.currentIndex(), d.DONE)
        self.assertEqual(self.config.get("engine"), "edge")


class SpeechJobTest(Sandbox):
    def job(self, *candidates, fetch_only=False) -> speech.SpeechJob:
        return speech.SpeechJob({"candidates": list(candidates), "play": voices.player(),
                                 "fetch_only": fetch_only, "spoken": "-lactamase"})

    def cand(self, name, make, **extra) -> dict:
        return {"file": os.path.join(self.tmp, name), "make": make, "speed": 1.0, **extra}

    def test_page_is_told_when_speech_starts_and_stops(self) -> None:
        evals: list = []
        speech.mw.web = types.SimpleNamespace(eval=evals.append)
        speech._told_page = speech._watching = False
        done: list = []
        speech._current = types.SimpleNamespace(poll=lambda: 0 if done else None)
        speech._watch_speaking()
        speech._watch_speaking()  # a second start while speaking doesn't tell it twice
        done.append(True)
        speech._check_speaking()  # what the 200 ms timer does
        self.assertEqual(len(evals), 2)
        self.assertIn("speaking: true", evals[0])
        self.assertIn("speaking: false", evals[1])

    def test_text_goes_in_a_file_so_a_leading_dash_is_read(self) -> None:
        c = self.cand("a.wav", ["/bin/sh", "-c", 'cat "$1" > "$0"', "{out}", "{text}"])
        self.wait(self.job(c))
        with open(c["file"]) as f:
            self.assertEqual(f.read(), "-lactamase")
        self.assertEqual(self.played_files(), [c["file"]])

    def test_failed_neural_voice_explains_once_and_pauses(self) -> None:
        neural = self.cand("n.mp3", ["/usr/bin/false"], neural=True, timeout=20)
        system = self.cand("s.wav", ["/bin/sh", "-c", 'echo audio > "$0"', "{out}"])
        self.wait(self.job(neural, system))
        self.assertEqual(self.played_files(), [system["file"]])
        self.assertEqual(len(self.tips), 1)
        self.assertIn("couldn't be reached", self.tips[0])
        # For the next few minutes the neural voice isn't tried (no 20 s waits) …
        self.config = {"engine": "edge"}
        voices.edge_command = lambda: (["/usr/bin/false"], {})
        self.assertIsNone(speech._neural_candidate("other", False))
        # … but clips already made still play, and Update tries again at once.
        os.makedirs(speech.CACHE_DIR, exist_ok=True)
        cached = speech._digest("en-US-AvaNeural", "+0%", "cached")
        with open(os.path.join(speech.CACHE_DIR, cached + ".mp3"), "w") as f:
            f.write("mp3")
        self.assertIsNotNone(speech._neural_candidate("cached", False))
        speech.neural_reset()
        self.assertIsNotNone(speech._neural_candidate("other", False))
        with open(cfg.LOG_PATH) as f:
            self.assertIn("neural voice failed", f.read())

    def test_hung_download_gives_up_and_the_next_voice_reads(self) -> None:
        neural = self.cand("n.mp3", ["/bin/sleep", "30"], neural=True, timeout=1)
        system = self.cand("s.wav", ["/bin/sh", "-c", 'echo audio > "$0"', "{out}"])
        start = time.time()
        self.wait(self.job(neural, system))
        self.assertLess(time.time() - start, 8)
        self.assertEqual(self.played_files(), [system["file"]])

    def test_key_waits_for_the_highlight_prefetch_instead_of_making_it_twice(self) -> None:
        count = os.path.join(self.tmp, "made")
        make = ["/bin/sh", "-c", f'echo x >> "{count}"; sleep 1; echo audio > "$0"', "{out}"]
        c = self.cand("p.mp3", make)
        prefetch = self.job(c, fetch_only=True)
        speech._prefetching[c["file"]] = prefetch
        time.sleep(0.2)
        self.wait(self.job(c))
        self.wait(prefetch)
        with open(count) as f:
            self.assertEqual(f.read().count("x"), 1)
        self.assertEqual(self.played_files(), [c["file"]])

    def test_stop_ends_it_at_once(self) -> None:
        job = self.job(self.cand("s.wav", ["/bin/sleep", "30"]))
        time.sleep(0.3)
        start = time.time()
        job.stop()
        self.wait(job)
        self.assertLess(time.time() - start, 3)

    def test_neural_voice_not_set_up_is_explained(self) -> None:
        self.config = {"engine": "edge"}
        voices.edge_command = lambda: None
        speech.speak("Klebsiella")
        self.assertTrue(any("isn't set up" in t for t in self.tips))

    @unittest.skipUnless(cfg.IS_MAC, "macOS voices")
    def test_mac_system_voice_renders_and_plays(self) -> None:
        self.config = {"engine": "system", "voice": "auto"}
        speech.speak("-lactamase", deck=None)
        self.wait(speech._current)
        played = self.played_files()
        self.assertEqual(len(played), 1)
        self.assertTrue(played[0].endswith(".aiff") and os.path.getsize(played[0]) > 1000)


class VoiceListTest(Sandbox):
    def test_refreshed_monthly_and_kept_when_offline(self) -> None:
        voices.EDGE_VOICES_FILE = os.path.join(self.tmp, "edge_voices.json")
        with open(voices.EDGE_VOICES_FILE, "w") as f:
            json.dump([["en-US-AvaNeural", "Female"]], f)
        voices.edge_command = lambda: None  # offline / not installed
        self.assertEqual(voices.edge_voice_list(), [("en-US-AvaNeural", "Female")])
        old = time.time() - 40 * 86400
        os.utime(voices.EDGE_VOICES_FILE, (old, old))
        voices.edge_command = lambda: (["/bin/sh", "-c", 'echo "en-GB-SoniaNeural   Female"'], {})
        self.assertEqual(voices.edge_voice_list(), [("en-GB-SoniaNeural", "Female")])


class WindowsVoiceListTest(unittest.TestCase):
    def test_listed_once_in_the_background(self) -> None:
        import functools
        saved, calls = voices.win_voice_list, []

        def slow():
            calls.append(1)
            time.sleep(0.2)
            return (("onecore:Microsoft Huihui", "Huihui", "zh-CN", "Female", "onecore"),)

        voices.win_voice_list = functools.lru_cache(maxsize=1)(slow)
        try:
            self.assertEqual(voices.win_voices_if_listed(), ())  # doesn't wait
            self.assertEqual(voices.win_voices_if_listed(), ())  # still listing: not started twice
            voices._win_lister.join(5)
            self.assertEqual(len(voices.win_voices_if_listed()), 1)
            self.assertEqual(calls, [1])
        finally:
            voices.win_voice_list = saved


class ScriptVoiceTest(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.saved += [(voices, n, getattr(voices, n))
                       for n in ("IS_MAC", "IS_WIN", "mac_voice_list", "win_voice_list",
                                 "win_voices_if_listed")]
        voices.mac_voice_list = lambda: (("Ava (Premium)", "en_US"), ("Eddy (Chinese (Taiwan))", "zh_TW"),
                                         ("Meijia", "zh_TW"), ("Tingting", "zh_CN"))
        voices.win_voice_list = lambda: (("sapi:Microsoft Zira", "Zira", "en-US", "Female", "sapi"),
                                         ("sapi:Microsoft Huihui", "Huihui", "zh-CN", "Female", "sapi"),
                                         ("onecore:Microsoft Huihui", "Huihui", "zh-CN", "Female", "onecore"))
        voices.win_voices_if_listed = voices.win_voice_list

    def test_english_text_keeps_the_chosen_voices(self) -> None:
        self.assertEqual(voices.for_script("Hola β-lactamase"), {})

    def test_chinese_gets_chinese_voices_on_each_platform(self) -> None:
        self.config.update(edge_voice="en-US-AvaNeural", voice="Ava (Premium)",
                           windows_voice="sapi:Microsoft Zira")
        voices.IS_MAC, voices.IS_WIN = True, False
        self.assertEqual(voices.for_script("银行"), {"cleanup": False, "edge_voice": "zh-CN-XiaoxiaoNeural",
                                                     "voice": "Tingting"})
        voices.IS_MAC, voices.IS_WIN = False, True
        self.assertEqual(voices.for_script("银行")["windows_voice"], "onecore:Microsoft Huihui")

    def test_voices_that_read_it_already_are_kept(self) -> None:
        self.config.update(edge_voice="en-US-AvaMultilingualNeural", voice="Meijia")
        voices.IS_MAC, voices.IS_WIN = True, False
        self.assertEqual(voices.for_script("银行"), {"cleanup": False})
        self.config.update(edge_voice="ja-JP-NanamiNeural")
        self.assertNotIn("edge_voice", voices.for_script("学生"))  # kanji on a Japanese voice
        self.assertEqual(voices.for_script("спасибо"), {"cleanup": False, "edge_voice": "ru-RU-SvetlanaNeural"})

    def test_offline_voice_hint_names_the_basic_language(self) -> None:
        voices.IS_MAC, voices.IS_WIN = True, False
        self.assertTrue(voices.has_good_voice("en"))
        self.assertFalse(voices.has_good_voice("zh"))  # only Tingting / Meijia
        speech.notice("failed", "zh")
        self.assertIn("make Chinese sound natural offline", self.tips[-1])
        speech._notices_shown.clear()
        speech.notice("failed", "en")
        self.assertIn("click here to update", self.tips[-1])

    def test_one_permission_prompt_adds_every_needed_windows_voice(self) -> None:
        sent = []
        saved = voices.run
        voices.run = lambda cmd, **kw: sent.append(cmd) or types.SimpleNamespace(returncode=0)
        try:
            self.assertTrue(setup_window.install_win_voices(["zh-CN", "ja-JP"]))
        finally:
            voices.run = saved
        encoded = sent[0][-1].split("'-EncodedCommand','")[1].split("'")[0]
        inner = __import__("base64").b64decode(encoded).decode("utf-16-le")
        self.assertEqual(inner, "try { foreach ($t in @('zh-CN','ja-JP')) { Add-WindowsCapability "
                         "-Online -Name \"Language.TextToSpeech~~~$t~0.0.1.0\" -ErrorAction Stop "
                         "| Out-Null }; exit 0 } catch { exit 1 }")
        self.assertEqual([setup_window._pack_for(l) for l in ("zh", "es", "xx")], ["zh-CN", "es-ES", None])

    def test_languages_read_are_remembered_for_the_setup_window(self) -> None:
        voices.IS_MAC, voices.IS_WIN = True, False
        for lang in ("en", "zh", "ja", "zh"):
            speech._remember_language(lang)
        self.assertEqual(cfg.local_state()["languages"], ["ja", "zh"])
        self.assertEqual(setup_window._names(["zh", "ja", "ko"]), "Chinese, Japanese and Korean")


class PreviewerTest(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.saved += [(read_aloud, "mw", read_aloud.mw),
                       (read_aloud, "AnkiWebView", read_aloud.AnkiWebView),
                       (read_aloud, "Previewer", read_aloud.Previewer)]
        read_aloud._previewers.clear()
        self.decks = {1: "HomeDeck", 2: "FilteredDeck", 3: "ReviewDeck"}
        self.reviewer_card = self._card(99, 3, 0, "reviewer text")
        read_aloud.mw = types.SimpleNamespace(
            state="deckBrowser",
            reviewer=types.SimpleNamespace(card=self.reviewer_card, web=object()),
            col=types.SimpleNamespace(decks=types.SimpleNamespace(name=lambda did: self.decks[did])),
        )

    @staticmethod
    def _card(cid: int, did: int, odid: int, fields: str):
        return types.SimpleNamespace(
            id=cid, did=did, odid=odid,
            note=lambda: types.SimpleNamespace(joined_fields=lambda: fields),
        )

    def test_pycmd_uses_previewer_card_deck_and_context(self) -> None:
        preview_card = self._card(42, 2, 1, "preview kanji context")
        previewer = types.SimpleNamespace(card=lambda: preview_card)
        calls: list = []
        saved_speak = speech.speak
        speech.speak = lambda *a, **kw: calls.append((a, kw))
        try:
            handled = read_aloud._on_pycmd((False, None), "readAloudSlow:vancomycin", previewer)
        finally:
            speech.speak = saved_speak
        self.assertEqual(handled, (True, None))
        self.assertEqual(calls, [(("vancomycin",), {
            "slow": True, "toggle": True,
            "deck": "HomeDeck", "context": "preview kanji context",
        })])

    def test_previewer_injects_and_stops_only_on_card_change_or_close(self) -> None:
        class FakeWeb:
            def __init__(self):
                self.evals: list = []

            def eval(self, js: str):
                self.evals.append(js)

        class FakeSignal:
            def __init__(self):
                self.cbs: list = []

            def connect(self, cb):
                self.cbs.append(cb)

            def emit(self):
                for cb in list(self.cbs):
                    cb(0)

        read_aloud.AnkiWebView = FakeWeb
        card1 = self._card(10, 1, 0, "first")
        card2 = self._card(20, 1, 0, "second")
        current = [card1]
        previewer = types.SimpleNamespace(
            _open=True, _web=FakeWeb(), finished=FakeSignal(), card=lambda: current[0]
        )
        stops: list = []
        saved_stop = speech.stop
        speech.stop = lambda: stops.append(1)
        try:
            read_aloud._on_previewer_init(previewer)
            # Anki: sounds first (the hook), then the card is drawn.
            read_aloud._on_will_play_tags([], "question", previewer)
            self.assertEqual(read_aloud._on_card_will_show("Q1", card1, "previewQuestion"), "Q1")
            self.assertEqual(len(stops), 1)
            self.assertIn(read_aloud._JS_NEW_CARD, previewer._web.evals[-1])

            # Flipping to the answer on the same card keeps speech and selection.
            read_aloud._on_will_play_tags([], "answer", previewer)
            read_aloud._on_card_will_show("A1", card1, "previewAnswer")
            self.assertEqual(len(stops), 1)
            self.assertNotIn(read_aloud._JS_NEW_CARD, previewer._web.evals[-1])

            # Advancing to another card stops speech and clears the selection.
            current[0] = card2
            read_aloud._on_will_play_tags([], "question", previewer)
            read_aloud._on_card_will_show("Q2", card2, "previewQuestion")
            self.assertEqual(len(stops), 2)
            self.assertIn(read_aloud._JS_NEW_CARD, previewer._web.evals[-1])

            # Closing the previewer cleans up and stops speech.
            previewer.finished.emit()
            self.assertEqual(len(stops), 3)
            self.assertNotIn(id(previewer), read_aloud._previewers)
        finally:
            speech.stop = saved_stop

    def test_context_menu_works_in_previewer_outside_review(self) -> None:
        from aqt.qt import QMenu

        preview_card = self._card(55, 1, 0, "amoxicillin clavulanate")
        web = types.SimpleNamespace(
            pageAction=lambda _a: types.SimpleNamespace(isEnabled=lambda: True),
            page=lambda: types.SimpleNamespace(selectedText=lambda: "amoxicillin"),
        )
        previewer = types.SimpleNamespace(_open=True, _web=web, card=lambda: preview_card)
        read_aloud._previewers[id(previewer)] = [previewer, 55]

        menu = QMenu()
        read_aloud._on_context_menu(web, menu)
        labels = [a.text() for a in menu.actions() if a.text()]
        self.assertEqual(labels, ["🔊 Read Aloud", "🐢 Read Slowly", "✏️ Fix Pronunciation…"])

        calls: list = []
        saved_speak = speech.speak
        speech.speak = lambda *a, **kw: calls.append((a, kw))
        try:
            menu.actions()[0].trigger()
        finally:
            speech.speak = saved_speak
        self.assertEqual(calls, [(("amoxicillin",), {
            "deck": "HomeDeck", "context": "amoxicillin clavulanate",
        })])

        # Other non-reviewer, non-previewer webviews stay untouched.
        other_web = types.SimpleNamespace(
            pageAction=lambda _a: types.SimpleNamespace(isEnabled=lambda: True),
            page=lambda: types.SimpleNamespace(selectedText=lambda: "other"),
        )
        other_menu = QMenu()
        read_aloud._on_context_menu(other_web, other_menu)
        self.assertEqual(other_menu.actions(), [])



class SettingsSaveTest(Sandbox):
    def _dialog(self):
        from aqt.qt import QWidget
        settings_window.tooltip = lambda *a, **kw: None
        voices.edge_command = lambda: (["edge-tts"], {})
        self.host = QWidget()
        return settings_window.SettingsDialog(self.host)

    def test_save_keeps_a_voice_turned_on_in_the_background(self) -> None:
        self.config = {"engine": "system"}
        d = self._dialog()
        self.config["engine"] = "edge"  # the walkthrough finished installing meanwhile
        d._save()
        self.assertEqual(self.config["engine"], "edge")

    def test_save_keeps_a_voice_the_person_picked(self) -> None:
        self.config = {"engine": "edge"}
        d = self._dialog()
        d.system_radio.click()
        d._save()
        self.assertEqual(self.config["engine"], "system")


# Reading cards aloud automatically
##############################################################################

ANKING_FRONT = ('<div class="text">{{cloze:Text}}</div>{{One by one}}'
                '{{#Tags}}<div>{{clickable::Tags}}</div>{{/Tags}}')
ANKING_BACK = ('<div class="text">{{edit:cloze:Text}}</div>'
               '{{#Extra}}<button>Extra</button><div>{{edit:Extra}}</div>{{/Extra}}'
               '{{#Lecture Notes}}<div>{{edit:Lecture Notes}}</div>{{/Lecture Notes}}')
BASIC_EXTRA_BACK = ('{{FrontSide}}<hr id=answer>{{Back}}'
                    '{{#Extra}}<div>{{Extra}}</div>{{/Extra}}{{hint:Mnemonic}}')


def fake_card(fields: dict, qfmt: str, afmt: str, cloze: bool, ord_: int = 0,
              sounds: bool = False, did: int = 1, answer_sounds: bool = False,
              autoplay: bool = True):
    class FakeNote:
        def note_type(self):
            return {"type": 1 if cloze else 0, "flds": [{"name": n} for n in fields]}

        def joined_fields(self):
            return "\x1f".join(fields.values())

        def __getitem__(self, key):
            return fields[key]

        def keys(self):
            return list(fields)

    note = FakeNote()
    return types.SimpleNamespace(
        id=7, did=did, odid=0, ord=ord_, note=lambda: note,
        template=lambda: {"qfmt": qfmt, "afmt": afmt},
        question_av_tags=lambda: ["sound"] if sounds else [],
        answer_av_tags=lambda: ["sound"] if answer_sounds else [],
        replay_question_audio_on_answer_side=lambda: True,
        autoplay=lambda: autoplay,
    )


def anking_card(ord_: int = 0, one_by_one: str = "", **kw):
    return fake_card({"Text": "{{c1::Vancomycin}} treats <b>{{c2::MRSA}}</b><br>"
                              "<img src=\"x.png\">[sound:x.mp3]",
                      "Extra": "Red man syndrome", "Lecture Notes": "slide 4",
                      "One by one": one_by_one},
                     ANKING_FRONT, ANKING_BACK, cloze=True, ord_=ord_, **kw)


def basic_card(**kw):
    return fake_card({"Front": "First-line for MRSA?", "Back": "Vancomycin",
                      "Extra": "Red man syndrome", "Mnemonic": "Vanco"},
                     "{{Front}}", BASIC_EXTRA_BACK, cloze=False, **kw)


class CardTextTest(unittest.TestCase):
    def test_cloze_question_says_nothing_for_the_hidden_part(self) -> None:
        self.assertEqual(card_text.question_text(anking_card(0)), "treats MRSA")
        self.assertEqual(card_text.question_text(anking_card(1)), "Vancomycin treats")

    def test_cloze_answer_whole_sentence_or_just_the_words(self) -> None:
        card = anking_card(1)
        self.assertEqual(card_text.answer_text(card), "Vancomycin treats MRSA")
        self.assertEqual(card_text.answer_text(card, card_text.WORDS), "MRSA")

    def test_extra_and_side_fields_never_read(self) -> None:
        for card in (anking_card(0), basic_card()):
            for said in (card_text.question_text(card), card_text.answer_text(card),
                         card_text.answer_text(card, card_text.WORDS)):
                self.assertNotIn("Red man", said)
                self.assertNotIn("slide", said)
                self.assertNotIn("Vanco ", said + " ")

    def test_basic_card_reads_front_then_back_either_way(self) -> None:
        card = basic_card()
        self.assertEqual(card_text.question_text(card), "First-line for MRSA?")
        self.assertEqual(card_text.answer_text(card), "Vancomycin")
        self.assertEqual(card_text.answer_text(card, card_text.WORDS), "Vancomycin")

    def test_reversed_card_back_reads_the_front_field(self) -> None:
        card = fake_card({"Front": "dog", "Back": "perro"}, "{{Back}}",
                         "{{FrontSide}}<hr id=answer>{{Front}}", cloze=False, ord_=1)
        self.assertEqual(card_text.question_text(card), "perro")
        self.assertEqual(card_text.answer_text(card), "dog")

    def test_html_hints_and_nested_clozes(self) -> None:
        self.assertEqual(card_text.plain("a&nbsp;b<div>c</div><script>x()</script>d"), "a b. c. d")
        card = fake_card({"Text": "{{c1::Na+::ion}} and {{c2::K+ via {{c1::ATPase}}}}"},
                         "{{cloze:Text}}", "{{cloze:Text}}", cloze=True)
        self.assertEqual(card_text.question_text(card), "ion and K+ via")
        self.assertEqual(card_text.answer_text(card, card_text.WORDS), "Na+, ATPase")

    def test_how_hidden_parts_are_said(self) -> None:
        cases = [
            ("Does hepatitis E have an envelope? blank", "Does hepatitis E have an envelope?"),
            # Anki's text for the milk-alkali card (a list of hidden values)
            ("How do the following laboratory values change in milk-alkali syndrome?  "
             "PTH: blank  Ca2+: blank  Metabolic blank",
             "How do the following laboratory values change in milk-alkali syndrome? "
             "PTH: Ca2+: Metabolic"),
            ("What are the 3 Ps? blank, blank, and blank", "What are the 3 Ps?"),
            ("Promoters bind [general/specific] transcription factors",
             "Promoters bind general or specific transcription factors"),
            ("Promoters bind blank transcription factors", "Promoters bind transcription factors"),
            ("Is it [yes / no]?", "Is it yes or no?"),
            ("Shown as [...] or [?] or [_]", "Shown as or or"),
            ("PTH is [↑/↓]", "PTH is ↑ or ↓"),
        ]
        for raw, said in cases:
            self.assertEqual(card_text.tidy_spoken(raw), said, raw)
        # On an answer side "blank" is the card's own word.
        self.assertEqual(card_text.tidy_spoken("a blank stare", question=False), "a blank stare")

    def test_question_with_the_answer_on_its_own_line(self) -> None:
        card = fake_card({"Text": "Does hepatitis E have an envelope?<br><br>{{c1::No}}"},
                         "{{cloze:Text}}", "{{cloze:Text}}", cloze=True)
        self.assertEqual(card_text.question_text(card), "Does hepatitis E have an envelope?")
        self.assertEqual(card_text.answer_text(card), "Does hepatitis E have an envelope? No")
        hinted = fake_card({"Text": "Promoters bind {{c1::general::general/specific}} factors"},
                           "{{cloze:Text}}", "{{cloze:Text}}", cloze=True)
        self.assertEqual(card_text.question_text(hinted), "Promoters bind general or specific factors")

    def test_image_occlusion_is_not_read(self) -> None:
        card = fake_card({"Image Occlusion": "{{c1::image-occlusion:rect:left=.1}}"},
                         "{{cloze:Image Occlusion}}", "{{cloze:Image Occlusion}}", cloze=True)
        self.assertEqual(card_text.question_text(card), "")


class AutoReadTest(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.saved += [(read_aloud, "mw", read_aloud.mw), (speech, "prefetch", speech.prefetch),
                       (speech, "stop", speech.stop)]
        read_aloud.mw = types.SimpleNamespace(
            state="review", reviewer=types.SimpleNamespace(card=None, web=None),
            col=types.SimpleNamespace(decks=types.SimpleNamespace(name=lambda did: "AnKing::Micro")))
        self.spoken: list = []
        self.fetched: list = []
        self.stops: list = []
        speech.speak = lambda text, **kw: self.spoken.append((text, kw))
        speech.prefetch = lambda text, **kw: self.fetched.append((text, kw))
        speech.stop = lambda: self.stops.append(1)
        read_aloud._first_review_hint = lambda: None

    def tearDown(self) -> None:
        read_aloud._first_review_hint = type(self)._hint
        super().tearDown()

    _hint = staticmethod(read_aloud._first_review_hint)

    def test_off_by_default_reads_nothing(self) -> None:
        read_aloud._on_show_question(anking_card())
        read_aloud._on_show_answer(anking_card())
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.fetched, [])

    def test_question_read_on_show_with_the_decks_voice(self) -> None:
        self.config = {"auto_read": True}
        read_aloud._on_show_question(anking_card(1))
        self.assertEqual(self.spoken[0][0], "Vancomycin treats")
        self.assertEqual(self.spoken[0][1]["deck"], "AnKing::Micro")
        self.assertNotIn("toggle", self.spoken[0][1])
        # The answer's audio is got ready meanwhile.
        self.assertEqual(self.fetched[0][0], "Vancomycin treats MRSA")
        self.assertTrue(self.fetched[0][1]["online"])

    def test_answer_whole_sentence_by_default_or_just_the_words(self) -> None:
        self.config = {"auto_read": True}
        read_aloud._on_show_answer(anking_card(1))
        self.config = {"auto_read": True, "auto_read_answer": "words"}
        read_aloud._on_show_answer(anking_card(1))
        self.assertEqual([t for t, _ in self.spoken], ["Vancomycin treats MRSA", "MRSA"])

    def test_one_by_one_cards_dont_give_the_answers_away(self) -> None:
        # Each answer is read as it is uncovered instead (RevealTest).
        self.config = {"auto_read": True}
        read_aloud._on_show_question(anking_card(1, one_by_one="y"))
        read_aloud._on_show_answer(anking_card(1, one_by_one="y"))
        self.assertEqual([t for t, _ in self.spoken], ["Vancomycin treats"])
        self.assertEqual(self.fetched, [])  # nothing sent ahead either
        self.assertFalse(card_text.one_by_one(anking_card(1, one_by_one="<br>")))  # empty field

    def test_basic_card_reads_back_not_extra(self) -> None:
        self.config = {"auto_read": True}
        read_aloud._on_show_question(basic_card())
        read_aloud._on_show_answer(basic_card())
        self.assertEqual([t for t, _ in self.spoken], ["First-line for MRSA?", "Vancomycin"])

    def test_cards_with_their_own_sound_are_left_alone(self) -> None:
        self.config = {"auto_read": True}
        read_aloud._on_show_question(basic_card(sounds=True))
        read_aloud._on_show_answer(basic_card(sounds=True))
        self.assertEqual(self.spoken, [])
        # Unless the deck doesn't play sounds by itself: then they're read.
        read_aloud._on_show_question(basic_card(sounds=True, autoplay=False))
        self.assertEqual([t for t, _ in self.spoken], ["First-line for MRSA?"])

    def test_older_anki_without_the_sound_hook_still_stops_on_a_new_card(self) -> None:
        saved = read_aloud._PLAY_HOOK
        read_aloud._PLAY_HOOK = None
        try:
            read_aloud._on_show_question(basic_card())
        finally:
            read_aloud._PLAY_HOOK = saved
        self.assertEqual(len(self.stops), 1)
        read_aloud._on_show_question(basic_card())  # with the hook: stopped there instead
        self.assertEqual(len(self.stops), 1)

    def test_the_setting_alone_turns_it_on_and_off(self) -> None:
        # The deck option "Don't play audio automatically" doesn't matter.
        self.config = {"auto_read": True}
        read_aloud._on_show_question(basic_card(autoplay=False))
        read_aloud._on_show_answer(basic_card(autoplay=False))
        self.assertEqual([t for t, _ in self.spoken], ["First-line for MRSA?", "Vancomycin"])
        self.config = {"auto_read": False}
        read_aloud._on_show_question(basic_card())
        read_aloud._on_show_answer(basic_card())
        self.assertEqual(len(self.spoken), 2)

    def test_sound_only_on_the_answer_still_reads_the_question(self) -> None:
        self.config = {"auto_read": True}
        read_aloud._on_show_question(basic_card(answer_sounds=True))
        self.assertEqual(self.fetched, [])  # its answer won't be read: nothing sent ahead
        read_aloud._on_show_answer(basic_card(answer_sounds=True))
        self.assertEqual([t for t, _ in self.spoken], ["First-line for MRSA?"])

    def test_flipping_stops_the_question_and_leaving_review_stops_it(self) -> None:
        self.config = {"auto_read": True}
        read_aloud._on_show_answer(basic_card())
        self.assertEqual(len(self.stops), 1)
        # A card with its own read-aloud line: that may be speaking, leave it.
        read_aloud._on_show_answer(basic_card(sounds=True))
        self.assertEqual(len(self.stops), 1)
        read_aloud._on_state_change("overview", "review")
        self.assertEqual(len(self.stops), 2)
        read_aloud._on_state_change("review", "overview")
        self.assertEqual(len(self.stops), 2)

    def test_settings_window_saves_the_choices(self) -> None:
        from aqt.qt import QWidget
        settings_window.tooltip = lambda *a, **kw: None
        self.host = QWidget()
        d = settings_window.SettingsDialog(self.host)
        self.assertFalse(d.auto_check.isChecked())
        self.assertFalse(d.answer_combo.isEnabled())  # only matters when it's on
        self.assertEqual(d.answer_combo.currentData(), "whole")
        d.auto_check.setChecked(True)
        self.assertTrue(d.answer_combo.isEnabled())
        d.answer_combo.setCurrentIndex(1)
        d._save()
        self.assertEqual((self.config["auto_read"], self.config["auto_read_answer"]),
                         (True, "words"))
        # Turning it off also stops a card being read right now.
        d = settings_window.SettingsDialog(self.host)
        self.assertTrue(d.auto_check.isChecked())
        d.auto_check.setChecked(False)
        self.stops.clear()
        d._save()
        self.assertIs(self.config["auto_read"], False)
        self.assertEqual(len(self.stops), 1)



# Stopping leftover speech just before a card's sounds play
##############################################################################


def pump(until, seconds: float = 3.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        _app.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return until()


class LeftoverSpeechTest(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.saved += [(speech, "stop", speech.stop), (read_aloud, "mw", read_aloud.mw)]
        self.stops: list = []
        speech.stop = lambda: self.stops.append(1)

    def test_new_card_or_question_stops_it_a_flip_with_nothing_to_play_doesnt(self) -> None:
        card = anking_card()
        reviewer = types.SimpleNamespace(card=card)
        read_aloud.mw = types.SimpleNamespace(reviewer=reviewer)
        read_aloud._audio_cards.clear()
        read_aloud._on_will_play_tags([], "question", reviewer)
        self.assertEqual(len(self.stops), 1)
        read_aloud._on_will_play_tags([], "answer", reviewer)  # flip, nothing to play
        self.assertEqual(len(self.stops), 1)


# AnKing's one-by-one clozes, read as they are uncovered
##############################################################################


class RevealTest(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.saved += [(read_aloud, "mw", read_aloud.mw)]
        self.spoken: list = []
        speech.speak = lambda text, **kw: self.spoken.append((text, kw))
        read_aloud.mw = types.SimpleNamespace(
            state="review", reviewer=types.SimpleNamespace(card=None, web=None),
            col=types.SimpleNamespace(decks=types.SimpleNamespace(name=lambda did: "AnKing::Micro")))

    def test_reveals_are_read_only_with_the_setting_on(self) -> None:
        self.assertFalse(read_aloud._reads_aloud(anking_card()))
        self.config = {"auto_read": True}
        self.assertTrue(read_aloud._reads_aloud(anking_card()))
        self.assertTrue(read_aloud._reads_aloud(anking_card(autoplay=False)))
        self.assertFalse(read_aloud._reads_aloud(None))

    def test_uncovered_cloze_is_read_with_the_decks_voice(self) -> None:
        card = anking_card()
        handled = read_aloud._on_pycmd((False, None), "readAloudReveal:11-deoxycortisol",
                                       types.SimpleNamespace(card=card))
        self.assertEqual(handled, (True, None))
        self.assertEqual(self.spoken[0][0], "11-deoxycortisol")
        self.assertEqual(self.spoken[0][1]["deck"], "AnKing::Micro")

    def test_page_script_reports_each_uncovered_cloze(self) -> None:
        # The injected script in a real browser page, with AnKing's markup
        # for hidden one-by-one clozes, uncovered the way AnKing does it.
        from aqt.qt import QWebEngineView
        view = QWebEngineView()
        page = ("<html><body><div id=qa>17-OHP to "
                "<span class='cloze one-by-one' id=a><span class=cloze-replacer>👑</span>"
                "<span class=cloze-hidden><b>11-deoxycortisol</b></span></span> via "
                "<span class='cloze one-by-one' id=b><span class=cloze-replacer>👑</span>"
                "<span class=cloze-hidden>21-hydroxylase</span></span></div></body></html>")
        loaded = []
        view.loadFinished.connect(lambda ok: loaded.append(ok))
        view.setHtml(page)
        self.assertTrue(pump(lambda: loaded, 15))
        result: list = []

        def js(code):
            done = []
            view.page().runJavaScript(code, lambda r: done.append(r))
            pump(lambda: done, 5)
            return done[0] if done else None

        uncover = ("(function(id){var c=document.getElementById(id);"
                   "c.removeChild(c.querySelector('.cloze-replacer'));"
                   "var h=c.querySelector('.cloze-hidden');c.removeChild(h);"
                   "while(h.childNodes.length)c.appendChild(h.childNodes[0]);})")
        js("window.sent=[];window.pycmd=function(m){window.sent.push(m)};"
           "window.__readAloudKey='v';window.__readAloudReveal=false;" + read_aloud._JS_INJECT)
        js(uncover + "('a')")
        pump(lambda: False, 0.3)
        self.assertEqual(js("window.sent"), [])  # not being read aloud: quiet
        # AnKing setting up the answer side: uncover and at once hide again.
        rehide = ("(function(id){var c=document.getElementById(id);var r=document.createElement('span');"
                  "r.className='cloze-replacer';var h=document.createElement('span');"
                  "h.className='cloze-hidden';while(c.childNodes.length)h.appendChild(c.childNodes[0]);"
                  "c.appendChild(r);c.appendChild(h);})")
        js(rehide + "('a')")  # covered again, as on a fresh card
        js("window.__readAloudReveal=true;window.err=null;try{" + uncover + "('a');" + rehide
           + "('a')}catch(e){window.err=String(e)}")
        self.assertIsNone(js("window.err"))
        pump(lambda: False, 0.3)
        self.assertEqual(js("window.sent"), [])
        js(uncover + "('b')")
        self.assertTrue(pump(lambda: js("window.sent.length") == 1, 3))
        self.assertEqual(js("window.sent"), ["readAloudReveal:21-hydroxylase"])
        from PyQt6 import sip
        sip.delete(view.page())
        sip.delete(view)
        pump(lambda: False, 0.2)



# Taking out the read-aloud lines an earlier test build put in templates
##############################################################################

from read_aloud import template_cleanup  # noqa: E402

PROTECTED = "<!-- ANKIHUB_END -->\n<!-- Do not edit or remove this comment -->\n"
REST = "<!-- Disable accidental website redirects when clicking images -->\n<script>x()</script>"
OLD_FRONT = (PROTECTED + '<!-- Read Aloud: reads the card aloud (Mac: Read Aloud add-on voice; iPhone: Ava). '
             "On/off: deck option \"Don't play audio automatically\". -->\n"
             "{{tts en_US voices=Read_Aloud,Apple_Ava_(Premium),Apple_Zoe_(Premium),Apple_Samantha "
             "speed=1.2:cloze:Text}}\n" + REST)
OLD_BACK = (PROTECTED + '<!-- Read Aloud: reads the card aloud (Mac: Read Aloud add-on voice; iPhone: Ava). '
            "On/off: deck option \"Don't play audio automatically\". Not on one-by-one cards (it would "
            'give away the answers). -->\n'
            "{{^One by one}}{{tts en_US voices=Read_Aloud,Apple_Ava_(Premium),Apple_Zoe_(Premium),"
            "Apple_Samantha speed=1.2:cloze-only:Text}}{{/One by one}}\n" + REST)
OTHERS = "<!--tts en_US voices=Apple_Samantha speed=1.4:cloze-only:Text-->{{tts en_US voices=Apple_Samantha:Front}}"


class TemplateCleanupTest(unittest.TestCase):
    def test_lines_come_out_leaving_the_template_as_it_was(self) -> None:
        self.assertEqual(template_cleanup.clean(OLD_FRONT), PROTECTED + REST)
        self.assertEqual(template_cleanup.clean(OLD_BACK), PROTECTED + REST)
        self.assertEqual(template_cleanup.clean("a {{tts en_US voices=Read_Aloud:Text}} b"), "a  b")

    def test_other_read_aloud_lines_are_left_alone(self) -> None:
        for template in (OTHERS, PROTECTED + REST, "", "{{cloze:Text}}"):
            self.assertEqual(template_cleanup.clean(template), template)

    def test_in_a_real_collection_cards_no_longer_read_by_themselves(self) -> None:
        # A throwaway Anki collection (not the user's): the old line makes Anki
        # play a read-aloud tag on every card; after the cleanup it's gone.
        from anki.collection import Collection
        from anki.sound import TTSTag
        folder = tempfile.mkdtemp()
        col = Collection(os.path.join(folder, "test.anki2"))
        try:
            model = col.models.copy(col.models.by_name("Cloze"))
            model["name"] = "AnKing-like"
            col.models.add_field(model, col.models.new_field("One by one"))
            front, back = model["tmpls"][0]["qfmt"], model["tmpls"][0]["afmt"]
            model["tmpls"][0]["qfmt"] = OLD_FRONT.replace(REST, front)
            model["tmpls"][0]["afmt"] = OLD_BACK.replace(REST, back)
            col.models.update_dict(model)
            note = col.new_note(col.models.by_name("AnKing-like"))
            note["Text"] = "{{c1::Vancomycin}} treats MRSA"
            col.add_note(note, col.decks.id("Default"))
            card = note.cards()[0]
            self.assertTrue(any(isinstance(t, TTSTag) for t in card.question_av_tags()))
            schema = col.db.scalar("select scm from col")
            self.assertEqual(template_cleanup.clean_collection(col), ["AnKing-like"])
            self.assertEqual(col.db.scalar("select scm from col"), schema)  # no full sync
            self.assertEqual(template_cleanup.clean_collection(col), [])  # nothing left: no change
            model = col.models.by_name("AnKing-like")
            self.assertEqual(model["tmpls"][0]["qfmt"], PROTECTED + front)
            self.assertEqual(model["tmpls"][0]["afmt"], PROTECTED + back)
            card = col.get_card(card.id)
            self.assertEqual(card.question_av_tags(), [])
            self.assertEqual(card.answer_av_tags(), [])
            self.assertIn("Vancomycin", card.answer())
        finally:
            col.close()
            shutil.rmtree(folder, ignore_errors=True)

    def test_runs_when_a_profile_opens(self) -> None:
        cleaned = []
        saved = (read_aloud.mw, template_cleanup.clean_collection, read_aloud._checked_setup)
        read_aloud.mw = types.SimpleNamespace(col="the collection")
        template_cleanup.clean_collection = lambda col: cleaned.append(col) or []
        read_aloud._checked_setup = True  # (skip the voice check)
        try:
            read_aloud._on_profile_open()
            read_aloud._on_profile_open()  # every time (another profile may have them)
        finally:
            read_aloud.mw, template_cleanup.clean_collection, read_aloud._checked_setup = saved
        self.assertEqual(cleaned, ["the collection", "the collection"])


class RealCardTest(Sandbox):
    """Real cards from a throwaway Anki collection, through the add-on's
    review hooks: the setting alone decides whether anything is read."""

    def test_off_reads_nothing_on_reads_the_card(self) -> None:
        from anki.collection import Collection
        folder = tempfile.mkdtemp()
        col = Collection(os.path.join(folder, "test.anki2"))
        self.saved += [(read_aloud, "mw", read_aloud.mw), (speech, "prefetch", speech.prefetch),
                       (speech, "stop", speech.stop),
                       (read_aloud, "_first_review_hint", read_aloud._first_review_hint)]
        spoken = []
        speech.speak = lambda text, **kw: spoken.append(text)
        speech.prefetch = lambda *a, **kw: None
        speech.stop = lambda: None
        read_aloud._first_review_hint = lambda: None
        read_aloud.mw = types.SimpleNamespace(state="review", col=col,
                                              reviewer=types.SimpleNamespace(card=None, web=None))
        try:
            note = col.new_note(col.models.by_name("Cloze"))
            note["Text"] = "{{c1::Vancomycin}} treats MRSA"
            note["Back Extra"] = "Red man syndrome"
            col.add_note(note, col.decks.id("Micro"))
            card = note.cards()[0]
            self.config = {"auto_read": False}
            read_aloud._on_show_question(card)
            read_aloud._on_show_answer(card)
            self.assertEqual(spoken, [])
            self.config = {"auto_read": True}
            read_aloud._on_show_question(card)
            read_aloud._on_show_answer(card)
            self.assertEqual(spoken, ["treats MRSA", "Vancomycin treats MRSA"])
        finally:
            col.close()
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
