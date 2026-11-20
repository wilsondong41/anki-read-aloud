"""
Read Aloud — Anki Add-on (v17)

Highlight text on a card and press V to hear it:

V (or the key chosen in the settings)
           → read the highlighted text (or the last thing you highlighted on
             this card, so you can press V again to replay it); pressing it
             while it's still talking stops it
Shift+V    → read it slowly (good for long drug / bug names)
Right-click → 🔊 Read Aloud / 🐢 Read Slowly / ✏️ Fix Pronunciation…
Tools → Read Aloud Settings… (or the add-on's Config button) → voice, key,
             speed, reading cards aloud automatically; from there: voices
             for particular decks, pronunciations

Reading cards aloud automatically (off unless turned on): the question when
it shows (a cloze's hidden part is read as "blank"), then the answer (the
whole sentence with it filled in, or just the answer words). Only the main
text is read, never Extra or other side fields, worked out from the note's
fields (card_text). Cards with their own sound are left alone.

Optional neural voice: Microsoft's online Edge read-aloud service through
edge-tts (not an official API), so the text being read is sent to
Microsoft. A guided walkthrough installs it in one click; it opens at every
start until the natural voice is on, unless "Don't show this again" is ticked.

Files: config (settings, state, log), text (clean-up of card text), voices
(finding voices and programs), speech (making and playing audio),
welcome_window (the natural voice walkthrough), setup_window and
settings_window (the other windows).

Anki's own V (replay own voice) and Shift+V (record own voice) shortcuts are
turned off in the reviewer while V is the key; both stay in the reviewer's
More menu.
"""

from __future__ import annotations

import json
import traceback

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, QTimer
from aqt.utils import tooltip
from aqt.webview import AnkiWebView

try:
    from aqt.browser.previewer import Previewer
except ImportError:
    Previewer = None

try:
    from aqt.qt import QWebEnginePage
except ImportError:
    QWebEnginePage = None

from . import config as cfg
from . import card_text, setup_window, speech
from .settings_window import FixPronunciationDialog, SettingsDialog, open_settings

# ── JS injected into every card ───────────────────────────────────────────────
# Mirrors AnKing's W-key pattern. pycmd("readAloud:" + text) calls back into
# Python. window.__readAloudKey is set on every injection, so a key chosen in
# the settings applies from the next card.

_JS_INJECT = """
(function() {
    if (window.__readAloudInjected) return;
    window.__readAloudInjected = true;
    window.__readAloudSel = "";

    function getSel() {
        var s = window.getSelection();
        return s ? s.toString().trim() : "";
    }

    // Remember the last non-empty selection, so the key still works after
    // the highlight is cleared (clicking elsewhere, or pressing it again).
    function remember() {
        var t = getSel();
        if (t) window.__readAloudSel = t;
    }
    document.addEventListener('selectionchange', remember);
    var lastPrefetch = "";
    document.addEventListener('mouseup', function() {
        setTimeout(function() {
            remember();
            // Let Python make the audio before the key is pressed.
            var t = getSel();
            if (t && t !== lastPrefetch && t.length <= 300) {
                lastPrefetch = t;
                pycmd('readAloudPrefetch:' + t);
            }
        }, 30);
    }, true);

    // Leave the key alone when it is part of a shortcut (Cmd+V / Ctrl+V
    // paste) or when typing in an editable field (Edit Field During Review).
    var skipNextKeyup = false;
    function isEditable(el) {
        if (!el) return false;
        if (el.isContentEditable) return true;
        var tag = el.tagName;
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    }
    function shouldIgnore(e) {
        return e.metaKey || e.ctrlKey || e.altKey ||
               isEditable(e.target) || isEditable(document.activeElement);
    }
    function isOurKey(e) {
        return e.key && e.key.toLowerCase() === (window.__readAloudKey || 'v');
    }

    document.addEventListener('keydown', function(e) {
        if (isOurKey(e)) {
            if (shouldIgnore(e)) {
                skipNextKeyup = true;
                return;
            }
            skipNextKeyup = false;
            e.preventDefault();
            e.stopPropagation();
        }
    }, true);

    // keyup → send the current (or last) selection to Python. Shift → slow.
    // Python decides whether a repeat press replays or stops.
    document.addEventListener('keyup', function(e) {
        if (isOurKey(e)) {
            if (skipNextKeyup || shouldIgnore(e)) {
                skipNextKeyup = false;
                return;
            }
            e.preventDefault();
            e.stopPropagation();
            var text = getSel() || window.__readAloudSel;
            if (text) {
                window.__readAloudSel = text;
                pycmd((e.shiftKey ? 'readAloudSlow:' : 'readAloud:') + text);
            } else {
                pycmd('readAloudNone');
            }
        }
    }, true);
})();
"""

