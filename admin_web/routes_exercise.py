# -*- coding: utf-8 -*-
"""
admin_web/routes_exercise.py — ניקוד תרגיל (רנטיים/דמו) + סימולטור + דיאגנוסטיקה
-------------------------------------------------------------------------------
Endpoints:
- POST /api/exercise/score        → דוח יחיד (רצוי מרנטיים; אחרת דמו תקין לפורמט ה-UI)
- POST /api/exercise/simulate     → סימולציית סטים/חזרות (דוחות מלאים לפורמט ה-UI)
- GET  /api/exercise/diag         → סטטוס קצר
- GET  /api/exercise/diag/stream  → SSE דיאגנוסטי

הקובץ מחזיר תמיד אובייקט בפורמט ה-UI שלך:
{
  "ui_ranges": {...},
  "exercise": {"id": "...", "family": "...", "equipment": "...", "display_name": "..."},
  "scoring": {
      "score": 0.87, "quality": "full"|"partial"|"poor", "unscored_reason": null|"...",
      "criteria": [ {id, available, reason, score_pct|score}, ... ],
      "criteria_breakdown_pct": { "<crit>": <int pct>|null, ... }
  },
  "hints": [...],
  "metrics_detail": {...},   # groups / rep_tempo_series / targets (אם יש)
  "ui": { "labels": {...} }  # לא חובה אבל שימושי לכותרות דו-לשוניות
}
"""
from __future__ import annotations
import json, time, math, random, queue
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, jsonify, request, Response, stream_with_context

bp = Blueprint("exercise", __name__)

# ------------------------------- Utils -------------------------------

def _color_bar() -> Dict[str, Any]:
    return {
        "color_bar": [
            {"label": "red",    "from_pct": 0,  "to_pct": 60},
            {"label": "orange", "from_pct": 60, "to_pct": 75},
            {"label": "green",  "from_pct": 75, "to_pct": 100},
        ]
    }

def _quality_from_pct(p: Optional[int]) -> Optional[str]:
    if p is None: return None
    if p >= 85: return "full"
    if p >= 70: return "partial"
    return "poor"

def _pct(v: Optional[float]) -> Optional[int]:
    try:
        if v is None: return None
        x = int(round(float(v) * 100.0))
        return max(0, min(100, x))
    except Exception:
        return None

# -------------------- Runtime (optional, best-effort) --------------------

def _get_runtime() -> Optional[Any]:
    """
    מנסה להביא רנטיים אם קיים בפרויקט. אם אין — מחזירים None ונלך ל-demo_score.
    נזהר לא להפיל אם אין מודול.
    """
    try:
        from exercise_engine.runtime import get_runtime  # type: ignore
        rt = get_runtime()
        return rt
    except Exception:
        return None

# ------------------------ Demo report builders ------------------------

_SAMPLE_ALIASES_LABELS = {
    "exercise":  {"he": "סקוואט גוף", "en": "Bodyweight Squat"},
    "family":    {"he": "סקוואט",    "en": "Squat"},
    "equipment": {"he": "משקל גוף",  "en": "Bodyweight"},
}

def _demo_criteria(mode: str) -> List[Dict[str, Any]]:
    """
    מחזיר מערך קריטריונים “אמיתי” מספיק ל-UI.
    """
    base = [
        {"id": "depth",        "available": True, "score_pct": 88},
        {"id": "knees",        "available": True, "score_pct": 90},
        {"id": "torso_angle",  "available": True, "score_pct": 86},
        {"id": "stance_width", "available": True, "score_pct": 92},
        {"id": "tempo",        "available": True, "score_pct": 84},
    ]
    if mode == "shallow":
        base[0]["score_pct"] = 35
        base[0]["reason"] = "shallow_depth"
    elif mode == "missing":
        base[0]["available"] = False
        base[0]["reason"] = "missing_critical: depth"
    elif mode == "mixed":
        base[0]["score_pct"] = 60 + int(random.random() * 25)
        base[1]["score_pct"] = 55 + int(random.random() * 30)
    # clamp
    for c in base:
        if "score_pct" in c and c["score_pct"] is not None:
            c["score_pct"] = max(0, min(100, int(c["score_pct"])))
    return base

