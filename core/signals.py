# core/signals.py
# -------------------------------------------------------
# ⏱️ עיבוד סיגנלים טמפורליים למנוע ProCoach (גרסה מוקשחת)
#
# מה יש כאן (API תואם לקודם):
# 1) now_ms                 – זמן נוכחי במילישניות.
# 2) EMA                    – החלקה אקספוננציאלית לערכים (עם reset ותמיכה ב-alpha דינמי).
# 3) TemporalFilter         – החלקת ערך + חישוב מהירות/תאוצה בזמן אמת (+ dt_ms), עם conf→alpha.
# 4) HysteresisBool         – היסטרזיס לדגלים בינאריים + min_hold_ms למניעת הבהוב.
# 5) JitterMeter            – מד "ריצוד": סטיית תקן/ממוצע בחלון זמן גולש (ms).
# 6) LKGBuffer              – Last-Known-Good: שמירת payload תקין לתקופה כשהזיהוי נפל.
# 7) AngleFilter            – פילטר ייעודי לזוויות מחזוריות ([-180,180)) עם EMA והגבלת קפיצה.
#
# חיזוקים עיקריים:
# • הגנות NaN/Inf בכל המסלולים הרגישים.
# • EMA: נעילת alpha לטווח (1e-4..1.0] כדי למנוע קיפאון/רעידות.
# • TemporalFilter: התעלמות מדגימות לא תקינות, clamp ל-alpha דינמי, dt_s מוגן.
# • JitterMeter.std(): sqrt(max(var,0)) כדי למנוע sqrt שלילי זעיר מנומריקה.
# • HysteresisBool: התעלמות מערכי קלט לא סופיים; כיבוד min_hold_ms.
# • LKGBuffer: מטא-דאטה עקבי תמיד, הגנות עותק/גיל.
# • AngleFilter: מטפל במחזוריות, מגביל צעד, ותומך ב-alpha דינמי.
# -------------------------------------------------------

from __future__ import annotations
from typing import Optional, Deque, Tuple, Dict, Any, Callable
from collections import deque
import time
import math

_EPS    = 1e-9
_MIN_A  = 1e-4  # alpha מינימלי ל-EMA/דינמי
_MAX_A  = 1.0   # alpha מקסימלי

def _isfinite(x: float) -> bool:
    try:
        xf = float(x)
        return math.isfinite(xf)
    except Exception:
        return False

def _clamp(x: float, lo: float, hi: float) -> float:
    if lo > hi:
        lo, hi = hi, lo
    try:
        xf = float(x)
        if not math.isfinite(xf):
            return lo if xf < lo else hi
        return min(max(xf, lo), hi)
    except Exception:
        return lo

# ------------------------------- זמן -------------------------------

def now_ms() -> int:
    """זמן מערכת במילישניות (int)."""
    return int(time.time() * 1000)

# ------------------------------- EMA -------------------------------

class EMA:
    """
    פילטר החלקה אקספוננציאלי לערכים סקלריים.
    תומך ב-alpha דינמי פר-דגימה: update(x, alpha=...) ידרוס את self.alpha לאותה דגימה בלבד.
    """
    def __init__(self, alpha: float = 0.3, initial: Optional[float] = None):
        self.alpha = _clamp(alpha, _MIN_A, _MAX_A)
        self._y: Optional[float] = float(initial) if (initial is not None and _isfinite(initial)) else None

    def reset(self, value: Optional[float] = None) -> None:
        """איפוס למסנן; אם value ניתן – אתחל לערך זה, אחרת None (יישב על הדגימה הבאה)."""
        self._y = float(value) if (value is not None and _isfinite(value)) else None

    def update(self, x: Optional[float], alpha: Optional[float] = None) -> Optional[float]:
        """
        עדכון ערך:
        - x: הערך החדש (או None לשימור מצב).
        - alpha: אם alpha ניתן – ישמש לפעם זו (override). אחרת נשתמש ב-self.alpha.
        """
        if x is None or not _isfinite(x):
            return self._y  # אין דגימה חדשה/תקינה; שומר את המצב הנוכחי
        x = float(x)
        a = self.alpha if alpha is None else _clamp(alpha, _MIN_A, _MAX_A)
        if self._y is None:
            self._y = x
        else:
            self._y = a * x + (1.0 - a) * self._y
        return self._y

    @property
    def value(self) -> Optional[float]:
        return self._y

# ---------------------------- TemporalFilter ----------------------------

