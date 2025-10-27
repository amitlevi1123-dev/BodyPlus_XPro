# -*- coding: utf-8 -*-
"""
manual_squat_dumbbell_check.py — בדיקה עצמאית ל-squat.dumbbell
----------------------------------------------------------------
• מאתר אוטומטית את פונקציית טעינת הספרייה (runtime)
• משתמש ב-classifier.pick לזיהוי
• משתמש ב-scoring.calc_score_yaml.score_criteria לניקוד (או נופל חכם ל-calc_criteria)
"""

import os, sys, json, pkgutil, importlib, inspect
from types import ModuleType
from typing import Callable, Optional, List, Any

# ---------- Path & packages ----------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PKG_DIRS = [
    os.path.join(ROOT, "exercise_engine"),
    os.path.join(ROOT, "exercise_engine", "runtime"),
    os.path.join(ROOT, "exercise_engine", "classifier"),
    os.path.join(ROOT, "exercise_engine", "scoring"),
]
for d in PKG_DIRS:
    if not os.path.isdir(d):
        raise FileNotFoundError(f"לא נמצאה התיקייה: {d}")
    init_path = os.path.join(d, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8") as f:
            f.write("# auto-created by manual_squat_dumbbell_check.py\n")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------- helpers ----------
def _import_pkg(pkg_name: str) -> ModuleType:
    return importlib.import_module(pkg_name)

def _iter_submodules(pkg: ModuleType) -> List[ModuleType]:
    mods: List[ModuleType] = []
    if not hasattr(pkg, "__path__"):
        return mods
    for m in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        try:
            mods.append(importlib.import_module(m.name))
        except Exception as e:
            print(f"⚠️ לא נטען מודול {m.name}: {e}")
    return mods

def _find_callable_any(mods: List[ModuleType], names: List[str]) -> Optional[Callable]:
    for m in mods:
        for nm in names:
            fn = getattr(m, nm, None)
            if callable(fn):
                return fn
    return None

def _list_public_callables(mod: ModuleType) -> List[str]:
    return sorted([n for n, o in vars(mod).items() if callable(o) and not n.startswith("_")])

def _auto_pick_loader() -> Callable[[], Any]:
    pkg = _import_pkg("exercise_engine.runtime")
    subs = _iter_submodules(pkg)
    prefer = []
    for sub in ("runtime", "loader", "runtime_loader"):
        try:
            prefer.append(importlib.import_module(f"exercise_engine.runtime.{sub}"))
        except Exception:
            pass
    fn = _find_callable_any(prefer, ["load_library", "load_exercise_library", "get_library", "build_library", "load"])
    if fn:
        return fn
    for m in (prefer or subs or [pkg]):
        for name, obj in vars(m).items():
            if callable(obj) and ("load" in name.lower() or "library" in name.lower()):
                try:
                    sig = inspect.signature(obj)
                    if all(p.default is not p.empty or p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                           for p in sig.parameters.values()):
                        return obj
                except Exception:
                    continue
    print("\n❌ לא נמצאה פונקציית טעינת ספרייה ב-exercise_engine.runtime.*")
    for m in set(prefer or subs or [pkg]):
        print("  -", m.__name__, ":", ", ".join(_list_public_callables(m)) or "(אין)")
    raise AttributeError("חסר loader לספרייה")

def _auto_pick_classifier() -> Callable[..., Any]:
    pkg = _import_pkg("exercise_engine.classifier")
    subs = _iter_submodules(pkg)
    prefer = []
    for sub in ("classifier", "classify", "picker"):
        try:
            prefer.append(importlib.import_module(f"exercise_engine.classifier.{sub}"))
        except Exception:
            pass
    fn = _find_callable_any(prefer or subs or [pkg], ["pick"])
    if fn:
        return fn
    print("\n❌ לא נמצאה פונקציה pick ב-exercise_engine.classifier.*")
    for m in set(prefer or subs or [pkg]):
        print("  -", m.__name__, ":", ", ".join(_list_public_callables(m)) or "(אין)")
    raise AttributeError("חסר classifier.pick")

def _auto_pick_scorer() -> Callable[..., Any]:
    # אצלך קיים exercise_engine.scoring.calc_score_yaml עם score_criteria/calc_criteria
    pkg = _import_pkg("exercise_engine.scoring")
    subs = _iter_submodules(pkg)
    prefer = []
    for sub in ("calc_score_yaml", "scoring", "score", "engine", "evaluator"):
        try:
            prefer.append(importlib.import_module(f"exercise_engine.scoring.{sub}"))
        except Exception:
            pass

    # 1) העדפה ל-score_criteria
    fn = _find_callable_any(prefer or subs or [pkg], ["score_criteria"])
    if fn:
        return fn

    # 2) נפילה ל-calc_criteria (נעטוף לדומה ל-interface)
    calc = _find_callable_any(prefer or subs or [pkg], ["calc_criteria"])
    if calc:
        def _wrapper(payload: dict, exercise_def: Any) -> dict:
            # מצפה שהפונקציה תחזיר פירוט קריטריונים; נוסיף שדות סיכום בסיסיים
            res = calc(payload, exercise_def)  # type: ignore
            out = {"criteria": res}
            # ננסה להוציא score_total אם יש aggregate חיצוני; אם אין, נחשב ממוצע פשוט (best-effort)
            try:
                scores = [c.get("score", 0.0) for c in res.values()]
                out["score_total"] = sum(scores)/len(scores) if scores else 0.0
            except Exception:
                out["score_total"] = 0.0
            return out
        return _wrapper

    print("\n❌ לא נמצאה פונקציית ניקוד מתאימה (score_criteria/calc_criteria) ב-exercise_engine.scoring.*")
    for m in set(prefer or subs or [pkg]):
        print("  -", m.__name__, ":", ", ".join(_list_public_callables(m)) or "(אין)")
    raise AttributeError("חסר scorer (score_criteria או calc_criteria)")

# ---------- resolve API ----------
load_library = _auto_pick_loader()
pick         = _auto_pick_classifier()
score_fn     = _auto_pick_scorer()

print("🚀 Manual Check: squat.dumbbell — loaders OK")

# ---------- load library ----------
library = load_library()

# ---------- sample payload ----------
payload = {
    "pose.available": True,
    "objdet.dumbbell_present": True,
    "objdet.bar_present": False,

    "knee_left_deg": 90,
    "knee_right_deg": 88,

    "torso_forward_deg": 20,
    "spine_flexion_deg": 8,
    "spine_curvature_side_deg": 3,

    "knee_foot_alignment_left_deg": 4,
    "knee_foot_alignment_right_deg": 5,

    "features.stance_width_ratio": 1.0,
    "toe_angle_left_deg": 12,
    "toe_angle_right_deg": 13,
    "heel_lift_left": 0,
    "heel_lift_right": 0,

    "rep.timing_s": 1.5,
}

# ---------- classify ----------
res = pick(payload, library)
print("\n🔎 זיהוי תרגיל:")
print(f"  ➤ exercise_id: {getattr(res, 'exercise_id', None)}")
print(f"  ➤ confidence:  {getattr(res, 'confidence', 0.0):.2f}")
print(f"  ➤ reason:      {getattr(res, 'reason', '')}")
print(f"  ➤ inferred eq: {getattr(res, 'equipment_inferred', '')}")

# ---------- score ----------
exercise = library.get(res.exercise_id)
report = score_fn(payload, exercise)

print("\n📊 פירוט ניקוד:")
print(json.dumps(report, indent=2, ensure_ascii=False))

score_total = float(report.get("score_total", 0.0))
print("\n🏁 סיכום:")
print(f"  ➤ ציון כולל: {score_total:.3f}")
if score_total >= 0.85:
    print("  ✅ טכניקה מצוינת!")
elif score_total >= 0.70:
    print("  🙂 טכניקה טובה, יש מקום לשיפור קטן.")
else:
    print("  ⚠️ הציון נמוך — בדוק יציבה/עומק/עקבים.")
print("\n✅ Done.\n")
