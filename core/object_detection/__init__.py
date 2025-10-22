# -------------------------------------------------------
# Lightweight init for core.object_detection:
# - לא מושך engine/config בזמן הייבוא
# - מספק אליאסים אמיתיים לתת-מודולים מה-kinematics (pose_points, joints)
# - מאפשר גם:
#     import core.object_detection.pose_points
#     from core.object_detection import pose_points
# - כולל __dir__ ו-TYPE_CHECKING לשיפור IDE/autocomplete
# -------------------------------------------------------

from importlib import import_module
import sys as _sys
from typing import TYPE_CHECKING

# תתי-מודולים "אמיתיים" תחת core.object_detection שיובאו בעצלנות אם יבקשו אותם
# ⚠️ הוספתי כאן "providers" כדי שה-IDE והייבוא העצל יתמכו גם בו.
_OD_SUBMODS = {
    "detector",
    "engine",
    "simdet",
    "tracks",
    "features",
    "angle",
    "config_loader",
    "providers",
}

# גשרים לשמירת תאימות: שם ישן → מודול ב-kinematics
_BRIDGES = {
    "pose_points": "core.kinematics.pose_points",
    "joints": "core.kinematics.joints",
}

_pkg_name = __name__
_pkg = _sys.modules[_pkg_name]

# צור אליאסים ב-sys.modules + globals כדי לתמוך בשתי צורות ה-import
for _name, _target in _BRIDGES.items():
    try:
        _mod = import_module(_target)
        # מאפשר import core.object_detection.pose_points
        _sys.modules[f"{_pkg_name}.{_name}"] = _mod
        # מאפשר from core.object_detection import pose_points
        setattr(_pkg, _name, _mod)
    except Exception:
        # אם משהו נכשל, __getattr__ ישמש fallback בזמן ריצה
        pass

__all__ = sorted(list(_OD_SUBMODS | set(_BRIDGES.keys())))

def __getattr__(name: str):
    # מפנה את pose_points / joints ל-core.kinematics.* (fallback אם לא הוזרק ב-globals)
    if name in _BRIDGES:
        mod = import_module(_BRIDGES[name])
        setattr(_pkg, name, mod)
        return mod

    # ייבוא עצל של תתי-מודולים תחת core.object_detection
    if name in _OD_SUBMODS:
        mod = import_module(f"{__name__}.{name}")
        setattr(_pkg, name, mod)
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def __dir__():
    # משפר השלמה ב-IDE/REPL
    return sorted(set(list(globals().keys()) + list(__all__)))

# תמיכה ל-IDE/typing בזמן פיתוח (ללא השפעה בזמן ריצה)
if TYPE_CHECKING:
    from . import detector, engine, simdet, tracks, features, angle, config_loader, providers  # noqa: F401
    from core.kinematics import pose_points as pose_points  # type: ignore  # noqa: F401
    from core.kinematics import joints as joints  # type: ignore  # noqa: F401
