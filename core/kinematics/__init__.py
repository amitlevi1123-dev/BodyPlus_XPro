# core/kinematics/__init__.py
# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🌐 Public API for kinematics package
# מה הקובץ עושה?
# • מייצא סינגלטון KINEMATICS שכבר נוצר בתוך engine.py
# • שומר תאימות ישנה:
#     from core.kinematics import KINEMATICS
# • מייצא גם PAYLOAD_VERSION ו־KINEMATICS_PATH לצורכי Debug
# • לא יוצר מופע כפול! (אין כאן KinematicsComputer())
# -------------------------------------------------------

from .engine import (
    KinematicsComputer,  # למחויבות לאחור/השלמה
    KINEMATICS,          # הסינגלטון שנוצר בתוך engine.py
    PAYLOAD_VERSION,     # גרסת הפיילוד לצורכי בדיקה/לוגים
    MODULE_PATH as KINEMATICS_PATH,  # נתיב מדויק של engine.py שנטען בפועל
)

__all__ = [
    "KINEMATICS",
    "KinematicsComputer",
    "PAYLOAD_VERSION",
    "KINEMATICS_PATH",
]
