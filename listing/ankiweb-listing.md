# AnkiWeb listing for Read Aloud v17

Upload: dist/read_aloud-ankiweb.ankiaddon (not read_aloud.ankiaddon)

## Title

Read Aloud: highlight text on a card and press V to hear it

## Tags

tts speech audio pronunciation medical voice accessibility language chinese japanese korean spanish

## Support Page

https://github.com/wilsondong41/anki-read-aloud/issues

## Branches

Min: 2.1.50
Max: 26.9.3   (no "-" prefix, so newer Anki versions can still download it)

## Description

Paste everything between the two lines. (Images: https://imgur.com/a/0iGHrxq)

---

**Highlight any word on a card and press V to hear it.** For language decks, medical terms, names, and anything else you're not sure how to say. Natural-sounding voices in many languages, and science shorthand is read the way you'd say it.

<img src="https://i.imgur.com/hC6adWd.png" width="640" alt="Highlight text on a card and press V, or right-click it">

## How to use it

- Highlight text on a card (in review or Browse Preview) and press **V**. Press **V** again to hear it again; while it's talking, **V** stops it.
- **Shift+V** reads it slowly, for long names.
- Or right-click the highlighted text: 🔊 Read Aloud, 🐢 Read Slowly, ✏️ Fix Pronunciation…

## Why it's nice

- **Natural voices.** The optional neural voices (Ava and others) sound like a person. They're online, through Microsoft (see Privacy below); offline, your computer's own voice reads instead.
- **Medical shorthand, read properly.** ↑K⁺ → "increased potassium", 5 μg/kg → "5 micrograms per kg", CD4+ → "CD4 positive", β → "beta", → → "leads to".
- **Fix a word once.** Teach it how a word should sound (Pseudomonas → "sue doh MOAN us") and it says it that way everywhere.
- **Other languages, automatically.** Chinese, Japanese, Korean, Russian, Arabic, Hebrew, Thai and Hindi text is read by a native voice of that language, with nothing to set up. For languages in the Latin alphabet, give a deck its own voice, like a Spanish voice for your Spanish deck.
- **Quick.** Each word is kept once it's been read, so it only goes online the first time.

<img src="https://i.imgur.com/goGu3tK.png" width="460" alt="Fix Pronunciation: say Pseudomonas like sue doh MOAN us">

## Setting up

Restart Anki after installing. A short guided window installs the natural voice in one click (free, under a minute) and shows how to use it. It comes back at each start until the natural voice is on, unless you tick "Don't show this again" (then it's the Recommended box in Settings). Everything else is in **Tools → Read Aloud Settings…**.

<img src="https://i.imgur.com/KRxEOdp.png" width="540" alt="The setup window">

<img src="https://i.imgur.com/76nm9P2.png" width="560" alt="Read Aloud settings: voice, key and speed">

## Privacy

The natural voice is Microsoft's online Edge read-aloud service, used through the free edge-tts tool (not an official Microsoft API), so **the text you have read aloud is sent to Microsoft**. If you turn on "Get audio ready as soon as I highlight text", what you highlight is sent even if you don't play it. Your computer's own voice works offline and sends nothing.

## Good to know

- Works on Mac and Windows. On Linux it uses espeak (and the natural voice if mpv is installed).
- Microsoft changes its service now and then. If the natural voice stops working while you're online: Tools → Read Aloud Settings… → Voice Downloads… → Update.
- Pressing V stops the card's own audio so the two don't overlap; R replays it.
- In the reviewer, V and Shift+V normally record and replay your own voice. Those stay in the reviewer's More menu, or pick another key in Settings.
- The setup installs edge-tts outside Anki. To remove it after uninstalling: run `uv tool uninstall edge-tts` and delete the "Read Aloud for Anki" folder (Mac: ~/Library/Application Support; Windows: %LOCALAPPDATA%).

**COMPLETELY VIBE CODED WITH THE GOAT CLAUDE AI**

**This is a beta.** If something goes wrong, Tools → Read Aloud Settings… → Open Log has details that help me fix it. Please report problems rather than leaving a low rating, so I can fix them.

---

## Images

1. 1-on-a-card.png → IMAGE_URL_1
2. 2-fix-pronunciation.png → IMAGE_URL_2
3. 3-settings.png → IMAGE_URL_3
4. 4-setup.png → IMAGE_URL_4
