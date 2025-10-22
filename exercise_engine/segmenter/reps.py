# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# exercise_engine/segmenter/reps.py
# מנוע חזרות כללי: זיהוי start→towards→turn→away, חישוב timing/ROM/tempo/quality
#
# API:
#   updates, rep_event = update_rep_state(canonical: dict, now_ms: int, exercise_cfg: Optional[dict])
#   reset_state()
#
# updates  => מילוי rep.* חיים (state/dir/active/progress/ecc_s/con_s/rom/timing/rest/quality/…)
# rep_event=> מילון (כשחזרה נסגרת) עם: rep_id, start_ts, turn_ts, end_ts,
#             timing_s, ecc_s, con_s, rom, units, quality, signal_key
# -----------------------------------------------------------------------------

from typing import Dict, Any, Optional, Tuple, List

__all__ = ["update_rep_state", "reset_state"]

# ---------- קבועים ----------
_DEFAULT_THRESH = {
    # נמוך יחסית כדי לצאת מ-"start" מהר אבל עדיין חסין רעשים
    "phase_delta": 2.0,       # deg (ל-units אחרים נעדכן בהמשך)
    "min_rom_good": 15.0,     # ROM טוב (deg/ratio/px לפי units)
    "min_rom_partial": None,  # אם None → 0.6 * min_rom_good
    "min_rep_ms": 400,        # מהירה מדי
    "max_rep_ms": 6000,       # איטית מדי
    "min_turn_ms": 80,        # שהייה מינימלית ב-"turn"
}
_DEFAULT_UNITS = "deg"
_DEFAULT_EMA_ALPHA = 0.30
_HISTORY_MAX = 10

# ---------- מצב פנימי ----------
_S: Dict[str, Any] = {
    "ema": None,
    "last_ms": None,
    "state": "start",          # start / towards / turn / away
    "active": False,
    "dir": None,               # "inc" / "dec"
    "rep_id": 0,
    "rep_start_ms": None,
    "turn_ms": None,
    "top_like_val": None,      # ערך ייחוס עליון (נקודת התחלה/סוף)
    "turn_val": None,          # ערך בנק' ההיפוך
    "last_end_ms": None,
    "last_timing_s": None,
    "last_rom": None,
    "last_ecc_s": None,        # זמן החצי הראשון (start→turn)
    "last_con_s": None,        # זמן החצי השני (turn→end)
    "units": None,
    "target": "min",           # כיוון חצי ראשון אל "min" או אל "max"
    "signal_key": None,
    "history": [],             # עד 10 חזרות אחרונות
}

def reset_state() -> None:
    """איפוס מלא של מצב פנימי (לשימוש בבדיקות/החלפת זרם נתונים)."""
    global _S
    _S.update({
        "ema": None, "last_ms": None, "state": "start", "active": False, "dir": None,
        "rep_start_ms": None, "turn_ms": None, "top_like_val": None, "turn_val": None,
        "last_end_ms": None, "last_timing_s": None, "last_rom": None,
        "last_ecc_s": None, "last_con_s": None, "signal_key": None,
    })
    # אם תרצה להתחיל מ-0 לגמרי:
    # _S["rep_id"] = 0
    # _S["history"] = []

# ---------- עזרים ----------
def _ema(prev: Optional[float], x: float, alpha: float) -> float:
    return x if prev is None else (alpha * x + (1.0 - alpha) * prev)

def _is_num(x: Any) -> bool:
    try:
        float(x); return True
    except Exception:
        return False

def _infer_units(key: str, explicit: Optional[str]) -> str:
    if explicit: return str(explicit)
    if key.endswith("_deg") or "angle" in key: return "deg"
    if key.endswith("_px") or ".y" in key or key.endswith("_y"): return "px"
    if "ratio" in key or "scale" in key: return "ratio"
    return _DEFAULT_UNITS

def _parse_source(source: str) -> Tuple[str, str, List[str]]:
    """פורמט מומלץ: "value|min|knee_left_deg,knee_right_deg"."""
    try:
        kind, agg, keys = source.split("|", 2)
        keys_list = [k.strip() for k in keys.split(",") if k.strip()]
        return kind.strip(), agg.strip(), keys_list
    except Exception:
        return "value", "first", [source.strip()]

def _agg_values(vals: List[float], agg: str) -> Optional[float]:
    if not vals: return None
    if   agg == "min": return min(vals)
    elif agg == "max": return max(vals)
    elif agg == "avg": return sum(vals) / len(vals)
    return vals[0]

