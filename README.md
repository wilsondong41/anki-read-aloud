# Read Aloud for Anki

Highlight text on any card (in review or Browse Preview) and press **V** to hear it (**Shift+V** slowly). Built for medical terms, drug names, and Latin/foreign phrases, using optional natural neural voices (`edge-tts`) or your computer's built-in offline voices.

![Highlight text on a card and press V](https://i.imgur.com/hC6adWd.png)

## Features

- **Highlight & press V** (or right-click → **Read Aloud** / **Read Slowly** / **Fix Pronunciation…**) in both the reviewer and Browse Preview.
- **Read cards aloud automatically (optional):** tick it in **Tools → Read Aloud Settings…** to hear each question when it shows (cloze answers skipped) and the answer when you flip, as the whole sentence or just the answer words. One setting turns it on and off. Main text only; cards with their own audio are left alone. AnKing one-by-one cards are read as each answer is uncovered. Desktop Anki only.
- **Medical & science shorthand cleanup:** reads `↑K⁺` as "increased potassium", `5 μg/kg` as "5 micrograms per kg", `CD4+` as "CD4 positive", `β` as "beta", `→` as "leads to", etc.
- **Custom pronunciations:** right-click any word → **Fix Pronunciation…** to teach it a phonetic respelling once and reuse it everywhere.
- **Automatic language detection & per-deck voices:** automatically picks native voices for Chinese, Japanese, Korean, Russian, Arabic, Hebrew, Thai, and Hindi, or lets you assign a voice per deck.
- **Works with Backdrop Video:** emits a `read-aloud` browser event while speaking so background video add-ons can duck volume automatically.

## Setup & Settings

1. Install from AnkiWeb (`1227298382`) and restart Anki.
2. A setup prompt offers one-click installation of the optional online neural voice (`edge-tts`); offline system voices work with nothing extra to install.
3. Open **Tools → Read Aloud Settings…** to choose voices, shortcut key, speed, per-deck voices, and pronunciations.

## Development & Tests

- Build packages into `dist/`: `python3 build.py`
- Run tests: `QT_QPA_PLATFORM=offscreen <anki-python> -m unittest discover -s tests`

## Bug Reports & Feedback

Please open an [issue](https://github.com/wilsondong41/anki-read-aloud/issues) with your OS, Anki version, voice engine (`edge` vs system), and what happened (attach details from **Tools → Read Aloud Settings… → Open Log** if available, omitting any card content you don't want public).

---

**COMPLETELY VIBE CODED WITH THE GOAT CLAUDE AI**
