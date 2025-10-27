# tools/find_camera_openers_plus.py
# -*- coding: utf-8 -*-
import os, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INCLUDE_VENV = False  # הפוך ל-True אם תרצה לסרוק גם venv

PATTERNS = [
    r"\bcv2\.\s*VideoCapture\s*\(",
    r"\bVideoCapture\s*\(",                 # import * / alias
    r"\.open\s*\(\s*(?:\d+|[\"'])/?dev/video0",  # cap.open("/dev/video0") / cap.open(0)
    r"\bCAP_(?:V4L2|DSHOW|MSMF|GSTREAMER|FFMPEG)\b",
    r"\bstart_auto_capture\s*\(",           # פותח מצלמה אצלך
    r"\bAUTO_CAPTURE\b",
    r"\bget_streamer\s*\(",                 # עלול להדליק סטרימר
]

TOP_LEVEL_SUSPECTS = [
    r"\bcv2\.\s*VideoCapture\s*\(",
    r"\bstart_auto_capture\s*\(",
]

ignore_dirs = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".idea", ".vscode"}
if not INCLUDE_VENV:
    ignore_dirs |= {".venv", "venv", "env"}

rx = [re.compile(p) for p in PATTERNS]
rx_top = [re.compile(p) for p in TOP_LEVEL_SUSPECTS]

def scan_file(p: Path):
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return [], False
    hits = []
    for i, line in enumerate(txt.splitlines(), 1):
        if any(r.search(line) for r in rx):
            hits.append((i, line.strip()))
    # בדיקה אם יש קריאות חשודות ברמת המודול (פשטני: בלי אינדנטציה/def/class)
    top_level = False
    for i, line in enumerate(txt.splitlines(), 1):
        ls = line.strip()
        if (ls and not ls.startswith(("#", "def ", "class ", "from ", "import "))
            and not line.startswith(" ") and not line.startswith("\t")):
            if any(r.search(ls) for r in rx_top):
                top_level = True
                break
    return hits, top_level

def main():
    total = 0
    print("\n=== 🔍 דו\"ח פתיחות מצלמה / חשודים ===\n")
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # סינון תיקיות
        dn = os.path.basename(root)
        if dn in ignore_dirs:
            dirs[:] = []
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            p = Path(root) / f
            hits, top = scan_file(p)
            if hits:
                print(f"📂 {p.relative_to(PROJECT_ROOT)}" + ("   [TOP-LEVEL SUSPECT]" if top else ""))
                for ln, line in hits:
                    print(f"   {ln:5d}: {line}")
                print("-" * 60)
                total += len(hits)
    print(f"\nסה\"כ {total} מופעים שנמצאו.\n")
    print("טיפים:\n"
          "- אם יש [TOP-LEVEL SUSPECT] → כנראה שנקרא בזמן import.\n"
          "- חפש קבצים שנגררים אוטומטית על ידי server.py / blueprints.\n")

if __name__ == "__main__":
    main()
