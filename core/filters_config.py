# core/filters_config.py
# -------------------------------------------------------
# 🔧 Filters Config – כל ההגדרות של המסננים למנוע ProCoach
# (לשימוש מ: core/kinematics/engine.py, core/signals.py, core/visibility.py, app/ui/*)
#
# כולל:
# - Gate לפי confidence
# - EMA (alpha דינמי לפי conf)
# - Outlier Rejector
# - Deadband
# - JitterMeter (חלון, ספים)
# - LKGBuffer (זיכרון מדידה אחרון טובה)
# - HysteresisBool (ספי on/off נפרדים)
# - Guards (טווחים בטוחים/קלמפינג/בדיקות sanity)
# - UI Rules (תצוגת צבעים/הסתרה)
# - פרופילים + overrides לפי שם מדד
# -------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Dict, Literal, Optional

# ========================= בסיסי =========================

@dataclass(frozen=True)
class EMAParams:
    # 🎯 כויל כדי להעביר jitter ≤ 0.7° בסיגמה 0.002 בלי לפגוע במונוטוניות:
    # alpha נמוך = יותר החלקה. בפועל, ב-conf≈0.9 נקבל ~0.27–0.29.
    alpha_min: float = 0.05
    alpha_max: float = 0.30
    gamma: float = 1.20   # מיפוי conf→alpha: alpha = alpha_min + (alpha_max-alpha_min) * (conf**gamma)

@dataclass(frozen=True)
class OutlierParams:
    angle_deg: float = 25.0
    px_abs: float = 30.0
    px_by_shoulder: float = 0.25
    ratio_abs: float = 0.20

@dataclass(frozen=True)
class DeadbandParams:
    # ↓ הקטנו ל-1.0° כדי שלא יפגע במונוטוניות עדינה בבדיקות sweep, אבל עדיין יוריד רעש מיקרו
    angle_deg: float = 1.0
    px: float = 10.0
    ratio: float = 0.05

@dataclass(frozen=True)
class JitterParams:
    window_ms: int = 350
    warn_angle_deg: float = 6.0
    warn_px: float = 18.0
    warn_ratio: float = 0.08

@dataclass(frozen=True)
class LKGParams:
    enabled: bool = True
    max_age_ms: int = 400
    min_conf_for_store: float = 0.70

@dataclass(frozen=True)
class HysteresisParams:
    on_thr: float = 0.65
    off_thr: float = 0.55
    min_hold_ms: int = 150

@dataclass(frozen=True)
class GuardParams:
    angle_min_deg: float = -180.0
    angle_max_deg: float = 180.0
    px_min: float = 0.0
    px_max: float = 4096.0
    ratio_min: float = -5.0
    ratio_max: float = 5.0

@dataclass(frozen=True)
class VisibilityParams:
    conf_thr: float = 0.60
    require_view: Literal["any","front","side","back"] = "any"

@dataclass(frozen=True)
class UIRules:
    hide_below: float = 0.60
    yellow_min: float = 0.60
    green_min: float = 0.80

@dataclass(frozen=True)
class PerfParams:
    ui_update_hz: float = 10.0
    loop_interval_ms: int = 10
    hands_every_n: int = 2

# ========================= פרופיל מלא =========================

@dataclass(frozen=True)
class Profile:
    # Gate / Visibility
    visibility: VisibilityParams = VisibilityParams()

    # EMA / Outlier / Deadband
    ema: EMAParams = EMAParams()
    outlier: OutlierParams = OutlierParams()
    deadband: DeadbandParams = DeadbandParams()

    # Jitter / LKG / Hysteresis / Guards
    jitter: JitterParams = JitterParams()
    lkg: LKGParams = LKGParams()
    hyst: HysteresisParams = HysteresisParams()
    guards: GuardParams = GuardParams()

    # UI + ביצועים
    ui: UIRules = UIRules()
    perf: PerfParams = PerfParams()

    # Overrides (אופציונלי): אפשר להגדיר לכל metric פרמטרים ספציפיים שיגברו על ברירת-המחדל
    # דוגמה שימוש: angle_overrides={"elbow_left_deg": 0.8} → משנה רק deadband/ema לפי לוגיקת מנוע
    angle_overrides: Optional[Dict[str, float]] = None
    px_overrides: Optional[Dict[str, float]] = None
    ratio_overrides: Optional[Dict[str, float]] = None

# ========================= פרופילים מוכנים =========================
# 🤝 ברירות מחדל מכוילות: jitter נמוך, מבלי לאבד תגובתיות בתנועות איטיות.

DEFAULT_PROFILE = Profile(
    visibility=VisibilityParams(conf_thr=0.60, require_view="any"),
    ema=EMAParams(alpha_min=0.05, alpha_max=0.30, gamma=1.20),
    outlier=OutlierParams(angle_deg=25.0, px_abs=30.0, px_by_shoulder=0.25, ratio_abs=0.20),
    deadband=DeadbandParams(angle_deg=1.0, px=10.0, ratio=0.05),
    jitter=JitterParams(window_ms=350, warn_angle_deg=6.0, warn_px=18.0, warn_ratio=0.08),
    lkg=LKGParams(enabled=True, max_age_ms=400, min_conf_for_store=0.70),
    hyst=HysteresisParams(on_thr=0.65, off_thr=0.55, min_hold_ms=150),
    guards=GuardParams(angle_min_deg=-180.0, angle_max_deg=180.0, px_min=0.0, px_max=4096.0, ratio_min=-5.0, ratio_max=5.0),
    ui=UIRules(hide_below=0.60, yellow_min=0.60, green_min=0.80),
    perf=PerfParams(ui_update_hz=10.0, loop_interval_ms=10, hands_every_n=2),
)

