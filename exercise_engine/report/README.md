
# 📘 מערכת הדו"חות (Reports) — מפרט מלא

מסמך זה מגדיר את **פורמט הדו"ח**, **מה מוצג ב־UI**, **איך נבנה הציון**, **כיסוי/זמינות**, **חזרות/סטים**, **סיכום מצלמה**, **טיפים**, ו־**אינדיקציות חכמות (Report Health)** לזיהוי בעיות בזמן אמת.
המסמך משמש גם את לוח הניהול (Server Admin) וגם בסיס לאפליקציית Flutter (בעתיד).

> שים לב: לפי ההנחיה שלך — **אין Grade (A/B/C/D)** במערכת.

---

## 1) מטרות

* להפיק דו"ח אחיד, קריא ומקצועי לכל תרגיל/סט/סשן.
* לאפשר תצוגת **תקציר מהיר** + **דו"ח מפורט**.
* לשמור נתונים לשיחזור מלא: מדדים קנוניים, חזרות, סטים, זמינות.
* להתריע על בעיות נתונים/תצורה באמצעות **אינדיקציות חכמות**.

---

## 2) מבנה נתונים כללי (JSON)

```jsonc
{
  "meta": {
    "generated_at": "2025-10-21T10:18:12.341Z",
    "payload_version": "1.0",
    "library_version": "d8a1f3b29c1a"
  },
  "exercise": {
    "id": "squat.bodyweight",
    "family": "squat",
    "equipment": "none",
    "display_name": "Squat (Bodyweight)"
  },
  "scoring": {
    "score": 0.86,                 // 0..1
    "score_pct": 86,               // עיגול למספר שלם (0..100)
    "quality": "full",             // full / partial / poor
    "unscored_reason": null,
    "applied_caps": [],            // רשימת Caps (אם יוגדרו בעתיד ב-YAML)
    "criteria": [
      {"id":"posture","available":true,"score":0.80,"score_pct":80,"reason":null},
      {"id":"depth","available":true,"score":0.90,"score_pct":90,"reason":null},
      {"id":"tempo","available":true,"score":0.88,"score_pct":88,"reason":null},
      {"id":"stance_width","available":true,"score":0.92,"score_pct":92,"reason":null},
      {"id":"knee_valgus","available":true,"score":0.75,"score_pct":75,"reason":null}
    ]
  },
  "coverage": {
    "available_ratio": 1.0,
    "available_pct": 100,
    "available_count": 5,
    "total_criteria": 5,
    "missing_reasons_top": [],
    "missing_critical": []
  },
  "camera": {
    "visibility_risk": false,
    "severity": "LOW",
    "message": "המדידה תקינה",
    "stats": {}
  },
  "sets": [
    {
      "index": 1,
      "reps": 10,
      "avg_tempo_s": 1.72,
      "avg_rom_deg": 64.8,
      "avg_score": 0.85,
      "min_score": 0.78,
      "max_score": 0.91,
      "duration_s": 23.0
    }
  ],
  "reps": [
    {"rep_id":1,"timing_s":1.6,"ecc_s":0.8,"con_s":0.8,"rom_deg":65.1,"score":0.86},
    {"rep_id":2,"timing_s":1.7,"rom_deg":63.9,"score":0.83}
  ],
  "hints": [
    "הישאר עם חזה פתוח בירידה לשיפור יציבה.",
    "יישור ברך-כף רגל גבולי – שים לב לולגוס."
  ],
  "diagnostics": [
    // רשימת אירועים אחרונים (info/warn/error)
  ],
  "canonical": {
    // עותק שטוח של כל המדדים הקנוניים וה-rep.* בעת בניית הדו"ח
  },
  "rep": {
    // ייצוג היררכי של rep.* (לפי מזהה חזרה/שדות)
  },
  "report_health": {
    "status": "OK",                // OK / WARN / FAIL
    "issues": []                   // רשימת בעיות מפורטות (ראה סעיף 7)
  }
}
```

---

