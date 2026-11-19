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

from aqt.qt import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import read_aloud  # noqa: E402
from read_aloud import config as cfg  # noqa: E402
from read_aloud import setup_window, speech, text, voices  # noqa: E402
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
        ]]
        fake_mw = types.SimpleNamespace(
            addonManager=types.SimpleNamespace(getConfig=lambda name: dict(self.config),
                                               writeConfig=lambda name, c: self.config.update(c)),
            taskman=types.SimpleNamespace(
                run_on_main=lambda f: f(),
                run_in_background=lambda fn, done=None: done(types.SimpleNamespace(result=fn))
                if done else fn()))
        cfg.mw = speech.mw = setup_window.mw = fake_mw
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
    def test_offered_once_per_computer_and_reason(self) -> None:
        shown = []
        found = {"edge": False, "mac_voice": True, "win_voices": 0}
        setup_window.status = lambda quick=False: found
        setup_window.SetupDialog = lambda s: types.SimpleNamespace(show=lambda: shown.append(s))
        self.config = {"engine": "system"}  # a new user: the natural voice is offered anyway
        setup_window.startup_check()
        setup_window.startup_check()  # next start: not again
        self.assertEqual(len(shown), 1)
        if cfg.IS_MAC:
            found["mac_voice"] = False
            setup_window.startup_check()  # something else missing: offered once more
            setup_window.startup_check()
            self.assertEqual(len(shown), 2)

    def test_nothing_offered_when_set_up(self) -> None:
        self.config = {"engine": "edge"}
        self.assertEqual(setup_window.reasons({"edge": True, "mac_voice": True, "win_voices": 0}), set())

    def test_installed_natural_voice_not_in_use_is_offered_once(self) -> None:
        # e.g. a reinstall: edge-tts is still there, but the default is the system voice.
        shown = []
        setup_window.status = lambda quick=False: {"edge": True, "mac_voice": True, "win_voices": 0}
        setup_window.SetupDialog = lambda s: types.SimpleNamespace(show=lambda: shown.append(s))
        self.config = {"engine": "system"}
        setup_window.startup_check()
        setup_window.startup_check()
        self.assertEqual(len(shown), 1)


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
            self.assertEqual(read_aloud._on_card_will_show("Q1", card1, "previewQuestion"), "Q1")
            self.assertEqual(len(stops), 1)
            self.assertIn(read_aloud._JS_NEW_CARD, previewer._web.evals[-1])

            # Flipping to the answer on the same card keeps speech and selection.
            read_aloud._on_card_will_show("A1", card1, "previewAnswer")
            self.assertEqual(len(stops), 1)
            self.assertNotIn(read_aloud._JS_NEW_CARD, previewer._web.evals[-1])

            # Advancing to another card stops speech and clears the selection.
            current[0] = card2
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


if __name__ == "__main__":
    unittest.main()
