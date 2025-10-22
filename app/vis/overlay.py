# app/vis/overlay.py
# -------------------------------------------------------
# 🎨 Overlay – שלד אלגנטי:
#   • נקודות עגולות גדולות: שמאל = תכלת, ימין = כתום
#   • חיבורים קצרים ודקים בצבע אפור-בהיר/לבן
#   • כפות ידיים – כל אצבע בצבע אחר
#   • HUD קטן קבוע עם View / Confidence / Quality (+ אופציה: מדדי ראש)
#   • קו כתפיים + קו אגן + קו מחבר ביניהם
#   • קווי ראש/צוואר בסיסיים: ציר ראש (אוזניים↔אף), נק׳ עיניים/אוזניים, צוואר (מרכז כתפיים→ראש)
# API:
#   draw_overlay(frame, results_pose, results_hands, hud=None)
#      hud = {
#          "view": str, "conf": float, "qs": float,
#          # אופציונלי למדדי ראש:
#          "head_yaw_deg": float, "head_pitch_deg": float, "head_roll_deg": float,
#          "head_confidence": float, "head_ok": float|int|bool,
#      }
# -------------------------------------------------------

from __future__ import annotations
from typing import Optional, Dict, Any, Iterable, Tuple
import cv2
import math

# Colors (BGR)
LEFT   = (255, 200, 120)   # תכלת-חם
RIGHT  = (60, 180, 255)    # כתום
LINK   = (230, 230, 230)   # אפור-בהיר/לבן
MID    = (0, 255, 255)     # צהוב לקווים המרכזיים
HEAD   = (255, 255, 0)     # ראש – צהוב בהיר
NECK   = (255, 220, 120)   # צוואר – טון חם בהיר
EYES   = (200, 255, 255)   # עיניים – טורקיז בהיר
EARS   = (255, 210, 180)   # אוזניים – כתמתם רך
NOSE   = (200, 255, 120)   # אף – ירקרק עדין

# Fingers
C_THUMB  = (180, 60, 200)
C_INDEX  = (60, 200, 100)
C_MIDDLE = (200, 200, 60)
C_RING   = (0, 170, 255)
C_PINKY  = (255, 80, 240)

DOT_R = 7       # רדיוס נקודה
LINK_T = 3      # עובי חיבור קצר
MID_T = 3       # עובי קו אמצע
HEAD_T = 2      # עובי קווי ראש
NECK_T = 3      # עובי צוואר

# Pose indices (MediaPipe Pose 0.x – 33 נק׳)
# (מיפוי שכיח: https://google.github.io/mediapipe/solutions/pose)
class P:
    NOSE=0
    L_EYE_IN=1; L_EYE=2; L_EYE_OUT=3
    R_EYE_IN=4; R_EYE=5; R_EYE_OUT=6
    L_EAR=7; R_EAR=8
    L_SH=11; R_SH=12
    L_EL=13; R_EL=14
    L_WR=15; R_WR=16
    L_HIP=23; R_HIP=24
    L_KNEE=25; R_KNEE=26
    L_ANK=27; R_ANK=28
    L_HEEL=29; R_HEEL=30
    L_TOE=31; R_TOE=32

LEFT_POINTS  = [P.L_SH, P.L_EL, P.L_WR, P.L_HIP, P.L_KNEE, P.L_ANK, P.L_HEEL, P.L_TOE]
RIGHT_POINTS = [P.R_SH, P.R_EL, P.R_WR, P.R_HIP, P.R_KNEE, P.R_ANK, P.R_HEEL, P.R_TOE]

LEFT_LINKS  = [(P.L_SH,P.L_EL),(P.L_EL,P.L_WR),(P.L_HIP,P.L_KNEE),(P.L_KNEE,P.L_ANK),(P.L_HEEL,P.L_TOE)]
RIGHT_LINKS = [(P.R_SH,P.R_EL),(P.R_EL,P.R_WR),(P.R_HIP,P.R_KNEE),(P.R_KNEE,P.R_ANK),(P.R_HEEL,P.R_TOE)]

# ידיים – אצבעות
F_THUMB  = [0,1,2,3,4]
F_INDEX  = [0,5,6,7,8]
F_MIDDLE = [0,9,10,11,12]
F_RING   = [0,13,14,15,16]
F_PINKY  = [0,17,18,19,20]