## 3) תצוגת UI (לוח ניהול) — תקציר + מפורט

### 3.1 תצוגת תקציר (Summary)

* **עגול מרכזי (Donut/Circle)** עם `score_pct` (למשל: **86%**).
* **פס אופקי צבעוני** מתחת לעיגול:

  * **אדום**: 0–60%
  * **כתום**: 60–75%
  * **ירוק**: 75–100%
* **Tooltip פירוק לקריטריונים**: hover על העיגול/אייקון “i” → טבלה קטנה:

  * posture 80%, depth 90%, tempo 88%, stance_width 92%, knee_valgus 75%
* **כרטיסי מידע** לימין/שמאל (Grid):

  * Coverage (available_pct, missing_critical)
  * Camera (visibility_risk + message)
  * Hints (2–3 ראשונים)
  * אינדיקציות (Report Health) בקו רמזור: OK/WARN/FAIL

### 3.2 תצוגה מפורטת (Deep Report)

* **Tabs**: Overview | Criteria | Sets | Reps | Camera | Diagnostics
* **Criteria**:

  * לכל קריטריון: שם, score_pct, סרגל מיני-חום (heat bar), הסבר קצר (מ־phrases/tooltip).
* **Sets**:

  * טבלה: index | reps | avg_tempo_s | avg_rom_deg | avg_score | min/max | duration_s
  * Mini sparkline של score לאורך הסט.
* **Reps**:

  * טבלה: rep_id | timing_s | ecc_s | con_s | rom_deg | score
  * אפשרות להרחיב Rep → לראות פיצול ציונים פר־קריטריון באותה חזרה (אם רלוונטי).
* **Camera**:

  * סטטוס, הודעה, וסטטיסטיקות (אם זמינות).
* **Diagnostics**:

  * רשימת אירועים אחרונים (log-tail) עם חיתוך לפי severity/type.

---

## 4) חישוב ציון (Scoring) — עקרונות

* הציונים מחושבים ע"פ **YAML לכל תרגיל** (weights/thresholds/criteria).
* `score` הכללי הוא שקלול משוקלל של הקריטריונים הזמינים בלבד.
* `quality`:

  * `full` — ≥3 קריטריונים בשקלול
  * `partial` — 1–2 קריטריונים
  * `poor` — 0 קריטריונים (או `unscored_reason` לא ריק)
* **אין Grade**. לא מוצג ולא נשמר.

---

## 5) כיסוי/זמינות (Coverage)

מטרת ה־coverage היא להבהיר ל־QA/מפתח/מאמן כמה קריטריונים באמת תרמו לציון:

* `available_pct` — אינדיקטור איכות נתונים (100% = מעולה).
* `missing_critical` — רשימת קריטריונים קריטיים שלא זמינים (תראה ב־Summary כ־Badge אדום/צהוב).
* `missing_reasons_top` — שלוש הסיבות הנפוצות ביותר לחוסר זמינות (לדוגמה: `missing_signal`, `low_confidence`).

---

## 6) סטים וחזרות (Aggregations)

### 6.1 Sets

עבור כל סט נאספים:

* `reps` (מספר חזרות בסט)
* `avg_tempo_s`, `avg_rom_deg`, `avg_score` (ממוצעים)
* `min_score`, `max_score`
* `duration_s` (אם זמין)

> חישורים מתבצעים מהשדות ב־`reps`.

### 6.2 Reps

לכל חזרה נשמרים:

* `rep_id`
* `timing_s`, `ecc_s`, `con_s`, `rom_deg` (אם זמינים)
* `score` (ציון כולל לחזרה; אם נדרש בעתיד — אפשר להוסיף per-criterion per-rep)

---

## 7) אינדיקציות חכמות (Report Health)

המערכת מצרפת לכל דו"ח בלוק `"report_health"` עם מצב כולל ורשימת בעיות.
אלו כללי “סף” מומלצים (ניתנים לכיול):

