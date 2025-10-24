# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# runtime.py — אורקסטרטור המנוע (Frame → Report)
# -----------------------------------------------------------------------------
# זרימה (פשוטה ונקייה):
# 1) Normalize (aliases)
# 2) Low-Confidence Gate (אופציונלי)
# 3) Classifier → בחירת תרגיל (לפני Reps/Sets) + Freeze guard
# 4) Rep Segmenter (rep.*) + Set Counter
# 5) Validate (availability / unscored)
# 6) Score/Vote (calc_score_yaml — מונחה YAML)
# 7) Hints
# 8) Build Report (+ Camera Audit בסוף סט) + הזרקת rep.* לדוח
# -----------------------------------------------------------------------------

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, List

from exercise_engine.runtime.engine_settings import SETTINGS
from exercise_engine.runtime import log as elog

def _emit(ev_type: str, severity: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    try:
        elog.emit(ev_type, severity, message, **(context or {}))
    except Exception:
        pass

# ───────────────────── Normalizer ─────────────────────
from dataclasses import dataclass as _dc_dataclass

@_dc_dataclass
class _NormalizeStats:
    input_keys: int = 0
    canonical_keys: int = 0
    rewrites: int = 0
    conflicts: int = 0
    unknowns: int = 0

@_dc_dataclass
class _NormalizeResult:
    canonical: Dict[str, Any] = field(default_factory=dict)
    rewrites: List[Tuple[str, str]] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    stats: _NormalizeStats = field(default_factory=_NormalizeStats)

_ALLOWED_PASS_PREFIXES = ("features.", "bar.", "rep.", "pose.", "view.", "objdet.")

def _unit_for_key(canonical_key: str, aliases: Dict[str, Any]) -> Optional[str]:
    try:
        return (aliases.get("canonical_keys") or {}).get(canonical_key, {}).get("unit")
    except Exception:
        return None

def _tol_for_unit(unit: Optional[str], aliases: Dict[str, Any]) -> float:
    base = (aliases.get("tolerances") or {})
    if unit and unit in base:
        try:
            return float(base[unit])
        except Exception:
            return 0.0
    return 0.0

def _numeric(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def _canonical_map(aliases: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    c = aliases.get("canonical_keys") or {}
    for canon, spec in c.items():
        al = (spec or {}).get("aliases") or []
        for a in al:
            if isinstance(a, str) and a:
                out[a] = canon
    for canon in c.keys():
        out.setdefault(canon, canon)
    return out

class _Normalizer:
    def __init__(self, aliases: Dict[str, Any]) -> None:
        if not isinstance(aliases, dict):
            raise ValueError("aliases must be a dict loaded from aliases.yaml")
        self.aliases = aliases
        self._raw2canon = _canonical_map(aliases)

    def normalize(self, raw_metrics: Dict[str, Any]) -> _NormalizeResult:
        res = _NormalizeResult()
        if not isinstance(raw_metrics, dict):
            return res
        res.stats.input_keys = len(raw_metrics)

        candidates: Dict[str, List[Tuple[str, Any]]] = {}
        unknowns: List[str] = []

        for raw_key, raw_val in raw_metrics.items():
            canon = self._raw2canon.get(raw_key)
            if canon:
                candidates.setdefault(canon, []).append((raw_key, raw_val))
                if canon != raw_key:
                    res.rewrites.append((raw_key, canon))
                continue
            if any(raw_key.startswith(pfx) for pfx in _ALLOWED_PASS_PREFIXES):
                candidates.setdefault(raw_key, []).append((raw_key, raw_val))
                continue
            unknowns.append(raw_key)

        canonical_out: Dict[str, Any] = {}
        conflicts: List[Dict[str, Any]] = []

        for canon_key, pairs in candidates.items():
            if len(pairs) == 1:
                canonical_out[canon_key] = pairs[0][1]
                continue

            unit = _unit_for_key(canon_key, self.aliases)
            tol = _tol_for_unit(unit, self.aliases)

            numeric_vals: List[float] = []
            non_numeric_vals: List[Any] = []
            for _, v in pairs:
                nv = _numeric(v)
                if nv is None:
                    non_numeric_vals.append(v)
                else:
                    numeric_vals.append(nv)

            conflict = False
            if numeric_vals:
                vmin, vmax = min(numeric_vals), max(numeric_vals)
                if (vmax - vmin) > tol:
                    conflict = True
                chosen_val = sum(numeric_vals) / len(numeric_vals)
            else:
                uniq = {repr(x) for x in non_numeric_vals}
                conflict = len(uniq) > 1
                chosen_val = non_numeric_vals[0] if non_numeric_vals else None

            if conflict:
                conflicts.append({
                    "canonical": canon_key,
                    "unit": unit,
                    "tolerance": tol,
                    "keys": [k for k, _ in pairs],
                    "values": [v for _, v in pairs],
                })
                _emit("alias_conflict", "warn",
                      f"conflict for '{canon_key}' (unit={unit}, tol={tol})",
                      {"canonical": canon_key,
                       "keys": [k for k, _ in pairs],
                       "values": [v for _, v in pairs]})

            canonical_out[canon_key] = chosen_val

        res.canonical = canonical_out
        res.conflicts = conflicts
        res.unknowns = unknowns
        res.stats.canonical_keys = len(canonical_out)
        res.stats.rewrites = len(res.rewrites)
        res.stats.conflicts = len(conflicts)
        res.stats.unknowns = len(unknowns)

        if res.stats.rewrites > 0:
            _emit("alias_rewrite", "info",
                  f"{res.stats.rewrites} alias rewrites applied",
                  {"count": res.stats.rewrites})
        return res

# ───────────────────── Runtime (Classifier/Gates/Report) ─────────────────────
from exercise_engine.registry.loader import ExerciseDef, Library
from exercise_engine.runtime.validator import evaluate_availability, decide_unscored
# חישוב ציון מונחה-YAML:
from exercise_engine.scoring import calc_score_yaml as scoring_basic
from exercise_engine.feedback.explain import generate_hints
from exercise_engine.classifier.classifier import pick as cls_pick, ClassifierState

# ספירת סטים
from exercise_engine.segmenter.set_counter import SETS

# דו"ח + מצלמה
from exercise_engine.report.report_builder import build_payload, attach_camera_summary
from exercise_engine.feedback.camera_wizard import SetVisibilityAudit, save_set_audit

# ───────────────────── זמן/Freeze ─────────────────────
def _now_ms() -> int:
    return int(time.time() * 1000)

def _detect_freeze(canon: Dict[str, Any]) -> bool:
    if not SETTINGS.classifier.FREEZE_DURING_REP:
        return False
    try:
        return bool(canon.get("rep.freeze_active") or canon.get("rep.in_rep_window"))
    except Exception:
        return False

# ───────────────────── State גלובלי ─────────────────────
_classifier_state = ClassifierState()
_RUNTIME_LAST_PICKED_ID: Optional[str] = None
_RUNTIME_LAST_SWITCH_MS: Optional[int] = None

# Audit למצלמה
_SET_AUDIT: Optional[SetVisibilityAudit] = None
_CURRENT_EX_ID: Optional[str] = None
_CURRENT_SET_INDEX: Optional[int] = None

# ───────────────────── עזרי סטים/מצלמה ─────────────────────
def _begin_set_audit(ex_id: Optional[str] = None, set_index: Optional[int] = None) -> None:
    global _SET_AUDIT, _CURRENT_EX_ID, _CURRENT_SET_INDEX
    _SET_AUDIT = SetVisibilityAudit()
    _SET_AUDIT.begin_set()
    _CURRENT_EX_ID = ex_id
    _CURRENT_SET_INDEX = set_index
    _emit("camera_audit", "info", "begin set audit", {"exercise": ex_id, "set_index": set_index})

def _ingest_set_audit(canon: Dict[str, Any]) -> None:
    try:
        if _SET_AUDIT is not None:
            _SET_AUDIT.ingest({
                "average_visibility": canon.get("average_visibility"),
                "confidence": canon.get("confidence") or canon.get("pose.confidence"),
                "dt_ms": canon.get("dt_ms") or canon.get("dt"),
                "availability": {
                    "pose": bool(canon.get("pose.available") or canon.get("pose.ok") or canon.get("pose")),
                    "measurements": bool(canon.get("measurements.ok") or canon.get("measurements")),
                }
            })
    except Exception:
        pass

def _end_set_audit_and_attach(report: Dict[str, Any]) -> Dict[str, Any]:
    global _SET_AUDIT
    if _SET_AUDIT is None:
        return attach_camera_summary(report, camera_summary=None, add_hint_if_risky=True, save_json=False)
    try:
        summary = _SET_AUDIT.end_set()
    except Exception:
        summary = None
    finally:
        _SET_AUDIT = None
    meta = {"exercise": _CURRENT_EX_ID, "set_index": _CURRENT_SET_INDEX}
    try:
        if summary:
            save_set_audit(summary, add_meta=meta)
    except Exception:
        pass
    return attach_camera_summary(report, summary, add_hint_if_risky=True, save_json=False, meta=meta)

# ───────────────────── הפונקציה הראשית ─────────────────────
def run_once(*, raw_metrics: Dict[str, Any], library: Library,
             exercise_id: Optional[str] = None, payload_version: str = "1.0") -> Dict[str, Any]:
    global _RUNTIME_LAST_PICKED_ID, _RUNTIME_LAST_SWITCH_MS, _CURRENT_EX_ID

    # 1) Normalize
    normalizer = _Normalizer(library.aliases)
    nres = normalizer.normalize(raw_metrics)
    canonical = nres.canonical

    # 1b) Low-Confidence Gate (אופציונלי)
    if SETTINGS.runtime.LOWCONF_GATE_ENABLED:
        pose_conf = None
        try:
            for k in ("pose.confidence", "average_visibility", "pose.average_confidence"):
                if canonical.get(k) is not None:
                    pose_conf = float(canonical.get(k))
                    break
        except Exception:
            pose_conf = None

        if pose_conf is not None and pose_conf < SETTINGS.runtime.LOWCONF_MIN:
            _emit("low_pose_confidence", "warn", "pose confidence below threshold",
                  {"value": pose_conf, "min": SETTINGS.runtime.LOWCONF_MIN})
            report = build_payload(
                exercise=None, canonical=canonical, availability={},
                overall_score=None, overall_quality=None,
                unscored_reason="low_pose_confidence",
                hints=["איכות זיהוי נמוכה — שפר תאורה/מרחק/זווית."],
                diagnostics_recent=elog.tail(SETTINGS.diagnostics.DIAG_TAIL_LIMIT),
                library_version=library.version, payload_version=payload_version,
            )
            _emit("report_built", "info", "report built (lowconf gate)", {"score": None, "unscored": True})
            return report

    # 2) Exercise pick (לפני Reps/Sets)
    ex: Optional[ExerciseDef] = None
    pick_res = None
    if exercise_id:
        ex = library.index_by_id.get(exercise_id)

    now_ms = int(time.time() * 1000)
    freeze_active = _detect_freeze(canonical)

    if ex is None:
        pick_res = cls_pick(canonical, library, prev_state=_classifier_state, freeze_active=freeze_active)
        picked_id = pick_res.exercise_id if pick_res and pick_res.exercise_id else None

        # שמירת תרגיל בזמן חלון חזרה
        if freeze_active and _RUNTIME_LAST_PICKED_ID and picked_id and picked_id != _RUNTIME_LAST_PICKED_ID:
            _emit("freeze_on_rep_window", "info", "runtime kept previous during freeze",
                  {"prev": _RUNTIME_LAST_PICKED_ID, "proposed": picked_id})
            picked_id = _RUNTIME_LAST_PICKED_ID

        if picked_id:
            ex = library.index_by_id.get(picked_id)

        if ex and ex.id:
            if _RUNTIME_LAST_PICKED_ID is None:
                _RUNTIME_LAST_PICKED_ID = ex.id
            elif ex.id != _RUNTIME_LAST_PICKED_ID:
                _RUNTIME_LAST_SWITCH_MS = now_ms
                _emit("classifier_switched_runtime", "info", "runtime detected exercise switch",
                      {"from": _RUNTIME_LAST_PICKED_ID, "to": ex.id})
                _RUNTIME_LAST_PICKED_ID = ex.id

    # אם עדיין אין תרגיל — בונים דו"ח "אין תרגיל"
    if ex is None:
        report = build_payload(
            exercise=None, canonical=canonical, availability={},
            overall_score=None, overall_quality=None, unscored_reason="no_exercise_selected",
            hints=[], diagnostics_recent=elog.tail(SETTINGS.diagnostics.DIAG_TAIL_LIMIT),
            library_version=library.version, payload_version=payload_version,
        )
        _emit("no_exercise_selected", "info", "report built (no exercise)", {"have_exercises": len(library.exercises)})
        return report

    # 2b) Grace Period אחרי החלפת תרגיל
    if SETTINGS.runtime.GRACE_MS > 0:
        last_sw = _RUNTIME_LAST_SWITCH_MS
        if pick_res is not None:
            try:
                st = getattr(pick_res, "stability", None)
                cand_last_sw = getattr(pick_res.state, "last_switch_ms", None) or (getattr(st, "last_switch_ms", None) if st else None)
                if cand_last_sw:
                    last_sw = cand_last_sw
            except Exception:
                pass

        within_grace = bool(last_sw and (now_ms - int(last_sw)) < SETTINGS.runtime.GRACE_MS)
        if within_grace:
            remain = max(0, SETTINGS.runtime.GRACE_MS - (now_ms - int(last_sw)))
            _emit("grace_period_active", "info", "scoring delayed due to grace window",
                  {"ms_remaining": remain, "exercise": ex.id})
            report = build_payload(
                exercise=ex, canonical=canonical, availability={},
                overall_score=None, overall_quality=None,
                unscored_reason="grace_period",
                hints=["החלפת תרגיל — מייצב נתונים רגעית."],
                diagnostics_recent=elog.tail(SETTINGS.diagnostics.DIAG_TAIL_LIMIT),
                library_version=library.version, payload_version=payload_version,
            )
            _emit("report_built", "info", "report built (grace period)", {"score": None, "unscored": True})
            return report

    # 3) Rep Segmenter (אחרי בחירה) + Set Counter
    # טריגרים התחלה/סיום סט (מצלמה/מטא) — נתחיל איסוף אם קיבלנו set.begin
    try:
        if bool(raw_metrics.get("set.begin")):
            _begin_set_audit(ex.id if ex else None, raw_metrics.get("set.index"))
    except Exception:
        pass

    rep_event: Optional[Dict[str, Any]] = None
    try:
        from exercise_engine.segmenter.reps import update_rep_state
        ex_cfg = ex.raw if ex else None  # ← חשוב: משתמשים ב-ex.raw (YAML אחרי extends)
        now_ms_rep = _now_ms()
        rep_updates, rep_event = update_rep_state(canonical, now_ms=now_ms_rep, exercise_cfg=ex_cfg)
        if rep_updates:
            canonical.update(rep_updates)
    except Exception as e:
        _emit("rep_segmenter_error", "warn", f"rep segmenter error: {e}")

    # ספירת סטים + הזרקת סטים ל-canonical
    try:
        now_ms2 = _now_ms()
        auto_closed = SETS.update(rep_event, now_ms2)
        if auto_closed:
            _emit("set_closed", "info", "set closed (auto)", auto_closed)
        SETS.inject(canonical)
        for k in ("rep.set_active", "rep.set_index", "rep.set_reps", "rep.set_total"):
            canonical.setdefault(k, 0 if k != "rep.set_active" else False)
    except Exception as e:
        _emit("set_counter_error", "warn", f"set counter error: {e}")

    # normalize: None → ערכי ברירת מחדל בשדות rep.* (ליציבות ה-UI)
    if "rep.state" in canonical or "rep.rep_id" in canonical:
        for k, v in list(canonical.items()):
            if k.startswith("rep.") and v is None:
                if k.endswith((".timing_s", ".rom", ".rest_s", ".ecc_s", ".con_s", ".progress")):
                    canonical[k] = 0.0
                elif k.endswith(".rep_id"):
                    canonical[k] = 0
                elif k.endswith((".active", ".eccentric", ".concentric", ".in_rep_window",
                                  ".freeze_active", ".set_active")):
                    canonical[k] = False
                else:
                    canonical[k] = 0

    # 4) Validate & Unscored
    availability = evaluate_availability(ex, canonical)
    is_unscored, reason, _ = decide_unscored(ex, availability)

    # 5) Score & Vote (מונחה YAML)
    overall_score: Optional[float] = None
    overall_quality: Optional[str] = None
    per_crit_scores: Dict[str, scoring_basic.CriterionScore] = {}
    if not is_unscored:
        per_crit_scores = scoring_basic.score_criteria(exercise=ex, canonical=canonical, availability=availability)
        vote_res = scoring_basic.vote(exercise=ex, per_criterion=per_crit_scores)
        overall_score, overall_quality = vote_res.overall, vote_res.quality
    else:
        # מייצרים רשומות ריקות לכל הקריטריונים (לתאימות דו"ח)
        for name, _info in (ex.criteria or {}).items():
            avail = bool(availability.get(name, {}).get("available", False))
            per_crit_scores[name] = scoring_basic.CriterionScore(id=name, available=avail, score=None, reason=None)

    # 6) Hints
    hints = generate_hints(exercise=ex, canonical=canonical, per_criterion_scores=per_crit_scores)
    if SETTINGS.report.MAX_HINTS and isinstance(hints, list) and len(hints) > SETTINGS.report.MAX_HINTS:
        hints = hints[:SETTINGS.report.MAX_HINTS]

    # 7) Build Report
    report = build_payload(
        exercise=ex, canonical=canonical, availability=availability,
        overall_score=overall_score if not is_unscored else None,
        overall_quality=overall_quality if not is_unscored else None,
        unscored_reason=reason if is_unscored else None,
        hints=hints,
        diagnostics_recent=elog.tail(SETTINGS.diagnostics.DIAG_TAIL_LIMIT),
        library_version=library.version, payload_version=payload_version,
        per_criterion_scores=per_crit_scores,
    )

    # הזרקת score_pct לכל קריטריון (אם יש ציון) — שימושי ל-Tooltip
    try:
        if per_crit_scores and "scoring" in report and isinstance(report["scoring"].get("criteria"), list):
            def _to_pct_local(x):
                try:
                    if x is None:
                        return None
                    v = float(x) * 100.0
                    return int(round(v)) if SETTINGS.report.ROUND_SCORE_PCT else v
                except Exception:
                    return None
            score_map = {k: v.score for k, v in per_crit_scores.items() if v.score is not None}
            for item in report["scoring"]["criteria"]:
                cid = item.get("id")
                if cid in score_map and item.get("available", False):
                    sc = float(score_map[cid])
                    item["score"] = sc
                    item["score_pct"] = _to_pct_local(sc)
    except Exception as e:
        _emit("criteria_score_pct_inject_error", "warn", f"{e}")

    # --- הזרקת rep.* לדוח (כולל שדות סט שהוזרקו ל-canonical) ---
    try:
        if not isinstance(report.get("measurements"), dict):
            report["measurements"] = {}
        m = report["measurements"]
        for k, v in canonical.items():
            if k.startswith("rep."):
                m[k] = v
    except Exception as e:
        _emit("rep_inject_error", "warn", f"failed to inject rep.* fields: {e}")

    # 8) Camera Summary בסוף סט
    try:
        if bool(raw_metrics.get("set.end")):
            report = _end_set_audit_and_attach(report)
    except Exception:
        pass

    _emit("report_built", "info", "report built", {
        "exercise": ex.id,
        "score": report["scoring"]["score"],
        "quality": report["scoring"]["quality"],
        "unscored": bool(report["scoring"]["unscored_reason"])
    })
    return report


# ───────────────────── בדיקת עשן ─────────────────────
if __name__ == "__main__":
    import json
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    from exercise_engine.registry.loader import load_library
    lib = load_library(ROOT / "exercise_library")

    raw_begin = {"set.begin": True, "set.index": 1}
    _ = run_once(raw_metrics=raw_begin, library=lib, exercise_id=None, payload_version="1.0")

    for i in range(5):
        raw = {"average_visibility": 0.65, "dt_ms": 120.0}
        _ = run_once(raw_metrics=raw, library=lib, exercise_id=None, payload_version="1.0")

    raw_end = {"set.end": True}
    out = run_once(raw_metrics=raw_end, library=lib, exercise_id=None, payload_version="1.0")
    print(json.dumps(out, ensure_ascii=False, indent=2))