class TemporalFilter:
    """
    החלקה טמפורלית + מהירות/תאוצה בזמן אמת.
    - EMA פנימי לערך (עם תמיכה ב-alpha דינמי דרך dynamic_alpha_fn(conf)).
    - חישוב vel/acc לפי dt_s מוגן (לא פחות מ-1e-6).
    """
    def __init__(
        self,
        alpha: float = 0.25,  # היה 0.35 – הורדנו כדי להפחית ריצוד
        *,
        dynamic_alpha_fn: Optional[Callable[[float], float]] = None,
        initial: Optional[float] = None
    ):
        self.ema = EMA(alpha=_clamp(alpha, _MIN_A, _MAX_A), initial=initial)
        self._dynamic_alpha_fn = dynamic_alpha_fn
        self._prev_t_ms: Optional[int] = None
        self._prev_y: Optional[float] = None
        self._prev_vel: Optional[float] = None

    def reset(self, initial: Optional[float] = None) -> None:
        """איפוס הפילטר; ניתן לאתחל לערך התחלתי."""
        self.ema.reset(initial)
        self._prev_t_ms = None
        self._prev_y = None
        self._prev_vel = None

    def update(
        self,
        x: Optional[float],
        *,
        conf: Optional[float] = None,
        alpha_override: Optional[float] = None
    ) -> Tuple[Optional[float], Optional[float], Optional[float], int]:
        """
        עדכון דגימה.
        :param x: הערך הנמדד (יכול להיות None).
        :param conf: אם סופק ויש dynamic_alpha_fn – נחשב alpha דינמי מה-conf.
        :param alpha_override: אם סופק – דורס את alpha (עדיפות עליונה) לדגימה זו.
        :return: (y, vel, acc, dt_ms)
        """
        t_ms = now_ms()
        dt_ms = 0 if self._prev_t_ms is None else max(1, t_ms - self._prev_t_ms)
        dt_s = max(1e-6, dt_ms / 1000.0)

        # קביעת alpha לדגימה זו
        step_alpha: Optional[float] = None
        if alpha_override is not None and _isfinite(alpha_override):
            step_alpha = _clamp(alpha_override, _MIN_A, _MAX_A)
        elif self._dynamic_alpha_fn is not None and conf is not None and _isfinite(conf):
            try:
                a_dyn = float(self._dynamic_alpha_fn(float(conf)))
                if _isfinite(a_dyn):
                    step_alpha = _clamp(a_dyn, _MIN_A, _MAX_A)
            except Exception:
                step_alpha = None  # fallback ל-EMA.alpha

        # התעלמות מדגימות לא סופיות (NaN/Inf)
        x_in = x if (x is not None and _isfinite(x)) else None
        y = self.ema.update(x_in, alpha=step_alpha)

        if x_in is None or y is None or self._prev_y is None:
            # אין מספיק היסטוריה לחישוב מהירות/תאוצה
            self._prev_t_ms = t_ms
            self._prev_y = y
            self._prev_vel = None
            return y, None, None, dt_ms

        vel = (y - self._prev_y) / dt_s
        acc = None if self._prev_vel is None else (vel - self._prev_vel) / dt_s

        self._prev_t_ms = t_ms
        self._prev_y = y
        self._prev_vel = vel
        return y, vel, acc, dt_ms

# ---------------------------- HysteresisBool ----------------------------

class HysteresisBool:
    """
    היסטרזיס לדגל בינארי: מונע ריצוד סביב סף.
    תומך גם ב-min_hold_ms (נעילת זמן) כדי לא "להבהב" מהר מדי.
    """
    def __init__(self, th_on: float, th_off: float, *, initial: bool = False, min_hold_ms: int = 0):
        assert th_off <= th_on, "th_off חייב להיות <= th_on"
        self.th_on = float(th_on)
        self.th_off = float(th_off)
        self.state = bool(initial)
        self.min_hold_ms = int(min_hold_ms)
        self._last_change_ms: Optional[int] = None

    def reset(self, state: bool = False) -> None:
        self.state = bool(state)
        self._last_change_ms = None

    def update(self, value: Optional[float | bool]) -> Optional[bool]:
        if value is None:
            return None
        t = now_ms()

        # תמיכה ישירה בבוליאן
        if isinstance(value, bool):
            if value != self.state and self._can_change(t):
                self.state = value
                self._last_change_ms = t
            return self.state

        # ערך מספרי
        if not _isfinite(value):
            return self.state  # התעלמות מערך לא תקין
        v = float(value)
        desired = self.state
        if v >= self.th_on:
            desired = True
        elif v <= self.th_off:
            desired = False

        if desired != self.state and self._can_change(t):
            self.state = desired
            self._last_change_ms = t

        return self.state

    def _can_change(self, t_now: int) -> bool:
        if self.min_hold_ms <= 0 or self._last_change_ms is None:
            return True
        return (t_now - self._last_change_ms) >= self.min_hold_ms

