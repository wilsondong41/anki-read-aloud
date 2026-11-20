"""What "Read cards aloud automatically" says, worked out from the note's
fields and its card template (not by scraping the shown card, which has
hint buttons, scripts and side fields like Extra).

Cloze cards: the cloze field(s) on the front. The question reads the
hidden part as "blank"; the answer reads the whole sentence with it filled
in, or only the hidden words.
Other cards: the fields shown on the front; the answer is the first field
the back adds (Back on a Basic card), never side fields like Extra.

Nothing here needs Anki: a card only needs ord, note() and template().
"""

from __future__ import annotations

import html
import re

WHOLE = "whole"  # the whole sentence with the answer filled in (default)
WORDS = "words"  # just the answer words

# Never read, even when a template shows them like a main field.
_SIDE_FIELDS = {"extra", "back extra", "notes", "personal notes", "lecture notes",
                "missed questions", "additional resources", "one by one"}
_SPECIAL = {"frontside", "tags", "deck", "subdeck", "card", "cardflag", "type", "cardid"}
_SKIP_FILTERS = {"hint", "type", "tts", "tts-voices", "furigana-hidden"}

_TAG_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
_CLOZE_RE = re.compile(r"\{\{c(\d+)::((?:(?!\{\{c\d+::)(?!\}\}).)*?)(?:::((?:(?!\{\{c\d+::)(?!\}\}).)*?))?\}\}",
                       re.S)


# The template
##############################################################################


def _refs(template: str) -> list:
    """Fields a template shows: (field name, filters, sections it is inside)."""
    out, sections = [], []
    for m in _TAG_RE.finditer(template or ""):
        tag = m.group(1).strip()
        if not tag or tag[0] in "!=":
            continue
        if tag[0] in "#^":
            sections.append(tag[1:].strip())
            continue
        if tag[0] == "/":
            name = tag[1:].strip()
            if name in sections:
                del sections[len(sections) - 1 - sections[::-1].index(name):]
            continue
        parts = tag.split(":")
        field = parts[-1].strip()
        filters = [p.strip().split(" ")[0].lower() for p in parts[:-1]]
        if tag.lower().startswith("tts "):
            filters.append("tts")
        out.append((field, filters, tuple(sections)))
    return out


def _readable(ref) -> bool:
    field, filters, _sections = ref
    low = field.lower()
    return (low not in _SPECIAL and low not in _SIDE_FIELDS
            and not any(f in _SKIP_FILTERS for f in filters))


def _plain_refs(template: str, names: set) -> list:
    """Fields shown as text, in order: those outside any {{#section}} first
    choice; a field inside only its own section ({{#Back}}{{Back}}{{/Back}})
    counts too."""
    picked = []
    for ref in _refs(template):
        field, filters, sections = ref
        if field not in names or not _readable(ref) or "cloze" in filters:
            continue
        if all(s == field for s in sections) and field not in picked:
            picked.append(field)
    return picked


# Turning field HTML into words
##############################################################################

_DROP_RE = re.compile(r"<(script|style|svg|button)\b.*?</\1\s*>", re.S | re.I)
_SOUND_RE = re.compile(r"\[sound:[^\]]*\]|\[anki:[^\]]*\].*?\[/anki:[^\]]*\]", re.S)
_BREAK_RE = re.compile(r"<\s*/?\s*(br|div|p|li|tr|h\d|hr)\b[^>]*>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]*>")


def plain(field_html: str) -> str:
    """Field HTML → the words on it: no images, sounds, scripts or tags; a
    line break becomes the end of a sentence."""
    text = _DROP_RE.sub(" ", field_html or "")
    text = _SOUND_RE.sub(" ", text)
    text = _BREAK_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return _sentences(line for line in lines if line)


def _sentences(parts) -> str:
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if out and out[-1][-1] not in ".!?:;,":
            out[-1] += "."
        out.append(part)
    return " ".join(out)


# Cloze
##############################################################################


def _fill_clozes(text: str, ordinal: int, hide: bool) -> str:
    """Inner clozes first (Anki allows nesting). The card's own cloze is
    "blank" when hide, else its words; the others show their words."""
    while True:
        new = _CLOZE_RE.sub(
            lambda m: " blank " if hide and int(m.group(1)) == ordinal else m.group(2), text)
        if new == text:
            return text
        text = new


def _cloze_words(text: str, ordinal: int) -> list:
    words = []
    while True:
        found = False

        def inner(m):
            nonlocal found
            found = True
            if int(m.group(1)) == ordinal:
                words.append(m.group(2))
            return m.group(2)

        text = _CLOZE_RE.sub(inner, text)
        if not found:
            return words


# What to read
##############################################################################


def _parts(card):
    note = card.note()
    model = note.note_type() if hasattr(note, "note_type") else note.model()
    names = [f["name"] for f in model["flds"]]
    template = card.template()
    is_cloze = model.get("type") == 1
    return note, set(names), template, is_cloze


def _cloze_fields(template: dict, names: set) -> list:
    fields = []
    for field, filters, _sections in _refs(template.get("qfmt", "")):
        if "cloze" in filters and field in names and field not in fields:
            fields.append(field)
    return fields


def _image_occlusion(value: str) -> bool:
    return "image-occlusion:" in value


def question_text(card) -> str:
    note, names, template, is_cloze = _parts(card)
    if is_cloze:
        ordinal = card.ord + 1
        values = [note[f] for f in _cloze_fields(template, names)]
        if any(_image_occlusion(v) for v in values):
            return ""
        return _sentences(plain(_fill_clozes(v, ordinal, hide=True)) for v in values)
    fields = _plain_refs(template.get("qfmt", ""), names)
    return _sentences(plain(note[f]) for f in fields)


def answer_text(card, mode: str = WHOLE) -> str:
    note, names, template, is_cloze = _parts(card)
    if is_cloze:
        ordinal = card.ord + 1
        values = [note[f] for f in _cloze_fields(template, names)]
        if any(_image_occlusion(v) for v in values):
            return ""
        if mode == WORDS:
            words = [plain(w) for v in values for w in _cloze_words(v, ordinal)]
            return ", ".join(w for w in words if w)
        return _sentences(plain(_fill_clozes(v, ordinal, hide=False)) for v in values)
    # The first field the back adds (Back on a Basic card; Front on a
    # reversed card's back). Either setting reads the same for these.
    front = set(_plain_refs(template.get("qfmt", ""), names))
    for field in _plain_refs(template.get("afmt", ""), names):
        if field not in front:
            return plain(note[field])
    return ""
