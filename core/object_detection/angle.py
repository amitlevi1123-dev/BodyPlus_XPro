# core/object_detection/angle.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple, List, Any, Dict
import math
import cv2
import numpy as np

@dataclass
class AngleResult:
    """תוצאת חישוב זווית."""
    angle_deg: Optional[float]   # [0..180) או None אם לא אמין
    quality: float               # 0..1
    ang_src: str                 # "pca" / "hough" / "none"

    # ✅ תאימות ל-Engine שמחפש .src
    @property
    def src(self) -> str:
        return self.ang_src

@dataclass
class AngleConfig:
    max_roi_px: int = 320 * 320
    blur_kernel: int = 3
    canny_low: int = 50
    canny_high: int = 150
    edge_dilate_iter: int = 0
    min_edge_pixels: int = 60
    min_quality_for_angle: float = 0.5
    pca_min_var_ratio: float = 0.65
    hough_enabled: bool = True
    hough_rho: float = 1.0
    hough_theta: float = math.pi / 180.0
    hough_threshold: int = 30
    hough_min_line_len: int = 20
    hough_max_line_gap: int = 10
    extra: Optional[Dict[str, Any]] = None

def compute_angle_for_box(
    frame_bgr: np.ndarray,
    box: Tuple[int, int, int, int],
    cfg: Any,
) -> AngleResult:
    max_roi_px         = int(getattr(cfg, "max_roi_px", 320 * 320))
    blur_kernel        = int(getattr(cfg, "blur_kernel", 3))
    canny_low          = int(getattr(cfg, "canny_low", 50))
    canny_high         = int(getattr(cfg, "canny_high", 150))
    edge_dilate_iter   = int(getattr(cfg, "edge_dilate_iter", 0))
    min_edge_pixels    = int(getattr(cfg, "min_edge_pixels", 60))
    pca_min_var_ratio  = float(getattr(cfg, "pca_min_var_ratio", 0.65))
    hough_enabled      = bool(getattr(cfg, "hough_enabled", True))
    hough_rho          = float(getattr(cfg, "hough_rho", 1.0))
    hough_theta        = float(getattr(cfg, "hough_theta", np.pi / 180.0))
    hough_threshold    = int(getattr(cfg, "hough_threshold", 30))
    hough_min_line_len = int(getattr(cfg, "hough_min_line_len", 20))
    hough_max_line_gap = int(getattr(cfg, "hough_max_line_gap", 10))
    min_quality_for_angle = float(getattr(cfg, "min_quality_for_angle", 0.5))

    if frame_bgr is None or not hasattr(frame_bgr, "shape") or getattr(frame_bgr, "size", 0) == 0:
        return AngleResult(angle_deg=None, quality=0.0, ang_src="none")

    x1, y1, x2, y2 = _sanitize_box(box, frame_bgr.shape[1], frame_bgr.shape[0])
    if x2 - x1 < 2 or y2 - y1 < 2:
        return AngleResult(angle_deg=None, quality=0.0, ang_src="none")

    roi, _scale = _extract_roi(frame_bgr, x1, y1, x2, y2, max_roi_px)
    if getattr(roi, "size", 0) == 0:
        return AngleResult(angle_deg=None, quality=0.0, ang_src="none")

    edges, edge_count = _edge_map(roi, blur_kernel, canny_low, canny_high, edge_dilate_iter)
    total_edge_px = edges.size  # סה"כ פיקסלים ב־ROI

    if edge_count < min_edge_pixels:
        q = _edge_quality(edge_count, total_edge_px)
        return AngleResult(angle_deg=None, quality=q, ang_src="none")

    pca_angle, pca_q = _angle_from_pca(edges, min_edge_pixels, pca_min_var_ratio)
    if pca_angle is not None:
        angle = _normalize_0_180(pca_angle)
        quality = _final_quality(pca_q, edge_count, total_edge_px)
        if quality >= min_quality_for_angle:
            return AngleResult(angle_deg=angle, quality=quality, ang_src="pca")

    if hough_enabled:
        h_angle, h_q = _angle_from_hough(
            edges,
            rho=hough_rho,
            theta=hough_theta,
            threshold=hough_threshold,
            min_line_len=hough_min_line_len,
            max_line_gap=hough_max_line_gap,
        )
        if h_angle is not None:
            angle = _normalize_0_180(h_angle)
            quality = _final_quality(h_q, edge_count, total_edge_px)
            if quality >= min_quality_for_angle:
                return AngleResult(angle_deg=angle, quality=quality, ang_src="hough")

    q = _edge_quality(edge_count, total_edge_px)
    return AngleResult(angle_deg=None, quality=q, ang_src="none")

def _sanitize_box(box: Tuple[int, int, int, int], w: int, h: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(int(x1), w - 1))
    y1 = max(0, min(int(y1), h - 1))
    x2 = max(0, min(int(x2), w - 1))
    y2 = max(0, min(int(y2), h - 1))
    if x2 <= x1: x2 = min(w - 1, x1 + 1)
    if y2 <= y1: y2 = min(h - 1, y1 + 1)
    return x1, y1, x2, y2

