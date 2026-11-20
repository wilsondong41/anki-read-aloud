## Read Aloud Configuration

Works on macOS and Windows (Linux: espeak, plus the neural voice if mpv is installed). Settings open in their own window: the add-on's **Config** button or **Tools → Read Aloud Settings…**. There you pick the voice, the key and the speed (▶ plays a sample), voices for particular decks, and your pronunciations. Chinese, Japanese, Korean, Russian, Arabic, Hebrew, Thai and Hindi text is read with a voice of that language on its own (unless your voice already speaks it). The first time, a short window installs the natural voice in one click (it comes back at each start until the natural voice is on, unless you tick "Don't show this again"). If the natural voice can't be reached, a computer voice reads instead; Settings → Voice Downloads… shows how to make it natural-sounding for the languages you read. Pressing the key stops the card's own audio (R replays it).

**Keys (in the reviewer and browser Preview):** highlight text, then
- **V** — read it. Press **V** again to replay; pressing V while it's still talking stops it.
- **Shift+V** — read it slowly.
- **Right-click** → 🔊 Read Aloud / 🐢 Read Slowly / ✏️ Fix Pronunciation…

V can be changed to another letter in the settings.

**Reading cards aloud automatically** (off unless you turn it on in Tools → Read Aloud Settings…; that one setting turns it on and off): the question is read when it shows (a cloze's hidden part is skipped), and the answer when you flip the card: the whole sentence with the answer filled in, or just the answer words. Only the card's main text is read, never Extra or other side fields. Cards with their own sound are left alone. Press V to stop it. Desktop Anki only.

**Privacy:** the neural voice uses Microsoft's online Edge read-aloud service
through the free edge-tts tool (not an official Microsoft API), so the text you
have read aloud is sent to Microsoft. With prefetch on, that happens as soon as
you highlight text. When cards are read automatically, the answer's text is
sent while the question is read, so it's ready when you flip. The system voice
works offline and sends nothing.

**Uninstalling:** the setup installs edge-tts outside Anki. To remove it too:
run `uv tool uninstall edge-tts`, and delete the "Read Aloud for Anki" folder
(Mac: ~/Library/Application Support; Windows: %LOCALAPPDATA%).

### Keys in the JSON (for reference)
- **engine**: `"edge"` (neural voice) or `"system"`.
- **edge_voice**: e.g. `"en-US-AvaNeural"`.
- **voice**: macOS voice name, `"auto"` (best installed) or `"default"` (the Read & Speak voice, which can be a Siri voice). On Linux, an espeak voice.
- **windows_voice**: e.g. `"onecore:Microsoft Libby"` or `"sapi:Microsoft Zira Desktop"`, or `"auto"`. Separate from `voice` because the config is shared between computers.
- **shortcut**: the key that reads (`"v"`); Shift+key reads slowly.
- **speed**: normal speed (`1.0` = 100%, up to `2.0`). **slow_speed**: Shift+key speed (`0.3`–`1.0`).
- **edge_prefetch**: fetch neural audio as soon as you highlight (sends the text to Microsoft). In Settings → Voice Downloads….
- **auto_read**: `true` reads each card's question and answer when they show (default `false`).
- **auto_read_answer**: on the answer side, `"whole"` (the sentence with the answer filled in, default) or `"words"` (just the answer).
- **cleanup**: read medical and science shorthand as words (K+ → potassium, ↑ → increased). Off automatically for decks with a non-English voice.
- **deck_voices**: `{"Deck name": {"edge_voice": …, "voice": …, "windows_voice": …, "cleanup": false}}`, edited in Settings → Voices for Specific Decks….
- **rate**: Mac system voice words per minute, `0` = normal (premium voices mostly ignore it).
- **edge_tts_path**: optional full path to `edge-tts` if it isn't found automatically.
- **pronunciations**: your respellings: right-click a word on a card → Fix Pronunciation…, or Settings → Pronunciations….