_JS_NEW_CARD = "window.__readAloudSel = '';"
_previewers: dict = {}  # id(Previewer) → [previewer, last rendered card id]


def _reviewer_web():
    try:
        reviewer = mw.reviewer
        if reviewer and isinstance(getattr(reviewer, "web", None), AnkiWebView):
            return reviewer.web
    except Exception:
        pass
    return None


def _inject_into(web, new_card: bool = False) -> None:
    # web.eval waits until the page has loaded; entering review (Study Now)
    # and opening the previewer reload the page, so running at once would miss it.
    if web:
        script = f"window.__readAloudKey = {json.dumps(cfg.shortcut())};" + _JS_INJECT
        web.eval(script + (_JS_NEW_CARD if new_card else ""))


def _inject(new_card: bool = False) -> None:
    _inject_into(_reviewer_web(), new_card=new_card)


def _on_show_question(card=None):
    # New card: forget the previous card's selection and stop any leftover speech.
    speech.stop()
    _inject(new_card=True)
    _first_review_hint()
    _auto_read(card, answer=False)


def _on_show_answer(card=None):
    _inject()
    _auto_read(card, answer=True)


def _has_own_sound(card) -> bool:
    # Its own [sound:] or {{tts}} would play under the voice (reading stops
    # the card's audio), so such cards are left alone, on both sides.
    try:
        return bool(card.question_av_tags() or card.answer_av_tags())
    except Exception:
        return False


def _auto_read(card=None, answer: bool = False) -> None:
    """With "Read cards aloud automatically" on: read the question when it
    shows, and the answer when that shows."""
    if not cfg.auto_read():
        return
    card = card or _card_from()
    if card is None:
        return
    if answer:
        speech.stop()  # the question may still be being read
    if _has_own_sound(card):
        return
    try:
        if answer:
            words = card_text.answer_text(card, cfg.auto_read_answer())
        else:
            words = card_text.question_text(card)
    except Exception:
        cfg.log("auto-read: couldn't get the card's text:\n" + traceback.format_exc())
        return
    where = _where_card(card)
    _safely(speech.speak, words, **where)
    if not answer:
        # Get the answer's audio ready while the question is read.
        try:
            later = card_text.answer_text(card, cfg.auto_read_answer())
        except Exception:
            later = ""
        if later:
            _safely(speech.prefetch, later, online=True, **where)


def _on_state_change(new_state, old_state) -> None:
    # Leaving review (deck list, overview) stops any reading.
    if old_state == "review" and new_state != "review":
        speech.stop()


def _on_previewer_init(previewer) -> None:
    _previewers[id(previewer)] = [previewer, None]
    previewer.finished.connect(lambda _ok=0, p=previewer: _on_previewer_closed(p))


def _on_previewer_closed(previewer) -> None:
    _previewers.pop(id(previewer), None)
    speech.stop()


def _on_card_will_show(text: str, card, kind: str) -> str:
    if kind in ("previewQuestion", "previewAnswer"):
        for entry in list(_previewers.values()):
            previewer, last_card_id = entry
            web = getattr(previewer, "_web", None)
            if not getattr(previewer, "_open", False) or not isinstance(web, AnkiWebView):
                continue
            current = _card_from(previewer)
            if current is None or current.id != card.id:
                continue
            new_card = last_card_id != card.id
            if new_card:
                entry[1] = card.id
                speech.stop()
            _inject_into(web, new_card=new_card)
    return text


def _first_review_hint():
    """Once per computer: how to use it."""
    if cfg.local_state().get("hint_shown"):
        return
    cfg.set_local_state(hint_shown=True)
    key = cfg.shortcut().upper()
    tooltip(f"<b>Read Aloud:</b> highlight text on a card and press <b>{key}</b> to hear it "
            f"(<b>Shift+{key}</b>: slowly). Settings: Tools → Read Aloud Settings…", period=9000)


def _card_from(source=None):
    if source is None:
        source = getattr(mw, "reviewer", None)
    card_attr = getattr(source, "card", None)
    return card_attr() if callable(card_attr) else card_attr


def _where(source=None) -> dict:
    """The deck of the card being studied or previewed (its home deck when
    in a filtered deck), for voices set per deck, and the card's text, for
    telling Japanese kanji from Chinese."""
    try:
        card = _card_from(source)
    except Exception:
        return {}
    return _where_card(card)


def _where_card(card) -> dict:
    try:
        if not card:
            return {}
        return {"deck": mw.col.decks.name(card.odid or card.did),
                "context": card.note().joined_fields()}
    except Exception:
        return {}


