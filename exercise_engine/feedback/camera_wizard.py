# -*- coding: utf-8 -*-
"""
camera_wizard.py — מודול בקרת מצלמה ובדיקת איכות סט (ללא טקסטים קשיחים)
---------------------------------------------------------------------------
מה חדש?
• אין ניסוחי טקסט קשיחים בקוד. אנחנו מחזירים רק code+severity+tips.
• רינדור טקסטים מבוצע בשכבה החיצונית (explain.render_camera_issue → phrases.yaml).
• SetVisibilityAudit מחזיר severity + stats נקיים; את ההודעה מנסחים ב-explain.

שימוש בזמן אמת (דוגמה):
    issue = wizard.say_next(payload)         # מחזיר Issue או None
    if issue:
        # הפוך לטקסט מ-phrases.yaml:
        line = render_camera_issue({"code": issue.code,
                                    "severity": issue.severity,
                                    "tips": issue.tips})
        if line:
            tts(line)  # או הצגה למסך

בסוף סט:
    audit = audit_obj.end_set()
    # העברה ל-explain.generate_set_hints(...) לצירוף הודעות טכניות מה-YAML
"""

from __future__ import annotations
import time, os, json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# ─────────────────────────────── חלק א' — Camera Wizard ───────────────────────────────

# קונפיג דיבור בזמן אמת (שקט, ללא ספאם)
STARTUP_GRACE_S            = 3.0
MIN_GAP_S                  = 2.0
MAX_REPEAT_PER_MSG         = 2
MIN_SPOKEN_SEVERITY        = "HIGH"

# ספים לזיהוי "יש אדם"
MIN_VISIBILITY_FOR_PERSON  = 0.40
MIN_CONFIDENCE_FOR_PERSON  = 0.50

# ספים טכניים
MAX_DT_MS_OK               = 500.0      # מעבר לזה נחשוד בקפיאות/איטיות
DARK_VISIBILITY_HINT       = 0.25       # מאוד חשוך → בעיית תאורה מובהקת

SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# קודי אירועים (להתאמה עם phrases.yaml.he.camera_wizard.*)
CW_LOW_FPS                 = "low_fps"
CW_LIGHTING_DARK           = "lighting_dark"
CW_FRAMING_VIS_LOW         = "framing_visibility_low"
CW_ALL_GOOD                = "all_good_hint"

@dataclass
class Issue:
    code: str
    severity: str
    tips: Optional[str] = None
    ts_created: float = 0.0

    def can_say_at(self, min_severity: str) -> bool:
        return SEVERITY_ORDER[self.severity] >= SEVERITY_ORDER[min_severity]

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "tips": self.tips}