# ------------------------------ JitterMeter ------------------------------

class JitterMeter:
    """מודד ריצוד: סטיית תקן/ממוצע מתגלגלים בחלון זמן (ms)."""
    def __init__(self, window_ms: int = 350):
        self.window_ms = int(window_ms)
        self.buf: Deque[Tuple[int, float]] = deque()

    def reset(self) -> None:
        self.buf.clear()

    def update(self, value: Optional[float]) -> None:
        t = now_ms()
        if value is not None and _isfinite(value):
            self.buf.append((t, float(value)))
        self._prune(t)

    def _prune(self, t_now: int) -> None:
        limit = t_now - self.window_ms
        while self.buf and self.buf[0][0] < limit:
            self.buf.popleft()

    def values(self) -> list[float]:
        return [v for _, v in self.buf]

    def mean(self) -> Optional[float]:
        vals = self.values()
        return None if not vals else (math.fsum(vals) / len(vals))

    def std(self) -> Optional[float]:
        vals = self.values()
        n = len(vals)
        if n < 2:
            return 0.0 if n == 1 else None
        m = math.fsum(vals) / n
        var = math.fsum((v - m) ** 2 for v in vals) / (n - 1)
        # הגנה נומרית: לעיתים var יכול לצאת שלילי זעיר (≈ -1e-16) → נצמיד ל-0
        var = var if var > 0.0 else 0.0
        return math.sqrt(var)

    def count(self) -> int:
        return len(self.buf)

# ------------------------------ LKGBuffer ------------------------------