LENIENT_PROFILE = Profile(
    visibility=VisibilityParams(conf_thr=0.55, require_view="any"),
    ema=EMAParams(alpha_min=0.05, alpha_max=0.35, gamma=1.10),
    outlier=OutlierParams(angle_deg=30.0, px_abs=36.0, px_by_shoulder=0.30, ratio_abs=0.25),
    deadband=DeadbandParams(angle_deg=1.5, px=12.0, ratio=0.06),
    jitter=JitterParams(window_ms=400, warn_angle_deg=7.5, warn_px=22.0, warn_ratio=0.10),
    lkg=LKGParams(enabled=True, max_age_ms=500, min_conf_for_store=0.65),
    hyst=HysteresisParams(on_thr=0.62, off_thr=0.52, min_hold_ms=150),
    guards=GuardParams(),
    ui=UIRules(hide_below=0.55, yellow_min=0.55, green_min=0.80),
    perf=PerfParams(ui_update_hz=9.0, loop_interval_ms=12, hands_every_n=3),
)

STRICT_PROFILE = Profile(
    visibility=VisibilityParams(conf_thr=0.65, require_view="any"),
    ema=EMAParams(alpha_min=0.06, alpha_max=0.28, gamma=1.35),  # strict = חלק במיוחד (alpha_max נמוך)
    outlier=OutlierParams(angle_deg=20.0, px_abs=24.0, px_by_shoulder=0.20, ratio_abs=0.15),
    deadband=DeadbandParams(angle_deg=0.8, px=8.0, ratio=0.04),
    jitter=JitterParams(window_ms=300, warn_angle_deg=5.0, warn_px=14.0, warn_ratio=0.06),
    lkg=LKGParams(enabled=True, max_age_ms=300, min_conf_for_store=0.75),
    hyst=HysteresisParams(on_thr=0.68, off_thr=0.58, min_hold_ms=180),
    guards=GuardParams(),
    ui=UIRules(hide_below=0.65, yellow_min=0.65, green_min=0.85),
    perf=PerfParams(ui_update_hz=12.0, loop_interval_ms=8, hands_every_n=2),
)

PROFILES: Dict[str, Profile] = {
    "default": DEFAULT_PROFILE,
    "lenient": LENIENT_PROFILE,
    "strict": STRICT_PROFILE,
}

# ========================= מנהל קונפיג =========================

class _Config:
    """ CONFIG.profile מחזיר את הפרופיל הפעיל (immutable).
        ניתן להחליף פרופיל או לעדכן שדות ספציפיים בצורה מבוקרת. """
    def __init__(self, active: Literal["default","lenient","strict"] = "default"):
        self._active_name = active
        self._profile = PROFILES[active]

    @property
    def profile(self) -> Profile:
        return self._profile

    @property
    def name(self) -> str:
        return self._active_name

    def set_profile(self, name: Literal["default","lenient","strict"]) -> None:
        if name not in PROFILES:
            raise KeyError(f"Unknown profile '{name}'. Options: {list(PROFILES)}")
        self._active_name = name
        self._profile = PROFILES[name]

    def patch(self, **kwargs) -> None:
        # עדכון נקודתי של שדות בפרופיל הפעיל
        self._profile = replace(self._profile, **kwargs)

CONFIG = _Config(active="default")

# ========================= פונקציות עזר =========================

def _clamp(x: float, lo: float, hi: float) -> float:
    return hi if x > hi else lo if x < lo else x

def alpha_from_conf(conf: float, p: EMAParams) -> float:
    """המרת conf → alpha בצורה רציפה, עם קלמפ להגנה."""
    if conf <= 0.0:
        return p.alpha_min
    if conf >= 1.0:
        return p.alpha_max
    a = p.alpha_min + (p.alpha_max - p.alpha_min) * (conf ** p.gamma)
    return _clamp(a, p.alpha_min, p.alpha_max)

def metric_deadband(value: float, last_value: float, kind: Literal["angle","px","ratio"], db: DeadbandParams) -> float:
    """מחזיר את הערך לאחר Deadband (אם ההפרש קטן מהסף – נשאר הערך הישן)."""
    diff = abs(value - last_value)
    thr = db.angle_deg if kind == "angle" else db.px if kind == "px" else db.ratio
    return last_value if diff < thr else value

def is_outlier(delta: float, kind: Literal["angle","px","ratio"], out: OutlierParams, shoulder_width_px: Optional[float] = None) -> bool:
    """בודק האם הפרש בין פריימים הוא חריג."""
    if kind == "angle":
        return abs(delta) > out.angle_deg
    if kind == "px":
        lim = out.px_abs
        if shoulder_width_px and shoulder_width_px > 0:
            lim = max(lim, out.px_by_shoulder * shoulder_width_px)
        return abs(delta) > lim
    # ratio
    return abs(delta) > out.ratio_abs

def guard_value(x: float, kind: Literal["angle","px","ratio"], g: GuardParams) -> float:
    """קלמפינג של ערך למדדים בטוחים."""
    if kind == "angle":
        lo, hi = g.angle_min_deg, g.angle_max_deg
    elif kind == "px":
        lo, hi = g.px_min, g.px_max
    else:
        lo, hi = g.ratio_min, g.ratio_max
    return _clamp(x, lo, hi)

def ui_color_for_conf(conf: float, ui: UIRules) -> Literal["hidden","yellow","green"]:
    """קובע קטגוריית UI לפי conf."""
    if conf < ui.hide_below:
        return "hidden"
    if conf < ui.green_min:
        return "yellow"
    return "green"