def _criteria_to_overall(criteria: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[str]]:
    avail = [c for c in criteria if c.get("available") and c.get("score_pct") is not None]
    if not avail:
        return None, None
    avg = sum(int(c["score_pct"]) for c in avail) / len(avail)
    return (avg / 100.0), _quality_from_pct(int(round(avg)))

def _demo_metrics_detail() -> Dict[str, Any]:
    return {
        "groups": {
            "joints": {"knee_left_deg": 160, "knee_right_deg": 158, "torso_forward_deg": 15, "spine_flexion_deg": 8},
            "stance": {"features.stance_width_ratio": 1.05, "toe_angle_left_deg": 8, "toe_angle_right_deg": 10, "heels_grounded": True},
            "other":  {}
        },
        "rep_tempo_series": [{"rep_id": 1, "timing_s": 1.6, "ecc_s": 0.8, "con_s": 0.8, "pause_top_s": 0.0, "pause_bottom_s": 0.0}],
        "targets": {"tempo": {"min_s": 0.7, "max_s": 2.5}},
        "stats": {}
    }

def _demo_report(mode: str = "good") -> Dict[str, Any]:
    crit = _demo_criteria(mode)
    score, quality = _criteria_to_overall(crit)
    hints: List[str] = []
    lows = sorted([c for c in crit if c.get("available") and (c.get("score_pct") or 0) < 70], key=lambda x: x.get("score_pct") or 0)
    if lows:
        hints.append(f"שפר {lows[0]['id']} (כעת {lows[0]['score_pct']}%)")
    return {
        "ui_ranges": _color_bar(),
        "exercise": {"id": "squat.bodyweight.md", "family": "squat", "equipment": "bodyweight", "display_name": "סקוואט גוף"},
        "scoring": {
            "score": score,
            "quality": quality,
            "unscored_reason": "missing_critical" if any(not c.get("available") for c in crit) else None,
            "criteria": crit,
            "criteria_breakdown_pct": {c["id"]: (c.get("score_pct") if c.get("available") else None) for c in crit},
        },
        "hints": hints,
        "metrics_detail": _demo_metrics_detail(),
        "ui": {"labels": _SAMPLE_ALIASES_LABELS},
    }

# ------------------------------ Endpoints ------------------------------

@bp.route("/api/exercise/score", methods=["POST"])
def api_exercise_score():
    """
    Body: { "metrics": {...}, "mode": "good|shallow|missing|mixed", "exercise_id": "..." }
    - אם יש runtime → ננסה להחזיר ממנו דוח מלא.
    - אם אין → נחזיר דוח דמו (כדי שה-UI יעבוד ויראה ציונים).
    """
    try:
        req = request.get_json(silent=True) or {}
        metrics = req.get("metrics") or {}
        ex_id   = req.get("exercise_id") or "squat.bodyweight.md"
        mode    = str(req.get("mode") or "mixed")

        # נסה רנטיים אמיתי
        rt = _get_runtime()
        if rt is not None:
            try:
                # מצופה: rt.score_single(metrics) → dict בפורמט הדוח שלנו (או קרוב)
                rep = rt.score_single(metrics=metrics, exercise_id=ex_id)  # type: ignore
                if isinstance(rep, dict) and rep.get("scoring"):
                    # ודא ש-ui_ranges קיים
                    rep["ui_ranges"] = rep.get("ui_ranges") or _color_bar()
                    return jsonify(rep)
            except Exception:
                # ניפול לדמו – שלא יישבר ה-UI
                pass

        # דמו
        return jsonify(_demo_report(mode=mode))

    except Exception as e:
        # fallback קשוח — עדיף דוח דמו מאשר ריק
        return jsonify(_demo_report(mode="mixed") | {"hints": [f"server_error: {e}"]}), 200


