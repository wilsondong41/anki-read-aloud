"""The natural voice walkthrough: a short guided window that installs the
neural voice in one click. It opens at every start until the natural voice
is installed and turned on (or the person ticks "Don't show this again"),
and from the Recommended box in Settings.

Three pages: why and Install → installing (or what went wrong, Try Again) →
all set, with how to use it."""

from __future__ import annotations

from aqt import mw
from aqt.qt import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
                    QPushButton, Qt, QVBoxLayout, QWidget)
from aqt.utils import tooltip

from . import config as cfg
from . import setup_window, speech, voices
from .config import COMPUTER, IS_MAC

SAMPLE = "Trimethoprim-sulfamethoxazole treats Pneumocystis jirovecii pneumonia."
READY = "Read Aloud is ready."

# The one button that matters on a page: big and a fixed blue, so it can't be
# mistaken for a disabled one (light and dark mode, window in front or not).
_BIG_BUTTON = ("QPushButton { font-size: 15px; font-weight: bold; padding: 9px 22px;"
               " border: none; border-radius: 7px; background-color: #1f6feb; color: white; }"
               " QPushButton:hover { background-color: #388bfd; }"
               " QPushButton:pressed { background-color: #1158c7; }")


def _label(html: str, gray: bool = False, size: int | None = None) -> QLabel:
    label = QLabel(html)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    style = "color: gray;" if gray else ""
    if size:
        style += f" font-size: {size}px;"
    if style:
        label.setStyleSheet(style)
    return label


def _title(text: str) -> QLabel:
    return _label(f"<b>{text}</b>", size=18)


class _Pages(QWidget):
    """One page showing at a time. (QStackedWidget would size the window to
    its tallest page, leaving empty space on the short ones.)"""

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._pages: list = []
        self._current = 0

    def addWidget(self, page: QWidget) -> None:
        self._pages.append(page)
        self._layout.addWidget(page)
        page.setVisible(len(self._pages) == 1)

    def setCurrentIndex(self, index: int) -> None:
        self._current = index
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)

    def currentIndex(self) -> int:
        return self._current