# ── pycmd handler ─────────────────────────────────────────────────────────────


def _safely(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:
        cfg.log("error:\n" + traceback.format_exc())
        tooltip("Read Aloud ran into a problem (details in Settings → Open Log).")


def _on_pycmd(handled, message, context):
    """Calls from the card's script (reviewer or browser previewer)."""
    if message.startswith("readAloud:"):
        _safely(speech.speak, message[len("readAloud:"):], toggle=True, **_where(context))
        return (True, None)
    if message.startswith("readAloudSlow:"):
        _safely(speech.speak, message[len("readAloudSlow:"):], slow=True, toggle=True,
                **_where(context))
        return (True, None)
    if message.startswith("readAloudPrefetch:"):
        _safely(speech.prefetch, message[len("readAloudPrefetch:"):], **_where(context))
        return (True, None)
    if message == "readAloudNone":
        if speech.is_speaking():
            speech.stop()
        else:
            tooltip("Read Aloud: highlight a word first")
        return (True, None)
    return handled


# ── context menu ──────────────────────────────────────────────────────────────


def _context_source(webview: AnkiWebView):
    if mw.state == "review" and webview is _reviewer_web():
        return mw.reviewer
    for previewer, _ in _previewers.values():
        if getattr(previewer, "_web", None) is webview:
            return previewer
    bridge = getattr(webview, "_bridge_context", None)
    if Previewer is not None and isinstance(bridge, Previewer):
        return bridge
    return None


def _on_context_menu(webview: AnkiWebView, menu: QMenu):
    if QWebEnginePage is None:
        return
    source = _context_source(webview)
    if source is None:
        return
    if not webview.pageAction(QWebEnginePage.WebAction.Copy).isEnabled():
        return
    selected = (webview.page().selectedText() or "").strip()
    if not selected:
        return
    where = _where(source)
    read = QAction("🔊 Read Aloud", menu)
    read.triggered.connect(lambda: _safely(speech.speak, selected, **where))
    slow = QAction("🐢 Read Slowly", menu)
    slow.triggered.connect(lambda: _safely(speech.speak, selected, slow=True, **where))
    fix = QAction("✏️ Fix Pronunciation…", menu)
    fix.triggered.connect(lambda: FixPronunciationDialog(selected).exec())

    actions = menu.actions()
    if actions:
        for a in (read, slow, fix):
            menu.insertAction(actions[0], a)
        menu.insertSeparator(actions[0])
    else:
        for a in (read, slow, fix):
            menu.addAction(a)


# ── wiring ────────────────────────────────────────────────────────────────────


def _on_state_shortcuts(state, shortcuts):
    # Free up the key (and Shift+key) in the reviewer so it reaches the card's
    # script (for V: instead of Anki's "you haven't recorded your voice yet").
    if state != "review":
        return
    key = cfg.shortcut()
    shortcuts[:] = [s for s in shortcuts
                    if not (isinstance(s[0], str) and s[0].lower() in (key, f"shift+{key}"))]


_checked_setup = False


def _on_profile_open():
    global _checked_setup
    if not _checked_setup:
        _checked_setup = True
        QTimer.singleShot(3000, setup_window.startup_check)


def _setup():
    gui_hooks.state_shortcuts_will_change.append(_on_state_shortcuts)
    gui_hooks.reviewer_did_show_question.append(_on_show_question)
    gui_hooks.reviewer_did_show_answer.append(_on_show_answer)
    gui_hooks.state_did_change.append(_on_state_change)
    gui_hooks.previewer_did_init.append(_on_previewer_init)
    gui_hooks.card_will_show.append(_on_card_will_show)
    gui_hooks.webview_did_receive_js_message.append(_on_pycmd)
    gui_hooks.webview_will_show_context_menu.append(_on_context_menu)

    # A new computer is missing the natural voices: offer to set them up,
    # once a profile is open (not over the profile chooser). On a Mac, Anki
    # opens the profile before main_window_did_init, so the hook alone would
    # miss it: check for an open profile here too.
    gui_hooks.profile_did_open.append(_on_profile_open)
    if getattr(mw, "col", None) is not None:
        _on_profile_open()

    # The add-on's Config button opens the settings window instead of raw JSON.
    mw.addonManager.setConfigAction(cfg.ADDON, open_settings)

    settings = QAction("Read Aloud Settings…", mw)
    settings.triggered.connect(lambda: SettingsDialog().exec())
    mw.form.menuTools.addAction(settings)


gui_hooks.main_window_did_init.append(_setup)