class LKGBuffer:
    """
    Last-Known-Good:
    - שומר את ה-payload האחרון התקין.
    - אם אין זיהוי/נראות – מחזיר את האחרון עד מקסימום זמן (max_age_ms).
    - אחרי זה יסמן meta.valid=False כדי שה-UI/מנוע ידעו להסתיר/להזהיר.
    - ניתן להגדיר סף קונפידנס מינימלי לשמירה (min_conf_for_store).
    """
    def __init__(self, *, enabled: bool = True, max_age_ms: int = 1000, min_conf_for_store: float = 0.70):
        self.enabled = bool(enabled)
        self.max_age_ms = int(max_age_ms)
        self.min_conf_for_store = float(min_conf_for_store)

        self.last: Optional[Dict[str, Any]] = None
        self.last_update_ms: Optional[int] = None

    def reset(self) -> None:
        self.last = None
        self.last_update_ms = None

    def apply(self, detected: bool, payload: Dict[str, Any], *, conf: Optional[float] = None) -> Dict[str, Any]:
        """
        :param detected: האם יש כרגע זיהוי אמיתי (True/False).
        :param payload: מילון נתונים עדכני (נחשב "תקין" אם detected=True וגם conf מספיק).
        :param conf: אם ניתן – ישמש להחלטה האם לשמור ל-LKG (בהתאם ל-min_conf_for_store).
        :return: payload להצגה/שידור, עם מטא-דאטה:
                 meta.detected / meta.valid / meta.age_ms / meta.updated_at
        """
        now = now_ms()

        def _with_meta(base: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(base)
            meta = dict(out.get("meta", {}))
            out["meta"] = meta
            return out

        if not self.enabled:
            out = _with_meta(payload)
            out["meta"]["detected"] = bool(detected)
            out["meta"]["valid"] = True
            out["meta"]["age_ms"] = int(out["meta"].get("age_ms", 0))
            out["meta"]["updated_at"] = now
            return out

        # אין כרגע זיהוי – נשתמש ב-LKG אם קיים ובתוקף
        if not detected and self.last is not None:
            lkg = _with_meta(self.last)
            prev = self.last_update_ms or now
            age_prev = int(lkg["meta"].get("age_ms", 0))
            age_ms = age_prev + (now - prev)

            lkg["meta"]["detected"] = False
            lkg["meta"]["age_ms"] = age_ms
            lkg["meta"]["updated_at"] = prev
            lkg["meta"]["valid"] = age_ms <= self.max_age_ms
            return lkg

        # יש זיהוי עדכני
        out = _with_meta(payload)
        out["meta"]["detected"] = bool(detected)
        out["meta"]["age_ms"] = 0
        out["meta"]["updated_at"] = now
        out["meta"]["valid"] = True

        # נשמור כ-LKG רק אם conf מספיק גבוה (אם conf לא סופק או לא סופי – נתייחס כאילו מספיק)
        store_ok = (conf is None) or (_isfinite(conf) and float(conf) >= self.min_conf_for_store)
        if store_ok:
            self.last = dict(out)
            self.last_update_ms = now

        return out

# ------------------------------ AngleFilter ------------------------------
# פילטר ייעודי לזוויות מחזוריות: מטפל ב-unwrap סביב 180-,180, מגביל צעד, ו-EMA.

from core.geometry import delta_deg, safe_deg  # שימוש בפונקציות המחזוריות של הגיאומטריה

class AngleFilter:
    """
    מסנן זוויות מחזוריות ([-180,180)):
    - מבצע unwrap באמצעות delta_deg כדי למזער קפיצה סביב -180/180.
    - מגביל קפיצת זווית רגעית (max_step_deg) כדי לחסום רעש שגורם לזינוקים.
    - מחליק באמצעות EMA (עם תמיכה ב-alpha דינמי דרך conf→dynamic_alpha_fn אם רוצים).

    שימוש:
        flt = AngleFilter(alpha=0.25, max_step_deg=2.0)
        y = flt.update(raw_angle_deg, conf=visibility_or_conf)
    """
    def __init__(
        self,
        alpha: float = 0.25,
        max_step_deg: float = 2.0,              # מגבלה על השינוי המיידי (°/דגימה)
        dynamic_alpha_fn: Optional[Callable[[float], float]] = None,
        initial: Optional[float] = None
    ):
        init = safe_deg(initial) if initial is not None else None
        self._ema = EMA(alpha=_clamp(alpha, _MIN_A, _MAX_A), initial=init)
        self._prev: Optional[float] = init
        self._max_step = float(max(0.0, max_step_deg))
        self._dyn = dynamic_alpha_fn

    def reset(self, value: Optional[float] = None) -> None:
        v = safe_deg(value) if value is not None else None
        self._ema.reset(v)
        self._prev = v

    def update(
        self,
        angle_deg: Optional[float],
        *,
        conf: Optional[float] = None,
        alpha_override: Optional[float] = None
    ) -> Optional[float]:
        """
        :param angle_deg: הזווית החדשה במעלות (חתומה, בטווח [-180,180)) או None.
        :param conf: קונפידנס/נראות ∈[0..1] (לא חובה). אם קיים ו-self._dyn סופק – יקבע alpha דינמי.
        :param alpha_override: דורס את alpha לדגימה זו (עדיפות עליונה).
        :return: זווית מוחלקת (חתומה, בטווח [-180,180)) או None אם אין עדיין מצב.
        """
        # אין דגימה? החזר את המצב הנוכחי
        if angle_deg is None or not _isfinite(angle_deg):
            return self._ema.value

        new = safe_deg(angle_deg)
        if new is None:
            return self._ema.value

        # unwrap מול הקודמת כדי למזער קפיצה סביב הגבול -180/180
        if self._prev is None:
            candidate = new
        else:
            d = delta_deg(new, self._prev)  # בטווח [-180,180)
            # הגבלת צעד מיידי כדי למנוע זינוקים מרעש
            if self._max_step > 0.0:
                d = _clamp(d, -self._max_step, self._max_step)
            candidate = self._prev + d
            candidate = safe_deg(candidate)

        # קביעה/דחיפה של alpha לדגימה (דינמי או override)
        step_alpha: Optional[float] = None
        if alpha_override is not None and _isfinite(alpha_override):
            step_alpha = _clamp(alpha_override, _MIN_A, _MAX_A)
        elif self._dyn is not None and conf is not None and _isfinite(conf):
            try:
                a_dyn = float(self._dyn(float(conf)))
                if _isfinite(a_dyn):
                    step_alpha = _clamp(a_dyn, _MIN_A, _MAX_A)
            except Exception:
                step_alpha = None

        y = self._ema.update(candidate, alpha=step_alpha)
        self._prev = y if y is not None else self._prev
        return y