class WelcomeDialog(QDialog):
    INTRO, INSTALLING, DONE = range(3)

    def __init__(self, found: dict, parent=None, startup: bool = False):
        super().__init__(parent or mw)
        self.setWindowTitle("Read Aloud — Natural Voice")
        self.setMinimumWidth(500)
        self.found = found
        self.startup = startup
        self.installed_ok = False

        self.pages = _Pages()
        self.pages.addWidget(self._intro_page())
        self.pages.addWidget(self._installing_page())
        self.pages.addWidget(self._done_page())

        # "Don't show again" only makes sense for the window that opens by itself.
        self.never = QCheckBox("Don't show this again")
        self.never.setVisible(startup)
        self.close_btn = QPushButton("Not Now")
        self.close_btn.setToolTip("Asks again the next time Anki starts")
        self.close_btn.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.never)
        bottom.addStretch(1)
        bottom.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)
        layout.addSpacing(4)
        layout.addLayout(bottom)
        self._go(self.INTRO)
        self.go_btn.setFocus()

    # pages

    def _intro_page(self) -> QWidget:
        page = QWidget()
        installed = bool(self.found.get("edge"))
        self.go_btn = QPushButton("Turn On Natural Voice" if installed else "Install Natural Voice")
        self.go_btn.setStyleSheet(_BIG_BUTTON)
        self.go_btn.setDefault(True)
        self.go_btn.setAutoDefault(True)
        self.go_btn.clicked.connect(self._go_clicked)
        hear = QPushButton("▶  Hear the Current Voice")
        hear.setToolTip("Plays a drug and bug name with the voice Read Aloud uses now")
        hear.clicked.connect(self._hear_current)

        go_row = QHBoxLayout()
        go_row.addWidget(self.go_btn)
        go_row.addStretch(1)
        hear_row = QHBoxLayout()
        hear_row.addWidget(hear)
        hear_row.addStretch(1)

        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title("Make Read Aloud sound natural"))
        v.addWidget(_label(
            f"Right now Read Aloud uses your {COMPUTER}'s built-in voice. It sounds robotic and "
            "often gets drug names, bacteria and Latin terms wrong. The free natural voice "
            "sounds like a real person."))
        v.addLayout(hear_row)
        v.addSpacing(10)
        v.addLayout(go_row)
        v.addWidget(_label(
            "Already downloaded: one click turns it on." if installed else
            "Free · about 10 MB · under a minute · needs internet. "
            "Nothing else on your computer changes.", gray=True))
        v.addSpacing(6)
        v.addWidget(_label(
            "It uses Microsoft's online Edge read-aloud service, so the text you have read "
            "aloud is sent to Microsoft. When you're offline, the built-in voice reads instead.",
            gray=True))
        v.addStretch(1)
        return page

    def _installing_page(self) -> QWidget:
        page = QWidget()
        self.inst_title = _title("Installing the natural voice…")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # moving bar: no way to know how far along it is
        self.progress.setTextVisible(False)
        self.inst_note = _label("This takes under a minute. You can keep using Anki; "
                                "this window can stay open in the background.", gray=True)

        self.retry_btn = QPushButton("Try Again")
        self.retry_btn.setStyleSheet(_BIG_BUTTON)
        self.retry_btn.clicked.connect(self._install)
        self.details_btn = QPushButton("Show Details")
        self.details_btn.setFlat(True)
        self.details_btn.clicked.connect(self._toggle_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.error_row = QWidget()
        er = QHBoxLayout(self.error_row)
        er.setContentsMargins(0, 0, 0, 0)
        er.addWidget(self.retry_btn)
        er.addWidget(self.details_btn)
        er.addStretch(1)

        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.inst_title)
        v.addWidget(self.progress)
        v.addWidget(self.inst_note)
        v.addWidget(self.error_row)
        v.addWidget(self.details)
        self.error_row.setVisible(False)  # only after a failed install
        self.details.setVisible(False)
        v.addStretch(1)
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        key = cfg.shortcut().upper()
        again = QPushButton("▶  Play Again")
        again.clicked.connect(lambda: speech.speak(READY))
        again_row = QHBoxLayout()
        again_row.addWidget(again)
        again_row.addStretch(1)

        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title("All set ✅"))
        v.addWidget(_label("Read Aloud now uses the natural voice."))
        v.addLayout(again_row)
        v.addSpacing(8)
        v.addWidget(_label(
            "<b>How to use it</b><br>"
            "1. Highlight a word or phrase on a card.<br>"
            f"2. Press <b>{key}</b> to hear it, or <b>Shift+{key}</b> to hear it slowly.<br>"
            "3. Said wrong? Right-click it → <b>Fix Pronunciation…</b><br>"
            "Voices and speed: Tools → Read Aloud Settings…"))
        # The other half of a good setup on a Mac: an offline backup voice.
        self.offline_row = QWidget()
        orow = QHBoxLayout(self.offline_row)
        orow.setContentsMargins(0, 8, 0, 0)
        orow.addWidget(_label("Optional: a better backup voice for when you're offline.",
                              gray=True), 1)
        how = QPushButton("Show Me How")
        how.clicked.connect(lambda: setup_window.open_setup(self))
        orow.addWidget(how)
        self.offline_row.setVisible(IS_MAC and not self.found.get("mac_voice"))
        v.addWidget(self.offline_row)
        v.addStretch(1)
        return page

    # actions

    def _go(self, page: int):
        self.pages.setCurrentIndex(page)
        if page == self.INSTALLING:
            self.close_btn.setText("Close")
            self.close_btn.setToolTip("Installing carries on in the background")
        elif page == self.DONE:
            self.close_btn.setText("Done")
            self.close_btn.setToolTip("")
            self.close_btn.setDefault(True)
            self.never.setVisible(False)
        self._fit()

    def _fit(self):
        """Height to fit this page's text: Qt's own guess for wrapped text
        leaves a tall empty window."""
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        width = max(self.width() if self.isVisible() else 0, 540)
        height = (layout.heightForWidth(width) if layout.hasHeightForWidth()
                  else layout.sizeHint().height())
        self.resize(width, max(height, 200))

    def _hear_current(self):
        with cfg.overlay({"engine": "system"}):
            speech.speak(SAMPLE)

    def _go_clicked(self):
        speech.stop()
        if self.found.get("edge"):
            self._turned_on()  # already downloaded: no install needed
        else:
            self._install()

    def _install(self):
        self.inst_title.setText("<b>Installing the natural voice…</b>")
        self.progress.setVisible(True)
        self.inst_note.setText("This takes under a minute. You can keep using Anki; "
                               "this window can stay open in the background.")
        self.error_row.setVisible(False)
        self.details.setVisible(False)
        self._go(self.INSTALLING)
        mw.taskman.run_in_background(setup_window.install_edge_tts, self._installed)

    def _installed(self, future):
        try:
            error = future.result()
        except Exception as e:
            error = str(e) or "Unknown error."
        cfg.log(f"neural voice install (walkthrough): {error or 'ok'}")
        if not error:
            # Turn it on even if the window was closed meanwhile: they asked for it.
            setup_window._use_edge()
            speech.neural_reset()
        try:
            visible = self.isVisible()
        except RuntimeError:
            visible = False  # window already gone
        if not visible:
            if not error:
                tooltip("Read Aloud: the natural voice is installed and on ✅")
                speech.speak(READY)
            return
        if error:
            self._show_error(error)
        else:
            self._turned_on()

    def _show_error(self, error: str):
        self.inst_title.setText("<b>Couldn't install the natural voice</b>")
        self.progress.setVisible(False)
        self.inst_note.setText("Check that you're connected to the internet, then click Try "
                               "Again. Until then, the built-in voice keeps reading.")
        self.details.setPlainText(error)
        self.details.setVisible(False)
        self.details_btn.setText("Show Details")
        self.error_row.setVisible(True)
        self.close_btn.setText("Not Now")
        self.retry_btn.setFocus()
        self._fit()

    def _toggle_details(self):
        show = not self.details.isVisible()
        self.details.setVisible(show)
        self.details_btn.setText("Hide Details" if show else "Show Details")
        self._fit()

    def _turned_on(self):
        setup_window._use_edge()
        speech.neural_reset()
        self.installed_ok = True
        self.found = {**self.found, "edge": True}
        if IS_MAC and not self.found.get("mac_voice"):
            # Offered on the last page: don't pop the setup window about it later.
            shown = set(cfg.local_state().get("setup_shown", []))
            cfg.set_local_state(setup_shown=sorted(shown | {"mac_voice"}))
        self._go(self.DONE)
        speech.speak(READY)

    def done(self, result):
        # Every way of closing (Not Now, Done, the window's X) comes here.
        if self.startup and self.never.isChecked() and not self.installed_ok:
            cfg.set_local_state(skip_setup_check=True)
            cfg.log("walkthrough: don't show again")
            tooltip("You can install the natural voice any time: "
                    "Tools → Read Aloud Settings…", period=8000)
        super().done(result)


_open_dialog = None  # keeps the start-up window alive while it's open


def show_at_startup(found: dict) -> None:
    global _open_dialog
    _open_dialog = WelcomeDialog(found, startup=True)
    _open_dialog.show()


def open_welcome(parent=None) -> bool:
    """From Settings or a notice. Returns whether the natural voice is on now."""
    WelcomeDialog(setup_window.status(), parent).exec()
    return setup_window._edge_in_use() and voices.edge_command() is not None
