"""Read Aloud as a voice for Anki's own read-aloud lines.

A card template can ask Anki to read a field aloud:

    {{tts en_US voices=Read_Aloud,Apple_Ava_(Premium) speed=1.2:cloze:Text}}

Anki uses the first voice in the list that the device has. On a computer
with this add-on that is Read_Aloud: the add-on reads it with its own voice
(natural voice, voice for the deck, pronunciation fixes, its own speed). A
phone has no Read_Aloud and moves on to the next voice (Ava on an iPhone).
So the same line reads on every device, and the deck option "Don't play
audio automatically" turns it on and off everywhere.

Anki's own rules for players (aqt.sound.Player): the player with the
highest rank for a line plays it; play() must say when it began, and must
call on_done exactly once when it ends, stopped or not, so Anki can move on.
"""

from __future__ import annotations

import re
import traceback

from aqt import gui_hooks, mw
from aqt.qt import QTimer
from aqt.sound import Player

from . import card_text
from . import config as cfg
from . import speech

try:
    from anki.sound import TTSTag
except ImportError:  # very old Anki
    TTSTag = None

try:
    from aqt.tts import TTSVoice
except ImportError:
    TTSVoice = None

VOICE = "Read_Aloud"
POLL_MS = 100


def line_text(tag) -> str:
    """The line's words. Anki leaves a field's sound files in them
    ("… [sound:x.mp3]"): those aren't read. Hidden parts are said like the
    add-on's own reading (card_text.tidy_spoken)."""
    return card_text.tidy_spoken(card_text.SOUND_RE.sub(" ", tag.field_text or ""))


class ReadAloudVoice(Player):
    def __init__(self) -> None:
        self._job = None
        self._on_done = None
        self._timer = None
        self._playing = 0  # counts plays, so a late "done" can't end a newer one
        # The deck (for its voice) and the card's text (for telling Japanese
        # from Chinese) of the card being read: locate() asks the add-on at
        # the time (a clicked play button, R, autoplay); where is the last
        # card whose sounds Anki played, for anywhere else.
        self.where: dict = {}
        self.locate = None

    # what Anki asks

    def rank_for_tag(self, tag):
        if TTSTag is None or not isinstance(tag, TTSTag) or VOICE not in tag.voices:
            return None
        # Same order rule as Anki's own voices: earlier in the list wins.
        return -tag.voices.index(VOICE)

    def voices(self) -> list:
        # Listed by {{tts-voices:}}.
        return [TTSVoice(name=VOICE, lang="en_US")] if TTSVoice else []

    def play(self, tag, on_done) -> None:
        self._end(call=False)  # a leftover from before (Anki has moved on)
        self._playing += 1
        self._on_done = on_done
        try:
            where = (self.locate() if self.locate else None) or self.where
            self._job = speech.speak(line_text(tag), stop_card_audio=False, **where)
        except Exception:
            cfg.log("read-aloud line: couldn't read it:\n" + traceback.format_exc())
            self._job = None
        try:
            gui_hooks.av_player_did_begin_playing(self, tag)
        except Exception:
            pass
        if self._job is None:
            self._end_soon()
            return
        if self._timer is None:  # one timer, reused for every line
            self._timer = QTimer(mw)
            self._timer.timeout.connect(self._check)
        self._timer.start(POLL_MS)

    def stop(self) -> None:
        # Anki stops the player before the next card's sounds (and on R, or
        # leaving review). Stop our speech, if it is still ours, and tell
        # Anki once we've stopped.
        if self._job is not None and speech.current() is self._job:
            speech.stop()
        if self._on_done is not None:
            self._end_soon()

    def shutdown(self) -> None:
        self._end(call=False)

    # keeping track

    def _check(self) -> None:
        job = self._job
        # Finished, or replaced (V on a highlight, or stopped with V).
        if job is None or job.poll() is not None or speech.current() is not job:
            self._end(call=True)

    def _end_soon(self) -> None:
        # After Anki has finished what it is doing (it stops a player, then
        # queues the next sounds, then waits for on_done).
        playing = self._playing
        QTimer.singleShot(0, lambda: self._playing == playing and self._end(call=True))

    def _end(self, call: bool) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._job = None
        done, self._on_done = self._on_done, None
        if call and done is not None:
            done()


player = ReadAloudVoice()


def register() -> None:
    from aqt.sound import av_player
    if player not in av_player.players:
        av_player.players.append(player)