@bp.route("/api/exercise/simulate", methods=["POST"])
def api_exercise_simulate():
    """
    Body: { sets:int, reps:int, mode:str, noise:float }
    מחזיר חבילה עם sets[] → reps[] → דוחות (בפורמט שה-JS שלך יודע לצרוך).
    """
    try:
        j = request.get_json(silent=True) or {}
        sets  = int(j.get("sets", 2))
        reps  = int(j.get("reps", 5))
        mode  = str(j.get("mode", "mixed"))
        noise = float(j.get("noise", 0.25))

        def jitter(p: int) -> int:
            if p is None: return p
            delta = int(round((random.random() * 2 - 1) * noise * 100))
            return max(0, min(100, p + delta))

        sets_out: List[Dict[str, Any]] = []
        for s in range(1, max(1, sets) + 1):
            reps_out: List[Dict[str, Any]] = []
            for r in range(1, max(1, reps) + 1):
                # בנה דוח דמו ואז "רעידות" קלות כדי שיהיה מגוון
                rep = _demo_report(mode=mode)
                for c in rep["scoring"]["criteria"]:
                    if c.get("score_pct") is not None:
                        c["score_pct"] = jitter(int(c["score_pct"]))
                # overall מחדש
                sc, ql = _criteria_to_overall(rep["scoring"]["criteria"])
                rep["scoring"]["score"] = sc
                rep["scoring"]["quality"] = ql
                reps_out.append({
                    "set": s,
                    "rep": r,
                    "exercise_id": rep["exercise"]["id"],
                    "score_pct": _pct(rep["scoring"]["score"]),
                    "quality": rep["scoring"]["quality"],
                    "unscored_reason": rep["scoring"]["unscored_reason"],
                    "criteria": rep["scoring"]["criteria"],
                    "criteria_breakdown_pct": rep["scoring"]["criteria_breakdown_pct"],
                    "metrics_detail": rep.get("metrics_detail"),
                    "notes": [{"text": h} for h in rep.get("hints", [])],
                })
            sets_out.append({
                "set": s,
                "exercise_id": "squat.bodyweight.md",
                "reps": reps_out,
            })

        return jsonify({
            "ok": True,
            "ui_ranges": _color_bar(),
            "exercise": {"id": "squat.bodyweight.md", "family": "squat", "equipment": "bodyweight", "display_name": "סקוואט גוף"},
            "sets": sets_out,
            "ui": {"labels": _SAMPLE_ALIASES_LABELS},
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


# ------------------------------ Diagnostics ------------------------------

_diag_q: "queue.Queue[str]" = queue.Queue(maxsize=200)

def _q_put(s: str) -> None:
    try:
        _diag_q.put_nowait(s)
    except Exception:
        # queue full; drop
        pass

@bp.route("/api/exercise/diag", methods=["GET"])
def api_exercise_diag():
    rt = _get_runtime()
    info: Dict[str, Any] = {"runtime": "absent"}
    if rt is not None:
        try:
            info = {
                "runtime": "present",
                "exercise": getattr(rt, "current_exercise_id", None),
                "last_scores": getattr(rt, "last_scores_count", None),
                "ready": True,
            }
        except Exception:
            info = {"runtime": "present", "ready": True}
    return jsonify({"ok": True, "ts": time.time(), "info": info})

@bp.route("/api/exercise/diag/stream")
def api_exercise_diag_stream():
    ping_ms = int(request.args.get("ping_ms", "15000"))
    rt = _get_runtime()
    _q_put(json.dumps({"ts": time.time(), "event": "open", "runtime": "present" if rt else "absent"}))

    def _gen():
        last_ping = time.time()
        while True:
            # periodic ping
            now = time.time()
            if now - last_ping >= (ping_ms / 1000.0):
                last_ping = now
                yield f"data: {json.dumps({'ts': now, 'event': 'ping'})}\n\n"
            # drain queue
            try:
                msg = _diag_q.get(timeout=0.25)
                yield f"data: {msg}\n\n"
            except Exception:
                pass

    return Response(stream_with_context(_gen()), mimetype="text/event-stream")