# ---------- בחירת סיגנל ----------
def _auto_pick_signal(canon: Dict[str, Any]):
    """
    בחירה אוטומטית פשוטה (fallback):
    - מנסה זוגות מפרקיים (min זווית ב-deg),
    - אם אין → גובה ב-px,
    - אם אין → ratio ראשון שקיים.
    """
    pairs = [
        ("knee_left_deg", "knee_right_deg"),
        ("hip_left_deg", "hip_right_deg"),
        ("elbow_left_deg", "elbow_right_deg"),
        ("shoulder_left_deg", "shoulder_right_deg"),
    ]
    for a, b in pairs:
        if _is_num(canon.get(a)) and _is_num(canon.get(b)):
            val = float(min(canon[a], canon[b]))
            return val, "deg", "min", a

    # <<< התאמה ל-canonical keys של aliases.yaml >>>
    singles_y = [
        "bar.y_px",
        "wrist_left_y_px", "wrist_right_y_px",
        "hand_y_left", "hand_y_right",  # נשאר כגיבוי אם ייכנס בקאנוני בעתיד
    ]
    for k in singles_y:
        if _is_num(canon.get(k)):
            return float(canon[k]), "px", "min", k

    for k in canon.keys():
        if "ratio" in k and _is_num(canon.get(k)):
            return float(canon[k]), "ratio", "min", k

    return None, _DEFAULT_UNITS, "min", None

def _pick_signal_from_cfg(canon: Dict[str, Any], cfg: Optional[Dict[str, Any]]):
    rs = (cfg or {}).get("rep_signal") or {}
    source = rs.get("source")
    target = (rs.get("target") or "min").lower()
    if source:
        _, agg, keys = _parse_source(source)
        vals = [float(canon[k]) for k in keys if _is_num(canon.get(k))]
        val = _agg_values(vals, agg)
        units = _infer_units(keys[0] if keys else "", rs.get("units"))
        sig_key = keys[0] if keys else None
        return val, units, target, sig_key
    return _auto_pick_signal(canon)

def _read_thresholds(cfg: Optional[Dict[str, Any]], units: str) -> Dict[str, float]:
    th = dict(_DEFAULT_THRESH)
    rsc = (cfg or {}).get("rep_signal") or {}
    for k, v in (rsc.get("thresholds") or {}).items():
        try: th[k] = float(v)
        except Exception: pass

    # אם לא הוגדר min_rom_partial—קבע 60% מ-good
    if th.get("min_rom_partial") is None:
        th["min_rom_partial"] = 0.6 * float(th.get("min_rom_good", _DEFAULT_THRESH["min_rom_good"]))

    # התאמות לפי יחידות שאינן מעלות
    if units == "ratio":
        th.setdefault("phase_delta", 0.01)
        th.setdefault("min_rom_good", 0.12)
        if th.get("min_rom_partial") is None:
            th["min_rom_partial"] = 0.6 * th["min_rom_good"]
    elif units == "px":
        th.setdefault("phase_delta", 3.0)
        th.setdefault("min_rom_good", 30.0)
        if th.get("min_rom_partial") is None:
            th["min_rom_partial"] = 0.6 * th["min_rom_good"]

    return th

def _phase_from_config(state: str, cfg: Optional[Dict[str, Any]]) -> Optional[str]:
    pmap = ((cfg or {}).get("rep_signal") or {}).get("phase_map") or {}
    name = pmap.get(state)
    return str(name) if name else None

