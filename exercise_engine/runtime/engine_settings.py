# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# exercise_engine/runtime/engine_settings.py
# מרכז את כל הספים/דגלים "מערכתיים" של המנוע:
# - ברירות מחדל בטוחות
# - אפשרות override דרך משתני סביבה (ENV)
# - dump() לאבחון
# הערה: מינימום חזרות לסט = 1 כברירת מחדל (SET_MIN_REPS=1)
# -----------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Tuple
import os
import json

__all__ = ["ClassifierSettings", "RuntimeSettings", "DiagnosticsSettings",
           "ReportSettings", "EngineSettings", "SETTINGS"]

# ─────────────────────────────── ENV helpers ────────────────────────────────

def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    return raw in ("1", "true", "yes", "on", "y", "t")

def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default

def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except Exception:
        return default

def _get_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw is not None else default

# ─────────────────────────────── Dataclasses ────────────────────────────────

@dataclass
class ClassifierSettings:
    """
    הגדרות מסווג תרגיל (היסטרזיס/אמון/מעברים).
    """
    S_MIN_ACCEPT: float                 # סף קבלה למועמד מוביל (0..1)
    H_MARGIN_KEEP: float                # מרווח כדי "להיצמד" לקודם
    H_MARGIN_SWITCH: float              # מרווח כדי לאשר החלפה
    CONF_EMA_ALPHA: float               # החלקת EMA לאמון
    LOW_CONF_EPS: float                 # סף אמון נמוך (EMA)
    LOW_CONF_T_SEC: float               # משך זמן לאמון נמוך לפני אזהרה
    FREEZE_DURING_REP: bool             # לנעול תרגיל בזמן חזרה
    STRONG_SWITCH_MARGIN: float         # מרווח "מעבר חזק"
    STRONG_SWITCH_BYPASS_FREEZE: bool   # לעקוף freeze במעבר חזק
    STRONG_SWITCH_BYPASS_GRACE: bool    # לעקוף grace במעבר חזק

@dataclass
class RuntimeSettings:
    """
    הגדרות ריצה כלליות (שערי אמון, גרייס, וזמני סטים).
    """
    GRACE_MS: int                       # חלון גרייס אחרי החלפת תרגיל (ms)
    LOWCONF_GATE_ENABLED: bool          # האם שער אמון נמוך פעיל
    LOWCONF_MIN: float                  # סף אמון לשער
    TIME_SOURCE: str                    # 'time' / 'monotonic' (עתידי)

    # סטים — ברירות מחדל מערכתיות (ניתן לדרוס ב-ENV):
    SET_MIN_REPS: int                   # מינימום חזרות לסט תקף (ברירת מחדל: 1)
    SET_RESET_TIMEOUT: float            # שניות ללא חזרה → סיום סט אוטומטי

@dataclass
class DiagnosticsSettings:
    DIAG_TAIL_LIMIT: int                # כמה רשומות לוג אחרונות לצרף לדו"ח
    LOG_RETENTION_DAYS: int             # שמירת לוגים (ימים) — אם רלוונטי

@dataclass
class ReportSettings:
    MAX_HINTS: int                      # מקסימום טיפים בדו"ח
    ROUND_SCORE_PCT: bool               # לעגל score_pct לשלם (0..100)
    GRADE_BANDS: Tuple[int, int, int, int]  # (A,B,C,D) כמינימוםי אחוזים

@dataclass
class EngineSettings:
    classifier: ClassifierSettings
    runtime: RuntimeSettings
    diagnostics: DiagnosticsSettings
    report: ReportSettings

    def dump(self) -> str:
        """החזרת JSON יפה לאבחון מהיר."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

# ─────────────────────────────── Loader ─────────────────────────────────────

def _load() -> EngineSettings:
    classifier = ClassifierSettings(
        S_MIN_ACCEPT=_get_float("EXR_S_MIN_ACCEPT", 0.40),
        H_MARGIN_KEEP=_get_float("EXR_H_MARGIN_KEEP", 0.10),
        H_MARGIN_SWITCH=_get_float("EXR_H_MARGIN_SWITCH", 0.20),
        CONF_EMA_ALPHA=_get_float("EXR_CONF_EMA_ALPHA", 0.25),
        LOW_CONF_EPS=_get_float("EXR_LOW_CONF_EPS", 0.30),
        LOW_CONF_T_SEC=_get_float("EXR_LOW_CONF_T_SEC", 1.0),
        FREEZE_DURING_REP=_get_bool("EXR_FREEZE_DURING_REP", True),
        STRONG_SWITCH_MARGIN=_get_float("EXR_STRONG_SWITCH_MARGIN", 0.45),
        STRONG_SWITCH_BYPASS_FREEZE=_get_bool("EXR_STRONG_SWITCH_BYPASS_FREEZE", False),
        STRONG_SWITCH_BYPASS_GRACE=_get_bool("EXR_STRONG_SWITCH_BYPASS_GRACE", False),
    )

    runtime = RuntimeSettings(
        GRACE_MS=_get_int("EXR_GRACE_MS", 1000),
        LOWCONF_GATE_ENABLED=_get_bool("EXR_LOWCONF_GATE", False),
        LOWCONF_MIN=_get_float("EXR_LOWCONF_MIN", 0.35),
        TIME_SOURCE=_get_str("EXR_TIME_SOURCE", "time"),

        # סטים — ברירת מחדל: סט תקף אחרי חזרה אחת (ניתן לשנות ב-ENV):
        #   EXR_SET_MIN_REPS=1/2/3...
        SET_MIN_REPS=_get_int("EXR_SET_MIN_REPS", 1),

        # סיום סט אוטומטי אחרי N שניות ללא חזרה:
        #   EXR_SET_RESET_TIMEOUT=7.0
        SET_RESET_TIMEOUT=_get_float("EXR_SET_RESET_TIMEOUT", 7.0),
    )

    diagnostics = DiagnosticsSettings(
        DIAG_TAIL_LIMIT=_get_int("EXR_DIAG_TAIL_LIMIT", 50),
        LOG_RETENTION_DAYS=_get_int("EXR_LOG_RETENTION_DAYS", 14),
    )

    report = ReportSettings(
        MAX_HINTS=_get_int("EXR_REPORT_MAX_HINTS", 5),
        ROUND_SCORE_PCT=_get_bool("EXR_ROUND_SCORE_PCT", True),
        GRADE_BANDS=(
            _get_int("EXR_GRADE_A_MIN", 90),
            _get_int("EXR_GRADE_B_MIN", 80),
            _get_int("EXR_GRADE_C_MIN", 70),
            _get_int("EXR_GRADE_D_MIN", 60),
        ),
    )

    return EngineSettings(
        classifier=classifier,
        runtime=runtime,
        diagnostics=diagnostics,
        report=report,
    )

# טעינה גלובלית לשימוש מידי במערכת
SETTINGS = _load()

# אינדיקציה שקטה לטעינה מוצלחת (אם log.emit קיים)
try:
    from exercise_engine.runtime.log import emit
    emit("settings_loaded", "info", "engine settings loaded", asdict(SETTINGS))
except Exception:
    pass
