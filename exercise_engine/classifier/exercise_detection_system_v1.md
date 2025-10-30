להדבקה כ־`docs/specs/exercise_detection_system_v1.md`

---

# 🤖 מערכת זיהוי תרגילים — מפרט מלא (v1)

מסמך זה מתאר מקצה־לקצה את זרימת הזיהוי, הסינון, הבחירה והייצוב של תרגילים (עם דגש על משפחת Squat), את מבנה קבצי ה־YAML, את ספי המסווג, את ה־fallbackים, את בדיקות האינטגרציה/ביצועים, ואת טלמטריית הניטור.

---

## 1) ארכיטקטורת־על

```
Camera (Video)
   │
   ▼
Pose Estimation (keypoints)     Object Detection (equipment)
        │                                 │
        └─────────────┬───────────────────┘
                      ▼
           Normalizer + Aliases
                      ▼
             Canonical Payload
                      ▼
            Exercise Classifier
        (scoring by match_hints)
                      ▼
               Hysteresis/Freeze
                      ▼
          PickResult (exercise_id,…)
                      ▼
       Exercise YAML (scoring engine)
                      ▼
         Feedback / Report / UI
```

---

## 2) Canonical Payload (דוגמא)

```json
{
  "pose.available": true,
  "objdet.bar_present": false,
  "objdet.dumbbell_present": true,
  "objdet.kettlebell_present": false,
  "knee_left_deg": 88,
  "knee_right_deg": 91,
  "spine_flexion_deg": 7,
  "spine_curvature_side_deg": 3,
  "features.stance_width_ratio": 1.05,
  "toe_angle_left_deg": 12,
  "toe_angle_right_deg": 15,
  "heel_lift_left": false,
  "heel_lift_right": false,
  "rep.timing_s": 2.1,
  "view.mode": "front"
}
```

> כל השמות קנוניים ונקבעים ב־`aliases.yaml`. מנועי הניתוח משתמשים **רק** במפתחות הקנוניים.

---

## 3) אינפרנס ציוד (Equipment Inference)

כלל החלטה (עדיפות גבוהה → נמוכה):

1. `objdet.bar_present = True` → `"barbell"`
2. אחרת `objdet.dumbbell_present = True` → `"dumbbell"`
3. אחרת `objdet.kettlebell_present = True` → `"kettlebell"`
4. אחרת → `"none"`

> במקרה קצה שבו מזוהים כמה סוגי ציוד בו־זמנית: עדיפות ברירת־מחדל — barbell > dumbbell > kettlebell > none.

---

## 4) סינון ספריית התרגילים

* מסירים קבצים לא־בר־בחירה:

  * `meta.selectable == false`
  * נתיב מכיל `_base`
  * `id` מסתיים ב־`.base`
* מסננים לפי ציוד:

  * `meta.equipment` חייב להיות **באנגלית** מתוך: `"none" | "dumbbell" | "barbell" | "kettlebell"`
  * נשארים רק תרגילים שהציוד שלהם תואם ל־Equipment Inference הנוכחי.
  * אם לאחר הסינון לא נשארו מועמדים → משתמשים בכל ה־selectable (Fail-open רך).

---

## 5) ניקוד התאמה ראשוני (Classifier scoring)

התבססות על `match_hints` שבקובץ התרגיל:

```yaml
match_hints:
  must_have:     [pose.available, objdet.bar_present]
  must_not_have: [objdet.dumbbell_present, objdet.kettlebell_present]
  any_of:        []
  pose_view:     ["front", "front_left", "front_right"]
  ranges:
    # דוגמה אופציונלית
    # features.stance_width_ratio: [0.6, 1.6]
```

כללים:

* **פסילה מיידית** אם אחד מ־`must_not_have` הוא truthy.
* **must_have**: כולם **truthy** כדי לקבל נקודה.
* **any_of**: לפחות אחד **truthy** כדי לקבל נקודה.
* **ranges**: עבור כל key אם הערך בתוך `[lo,hi]` → נקודה.
* **pose_view**: אם `view.mode` תואם לרשימה → נקודה.
* נרמול לניקוד `[0..1]` והכפלה ב־`weight` (אם מוגדר ברמזים).

> **truthy** = בוליאן True, מספר שאינו 0, מחרוזת לא ריקה; ערך חסר/None/False/0 נחשב False.

---