# ---------- ליבה ----------
def update_rep_state(canonical: Dict[str, Any], now_ms: int, exercise_cfg: Optional[Dict[str, Any]] = None):
    """
    מעדכן rep.* בתוך canonical; מחזיר (updates, rep_event) כשנסגרת חזרה תקפה.
    """
    updates: Dict[str, Any] = {}
    rep_event: Optional[Dict[str, Any]] = None

    # 1) בחירת סיגנל
    val, units, target, sig_key = _pick_signal_from_cfg(canonical, exercise_cfg)
    _S["units"] = units
    _S["target"] = target
    _S["signal_key"] = sig_key

    # אם אין סיגנל → איפוס רך
    if val is None or not _is_num(val):
        updates.update({
            "rep.state": "start",
            "rep.active": False,
            "rep.dir": None,
            "rep.in_rep_window": False,
            "rep.freeze_active": False,
            "rep.units": _S["units"],
            "rep.errors.missing_signal": True,
            "rep.progress": 0.0,
            "rep.quality": "none",
        })
        if _S.get("last_end_ms") is not None:
            updates["rep.rest_s"] = round((now_ms - _S["last_end_ms"]) / 1000.0, 3)
        phase_name = _phase_from_config("start", exercise_cfg)
        if phase_name: updates["rep.phase"] = phase_name
        return updates, None

    # 2) ספים + החלקה
    th = _read_thresholds(exercise_cfg, units)
    alpha = float(((exercise_cfg or {}).get("rep_signal") or {}).get("ema_alpha", _DEFAULT_EMA_ALPHA))
    val = float(val)
    ema_prev = _S["ema"]
    ema_now = _ema(ema_prev, val, alpha)
    _S["ema"] = ema_now

    # 3) דגימה ראשונה / bootstrap
    last_ms = _S["last_ms"]
    _S["last_ms"] = now_ms
    if last_ms is None or ema_prev is None:
        # top_like פעם ראשונה
        _S["top_like_val"] = ema_now if _S.get("top_like_val") is None else _S["top_like_val"]
        updates.update({
            "rep.state": "start",
            "rep.active": False,
            "rep.dir": None,
            "rep.in_rep_window": False,
            "rep.freeze_active": False,
            "rep.rep_id": int(_S["rep_id"]),
            "rep.units": _S["units"],
            "rep.progress": 0.0,
        })
        phase_name = _phase_from_config("start", exercise_cfg)
        if phase_name: updates["rep.phase"] = phase_name
        # אזהרה עקבית כשאין source מפורש
        if exercise_cfg is None or not ((exercise_cfg.get("rep_signal") or {}).get("source")):
            updates["rep.warnings.auto_target_used"] = True
            updates["rep.warnings.auto_signal_used"] = True
        return updates, None

    # 4) כיוון
    d = ema_now - ema_prev
    if abs(d) < th["phase_delta"]:
        dir_ = _S["dir"]
    else:
        dir_ = "inc" if d > 0 else "dec"
    _S["dir"] = dir_

    towards_now = bool(
        (_S["target"] == "min" and _S["dir"] == "dec") or
        (_S["target"] == "max" and _S["dir"] == "inc")
    )

    # 5) State machine
    state = _S["state"]

    if state == "start" and towards_now:
        state = "towards"
        _S["state"] = state
        _S["active"] = True
        _S["rep_start_ms"] = now_ms
        _S["last_ecc_s"] = None
        _S["last_con_s"] = None
        _S["top_like_val"] = ema_prev if ema_prev is not None else ema_now

    elif state == "towards" and not towards_now and dir_ is not None:
        state = "turn"
        _S["state"] = state
        _S["turn_ms"] = now_ms
        _S["turn_val"] = ema_prev if ema_prev is not None else ema_now
        try:
            if _S.get("rep_start_ms") is not None:
                _S["last_ecc_s"] = round((_S["turn_ms"] - _S["rep_start_ms"]) / 1000.0, 3)
        except Exception:
            _S["last_ecc_s"] = None

    elif state == "turn":
        stayed = (now_ms - int(_S.get("turn_ms") or now_ms)) >= th["min_turn_ms"]
        if stayed and not towards_now and dir_ is not None:
            _S["state"] = "away"

    elif state == "away":
        top_ref = _S.get("top_like_val", ema_now)
        rom = None
        if _S.get("turn_val") is not None:
            rom = abs(float(_S["turn_val"]) - float(top_ref))

        tol_close = max(th["phase_delta"], 0.4 * ((rom or th["min_rom_good"])))
        close_enough = abs(ema_now - top_ref) <= tol_close

        if close_enough:
            rep_ms = now_ms - int(_S.get("rep_start_ms") or now_ms)

            fast = rep_ms < th["min_rep_ms"]
            slow = rep_ms > th["max_rep_ms"]

            rom_val = float(round(rom, 3)) if rom is not None else None
            rom_good = (rom_val is not None) and (rom_val >= th["min_rom_good"])
            rom_partial = (rom_val is not None) and (th["min_rom_partial"] <= rom_val < th["min_rom_good"])

            quality = None
            errs: Dict[str, Any] = {}
            if not fast and not slow:
                if rom_good:
                    quality = "good"
                elif rom_partial:
                    quality = "partial"
                else:
                    quality = "short"; errs["rep.errors.small_rom"] = True
            else:
                if fast: quality = "fast";  errs["rep.errors.fast_rep"] = True
                if slow: quality = "slow";  errs["rep.errors.slow_rep"] = True
                if quality is None:
                    quality = "incomplete"

            try:
                if _S.get("turn_ms") is not None:
                    _S["last_con_s"] = round((now_ms - _S["turn_ms"]) / 1000.0, 3)
            except Exception:
                _S["last_con_s"] = None

            _S["top_like_val"] = ema_now
            _S["state"] = "start"
            _S["active"] = False

            if quality in ("good", "partial"):
                _S["rep_id"] = int(_S["rep_id"]) + 1
                timing_s = round(rep_ms / 1000.0, 3)
                _S["last_timing_s"] = timing_s
                _S["last_rom"] = rom_val
                _S["last_end_ms"] = now_ms

                rep_event = {
                    "rep_id": int(_S["rep_id"]),
                    "start_ts": int(_S["rep_start_ms"] or now_ms),
                    "turn_ts": int(_S.get("turn_ms") or now_ms),
                    "end_ts": now_ms,
                    "timing_s": timing_s,
                    "rom": _S["last_rom"],
                    "units": _S["units"],
                    "quality": quality,
                    "signal_key": _S.get("signal_key"),
                    "ecc_s": float(_S.get("last_ecc_s")) if _S.get("last_ecc_s") is not None else None,
                    "con_s": float(_S.get("last_con_s")) if _S.get("last_con_s") is not None else None,
                }

                try:
                    _S["history"].append(dict(rep_event))
                    if len(_S["history"]) > _HISTORY_MAX:
                        _S["history"] = _S["history"][-_HISTORY_MAX:]
                except Exception:
                    pass
            else:
                _S["last_end_ms"] = now_ms

            updates["rep.quality"] = quality
            for k, v in errs.items():
                updates[k] = v

    # 6) כתיבה חיה
    updates["rep.state"] = _S["state"]
    updates["rep.active"] = bool(_S["active"])
    updates["rep.dir"] = _S["dir"]
    updates["rep.rep_id"] = int(_S["rep_id"])
    updates["rep.units"] = _S["units"]
    updates["rep.in_rep_window"] = updates["rep.active"]
    updates["rep.freeze_active"] = updates["rep.active"]

    concentric_now = (
        (_S["target"] == "min" and _S["dir"] == "inc") or
        (_S["target"] == "max" and _S["dir"] == "dec")
    )
    updates["rep.eccentric"]  = bool((_S["state"] in ("towards", "turn")) and not concentric_now)
    updates["rep.concentric"] = bool((_S["state"] in ("away", "turn")) and concentric_now)

    # Progress דו-קטעי 0..1
    try:
        top_ref  = _S.get("top_like_val")
        turn_val = _S.get("turn_val")
        if _S["active"] and turn_val is not None and top_ref is not None:
            if ((_S["target"] == "min" and _S["dir"] == "dec") or
                (_S["target"] == "max" and _S["dir"] == "inc")):
                num = abs(_S["ema"] - top_ref); den = max(abs(turn_val - top_ref), 1e-6)
                progress = max(0.0, min(1.0, num/den)) * 0.5
            else:
                num = abs(_S["ema"] - turn_val); den = max(abs(turn_val - top_ref), 1e-6)
                progress = 0.5 + (1.0 - max(0.0, min(1.0, num/den))) * 0.5
        else:
            progress = 0.0
    except Exception:
        progress = 0.0
    updates["rep.progress"] = round(float(progress), 3)

    # מדדים אחרונים
    if _S.get("last_timing_s") is not None:
        updates["rep.timing_s"] = float(_S["last_timing_s"])
    if _S.get("last_rom") is not None:
        updates["rep.rom"] = float(_S["last_rom"])
    if _S.get("last_end_ms") is not None:
        updates["rep.rest_s"] = round((now_ms - _S["last_end_ms"]) / 1000.0, 3)
    if _S.get("last_ecc_s") is not None:
        updates["rep.ecc_s"] = float(_S["last_ecc_s"])
    if _S.get("last_con_s") is not None:
        updates["rep.con_s"] = float(_S["last_con_s"])

    # rep.phase (אם מוגדר phase_map ב-YAML)
    phase_name = _phase_from_config(_S["state"], exercise_cfg)
    if phase_name:
        updates["rep.phase"] = phase_name

    # אזהרה אם אין source מפורש בתרגיל
    if exercise_cfg is None or not ((exercise_cfg.get("rep_signal") or {}).get("source")):
        updates["rep.warnings.auto_target_used"] = True
        updates["rep.warnings.auto_signal_used"] = True

    return updates, rep_event