| קוד                  | תנאי                                   | רמת חומרה | הודעה                                                |
| -------------------- | -------------------------------------- | --------- | ---------------------------------------------------- |
| `NO_EXERCISE`        | `exercise == null`                     | `FAIL`    | לא זוהה תרגיל. בדוק classifier/aliases.              |
| `UNSCORED`           | `scoring.score == null`                | `WARN`    | לא חושב ציון. חסרים קריטריונים/Low-Confidence/Grace. |
| `LOW_COVERAGE`       | `coverage.available_pct < 60`          | `WARN`    | זמינות נמוכה (X%/Y קריטריונים). בדוק מצלמה/זיהוי.    |
| `MISSING_CRITICAL`   | `coverage.missing_critical.length > 0` | `FAIL`    | חסרים קריטריונים קריטיים: [...].                     |
| `CAMERA_RISK`        | `camera.visibility_risk == true`       | `WARN`    | תנאי צילום גבוליים — ייתכנו סטיות במדידה.            |
| `ALIAS_CONFLICTS`    | אירוע `alias_conflict` ב־diagnostics   | `WARN`    | התנגשות ערכים בין אליאסים (ראה diagnostics).         |
| `LOW_QUALITY`        | `scoring.quality == "poor"`            | `WARN`    | איכות נמוכה — חסר בסיס לשקלול אמין.                  |
| `SET_COUNTER_ERROR`  | אירוע `set_counter_error`              | `WARN`    | ספירת סטים כשלה חלקית — ודא אותות set.begin/end.     |
| `REP_ENGINE_ERROR`   | אירוע `rep_segmenter_error`            | `WARN`    | מנוע חזרות דיווח שגיאה — ראה diagnostics.            |
| `THRESHOLD_MISMATCH` | אירוע סף/threshold חריג                | `WARN`    | ספי YAML חריגים עבור הקריטריון.                      |

**סטטוס כולל**:

* אם יש לפחות `FAIL` → `status = "FAIL"`
* אחרת אם יש לפחות `WARN` → `status = "WARN"`
* אחרת → `status = "OK"`

> ההמלצה: להציג Badge פינתית (OK ירוק / WARN כתום / FAIL אדום) בכל מסך דו"ח.

---

## 8) תצוגת UI — פרטים ויזואליים

* **Score Circle**: עיגול עבה עם מספר גדול (86%). מתחת, תיאור קצר (quality, למשל “Full data”).
* **Color Bar**: פס עם חלוקה לשלושה אזורים (אדום/כתום/ירוק). אינדיקטור אנכי דק במיקום `score_pct`.
* **Tooltip Breakdown**:

  * טבלה קטנה: קריטריון | % | אינדיקטור צבע נקודתי (לפי טווח צבעי הפס).
  * אם `available=false` → מוצג “N/A” ואייקון הסבר עם `reason`.
* **Coverage Card**: Gauge/Indicator עם % ו־badge ל־missing_critical.
* **Camera Card**: אייקון מצלמה + Severity + הודעה קצרה. אם יש סיכון — Badge כתום.
* **Hints Card**: רשימה קצרה (2–3). קישור “הצג הכל” פותח דיאלוג עם כל הטיפים.
* **Tabs מפורט**: טבלאות עם מיון/חיפוש; הדגשת חריגים בצהוב/אדום.

---

## 9) תאימות ל־YAML ו־Aliases

* **הכול** ניזון מ־`aliases.yaml` + קבצי תרגיל ב־`exercise_library/exercises/`.
* הוספת קריטריון/סף/משקל ב־YAML תופיע אוטומטית בדו"ח (אין צורך לגעת בקוד).
* אם יש **קלידים לא מוכרים** או **קונפליקט בין אליאסים** — יופיעו ב־`diagnostics` + ב־Report Health.

---

## 10) גרסאות, אחסון, ו־API

