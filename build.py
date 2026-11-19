"""Package the add-on:

  dist/read_aloud.ankiaddon          to share as a file (Tools → Add-ons → Install from file)
  dist/read_aloud-ankiweb.ankiaddon  to upload to AnkiWeb (no manifest.json)

Only the add-on's own files go in: never meta.json (your settings), user_files
(your audio cache), backups or __pycache__.
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "read_aloud")
DIST = os.path.join(ROOT, "dist")
FILES = ["__init__.py", "config.py", "text.py", "voices.py", "speech.py", "setup_window.py",
         "settings_window.py", "win_tts.ps1", "config.json", "config.md", "manifest.json"]


def package(out: str, skip: set) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            if name not in skip:
                z.write(os.path.join(SRC, name), name)
    print(f"built {out}")


def main() -> None:
    os.makedirs(DIST, exist_ok=True)
    package(os.path.join(DIST, "read_aloud.ankiaddon"), set())
    package(os.path.join(DIST, "read_aloud-ankiweb.ankiaddon"), {"manifest.json"})


if __name__ == "__main__":
    main()
