# -*- coding: utf-8 -*-
"""
manual_squat_dumbbell_check.py — בדיקה עצמאית חכמה ל-squat.dumbbell
--------------------------------------------------------------------
1) מבטיח שהתיקיות exercise_engine/* הן חבילות (יוצר __init__.py אם חסר).
2) מוסיף את שורש הפרויקט ל-sys.path.
3) מאתר *אוטומטית* פונקציות מתוך:
   • exercise_engine.runtime   → פונקציית טעינת ספרייה (load/get/build library)
   • exercise_engine.classifier → pick
   • exercise_engine.scoring   → score_exercise / score
4) מריץ זיהוי + ניקוד עם payload לדוגמה ומדפיס תוצאות.
"""

import os, sys, json, pkgutil, importlib, inspect
from types import ModuleType
from typing import Callable, Optional, List, Any

# --- 1) מצא את שורש הפרויקט והכן חבילות ---
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

# --- 2) ודא ששורש הפרויקט ב-path ---
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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

def _find_callable(mod: ModuleType, names: List[str]) -> Optional[Callable]:
    for nm in names:
        fn = getattr(mod, nm, None)
        if callable(fn):
            return fn
    return None

def _find_callable_any(mods: List[ModuleType], names: List[str]) -> Optional[Callable]:
    for m in mods:
        fn = _find_callable(m, names)
        if fn:
            return fn
    return None

def _list_public_callables(mod: ModuleType) -> List[str]:
    out = []
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        if callable(obj):
            out.append(name)
    return sorted(out)

def _auto_pick_loader(pkg_name: str) -> Callable[[], Any]:
    """
    מוצא פונקציית 'טעינת ספרייה' ב-exercise_engine.runtime.* לפי:
    1) שמות מועמדים נפוצים
    2) כל פונקציה ששמה מכיל 'load' או 'library', עם 0 ארגומנטים נדרשים
    """
    pkg = _import_pkg(pkg_name)
    subs = _iter_submodules(pkg)

    # 1) שמות נפוצים
    candidate_mods = []
    for subname in ("runtime", "loader", "runtime_loader"):
        try:
            candidate_mods.append(importlib.import_module(f"{pkg_name}.{subname}"))
        except Exception:
            pass
    candidate_names = ["load_library", "load_exercise_library", "get_library", "build_library", "load"]
    fn = _find_callable_any(candidate_mods, candidate_names)
    if fn:
        return fn

    # 2) סריקה רחבה: כל פונקציה עם 'load' או 'library' בשם וללא פרמטרים נדרשים
    search_mods = candidate_mods or subs or [pkg]
    for m in search_mods:
        for name, obj in vars(m).items():
            if not callable(obj):
                continue
            low = name.lower()
            if ("load" in low or "library" in low) and not name.startswith("_"):
                sig = None
                try:
                    sig = inspect.signature(obj)
                except Exception:
                    continue
                has_required = any(p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                                   for p in sig.parameters.values())
                if not has_required:
                    # ניסיון קריאה זהיר — אם נכשל, נמשיך הלאה
                    return obj

    # 3) דיאגנוסטיקה מועילה
    print("\n❌ לא נמצאה פונקציית טעינת ספרייה ב-exercise_engine.runtime.*")
    print("📂 מודולים זמינים:")
    for m in [*set(search_mods)]:
        print("  -", m.__name__)
        print("    פונקציות:", ", ".join(_list_public_callables(m)) or "(אין)")
    raise AttributeError("לא נמצאה פונקציית טעינת ספרייה (load/get/build library)")

def _auto_pick_function(pkg_name: str, prefer_modules: List[str], prefer_funcs: List[str]) -> Callable:
    pkg = _import_pkg(pkg_name)
    subs = _iter_submodules(pkg)

    # 1) נסה מודולים ופונקציות מועדפים
    prefer_mods = []
    for sub in prefer_modules:
        try:
            prefer_mods.append(importlib.import_module(f"{pkg_name}.{sub}"))
        except Exception:
            pass
    fn = _find_callable_any(prefer_mods, prefer_funcs)
    if fn:
        return fn

    # 2) סריקה רחבה על כל המודולים
    for m in (prefer_mods or subs or [pkg]):
        fn = _find_callable(m, prefer_funcs)
        if fn:
            return fn

    # 3) דיאגנוסטיקה
    print(f"\n❌ לא נמצאה פונקציה מתוך {prefer_funcs} בתוך {pkg_name}.*")
    print("📂 מודולים זמינים:")
    for m in set(prefer_mods or subs or [pkg]):
        print("  -", m.__name__)
        print("    פונקציות:", ", ".join(_list_public_callables(m)) or "(אין)")
    raise AttributeError(f"לא נמצאה פונקציה מתאימה ב-{pkg_name}")

# --- 3) אתור אוטומטי של הפונקציות הדרושות ---
load_library = _auto_pick_loader("exercise_engine.runtime")
pick = _auto_pick_function(
    "exercise_engine.classifier",
    prefer_modules=["classifier", "classify", "picker"],
    prefer_funcs=["pick"]
)
score_exercise = _auto_pick_function(
    "exercise_engine.scoring",
    prefer_modules=["scoring", "score", "engine", "evaluator"],
    prefer_funcs=["score_exercise", "score"]
)

print("🚀 Manual Check: squat.dumbbell (auto-discovery imports OK)")

# --- 4) טען ספריית תרגילים ---
library = load_library()

# --- 5) Payload לדוגמה (דאמבל מזוהה, אין מוט) ---
payload = {
    "pose.available": True,
    "objdet.dumbbell_present": True,
    "objdet.bar_present": False,

    # עומק/ברכיים
    "knee_left_deg": 90,
    "knee_right_deg": 88,

    # גו/עמוד שדרה
    "torso_forward_deg": 20,
    "spine_flexion_deg": 8,
    "spine_curvature_side_deg": 3,

    # יישור ברך-כף רגל
    "knee_foot_alignment_left_deg": 4,
    "knee_foot_alignment_right_deg": 5,

    # עמידה/כפות רגליים
    "features.stance_width_ratio": 1.0,
    "toe_angle_left_deg": 12,
    "toe_angle_right_deg": 13,
    "heel_lift_left": 0,
    "heel_lift_right": 0,

    # טמפו
    "rep.timing_s": 1.5,
}

# --- 6) זיהוי תרגיל ---
res = pick(payload, library)

print("\n🔎 זיהוי תרגיל:")
print(f"  ➤ exercise_id: {getattr(res, 'exercise_id', None)}")
print(f"  ➤ confidence:  {getattr(res, 'confidence', 0.0):.2f}")
print(f"  ➤ reason:      {getattr(res, 'reason', '')}")
print(f"  ➤ inferred eq: {getattr(res, 'equipment_inferred', '')}")

# --- 7) ניקוד ---
exercise = library.get(res.exercise_id)
report = score_exercise(payload, exercise)

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