def _extract_roi(frame_bgr: np.ndarray, x1: int, y1: int, x2: int, y2: int, max_px: int) -> Tuple[np.ndarray, float]:
    roi = frame_bgr[y1:y2, x1:x2]
    h, w = roi.shape[:2]
    scale = 1.0
    if w * h > max_px and w > 0 and h > 0:
        r = math.sqrt(max_px / float(w * h))
        nw, nh = max(1, int(w * r)), max(1, int(h * r))
        roi = cv2.resize(roi, (nw, nh), interpolation=cv2.INTER_AREA)
        scale = r
    return roi, scale

def _edge_map(roi_bgr: np.ndarray, blur_kernel: int, canny_low: int, canny_high: int,
              edge_dilate_iter: int) -> Tuple[np.ndarray, int]:
    blur_kernel = int(max(0, blur_kernel))
    if blur_kernel % 2 == 0 and blur_kernel > 0:
        blur_kernel += 1
    canny_low = int(max(0, canny_low))
    canny_high = int(max(canny_low + 1, canny_high))

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    if blur_kernel > 0:
        gray = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
    try:
        edges = cv2.Canny(gray, canny_low, canny_high)
    except Exception:
        edges = np.zeros_like(gray, dtype=np.uint8)

    if edge_dilate_iter > 0:
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=int(edge_dilate_iter))

    edge_count = int(np.count_nonzero(edges))
    return edges, edge_count

def _edge_quality(edge_count: int, total_edge_px: int) -> float:
    if total_edge_px <= 0:
        return 0.0
    density = edge_count / float(total_edge_px)
    return float(max(0.0, min(1.0, density / 0.02)))  # ~2% צפיפות → איכות 1.0

def _final_quality(model_q: float, edge_count: int, total_edge_px: int) -> float:
    edge_q = _edge_quality(edge_count, total_edge_px)
    return float(max(0.0, min(1.0, 0.7 * model_q + 0.3 * edge_q)))

def _angle_from_pca(edges: np.ndarray, min_edge_pixels: int, pca_min_var_ratio: float) -> Tuple[Optional[float], float]:
    ys, xs = np.nonzero(edges)
    if xs.size < min_edge_pixels:
        return None, 0.0
    pts = np.column_stack((xs.astype(np.float32), ys.astype(np.float32)))
    mean = np.mean(pts, axis=0)
    pts_c = pts - mean
    cov = np.cov(pts_c, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    idx_max = int(np.argmax(eigvals))
    v = eigvecs[:, idx_max]
    e0 = float(max(eigvals[idx_max], 1e-9))
    e1 = float(max(np.min(eigvals), 1e-9))
    var_ratio = e0 / (e0 + e1)
    if var_ratio < pca_min_var_ratio:
        return None, var_ratio
    angle_deg = math.degrees(math.atan2(float(v[1]), float(v[0])))
    angle_deg = _normalize_0_180(angle_deg)
    pca_q = float(max(0.0, min(1.0, (var_ratio - 0.5) / 0.5)))
    return angle_deg, pca_q

def _angle_from_hough(edges: np.ndarray,
                      rho: float, theta: float, threshold: int,
                      min_line_len: int, max_line_gap: int) -> Tuple[Optional[float], float]:
    rho = float(max(1e-3, rho))
    theta = float(max(1e-6, theta))
    threshold = int(max(1, threshold))
    min_line_len = int(max(1, min_line_len))
    max_line_gap = int(max(0, max_line_gap))
    lines = cv2.HoughLinesP(edges, rho=rho, theta=theta, threshold=threshold,
                            minLineLength=min_line_len, maxLineGap=max_line_gap)
    if lines is None or len(lines) == 0:
        return None, 0.0
    angles: List[float] = []
    weights: List[float] = []
    for l in lines:
        x1, y1, x2, y2 = map(int, l[0])
        dx, dy = float(x2 - x1), float(y2 - y1)
        length = math.hypot(dx, dy)
        if length < min_line_len:
            continue
        ang = math.degrees(math.atan2(dy, dx))
        angles.append(_normalize_0_180(ang))
        weights.append(length)
    if not angles:
        return None, 0.0
    doubled = [math.radians(a * 2.0) for a in angles]
    c = sum(math.cos(a) * w for a, w in zip(doubled, weights))
    s = sum(math.sin(a) * w for a, w in zip(doubled, weights))
    mean_doubled = math.degrees(math.atan2(s, c)) % 360.0
    mean_angle = (mean_doubled / 2.0) % 180.0
    total_len = float(sum(weights))
    hough_q = float(max(0.0, min(1.0, total_len / max(1.0, float(min_line_len) * 10.0))))
    return mean_angle, hough_q

def _normalize_0_180(angle_deg: float) -> float:
    a = float(angle_deg) % 180.0
    if a < 0:
        a += 180.0
    return a