# ---------- כלי עזר ----------
def _xy(frame, lm, idx) -> Tuple[int,int,float]:
    h,w=frame.shape[:2]
    p=lm[idx]
    return int(p.x*w), int(p.y*h), float(getattr(p,"visibility",1.0))

def _dot(frame, x, y, color, r: int = DOT_R):
    cv2.circle(frame, (x,y), r, color, -1, cv2.LINE_AA)

def _short_link(frame, x1, y1, x2, y2, color, t: int = LINK_T):
    cx = int((x1+x2)/2); cy = int((y1+y2)/2)
    cv2.line(frame, (x1,y1), (cx,cy), color, t, cv2.LINE_AA)
    cv2.line(frame, (cx,cy), (x2,y2), color, t, cv2.LINE_AA)

def _safe_mid(a: Tuple[int,int], b: Tuple[int,int]) -> Tuple[int,int]:
    return ( (a[0]+b[0])//2, (a[1]+b[1])//2 )

def _fmt(v: Any, decimals=1, fallback="–") -> str:
    try:
        if v is None: return fallback
        return f"{float(v):.{decimals}f}"
    except Exception:
        return fallback

# ---------- ציור שלד צד שמאל/ימין ----------
def _draw_side(frame, lm, points: Iterable[int], links: Iterable[Tuple[int,int]], color):
    for i in points:
        x,y,_ = _xy(frame,lm,i)
        _dot(frame,x,y,color)
    for a,b in links:
        x1,y1,_=_xy(frame,lm,a); x2,y2,_=_xy(frame,lm,b)
        _short_link(frame, x1,y1,x2,y2, LINK)

# ---------- קווי אמצע (כתפיים/אגן) ----------
def _midline(frame, lm):
    try:
        # קו כתפיים
        x1,y1,_=_xy(frame,lm,P.L_SH); x2,y2,_=_xy(frame,lm,P.R_SH)
        cv2.line(frame,(x1,y1),(x2,y2),MID,MID_T,cv2.LINE_AA)
        # קו אגן
        x3,y3,_=_xy(frame,lm,P.L_HIP); x4,y4,_=_xy(frame,lm,P.R_HIP)
        cv2.line(frame,(x3,y3),(x4,y4),MID,MID_T,cv2.LINE_AA)
        # חיבור בין קו כתפיים לקו אגן (מרכזים)
        xc,yc=_safe_mid((x1,y1),(x2,y2))
        xh,yh=_safe_mid((x3,y3),(x4,y4))
        cv2.line(frame,(xc,yc),(xh,yh),MID,MID_T,cv2.LINE_AA)
        _dot(frame,xc,yc,MID, r=5); _dot(frame,xh,yh,MID, r=5)
    except Exception:
        pass

# ---------- ראש / צוואר ----------
def _head_overlay(frame, lm):
    """
    מצייר ציר ראש בסיסי:
    • נק׳: עיניים/אוזניים/אף
    • ציר אוזניים↔אף (קו כיוון), וצוואר מהכתפיים לראש
    """
    try:
        # נק׳ רלוונטיות
        xLeye,yLeye,_=_xy(frame,lm,P.L_EYE)
        xReye,yReye,_=_xy(frame,lm,P.R_EYE)
        xLear,yLear,_=_xy(frame,lm,P.L_EAR)
        xRear,yRear,_=_xy(frame,lm,P.R_EAR)
        xN,yN,_=_xy(frame,lm,P.NOSE)
        xLsh,yLsh,_=_xy(frame,lm,P.L_SH)
        xRsh,yRsh,_=_xy(frame,lm,P.R_SH)

        # ציור נקודות
        _dot(frame, xLeye, yLeye, EYES, r=5)
        _dot(frame, xReye, yReye, EYES, r=5)
        _dot(frame, xLear, yLear, EARS, r=5)
        _dot(frame, xRear, yRear, EARS, r=5)
        _dot(frame, xN, yN, NOSE, r=6)

        # צוואר: מרכז כתפיים → מרכז ראש (אמצע עיניים)
        cx_sh, cy_sh = _safe_mid((xLsh,yLsh),(xRsh,yRsh))
        cx_eye, cy_eye = _safe_mid((xLeye,yLeye),(xReye,yReye))
        cv2.line(frame, (cx_sh,cy_sh), (cx_eye,cy_eye), NECK, NECK_T, cv2.LINE_AA)

        # ציר ראש: מרכז אוזניים → אף
        cx_ear, cy_ear = _safe_mid((xLear,yLear),(xRear,yRear))
        cv2.line(frame, (cx_ear, cy_ear), (xN, yN), HEAD, HEAD_T, cv2.LINE_AA)
        _dot(frame, cx_ear, cy_ear, HEAD, r=4)
    except Exception:
        pass

# ---------- ידיים ----------
def _hands(frame, results_hands):
    try:
        for hlm in results_hands.multi_hand_landmarks:
            l = hlm.landmark
            for chain, col in [(F_THUMB,C_THUMB),(F_INDEX,C_INDEX),(F_MIDDLE,C_MIDDLE),(F_RING,C_RING),(F_PINKY,C_PINKY)]:
                for i in range(len(chain)-1):
                    x1,y1,_=_xy(frame,l,chain[i]); _dot(frame,x1,y1,col, r=5)
                    x2,y2,_=_xy(frame,l,chain[i+1]); _short_link(frame,x1,y1,x2,y2,LINK, t=2)
                xN,yN,_=_xy(frame,l,chain[-1]); _dot(frame,xN,yN, col, r=6)
    except Exception:
        pass

# ---------- HUD ----------
def _hud(frame, hud: Optional[Dict[str,Any]]):
    if not hud: return
    # פרמטרים
    conf = hud.get("conf", None)
    qs   = hud.get("qs", None)

    # צבע קצה לפי confidence אם קיים
    def _edge_color(c):
        try:
            if c is None: return (200,200,200)
            c = float(c)
            if c >= 0.8: return (80,200,120)   # ירקרק
            if c >= 0.5: return (80,180,255)   # כתום-תכלת
            return (60,60,220)                 # אדום-קר
        except Exception:
            return (200,200,200)

    # קנבס חצי שקוף
    overlay = frame.copy()
    pad = 10
    # נבנה רשימת שורות – כולל מדדי ראש אם קיימים
    head_lines = []
    if "head_yaw_deg" in hud or "head_pitch_deg" in hud or "head_roll_deg" in hud:
        head_lines.append(f"Head: yaw={_fmt(hud.get('head_yaw_deg'))}°, pitch={_fmt(hud.get('head_pitch_deg'))}°, roll={_fmt(hud.get('head_roll_deg'))}°")
        if "head_confidence" in hud:
            ok = hud.get("head_ok", None)
            ok_s = "OK" if (bool(ok) if isinstance(ok,(int,float,bool)) else False) else "–"
            head_lines.append(f"H-Conf: {_fmt(hud.get('head_confidence'),3)} | {ok_s}")

    lines = [
        f"View: {hud.get('view','–')}",
        f"Conf: {_fmt(conf,3)}",
        f"QScore: {_fmt(qs,0)}",
    ] + head_lines

    # גודל תיבה דינמי
    x0,y0 = 12, 12
    width = 0
    for t in lines:
        width = max(width, cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0][0])
    width += 20
    height = 18 + len(lines)*22
    x1,y1 = x0+width+pad, y0+height+pad

    # רקע שקוף + מסגרת בצבע קונפידנס
    cv2.rectangle(overlay,(x0,y0),(x1,y1),(0,0,0),-1)
    cv2.addWeighted(overlay,0.33,frame,0.67,0,frame)
    cv2.rectangle(frame,(x0,y0),(x1,y1),_edge_color(conf),1,cv2.LINE_AA)

    # טקסט
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (x0+10, y0+22+i*22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1, cv2.LINE_AA)

# ---------- API ----------
def draw_overlay(frame, results_pose: Optional[object], results_hands: Optional[object], hud: Optional[Dict[str,Any]] = None):
    """
    מצייר שלד/ידיים/ראש + HUD. מחוסן משגיאות — לא מפיל את הפריים.
    """
    try:
        if results_pose and getattr(results_pose,"pose_landmarks",None):
            lm = results_pose.pose_landmarks.landmark
            _draw_side(frame, lm, LEFT_POINTS, LEFT_LINKS, LEFT)
            _draw_side(frame, lm, RIGHT_POINTS, RIGHT_LINKS, RIGHT)
            _midline(frame, lm)
            _head_overlay(frame, lm)
        if results_hands and getattr(results_hands,"multi_hand_landmarks",None):
            _hands(frame, results_hands)
        _hud(frame, hud)
    except Exception:
        pass
    return frame
