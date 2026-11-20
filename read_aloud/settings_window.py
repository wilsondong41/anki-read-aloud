"""The settings window (the add-on's Config button and Tools → Read Aloud
Settings…), voices for particular decks, and the pronunciation windows."""

from __future__ import annotations

from aqt import mw
from aqt.qt import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QStyle,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from aqt.utils import openFolder, tooltip

from . import config as cfg
from . import setup_window, speech, voices, welcome_window
from .config import COMPUTER, IS_MAC, IS_WIN

SAMPLE_TEXT = "Pseudomonas aeruginosa makes β-lactamase"
DECK_SAMPLE = "This is how cards in this deck will sound."


def _select_data(combo, value):
    """Select the item whose data matches value (case-insensitive), adding
    it if it isn't in the list."""
    for i in range(combo.count()):
        data = combo.itemData(i)
        if isinstance(data, str) and data.lower() == (value or "").lower():
            combo.setCurrentIndex(i)
            return
    if value:
        combo.addItem(value, value)
        combo.setCurrentIndex(combo.count() - 1)


def _english_first(lang: str) -> int:
    lang = lang.lower().replace("_", "-")
    return 0 if lang.startswith("en-us") else 1 if lang.startswith("en") else 2


def fill_edge_combo(combo, edge_voices):
    """Neural voices: the recommended ones, then the other English ones,
    then every other language."""
    current = combo.currentData()
    combo.clear()
    recommended = dict(voices.RECOMMENDED_EDGE)
    rest = sorted((v for v in edge_voices if v[0] not in recommended),
                  key=lambda v: (_english_first(v[0]), v[0]))
    for vid, gender in list(voices.RECOMMENDED_EDGE) + rest:
        combo.addItem(voices.edge_label(vid, gender), vid)
    _select_data(combo, current)


def fill_system_combo(combo, win_voices, mac_voices):
    current = combo.currentText() if combo.isEditable() else combo.currentData()
    combo.clear()
    if IS_WIN:
        combo.addItem("Windows default voice", "auto")
        for value, name, lang, gender, kind in sorted(
                win_voices, key=lambda v: (_english_first(v[2]), v[4] != "onecore", v[1].lower())):
            classic = " (classic)" if kind == "sapi" else ""
            combo.addItem(f"{name} — {lang}, {gender.lower()}{classic}", value)
    if IS_MAC:
        best = voices.mac_best_voice()
        combo.addItem(f"Automatic — best installed ({best or 'default'})", "auto")
        combo.addItem("Your Mac's spoken-content voice (set in Read & Speak)", "default")
        quality = lambda n: 0 if "premium" in n.lower() else 1 if "enhanced" in n.lower() else 2  # noqa: E731
        for name, locale in sorted(mac_voices, key=lambda v: (_english_first(v[1]), quality(v[0]),
                                                              v[0].lower())):
            combo.addItem(f"{name} — {locale.replace('_', '-')}", name)
    _select_data(combo, current)


def _is_english_voice(value: str, edge: bool) -> bool:
    """Whether a voice reads English (so medical shorthand is spelled out)."""
    if edge:
        return value.lower().startswith("en-")
    if IS_MAC:
        locale = dict(voices.mac_voice_list()).get(value)
        return locale is None or locale.startswith("en")
    if IS_WIN:
        lang = {v[0]: v[2] for v in voices.win_voice_list()}.get(value)
        return lang is None or lang.lower().startswith("en")
    return True