* `payload_version`: תעלה כשיש שינוי שבירת תאימות בפורמט.
* `library_version`: hash קצר מהטוען (loader) — מאפשר Cache/Invalidate.
* מומלץ לשמור כל דו"ח כ־JSON (קובץ/DB) עם מזהה ייחודי (UUID + timestamp).
* **REST מוצע**:

  * `GET /api/reports/latest` → הדו"ח האחרון (למכשיר/משתמש)
  * `GET /api/reports/:id` → דו"ח לפי מזהה
  * `GET /api/reports?exercise_id=...&from=...&to=...` → פילטרים

---

## 11) בדיקות ו־QA (צ'ק־ליסט)

* ✅ דו"ח עם כיסוי מלא (100%) + ציון גבוה → מציג ירוק, ללא אינדיקציות.
* ✅ דו"ח ללא תרגיל (exercise=null) → FAIL.
* ✅ דו"ח עם `unscored_reason` → WARN “UNSCORED”.
* ✅ alias_conflict בלוג → WARN.
* ✅ מצלמה בסיכון → WARN “CAMERA_RISK”.
* ✅ חסרים critical → FAIL “MISSING_CRITICAL”.
* ✅ מעט קריטריונים זמינים (<60%) → WARN “LOW_COVERAGE”.

---

## 12) דוגמאות “בעייתיות” (לקלות debug)

### 12.1 לא זוהה תרגיל

```jsonc
"exercise": null,
"scoring": {"score": null, "unscored_reason": "no_exercise_selected"}
"report_health": {"status":"FAIL","issues":[{"code":"NO_EXERCISE","message":"לא זוהה תרגיל"}]}
```

### 12.2 זמינות נמוכה

```jsonc
"coverage": {"available_pct": 40, "missing_critical": ["depth"]},
"report_health": {"status":"FAIL","issues":[{"code":"MISSING_CRITICAL","message":"חסר depth"}]}
```

---

## 13) הרחבות עתידיות (אופציונלי)

* **Trendline**: מעקב ציון לאורך זמן (סשנים/שבועות).
* **Per-criterion per-rep**: הצגת ציוני קריטריונים לכל חזרה (אם יוגדר).
* **Export**: PDF/CSV ייצוא דו"ח.
* **Realtime Stream**: WebSocket לעדכון חי של העיגול/הפס/טבלאות.

---

# נספח A — כללי חישוב שקיפות (שדות/משמעות)

* `scoring.score_pct = round(scoring.score * 100)` (אם score קיים)
* `scoring.quality` נקבע לפי מספר הקריטריונים שנכנסו לשקלול בפועל.
* `coverage` מחשב זמינות לפי `availability` שהגיעה מה־validator.
* `reps` נגזרים מאירועי ה־Segmenter. אם חסרים `rep.*` → מופיע diagnostics.

---

# נספח B — אינטגרציית UI (מינימום לשלב ראשון)

* **צריך מה־API**: האובייקט הנ"ל בדיוק (fields/keys).
* **UI צבעים**:

  * אדום `#E53935`, כתום `#FB8C00`, ירוק `#43A047` (או פריסת צבעים שלך).
* **פונטים/Spacing**: כרטיסים עם כותרת, גוף, ו־footer קטן לטיימסטמפ/גירסה.

---

# נספח C — מפת מפתחות חשובה

* `meta.*` — גרסאות ותזמון
* `exercise.*` — זיהוי תרגיל
* `scoring.*` — ציון גלובלי + per-criterion
* `coverage.*` — זמינות
* `camera.*` — איכות צילום
* `sets[]` / `reps[]` — ביצוע בפועל
* `hints[]` — תובנות לשיפור
* `diagnostics[]` — אירועי מערכת
* `canonical` / `rep` — נתוני גולמי מקוננים לשחזור
* `report_health.*` — מצב ואזהרות

---

## סיכום

המסמך מגדיר **במדויק** איך לבנות, להציג, ולאמת דו"חות מערכת — עם **אינדיקציות חכמות** שמאותתות על כל בעיה אפשרית בנתונים/חישוב/תצורה.
ה־UI בשרת הניהול יכול להשתמש בנתונים “as-is”, והאפליקציה ב־Flutter תוכל לצרוך את אותו JSON ללא שינויים.

---