## 6) דירוג ובחירה

* ממיינים מועמדים לפי `score` (גדול→קטן).
* אם `top1.score < S_MIN_ACCEPT`:

  * אם יש תרגיל קודם יציב → נשארים עליו.
  * אחרת → נופלים ל־`fallback_bodyweight_id` (לרוב `squat.bodyweight`).
* אחרת → עוברים ל־Hysteresis (סעיף 7) להחלטה סופית.

---

## 7) ייצוב (Hysteresis) + Freeze + Strong Override

הגדרות (ברירת־מחדל; ניתנות לקונפיגורציה):

* `S_MIN_ACCEPT = 0.40`
* `H_MARGIN_KEEP = 0.10`  (margin קטן → נשארים על הקודם)
* `H_MARGIN_SWITCH = 0.20` (margin גדול → מחליפים)
* `STRONG_SWITCH_MARGIN = 0.35` (פער גדול מאוד)
* `STRONG_SWITCH_BYPASS_FREEZE = True/False`
* `FREEZE_DURING_REP = True` (אין החלפות באמצע חזרה)
* `CONF_EMA_ALPHA = 0.25` (EMA לציון בטחון)
* `LOW_CONF_EPS = 0.30` + `LOW_CONF_T_SEC = 1.0` (דגל “בטחון נמוך לאורך זמן”)

חישוב:

* `margin = top1.score - top2.score`
* אם `freeze_active == True`:

  * לא מחליפים, **אלא אם** `margin ≥ STRONG_SWITCH_MARGIN` **ול**־`STRONG_SWITCH_BYPASS_FREEZE==True`
* אם `margin < H_MARGIN_KEEP` → שומרים הקודם.
* אם `margin ≥ H_MARGIN_SWITCH` → מחליפים למוביל.
* ערכים בין הספים → “אזור ביניים”, לרוב שומרים הקודם עד התייצבות.
* `confidence_ema = EMA(confidence_ema_prev, top1.score, alpha=CONF_EMA_ALPHA)`

---

## 8) PickResult (פלט המסווג)

```json
{
  "status": "ok",
  "exercise_id": "squat.barbell",
  "family": null,                // אופציונלי
  "equipment_inferred": "barbell",
  "confidence": 0.86,            // EMA
  "reason": "best_match_rules",  // או kept_prev / strong_override / fallback_bodyweight
  "stability": {
    "kept_previous": false,
    "margin": 0.27,
    "freeze_active": false,
    "last_switch_ms": 1730000000000,
    "strong_override": false
  },
  "candidates": [
    {"id": "squat.barbell",   "score": 0.86},
    {"id": "squat.dumbbell",  "score": 0.44},
    {"id": "squat.bodyweight.md","score": 0.22}
  ],
  "diagnostics": []
}
```

---

## 9) טעינת YAML הנבחר (Scoring Engine)

לאחר בחירת `exercise_id`, המנוע טוען את קובץ ה־YAML הרלוונטי ומחשב ציון טכני לפי הקריטריונים, המשקלים ו־Safety Caps של התרגיל:

* בטיחות: משקל גבוה לעגילת גב, ולגוס, עיקום צדדי.
* טכניקה: עומק עד 90° ציון מלא, עקבים נעוצים, טמפו, רוחב עמידה, כיוון כפות רגליים, יישור ראש־עמוד שדרה.
* **אין Grade** — ציון מספרי בלבד; בטיחות יכולה להגביל ציון סופי (caps), אך לא “למחוק” לגמרי את הערך למבצע טוב.

---

## 10) תבניות YAML — דרישות אחידות

* `meta.selectable: true`
* `meta.equipment`: `"none" | "dumbbell" | "barbell" | "kettlebell"`
* `match_hints.must_have`: מפתחות שצריכים להיות **truthy**.
* `match_hints.must_not_have`: מפתחות שאם הם **truthy** → פסילה.
* `match_hints.any_of`: לפחות אחד **truthy** (רשות).
* `match_hints.pose_view`: זוויות צילום מותרות, לדוגמה `["front","front_left","front_right"]`.
* `match_hints.ranges`: מפתחות שמבוקרים בטווח `[lo,hi]` (רשות).

דוגמה קצרה (Barbell Squat):

