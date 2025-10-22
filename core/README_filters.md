# 📑 README – System Filters (ProCoach Engine)

## 🔹 מבנה כללי
המנוע מקבל קלט (Pose + Hands), מחשב מדדים גולמיים ומעביר אותם דרך **שרשרת מסננים**:


בסוף מתקבל **Payload** מסונן + מטא-דאטה (confidence/view/fps וכו').

---

## 🔹 איפה שולטים במסננים?
קובץ מרכזי: `core/filters_config.py`

- **Gate / Confidence**
  - `CONF_THR` – סף מינימלי (ברירת מחדל 0.60).
- **EMA (Exponential Moving Average)**
  - `alpha_min`, `alpha_max`, `gamma`.
  - דינמי: conf נמוך → alpha קטן (רכה), conf גבוה → alpha גדול (חדה).
- **Outlier Rejector**
  - `angle_deg` – סף שינוי לזוויות (ברירת מחדל 25°).
  - `px_abs` – שינוי פיקסלים מוחלט (30px).
  - `px_by_shoulder` – שינוי יחסי (0.25 × רוחב כתפיים).
  - `ratio_abs` – שינוי ביחס (0.20).
- **Deadband (אזור מת)**
  - `angle_deg` – ±2°.
  - `px` – ±10px.
  - `ratio` – ±0.05.
- **JitterMeter**
  - `window_ms` – חלון חישוב סטיית תקן (ברירת מחדל 800ms).
- **LKGBuffer**
  - `max_age_ms` – כמה זמן להחזיק ערך אחרון תקין (ברירת מחדל 1000ms).
- **HysteresisBool**
  - `on_thr`, `off_thr` – ספי ON/OFF.
  - `min_hold_ms` – זמן מינימום לפני החלפה (מונע הבהובים).
- **Guards**
  - מסנני sanity: מונעים NaN/Inf, קלמפינג לטווחי זווית/יחס סבירים.
- **UI Rules**
  - `hide_below` – לא מציגים מתחת לסף זה.
  - `yellow_min` – צהוב ⚠️.
  - `green_min` – ירוק ✅.
- **Profiles**
  - `default`, `lenient`, `strict` – אוספים של ערכים מותאמים.
  - החלפה:  
    ```python
    from core.filters_config import CONFIG
    CONFIG.set_profile("strict")
    ```

---

## 🔹 קריאת הפלט (payload)
- `confidence` – ממוצע נראות הנקודות (0..1).
- `ui.conf_category` – hidden / yellow / green.
- `*_deg` – זוויות אחרי סינון.
- `*_jitter_std` – מדד רעידות.
- `meta.valid` – האם הערכים תקפים.
- `meta.age_ms` – גיל ערך LKG (אם שוחזר).

---

## 🔹 טבלת תפעול (Symptom → מה לשנות)

| Symptom 🐞                        | מה לשנות ⚙️                                        |
|----------------------------------|----------------------------------------------------|
| לא רואה ערכים (מוסתר)           | העלה `UI_RULES.hide_below` או שפר תאורה/זיהוי      |
| ערכים “תקועים”                   | הקטן `deadband.angle_deg` (למשל מ-2.0 ל-1.0)       |
| קפיצות חדות בין פריימים          | הקשח Outlier: הורד `outlier.angle_deg` ל-20°       |
| תגובה איטית מדי                  | הגדל `ema.alpha_max` או הורד `gamma`               |
| ON/OFF הבהובי (כף רגל/עקב)      | הגדל `hysteresis.min_hold_ms` ל-200–250ms          |
| נעלמים ערכים כש-conf צונח        | העלה `lkg.max_age_ms` (400–600ms)                  |
| jitter גבוה (רעידות)             | הארך `jitter.window_ms` (למשל 1000ms)             |

---

## 🔹 מגבלות שכדאי לזכור
- **תצוגה לא נכונה** → מדדי side מוצגים רק ב־Side view.  
- **אוקלוזיות (הסתרות)** → מורידות confidence → יותר “hidden”.  
- **FPS נמוך** → חישובי מהירות/תאוצה פחות יציבים.  
- **בגדים רחבים / תנאים לא אידיאליים** → עלולים לפגוע בדיוק.

אם רוצים לבדוק
להריץ בטרמינל

from core.filters_config import CONFIG
print(CONFIG.profile)

---

## 🔹 דוגמה לקוד
```python
from core.filters_config import CONFIG
from dataclasses import replace

# שימוש בפרופיל מוכן
CONFIG.set_profile("lenient")

# טוויק ידני (לדוגמה: Deadband צר יותר, EMA חד יותר)
p = CONFIG.profile
CONFIG.patch(
    deadband=replace(p.deadband, angle_deg=1.0),
    ema=replace(p.ema, alpha_max=0.75)
)
---