def _play_button(parent, on_click):
    """▶ next to a voice list."""
    button = QPushButton()
    button.setIcon(parent.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
    button.setFixedWidth(40)
    button.setToolTip("Hear this voice")
    button.clicked.connect(on_click)
    return button


class SettingsDialog(QDialog):
    """Voice, key and speed. Everything else is in the setup window (Voice
    Downloads…), the natural voice walkthrough, the
    deck voices window or the pronunciations window."""

    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Read Aloud Settings")
        self.setMinimumWidth(560)
        config = cfg.get()
        self._edge_voices = list(voices.RECOMMENDED_EDGE)
        voices.mac_voice_list.cache_clear()  # pick up voices downloaded since start-up
        self._mac_voices = list(voices.mac_voice_list()) if IS_MAC else []
        self._win_voices = (list(voices.win_voice_list())
                            if voices.win_voice_list.cache_info().currsize else [])

        # Voice
        self.edge_radio = QRadioButton("Neural voice — most natural (online; text is sent to Microsoft)")
        self.system_radio = QRadioButton("System voice only — works offline")
        self.edge_combo = QComboBox()
        self.system_combo = QComboBox()
        self.system_combo.setEditable(not (IS_MAC or IS_WIN))
        self.edge_status = QLabel()
        self.edge_status.setWordWrap(True)
        self.edge_status.setStyleSheet("color: gray;")
        self._update_edge_status()
        self.system_label = QLabel()
        self.system_label.setStyleSheet("color: gray;")
        decks = QPushButton("Voices for Specific Decks…")
        decks.setToolTip("A different voice for some decks, e.g. a Spanish voice for your Spanish deck")
        decks.clicked.connect(lambda: DeckVoicesDialog(self).exec())

        # Hard to miss: the natural voice isn't on yet, and one button fixes it.
        self.recommend = QFrame()
        self.recommend.setObjectName("raRecommend")
        self.recommend.setStyleSheet(
            "#raRecommend { border: 1px solid rgba(214, 160, 0, 0.85); border-radius: 6px;"
            " background: rgba(255, 196, 0, 0.14); }")
        rec_text = QLabel("⭐ <b>Recommended: the natural voice.</b> It sounds far better than "
                          "the system voice, especially for drug names, bacteria and Latin terms.")
        rec_text.setWordWrap(True)
        self.recommend_btn = QPushButton()
        self.recommend_btn.setDefault(False)
        self.recommend_btn.setAutoDefault(False)
        self.recommend_btn.clicked.connect(self._recommend_clicked)
        rl = QHBoxLayout(self.recommend)
        rl.addWidget(rec_text, 1)
        rl.addWidget(self.recommend_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        voice_box = QGroupBox("Voice")
        vl = QVBoxLayout(voice_box)
        if voices.NEURAL_OK:
            vl.addWidget(self.recommend)
            vl.addWidget(self.edge_radio)
            vl.addLayout(self._indented(self.edge_combo,
                                        _play_button(self, lambda: self._preview(False, "edge"))))
            vl.addLayout(self._indented(self.edge_status))
        vl.addWidget(self.system_radio)
        # Always selectable: with the neural voice on, this is its backup.
        vl.addLayout(self._indented(self.system_label))
        vl.addLayout(self._indented(self.system_combo,
                                    _play_button(self, lambda: self._preview(False, "system"))))
        decks_row = QHBoxLayout()
        decks_row.addStretch(1)
        decks_row.addWidget(decks)
        vl.addLayout(decks_row)
        self.edge_radio.toggled.connect(self._update_enabled)
        # Only a voice the person picked here is saved: the walkthrough can
        # turn the natural voice on in the background while this is open.
        self._voice_picked = False
        for radio in (self.edge_radio, self.system_radio):
            radio.clicked.connect(self._picked_voice)

        # Key and speed
        self.key_combo = QComboBox()
        for key in cfg.SHORTCUT_KEYS:
            self.key_combo.addItem(key.upper(), key)
        self.key_combo.currentIndexChanged.connect(self._update_key_labels)
        self.key_note = QLabel()
        self.key_note.setStyleSheet("color: gray;")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_combo)
        key_row.addWidget(self.key_note, 1)
        self.speed_slider, speed_row = self._slider(50, 200, config.get("speed", 1.0))
        self.slow_slider, slow_row = self._slider(30, 100, config.get("slow_speed", 0.65))
        slow_row.addWidget(_play_button(self, lambda: self._preview(True)))
        speed_box = QGroupBox("Key and speed")
        sf = QFormLayout(speed_box)
        sf.addRow("Read with:", key_row)
        self.speed_label, self.slow_label = QLabel(), QLabel()
        sf.addRow(self.speed_label, speed_row)
        sf.addRow(self.slow_label, slow_row)

        # Reading cards aloud automatically
        self.auto_check = QCheckBox("Read cards aloud automatically")
        self.auto_check.setToolTip("The question when it shows, then the answer when you flip it. "
                                   "Press the key to stop it.")
        self.answer_combo = QComboBox()
        self.answer_combo.addItem("the whole sentence with the answer filled in", "whole")
        self.answer_combo.addItem("just the answer words", "words")
        self.auto_note = QLabel("Only the card's main text is read (never Extra or other side "
                                "fields). Cards with their own sound or read-aloud line are "
                                "left alone: those follow the deck option \u201cDon't play "
                                "audio automatically\u201d.")
        self.auto_note.setWordWrap(True)
        self.auto_note.setStyleSheet("color: gray;")
        answer_row = QHBoxLayout()
        answer_row.addSpacing(24)
        answer_row.addWidget(QLabel("On the answer side, read:"))
        answer_row.addWidget(self.answer_combo, 1)
        auto_box = QGroupBox("Reading cards")
        al = QVBoxLayout(auto_box)
        al.addWidget(self.auto_check)
        al.addLayout(answer_row)
        al.addLayout(self._indented(self.auto_note))
        self.auto_check.toggled.connect(self._update_auto)

        # The rest, out of the way
        pron = QPushButton("Pronunciations…")
        pron.setToolTip("Words you've taught it to say differently (right-click a word on a card "
                        "→ Fix Pronunciation… to add one)")
        pron.clicked.connect(lambda: PronunciationListDialog(self).exec())
        setup = QPushButton("Voice Downloads…")
        setup.setToolTip("Update the natural voice, or add offline voices and languages")
        setup.clicked.connect(self._run_setup)
        log = QPushButton("Open Log")
        log.setToolTip("Details of anything that went wrong")
        log.clicked.connect(lambda: openFolder(cfg.LOCAL_DIR))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        for b in (pron, setup, log):
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(voice_box)
        layout.addWidget(speed_box)
        layout.addWidget(auto_box)
        layout.addLayout(bottom)

        self._load(config)
        self._load_voice_lists()

    def _load_voice_lists(self):
        """The full lists take a moment (they run programs), so they arrive
        in the background; the window starts with what's already known."""
        if voices.NEURAL_OK and voices.edge_command():
            mw.taskman.run_in_background(voices.edge_voice_list, self._on_edge_voices)
        if IS_WIN:
            mw.taskman.run_in_background(voices.win_voice_list, self._on_win_voices)

    def _update_edge_status(self):
        self.edge_status.setText(
            "If you're offline, the voice below reads instead." if voices.edge_command() else
            f"Not installed on this {COMPUTER} yet: click Install Natural Voice above.")

    def _update_recommend(self):
        installed = voices.edge_command() is not None
        on = installed and self.edge_radio.isChecked()
        self.recommend.setVisible(voices.NEURAL_OK and not on)
        self.recommend_btn.setText("Turn On Natural Voice" if installed else "Install Natural Voice")

    def _picked_voice(self):
        self._voice_picked = True

    def _recommend_clicked(self):
        if voices.edge_command():
            # Already downloaded: choose it here (saved with Save) and let them hear it.
            self.edge_radio.setChecked(True)
            self._voice_picked = True
            self._preview(False, "edge")
            return
        welcome_window.open_welcome(self)
        self._after_setup()

    def _update_key_labels(self):
        key = (self.key_combo.currentData() or "v").upper()
        self.speed_label.setText(f"Normal ({key}):")
        self.slow_label.setText(f"Slow (Shift+{key}):")
        self.key_note.setText(f"Highlight text on a card, then press {key}. Shift+{key} reads slowly.")

    def _run_setup(self):
        setup_window.open_setup(self)
        self._after_setup()

    def _after_setup(self):
        # Setup may have turned the natural voice on: show that here, so
        # Save doesn't switch it back.
        if setup_window._edge_in_use() and voices.edge_command():
            self.edge_radio.setChecked(True)
        self._update_edge_status()
        self._update_recommend()
        self._mac_voices = list(voices.mac_voice_list())
        self._fill_voice_lists()
        self._load_voice_lists()

    # layout helpers

    @staticmethod
    def _indented(widget, extra=None):
        row = QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(widget, 1)
        if extra:
            row.addWidget(extra)
        return row

    @staticmethod
    def _slider(lo, hi, value):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        label = QLabel()
        label.setMinimumWidth(44)
        slider.valueChanged.connect(lambda v: label.setText(f"{v}%"))
        slider.setValue(round(float(value) * 100) if isinstance(value, (int, float)) else 100)
        label.setText(f"{slider.value()}%")
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(label)
        return slider, row

    # voice lists

    def _fill_voice_lists(self):
        if self.edge_combo.currentData() is None:
            self.edge_combo.addItem(self._pending_edge, self._pending_edge)
        fill_edge_combo(self.edge_combo, self._edge_voices)
        if not self.system_combo.isEditable() and self.system_combo.currentData() is None:
            self.system_combo.addItem(self._pending_system, self._pending_system)
        fill_system_combo(self.system_combo, self._win_voices, self._mac_voices)

    def _on_edge_voices(self, future):
        try:
            found = future.result()
            if found:
                self._edge_voices = found
                self._fill_voice_lists()
        except Exception:
            pass  # window already closed, or edge-tts offline: keep the short list

    def _on_win_voices(self, future):
        try:
            found = future.result()
            if found:
                self._win_voices = list(found)
                self._fill_voice_lists()
        except Exception:
            pass

    def _system_value(self):
        if IS_MAC or IS_WIN:
            return self.system_combo.currentData()
        return self.system_combo.currentText().strip()

    def _update_auto(self):
        self.answer_combo.setEnabled(self.auto_check.isChecked())

    def _update_enabled(self):
        edge = self.edge_radio.isChecked() and voices.NEURAL_OK
        self.edge_combo.setEnabled(edge)
        self._update_recommend()
        self.system_label.setText(
            "Backup voice, for when the neural voice can't be reached:" if edge else "Voice:")

    # settings ⇄ widgets

    def _load(self, config):
        self._pending_edge = config.get("edge_voice") or voices.DEFAULT_EDGE
        self._pending_system = config.get(voices.VOICE_KEY) or "auto"
        self.edge_combo.clear()
        self.system_combo.clear()
        if self.system_combo.isEditable():
            self.system_combo.setEditText("" if self._pending_system == "auto" else self._pending_system)
        self._fill_voice_lists()
        use_edge = voices.NEURAL_OK and config.get("engine") == "edge"
        (self.edge_radio if use_edge else self.system_radio).setChecked(True)
        self._update_enabled()
        self.speed_slider.setValue(round(float(config.get("speed", 1.0)) * 100))
        self.slow_slider.setValue(round(float(config.get("slow_speed", 0.65)) * 100))
        key = config.get("shortcut")
        _select_data(self.key_combo, key if key in cfg.SHORTCUT_KEYS else "v")
        self._update_key_labels()
        self.auto_check.setChecked(config.get("auto_read") is True)
        _select_data(self.answer_combo,
                     "words" if config.get("auto_read_answer") == "words" else "whole")
        self._update_auto()

    def _values(self) -> dict:
        return {
            "engine": "edge" if self.edge_radio.isChecked() and voices.NEURAL_OK else "system",
            "edge_voice": self.edge_combo.currentData() or voices.DEFAULT_EDGE,
            voices.VOICE_KEY: self._system_value() or ("auto" if IS_MAC or IS_WIN else ""),
            "speed": self.speed_slider.value() / 100,
            "slow_speed": self.slow_slider.value() / 100,
            "shortcut": self.key_combo.currentData() or "v",
            "auto_read": self.auto_check.isChecked(),
            "auto_read_answer": self.answer_combo.currentData() or "whole",
        }

    def _preview(self, slow, engine=None):
        values = self._values()
        if engine:
            values["engine"] = engine
        with cfg.overlay(values):
            speech.speak(SAMPLE_TEXT, slow=slow)

    def _save(self):
        speech.stop()
        config = cfg.get()
        values = self._values()
        if not self._voice_picked:
            values.pop("engine")  # keep what's saved (setup may have changed it)
        config.update(values)
        cfg.save(config)
        tooltip("Read Aloud settings saved")
        self.accept()

    def reject(self):
        speech.stop()
        super().reject()


def open_settings():
    SettingsDialog(QApplication.activeWindow()).exec()
    return True


# Voices for particular decks
##############################################################################


class DeckVoicesDialog(QDialog):
    """Rows of deck → voice. A deck's subdecks use the same voice, and
    medical shorthand is only spelled out for English voices."""

    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Read Aloud: Voices for Specific Decks")
        self.resize(720, 340)
        config = cfg.get()
        # The list matches the voice in use: neural voices, or system ones.
        self._edge = voices.NEURAL_OK and config.get("engine") == "edge"
        self._key = "edge_voice" if self._edge else voices.VOICE_KEY
        self._edge_voices = list(voices.RECOMMENDED_EDGE)
        self._mac_voices = list(voices.mac_voice_list()) if IS_MAC else []
        self._win_voices = list(voices.win_voice_list()) if IS_WIN else []
        try:
            self._decks = sorted(d.name for d in mw.col.decks.all_names_and_ids())
        except Exception:
            self._decks = []
        stored = config.get("deck_voices")
        self._stored = stored if isinstance(stored, dict) else {}

        intro = QLabel("Cards in these decks (and their subdecks) are read with this voice instead "
                       "— for example a Spanish voice for your Spanish deck.")
        intro.setWordWrap(True)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Deck", "Voice", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for name, values in sorted(self._stored.items()):
            if isinstance(values, dict) and values.get(self._key):
                self._add_row(name, values[self._key])

        add = QPushButton("Add Deck")
        add.clicked.connect(lambda: self._add_row("", ""))
        delete = QPushButton("Remove")
        delete.clicked.connect(self._delete_rows)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(add)
        bottom.addWidget(delete)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.table)
        layout.addLayout(bottom)
        if self._edge and voices.edge_command():
            mw.taskman.run_in_background(voices.edge_voice_list, self._on_edge_voices)

    def _fill(self, combo):
        if self._edge:
            fill_edge_combo(combo, self._edge_voices)
        else:
            fill_system_combo(combo, self._win_voices, self._mac_voices)

    def _add_row(self, deck: str, voice: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        deck_box = QComboBox()
        deck_box.addItems(self._decks)
        if deck and deck not in self._decks:
            deck_box.addItem(deck)
        if deck:
            deck_box.setCurrentText(deck)
        voice_box = QComboBox()
        voice_box.setEditable(not (self._edge or IS_MAC or IS_WIN))
        if voice:
            voice_box.addItem(voice, voice)
        self._fill(voice_box)
        play = _play_button(self, lambda _=False, box=deck_box: self._test(box))
        for col, widget in enumerate((deck_box, voice_box, play)):
            self.table.setCellWidget(r, col, widget)

    def _row(self, r: int) -> tuple:
        deck = self.table.cellWidget(r, 0).currentText().strip()
        box = self.table.cellWidget(r, 1)
        voice = box.currentText().strip() if box.isEditable() else box.currentData()
        values = dict(self._stored.get(deck) or {})  # keeps the voice for the other kind
        values[self._key] = voice
        values["cleanup"] = _is_english_voice(voice or "", self._edge)
        return deck, values

    def _test(self, deck_box):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 0) is deck_box:
                with cfg.overlay(self._row(r)[1]):
                    speech.speak(DECK_SAMPLE)
                return

    def _on_edge_voices(self, future):
        try:
            found = future.result()
            if not found:
                return
            self._edge_voices = found
            for r in range(self.table.rowCount()):
                self._fill(self.table.cellWidget(r, 1))
        except Exception:
            pass  # window closed, or offline: keep the short list

    def _delete_rows(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _save(self):
        decks = {}
        for r in range(self.table.rowCount()):
            deck, values = self._row(r)
            if deck and values.get(self._key):
                decks[deck] = values
        config = cfg.get()
        config["deck_voices"] = decks
        cfg.save(config)
        speech.stop()
        self.accept()


# Pronunciations
##############################################################################

_RESPELL_HINT = (
    "Spell it the way it should sound, using everyday words or syllables separated by "
    "spaces — e.g. Pseudomonas → <i>sue doh MOAN us</i>, MRSA → <i>mursa</i>. Press Test "
    "until it sounds right. Applies everywhere the word appears (not case-sensitive)."
)


def _find_key(pronunciations: dict, term: str):
    for k in pronunciations:
        if k.lower() == term.lower():
            return k
    return None


class FixPronunciationDialog(QDialog):
    def __init__(self, term: str, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Fix Pronunciation")
        self.setMinimumWidth(460)
        pronunciations = cfg.pronunciations()
        existing = _find_key(pronunciations, term)

        self.term_edit = QLineEdit(existing or term)
        self.say_edit = QLineEdit(pronunciations[existing] if existing else "")
        self.say_edit.setPlaceholderText("how it should sound")

        test_orig = QPushButton("▶ Current")
        test_orig.setToolTip("Hear how it is read without a fix")
        test_orig.clicked.connect(lambda: speech.speak(self.term_edit.text(), respell=False))
        test_new = QPushButton("▶ Test")
        test_new.setToolTip("Hear your respelling")
        test_new.clicked.connect(lambda: speech.speak(self.say_edit.text() or self.term_edit.text()))

        term_row = QHBoxLayout()
        term_row.addWidget(self.term_edit, 1)
        term_row.addWidget(test_orig)
        say_row = QHBoxLayout()
        say_row.addWidget(self.say_edit, 1)
        say_row.addWidget(test_new)

        form = QFormLayout()
        form.addRow("Word on card:", term_row)
        form.addRow("Say it like:", say_row)
        hint = QLabel(_RESPELL_HINT)
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        if existing:
            remove = buttons.addButton("Remove", QDialogButtonBox.ButtonRole.DestructiveRole)
            remove.clicked.connect(self._remove)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.say_edit.setFocus()

    def _save(self):
        term = self.term_edit.text().strip()
        say_as = self.say_edit.text().strip()
        if not term or not say_as:
            tooltip("Fill in both boxes (or Cancel).", parent=self)
            return
        pronunciations = cfg.pronunciations()
        old = _find_key(pronunciations, term)
        if old:
            del pronunciations[old]
        pronunciations[term] = say_as
        cfg.save_pronunciations(pronunciations)
        tooltip(f"Saved: {term} → {say_as}")
        self.accept()

    def _remove(self):
        pronunciations = cfg.pronunciations()
        key = _find_key(pronunciations, self.term_edit.text().strip())
        if key:
            del pronunciations[key]
            cfg.save_pronunciations(pronunciations)
            tooltip(f"Removed pronunciation for {key}")
        self.accept()


class PronunciationListDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Read Aloud Pronunciations")
        self.resize(520, 440)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Word on card", "Say it like"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for term, say_as in sorted(cfg.pronunciations().items(), key=lambda kv: kv[0].lower()):
            self._add_row(term, say_as)

        add = QPushButton("Add")
        add.clicked.connect(self._new_row)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete_rows)
        test = QPushButton("▶ Test")
        test.clicked.connect(self._test)
        row = QHBoxLayout()
        for b in (add, delete):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(test)

        hint = QLabel(_RESPELL_HINT)
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(row)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _add_row(self, term="", say_as=""):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(term))
        self.table.setItem(r, 1, QTableWidgetItem(say_as))
        return r

    def _new_row(self):
        r = self._add_row()
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))

    def _delete_rows(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _cell(self, r, c):
        item = self.table.item(r, c)
        return item.text().strip() if item else ""

    def _rows(self) -> dict:
        out = {}
        for r in range(self.table.rowCount()):
            term, say_as = self._cell(r, 0), self._cell(r, 1)
            if term and say_as:
                out[term] = say_as
        return out

    def _test(self):
        r = self.table.currentRow()
        if r >= 0:
            speech.speak(self._cell(r, 1) or self._cell(r, 0))

    def _save(self):
        cfg.save_pronunciations(self._rows())
        self.accept()