class _CameraWizard:
    """אשף מצלמה שקט – מחזיר אירועים עם code/severity/tips בלבד (הטקסט ב-explain)."""
    def __init__(self):
        self._t0 = time.time()
        self._last_say_ts: float = 0.0
        self._said_counts: Dict[str, int] = {}
        self._pending_lock: bool = False
        self._last_person_seen_ts: float = 0.0

    def evaluate(self, payload: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        now = time.time()

        # מדברים רק אם יש אדם
        if self._is_person_detected(payload):
            self._last_person_seen_ts = now
        else:
            return []

        # FPS / זרימה
        dt_raw = payload.get("dt_ms") if payload.get("dt_ms") is not None else payload.get("dt")
        try:
            dt_ms = float(dt_raw) if dt_raw is not None else 0.0
        except Exception:
            dt_ms = 0.0
        if dt_ms > MAX_DT_MS_OK:
            issues.append(self._mk(CW_LOW_FPS, "HIGH", f"dt_ms={dt_ms:.0f}"))

        # תאורה / נראות
        vis_raw = payload.get("average_visibility")
        try:
            vis = float(vis_raw) if vis_raw is not None else None
        except Exception:
            vis = None

        if vis is not None:
            if vis < DARK_VISIBILITY_HINT:
                issues.append(self._mk(CW_LIGHTING_DARK, "HIGH", f"avg_visibility={vis:.2f}"))
            elif vis < MIN_VISIBILITY_FOR_PERSON + 0.05:
                issues.append(self._mk(CW_FRAMING_VIS_LOW, "MEDIUM", f"avg_visibility={vis:.2f}"))
            elif dt_ms <= MAX_DT_MS_OK and vis >= MIN_VISIBILITY_FOR_PERSON + 0.10:
                issues.append(self._mk(CW_ALL_GOOD, "LOW", f"avg_visibility={vis:.2f}"))

        return issues

    def next_speakable(self, payload: Dict[str, Any]) -> Optional[Issue]:
        now = time.time()
        if (now - self._t0) < STARTUP_GRACE_S:
            return None
        if self._pending_lock:
            return None
        if (now - self._last_say_ts) < MIN_GAP_S:
            return None
        if (now - self._last_person_seen_ts) > 3.0:
            return None

        issues = self.evaluate(payload)
        if not issues:
            return None
        issues.sort(key=lambda it: (-SEVERITY_ORDER[it.severity], it.ts_created))

        for it in issues:
            if not it.can_say_at(MIN_SPOKEN_SEVERITY):
                continue
            said_n = self._said_counts.get(it.code, 0)
            if said_n >= MAX_REPEAT_PER_MSG:
                continue
            return it
        return None

    def say_next(self, payload: Dict[str, Any]) -> Optional[Issue]:
        """
        מחזיר Issue (ללא טקסט). את ההמרה לטקסט מבצעים בשכבה החיצונית בעזרת
        explain.render_camera_issue(issue.to_dict()) על בסיס phrases.yaml.
        """
        it = self.next_speakable(payload)
        if it is None:
            return None
        self._pending_lock = True
        try:
            self._said_counts[it.code] = self._said_counts.get(it.code, 0) + 1
            self._last_say_ts = time.time()
            return it
        finally:
            self._pending_lock = False

    def _mk(self, code: str, severity: str, tips: Optional[str] = None) -> Issue:
        return Issue(code=code, severity=severity, tips=tips, ts_created=time.time())

    def _is_person_detected(self, payload: Dict[str, Any]) -> bool:
        avail = (payload.get("availability") or {})
        pose_ok = bool(avail.get("pose")) or bool(avail.get("measurements"))
        # נראות/ביטחון אם קיימים
        vis_raw = payload.get("average_visibility")
        try:
            vis = float(vis_raw) if vis_raw is not None else None
        except Exception:
            vis = None
        conf = payload.get("confidence")
        conf_ok = (conf is not None)
        try:
            conf_ok = conf_ok and (float(conf) >= MIN_CONFIDENCE_FOR_PERSON)
        except Exception:
            conf_ok = conf_ok and False
        if pose_ok:
            return True
        if conf_ok:
            return True
        if vis is not None and vis >= MIN_VISIBILITY_FOR_PERSON:
            return True
        return False

wizard = _CameraWizard()

# ─────────────────────────────── חלק ב' — Set Visibility Audit ───────────────────────────────

# קונפיג לריכוך רגישות הבדיקה בסוף סט
VIS_OK_MIN              = 0.60
VIS_WARN_MIN            = 0.45
VIS_VERY_BAD            = 0.20
CONF_BAD                = 0.60
DT_MS_BAD               = 500.0
DT_MS_VERY_BAD          = 1200.0

MIN_FRAMES_FOR_AUDIT    = 30
MIN_DURATION_S          = 3.0

# אחוזים על פריימים מדידים (לא על כל הפריימים הגולמיים)
FRAC_BAD_VIS_MED        = 0.35
FRAC_VERY_BAD_VIS_HIGH  = 0.20
FRAC_BAD_DT_MED         = 0.30
FRAC_LOW_CONF_MED       = 0.30
PERSON_MIN_RATIO        = 0.50

class SetVisibilityAudit:
    """
    מעקב שקט לאורך סט — מחזיר מדדים נקיים (ללא ניסוחים). ניסוח סופי ייעשה ב-explain.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._in_set = False
        self.t0 = self.t_last = 0.0

        self.n_frames_total = 0

        # נראות
        self.vis_sum = 0.0
        self.vis_min = 1.0
        self.n_vis_measured = 0
        self.n_bad_vis = 0
        self.n_very_bad_vis = 0

        # ביטחון
        self.n_conf_measured = 0
        self.n_low_conf = 0

        # זרימה/זמן בין פריימים
        self.dt_sum = 0.0
        self.dt_max = 0.0
        self.n_dt_measured = 0
        self.n_bad_dt = 0

        # נוכחות אדם
        self.n_person_frames = 0

    def begin_set(self):
        self.reset()
        self._in_set = True
        self.t0 = time.time()

    def ingest(self, payload: Dict[str, Any]):
        if not self._in_set:
            return
        self.n_frames_total += 1
        self.t_last = time.time()

        # נראות
        vis_raw = payload.get("average_visibility")
        try:
            vis = float(vis_raw) if vis_raw is not None else None
        except Exception:
            vis = None
        if vis is not None:
            self.n_vis_measured += 1
            self.vis_sum += vis
            self.vis_min = min(self.vis_min, vis)
            if vis < VIS_WARN_MIN:
                self.n_bad_vis += 1
            if vis < VIS_VERY_BAD:
                self.n_very_bad_vis += 1

        # ביטחון
        conf_raw = payload.get("confidence")
        try:
            conf = float(conf_raw) if conf_raw is not None else None
        except Exception:
            conf = None
        if conf is not None:
            self.n_conf_measured += 1
            if conf < CONF_BAD:
                self.n_low_conf += 1

        # זמן בין פריימים
        dt_raw = payload.get("dt_ms") if payload.get("dt_ms") is not None else payload.get("dt")
        try:
            dt_ms = float(dt_raw) if dt_raw is not None else None
        except Exception:
            dt_ms = None
        if dt_ms is not None:
            self.n_dt_measured += 1
            self.dt_sum += dt_ms
            if dt_ms > DT_MS_BAD:
                self.n_bad_dt += 1
            self.dt_max = max(self.dt_max, dt_ms)

        # האם "יש אדם" בפריים?
        avail = (payload.get("availability") or {})
        pose_ok = bool(avail.get("pose")) or bool(avail.get("measurements"))
        conf_ok = (conf is not None) and (conf >= MIN_CONFIDENCE_FOR_PERSON)
        vis_ok = (vis is not None) and (vis >= MIN_VISIBILITY_FOR_PERSON)
        if pose_ok or conf_ok or vis_ok:
            self.n_person_frames += 1

    def end_set(self) -> Dict[str, Any]:
        if not self._in_set:
            # מחזיר מבנה מינימלי, ללא message. ניסוח ייעשה ב-explain.
            return {"visibility_risk": False, "severity": "LOW", "stats": {"frames": 0}}
        self._in_set = False

        duration_s = (self.t_last - self.t0) if self.t_last else 0.0

        # ממוצעים/אחוזים על פריימים מדידים בלבד
        avg_vis = (self.vis_sum / self.n_vis_measured) if self.n_vis_measured else None
        bad_vis_pct = (self.n_bad_vis / self.n_vis_measured) if self.n_vis_measured else 0.0
        very_bad_vis_pct = (self.n_very_bad_vis / self.n_vis_measured) if self.n_vis_measured else 0.0

        low_conf_pct = (self.n_low_conf / self.n_conf_measured) if self.n_conf_measured else 0.0
        avg_dt_ms = (self.dt_sum / self.n_dt_measured) if self.n_dt_measured else None
        bad_dt_pct = (self.n_bad_dt / self.n_dt_measured) if self.n_dt_measured else 0.0
        person_ratio = (self.n_person_frames / self.n_frames_total) if self.n_frames_total else 0.0

        severity = "LOW"
        reasons: List[str] = []

        limited_data = (self.n_frames_total < MIN_FRAMES_FOR_AUDIT) or (duration_s < MIN_DURATION_S)
        if limited_data:
            reasons.append("limited_data")

        # כלל נראות רך
        if avg_vis is not None:
            if avg_vis < VIS_WARN_MIN:
                if very_bad_vis_pct >= 0.20 or bad_vis_pct >= 0.50:
                    severity = "HIGH"; reasons.append("low_visibility_long")
                else:
                    severity = "MEDIUM"; reasons.append("low_visibility_medium")
            elif avg_vis < VIS_OK_MIN:
                if bad_vis_pct >= FRAC_BAD_VIS_MED:
                    severity = max(severity, "MEDIUM", key=lambda s: SEVERITY_ORDER[s]); reasons.append("streak_low_visibility")

        # נוכחות אדם
        if person_ratio < PERSON_MIN_RATIO:
            severity = max(severity, "MEDIUM", key=lambda s: SEVERITY_ORDER[s]); reasons.append("low_person_ratio")

        # זרימה/קפיאות
        if bad_dt_pct >= FRAC_BAD_DT_MED:
            severity = max(severity, "MEDIUM", key=lambda s: SEVERITY_ORDER[s]); reasons.append("slow_video")
        if self.dt_max >= DT_MS_VERY_BAD and (avg_vis is not None and avg_vis < VIS_OK_MIN):
            severity = "HIGH"; reasons.append("very_high_dt")

        # ביטחון זיהוי נמוך
        if low_conf_pct >= FRAC_LOW_CONF_MED:
            severity = max(severity, "MEDIUM", key=lambda s: SEVERITY_ORDER[s]); reasons.append("low_confidence")

        # מעט מדידות → לא HIGH
        measured_signals = sum([1 if self.n_vis_measured else 0,
                                1 if self.n_conf_measured else 0,
                                1 if self.n_dt_measured else 0])
        if measured_signals <= 1 and severity == "HIGH":
            severity = "MEDIUM"; reasons.append("partial_signals")

        risk = severity in ("MEDIUM", "HIGH")

        stats = {
            "frames": int(self.n_frames_total),
            "duration_s": round(duration_s, 2),
            "avg_visibility": round(avg_vis, 3) if avg_vis is not None else None,
            "min_visibility": round(self.vis_min, 3) if self.n_vis_measured else None,
            "low_visibility_pct": round(bad_vis_pct, 3) if self.n_vis_measured else None,
            "very_low_visibility_pct": round(very_bad_vis_pct, 3) if self.n_vis_measured else None,
            "low_confidence_pct": round(low_conf_pct, 3) if self.n_conf_measured else None,
            "avg_dt_ms": round(avg_dt_ms, 1) if avg_dt_ms is not None else None,
            "max_dt_ms": round(self.dt_max, 1) if self.n_dt_measured else None,
            "bad_dt_pct": round(bad_dt_pct, 3) if self.n_dt_measured else None,
            "person_ratio": round(person_ratio, 3),
            "notes": reasons,
            "vis_measured_frames": int(self.n_vis_measured),
            "conf_measured_frames": int(self.n_conf_measured),
            "dt_measured_frames": int(self.n_dt_measured),
        }

        return {"visibility_risk": risk, "severity": severity, "stats": stats}

# ─────────────────────────────── חלק ג' — Save Audit JSON ───────────────────────────────

def save_set_audit(summary: Dict[str, Any],
                   dir_path: str = "reports",
                   prefix: str = "set_summary",
                   add_meta: Optional[Dict[str, Any]] = None) -> str:
    """שומר דוח סט לקובץ JSON בתיקייה reports ומחזיר את הנתיב."""
    os.makedirs(dir_path, exist_ok=True)
    now = datetime.now()
    ts_tag = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts_tag}.json"
    fullpath = os.path.join(dir_path, filename)

    data = dict(summary or {})
    data.setdefault("saved_at", now.isoformat(timespec="seconds"))
    if add_meta:
        for k, v in add_meta.items():
            if k not in data:
                data[k] = v
    with open(fullpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return fullpath
