"""Takes out the read-aloud lines an earlier test build put in card templates.

That build added, for phones, a line like

    <!-- Read Aloud: reads the card aloud (…) -->
    {{tts en_US voices=Read_Aloud,Apple_Ava_(Premium),… speed=1.2:cloze:Text}}

(on the answer side wrapped in {{^One by one}}…{{/One by one}}). Anki plays
such a line by itself on every card, so the add-on's own "Read cards aloud
automatically" switch couldn't turn it off. Reading cards aloud is now the
add-on's job only, so these lines are removed, leaving each template as it
was before. Only lines naming the Read_Aloud voice are touched.
"""

from __future__ import annotations

import re

# A whole line holding only our comment, or only our {{tts}} (bare or
# wrapped in {{^One by one}}), newline included.
_LINE_RE = re.compile(
    r"^[ \t]*(?:"
    r"<!-- Read Aloud: reads the card aloud[^\n]*?-->"
    r"|(?:\{\{\^One by one\}\})?\{\{tts [^{}\n]*\bRead_Aloud\b[^{}\n]*\}\}(?:\{\{/One by one\}\})?"
    r")[ \t]*(?:\r?\n|$)",
    re.M)
# Anything else naming the voice, inside other text.
_TAG_RE = re.compile(r"(?:\{\{\^One by one\}\})?\{\{tts [^{}]*\bRead_Aloud\b[^{}]*\}\}(?:\{\{/One by one\}\})?")


def clean(template: str) -> str:
    """The template without the add-on's read-aloud lines."""
    text = template or ""
    if "Read_Aloud" not in text and "Read Aloud: reads the card aloud" not in text:
        return text
    return _TAG_RE.sub("", _LINE_RE.sub("", text))


def clean_collection(col) -> list:
    """Remove the lines from every note type. Returns the names of the note
    types changed (only template text changes: no full sync needed)."""
    changed = []
    for model in col.models.all():
        touched = False
        for template in model.get("tmpls", []):
            for side in ("qfmt", "afmt"):
                old = template.get(side, "")
                new = clean(old)
                if new != old:
                    template[side] = new
                    touched = True
        if touched:
            col.models.update_dict(model)
            changed.append(model.get("name", ""))
    return changed
