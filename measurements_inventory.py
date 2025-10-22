# -*- coding: utf-8 -*-
# tools/diagnostics/measurements_inventory.py
# ------------------------------------------------------------
# אינבנטורי מדידות: בודק אילו מפתחות קנוניים מ-aliases.yaml באמת מופיעים
# בקבצי JSON (למשל בתיקיית reports/), ומה חסר.
#
# הוראות הרצה (PowerShell):
#   cd C:/Users/Owner/Desktop/BodyPlus/BodyPlus_XPro
#   $env:PYTHONPATH = "$PWD"
#   python tools/diagnostics/measurements_inventory.py --aliases exercise_library/aliases.yaml --scan reports
#
# תלות: pip install pyyaml
# ------------------------------------------------------------

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple

try:
    import yaml  # PyYAML
except Exception:
    yaml = None


# --------------- עזרי IO ---------------

def load_aliases(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(f"[ERROR] aliases file not found: {path}", file=sys.stderr)
        sys.exit(1)
    if yaml is None:
        print("[ERROR] PyYAML is not installed. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict) or "canonical_keys" not in data:
            raise ValueError("aliases.yaml missing 'canonical_keys' root key")
        return data
    except Exception as e:
        print(f"[ERROR] failed to load aliases.yaml: {e}", file=sys.stderr)
        sys.exit(1)


def discover_json_files(root: Path) -> List[Path]:
    if root.is_file() and root.suffix.lower() == ".json":
        return [root]
    if not root.exists():
        return []
    files: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".json":
            files.append(p)
    return files


# --------------- עזרי Flatten ---------------

def _flatten_json(obj: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            nk = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten_json(v, nk))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            nk = f"{prefix}.{i}" if prefix else str(i)
            out.update(_flatten_json(v, nk))
    else:
        out[prefix] = obj
    return out


# --------------- לוגיקת אינבנטורי ---------------

PASS_PREFIXES: Tuple[str, ...] = ("rep.", "pose.", "view.", "bar.", "objdet.", "features.")

def canonical_keyset(aliases: Dict[str, Any]) -> Set[str]:
    c = aliases.get("canonical_keys") or {}
    return set(c.keys())


def build_alias_map(aliases: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    c = aliases.get("canonical_keys") or {}
    for canon, spec in c.items():
        out[canon] = canon
        al = (spec or {}).get("aliases") or []
        for a in al:
            if isinstance(a, str) and a:
                out[a] = canon
    return out


def map_seen_to_canonical(flat: Dict[str, Any], alias_map: Dict[str, str]) -> Set[str]:
    seen: Set[str] = set()
    for k in flat.keys():
        if k in alias_map:
            seen.add(alias_map[k])
            continue
        if any(k.startswith(pfx) for pfx in PASS_PREFIXES):
            seen.add(k)
    return seen


def rep_core_keys() -> List[str]:
    return [
        "rep.state",
        "rep.active",
        "rep.dir",
        "rep.eccentric",
        "rep.concentric",
        "rep.progress",
        "rep.rep_id",
        "rep.timing_s",
        "rep.rom",
        "rep.rest_s",
        "rep.ecc_s",
        "rep.con_s",
        "rep.quality",
    ]


def pretty_pct(n: int, d: int) -> str:
    return "—" if d == 0 else f"{(100.0*n/d):.1f}%"


def run_inventory(aliases_path: Path, scan_paths: List[Path], print_canonical: bool) -> int:
    aliases = load_aliases(aliases_path)
    canon_keys = canonical_keyset(aliases)
    alias_map = build_alias_map(aliases)

    if print_canonical:
        print("\n=== CANONICAL KEYS ===")
        for k in sorted(canon_keys):
            unit = (aliases.get("canonical_keys", {}).get(k, {}) or {}).get("unit")
            print(f"- {k}  [{unit}]")
        print(f"\nTotal: {len(canon_keys)} keys")
        return 0

    files: List[Path] = []
    for p in scan_paths:
        files.extend(discover_json_files(p))

    if not files:
        print("[WARN] לא נמצאו קבצי JSON לסריקה (בדוק את --scan).")
        return 0

    seen_counts: Dict[str, int] = {k: 0 for k in canon_keys}
    rep_core_presence: Dict[str, int] = {k: 0 for k in rep_core_keys()}
    total_files = 0

    for fp in files:
        # תמיכה גם ב-json וגם ב-jsonl פשוט
        try:
            with fp.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            try:
                with fp.open("r", encoding="utf-8") as f:
                    lines = [json.loads(line) for line in f if line.strip().startswith("{")]
                    data = {"_jsonl": lines}
            except Exception:
                continue

        total_files += 1
        objs: List[Any] = []
        if isinstance(data, dict) and "_jsonl" in data and isinstance(data["_jsonl"], list):
            objs.extend(data["_jsonl"])
        else:
            objs.append(data)

        seen_here: Set[str] = set()
        rep_seen_here: Set[str] = set()

        for obj in objs:
            flat = _flatten_json(obj)
            mapped = map_seen_to_canonical(flat, alias_map)
            seen_here.update(mapped)
            for rk in rep_core_keys():
                if rk in flat or any(k.startswith(rk) for k in flat.keys()):
                    rep_seen_here.add(rk)

        for k in seen_here:
            if k in seen_counts:
                seen_counts[k] += 1
        for rk in rep_seen_here:
            rep_core_presence[rk] += 1

    print("=== MEASUREMENTS INVENTORY ===")
    print(f"Aliases: {aliases_path}")
    print(f"Scanned files: {len(files)} (counted {total_files} loaded)\n")

    missing = sorted([k for k, c in seen_counts.items() if c == 0])
    print("— Canonical coverage —")
    covered = sum(1 for c in seen_counts.values() if c > 0)
    print(f"Covered: {covered}/{len(seen_counts)}  ({pretty_pct(covered, len(seen_counts))})")
    if missing:
        print("\nMissing canonical keys (never seen):")
        for k in missing:
            unit = (aliases.get("canonical_keys", {}).get(k, {}) or {}).get("unit")
            print(f"  - {k} [{unit}]")
    else:
        print("\nGreat! All canonical keys appeared at least once in the scanned data.")

    print("\n— Rep core presence (how many files contained each) —")
    width = max(len(k) for k in rep_core_keys())
    for k in rep_core_keys():
        cnt = rep_core_presence.get(k, 0)
        print(f"  {k.ljust(width)} : {cnt}/{total_files} ({pretty_pct(cnt, total_files)})")

    print("\nTips:")
    print("  • אם מפתח קנוני קריטי חסר — ודא שהחישוב בקינמטיקס קיים ושיש אליו alias.")
    print("  • אם ה-rep.* נמוכים מדי — בדוק את ספי rep_signal בתרגיל (phase_delta/min_rom/min_rep_ms וכו').")
    print("  • לפני הוספת תרגיל חדש, הרץ שוב אחרי סט דמו קצר והבט שהמדדים מופיעים.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Measurements Inventory")
    ap.add_argument("--aliases", required=True, help="Path to exercise_library/aliases.yaml")
    ap.add_argument("--scan", nargs="+", help="Folders or JSON files to scan (e.g., reports/)", default=["reports"])
    ap.add_argument("--print-canonical", action="store_true", help="Print canonical key list and exit")
    args = ap.parse_args()

    aliases_path = Path(args.aliases).resolve()
    scan_paths = [Path(p).resolve() for p in args.scan]

    rc = run_inventory(aliases_path, scan_paths, args.print_canonical)
    sys.exit(rc)


if __name__ == "__main__":
    main()