```yaml
meta:
  selectable: true
  equipment: "barbell"

match_hints:
  must_have:     [pose.available, objdet.bar_present]
  must_not_have: [objdet.dumbbell_present, objdet.kettlebell_present]
  pose_view:     ["front","front_left","front_right"]
```

---

## 11) Fallbackים חכמים (ללא זיהוי ציוד)

עבור משפחות עיקריות כדאי להגדיר fallback מבוסס קינמטיקה:

* **“Barbell-hold pattern”** לסקוואט עם מוט:

  * `elbow_left_deg < ~110°` **AND** `elbow_right_deg < ~110°`
  * `shoulder_left_deg > ~35°` **OR** `shoulder_right_deg > ~35°`
* אם תבנית זו מתקיימת לאורך חלון קצר, אפשר לתת עדיפות ל־barbell גם אם `objdet.bar_present=False` זמנית.

> ספי fallback יוגדרו ב־`settings` או בקובץ ספים מרוכז (שישלח בהמשך).

---

## 12) טלמטריה (ניטור)

* `switch_count` — כמה פעמים הוחלף exercise_id.
* `kept_prev_count` — כמה פעמים נשמר הקודם.
* `fallback_count` — כמה פעמים נפלנו ל־fallback.
* `stable_switch_time_ms_avg` — זמן ממוצע מזיהוי שינוי עד בחירה יציבה.
* `low_confidence_events` — מופעי EMA נמוך לאורך זמן.

הצגה ב־log/console/metrics לפי סביבת הריצה.

---

## 13) בדיקות — מה בודקים (pytest)

בדיקות ניתבות:

* `bar_present=True` → בחירת `"squat.barbell"`.
* `dumbbell_present=True` → `"squat.dumbbell"`.
* ללא ציוד → `"squat.bodyweight"`.
* `bar=True & dumbbell=True` → barbell מנצח.
* `must_not_have=True` → פסילה של התרגיל המתאים.
* `pose_view` לא תואם → ניקוד נמוך.

בדיקות ייצוב:

* `margin < H_MARGIN_KEEP` → נשאר תרגיל קודם.
* `margin ≥ H_MARGIN_SWITCH` → עוברים לתרגיל החדש.
* `freeze_active=True` → אין החלפה (אלא אם `STRONG_SWITCH_MARGIN` וב־`BYPASS_FREEZE=True`).

בדיקות ביצועים:

* זמן ריצה ממוצע ל־`pick()` קטן מהיעד (למשל < 2ms בקריאה, תלוי מחשב).

---

## 14) מפת דרכים קצרה

* הוספת `ranges` קינמטיים לזיהוי עדין בין תרגילים דומים עם אותו ציוד.
* הרחבת fallbackים לפי תבניות תנועה.
* ריכוז ספי מסווג בקובץ settings יחיד.
* הוספת בדיקות אינטגרציה “End-to-End” עם payloadים מוקלטים.
* הרחבת הטלמטריה לתצוגה ב־UI אדמין.

---

## 15) מילון מונחים קצר

* **Canonical Payload**: מילון אחיד של מדדים אחרי `aliases.yaml`.
* **match_hints**: רמזי התאמה בקובץ תרגיל לזיהוי ראשוני (לא ניקוד טכני).
* **Hysteresis**: מנגנון ייצוב כדי למנוע ריצוד בזיהוי.
* **Freeze**: “חלון חזרה” שבו אסור להחליף תרגיל.
* **EMA**: החלקת בטחון אקספוננציאלית.
* **Safety Caps**: תקרה על הציון הסופי אם קריטריון בטיחותי חמור.

---

## 16) TL;DR (תקציר פעולה)

1. איחוד שמות → Canonical Payload
2. אינפרנס ציוד → `"barbell"/"dumbbell"/"kettlebell"/"none"`
3. סינון ספרייה לפי `meta.equipment`
4. ניקוד התאמה לפי `match_hints`
5. ספים + Hysteresis + Freeze → בחירה יציבה
6. טעינת YAML תרגיל → חישוב ציון טכני + פידבק
7. טלמטריה + בדיקות + כוונון ספים

---

> זהו. זה “הכול־כול־הכול” למסמך ה־MD.
> תרצה שאמייר את זה בקוד (עדכון פונקציות `_infer_equipment` ו־`_score_candidate` + דוגמאות בדיקות), או קודם נעבור יחד על קובץ הספים שלך ונחבר את הערכים ל־`SETTINGS.classifier`?
