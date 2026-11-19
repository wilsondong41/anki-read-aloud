"""Turning highlighted card text into something a voice reads well.

Voices skip or mangle a lot of medical and science shorthand ("5 μg" is read
as just "five", "β" as "Greek small letter beta", arrows are silent), so it
is spelled out as English words. Nothing here needs Anki.
"""

from __future__ import annotations

import re

_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "µ": "mu", "ν": "nu", "ξ": "xi", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
    "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "gamma", "Δ": "delta", "Θ": "theta", "Λ": "lambda", "Π": "pi",
    "Σ": "sigma", "Φ": "phi", "Ψ": "psi", "Ω": "omega",
}

_SYMBOLS = {
    "↑": "increased", "↓": "decreased", "→": "leads to", "⇒": "leads to",
    "⟶": "leads to", "->": "leads to", "-->": "leads to", "=>": "leads to",
    "←": "from", "<-": "from", "↔": " ",
    "≥": "greater than or equal to", "≤": "less than or equal to",
    ">=": "greater than or equal to", "<=": "less than or equal to",
    ">": "greater than", "<": "less than", "≠": "not equal to",
    "±": "plus or minus", "+/-": "plus or minus", "≈": "approximately", "×": "times",
    "°C": "degrees Celsius", "°F": "degrees Fahrenheit", "°": "degrees",
}

# Ions as they're said: "K+" → potassium, "Ca2+" / "Ca++" → calcium.
_CATIONS = {"Na": "sodium", "K": "potassium", "Ca": "calcium", "Mg": "magnesium",
            "Li": "lithium", "Zn": "zinc", "Cu": "copper", "NH4": "ammonium",
            "H": "hydrogen ion", "Fe": "iron"}
_ANIONS = {"Cl": "chloride", "HCO3": "bicarbonate", "PO4": "phosphate"}  # not "I-": MHC I-
_ION_NAMES = set(_CATIONS.values()) | set(_ANIONS.values()) | {"ferrous iron", "ferric iron"}
_CATION_RE = re.compile(r"(?<![\w+])(NH4|Na|Ca|Mg|Li|Zn|Cu|Fe|K|H)([1-3]?\+|\+\+)(?![\w+])")
_ANION_RE = re.compile(r"(?<![\w-])(HCO3|PO4|Cl)(\s?[1-3]?[-−])(?![\w-])")
# "Na+/K+ ATPase" → "sodium-potassium ATPase"
_ION_ALT = "|".join(sorted(_ION_NAMES, key=len, reverse=True))
_ION_PAIR_RE = re.compile(r"\b(" + _ION_ALT + r")\s?/\s?(?=(?:" + _ION_ALT + r")\b)")
# Markers: "CD4+" → "CD4 positive", "Gram-" → "Gram negative", "+ve" / "-ve".
_POSITIVE_RE = re.compile(r"(?<![\w+])([A-Z][A-Za-z0-9]{0,5})\+(?![\w+])")
_NEGATIVE_RE = re.compile(r"(?<![\w-])(CD\d+[a-z]?|HER2|ER|PR|Gram|Rh|HIV|ANA|HBsAg)[-−]"
                          r"(?=[\s,;:.)/]|$)")
_VE_RE = re.compile(r"(?<=\w)\s*([+-])ve\b")
# Units after a slash: "mg/dL" → "mg per dL", "5 μg/kg" → "5 micrograms per kg".
_PER_RE = re.compile(r"(?<=[A-Za-zµμ%\d])\s*/\s*(?=(?:kg|g|mg|mcg|µg|μg|min|h|hr|hrs|hour|"
                     r"day|d|wk|week|mo|month|yr|year|L|dL|mL|µL|μL|uL|mm3|mm³|m2|m²|s|sec|"
                     r"dose|breath|beat)\b)")

_MICRO_UNITS = {"g": "micrograms", "l": "microliters", "m": "micrometers",
                "mol": "micromoles", "u": "microunits"}
# μg / µL / μmol … standing on their own (not part of a longer word)
_MICRO_RE = re.compile(r"(?<![^\W\d_])[μµ](mol|g|l|m|u)(?![^\W\d_])", re.IGNORECASE)
_MCG_RE = re.compile(r"(?<=\d)\s*mcg\b|\bmcg\b", re.IGNORECASE)
_TILDE_RE = re.compile(r"~\s*(?=\d)")
_SYMBOL_RE = re.compile("|".join(re.escape(s) for s in sorted(_SYMBOLS, key=len, reverse=True)))
_GREEK_RE = re.compile("[" + "".join(_GREEK) + "]")


