# core/object_detection/detector.py
# -------------------------------------------------------
# Shim לשמירת תאימות: מייצא את ה-API מ-detector_base.
# אין כאן לוגיקה; כל המימוש ב-detector_base/providers.
# -------------------------------------------------------
from .detector_base import (
    BBox,
    DetectionItem,
    DetectorState,
    ObjectDetectionConfig,
    Track,
    CentroidTracker,
    DetectorService,
)