def _spaced(m, word: str) -> str:
    """Replacement word padded with spaces, except next to a hyphen
    ("β-lactamase" → "beta-lactamase", "IL-1β" → "IL-1 beta")."""
    s = m.string
    before = "" if m.start() > 0 and s[m.start() - 1] == "-" else " "
    after = "" if m.end() < len(s) and s[m.end()] == "-" else " "
    return before + word + after


def _ion(m, names) -> str:
    symbol, charge = m.group(1), m.group(2).strip()
    if symbol == "Fe" and charge in ("2+", "++"):
        return "ferrous iron"
    if symbol == "Fe" and charge == "3+":
        return "ferric iron"
    if symbol == "H" and re.match(r"\s*ions?\b", m.string[m.end():], re.IGNORECASE):
        return "hydrogen"  # "H+ ions"
    return names[symbol]


# Scripts a voice of another language can't read: (its characters, the
# languages written in it, the language to read it in). Kana comes before
# Han, so Japanese with kanji is Japanese. Not Greek: α and β are on
# science cards.
_KANA = "぀-ヿ"
_HAN = "㐀-䶿一-鿿"
_HANGUL = "가-힯ᄀ-ᇿ㄰-㆏"
_THAI = "฀-๿"
_KANA_RE = re.compile(f"[{_KANA}]")
_SCRIPTS = [
    (_KANA_RE, ("ja",), "ja"),
    (re.compile(f"[{_HANGUL}]"), ("ko",), "ko"),
    (re.compile(f"[{_HAN}]"), ("zh", "ja"), "zh"),
    (re.compile("[Ѐ-ӿ]"), ("ru", "uk", "bg", "sr", "mk", "be", "kk", "mn"), "ru"),
    (re.compile("[؀-ۿ]"), ("ar", "fa", "ur", "ps"), "ar"),
    (re.compile("[֐-׿]"), ("he", "yi"), "he"),
    (re.compile(f"[{_THAI}]"), ("th",), "th"),
    (re.compile("[ऀ-ॿ]"), ("hi", "mr", "ne"), "hi"),
]
# Written without spaces between words (or, in Korean, with endings joined on).
_NO_SPACES_RE = re.compile(f"[{_KANA}{_HAN}{_HANGUL}{_THAI}]")


def script_language(text: str, context: str = ""):
    """(language to read it in, languages that can) when the text is in one
    of the scripts above, else None. context is the rest of the card: kanji
    on a card with kana is Japanese."""
    for chars, langs, lang in _SCRIPTS:
        if chars.search(text):
            if lang == "zh" and _KANA_RE.search(context or ""):
                return "ja", ("ja",)
            return lang, langs
    return None


def _term(t: str) -> str:
    # Whole words only, except in scripts without spaces (a fix for one
    # Chinese word must match inside a longer phrase).
    return re.escape(t) if _NO_SPACES_RE.search(t) else r"(?<!\w)" + re.escape(t) + r"(?!\w)"


def respell(text: str, pronunciations: dict) -> str:
    """Apply the user's respellings (whole words, any case)."""
    if not pronunciations:
        return text
    lookup = {k.lower(): v for k, v in pronunciations.items()}
    terms = sorted(pronunciations, key=len, reverse=True)
    pattern = re.compile("|".join(_term(t) for t in terms), re.IGNORECASE)
    return pattern.sub(lambda m: lookup.get(m.group(0).lower(), m.group(0)), text)


def prepare(text: str, pronunciations: dict | None = None, cleanup: bool = True) -> str:
    """Highlighted card text → what the voice is given."""
    text = text.replace("[...]", " ").replace("•", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # Your own respellings win over the automatic fixes below.
    text = respell(text, pronunciations or {})
    if cleanup:
        text = _MICRO_RE.sub(lambda m: _spaced(m, _MICRO_UNITS[m.group(1).lower()]), text)
        text = _MCG_RE.sub(" micrograms", text)
        text = _TILDE_RE.sub("about ", text)
        text = _CATION_RE.sub(lambda m: _ion(m, _CATIONS), text)
        text = _ANION_RE.sub(lambda m: _ion(m, _ANIONS), text)
        text = _ION_PAIR_RE.sub(r"\1-", text)
        text = _VE_RE.sub(lambda m: " positive" if m.group(1) == "+" else " negative", text)
        text = _POSITIVE_RE.sub(r"\1 positive", text)
        text = _NEGATIVE_RE.sub(r"\1 negative", text)
        text = _PER_RE.sub(" per ", text)
        text = _SYMBOL_RE.sub(lambda m: _spaced(m, _SYMBOLS[m.group(0)]), text)
        text = _GREEK_RE.sub(lambda m: _spaced(m, _GREEK[m.group(0)]), text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,;:()[]{}\"'")
