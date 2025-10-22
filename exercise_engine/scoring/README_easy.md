מושלם 👌
הנה **README מלא ומעודכן במיוחד למנוע הציונים** שלך — תואם למבנה הנוכחי של הפרויקט (`exercise_engine/scoring/calc_score_yaml.py`)
ומתועד באותו סגנון כמו ה־README של ה־Loader/Schema/Preflight.
אפשר פשוט להעתיק את זה ישירות לקובץ:
📄 `exercise_engine/scoring/README.md`

---

# ⚖️ מנוע הציונים (Scoring Engine)

מסמך זה מתאר את הלוגיקה, הזרימה, והחוזים של המנוע שמחשב את **ציוני התרגילים**
במערכת BodyPlus_XPro — קובץ:
`exercise_engine/scoring/calc_score_yaml.py`

---

## 🎯 מטרת המנוע

לאפשר חישוב **אובייקטיבי, כללי וגמיש** של ציוני תרגילים לפי הגדרות YAML בלבד,
ללא צורך לשנות קוד בכל פעם שנוסף או נערך תרגיל.

המנוע מתייחס לכל תרגיל כאל אובייקט נתונים (`ExerciseDef`) שמגיע מה־loader,
ומחשב ציונים לפי הספים והמשקלים שהוגדרו עבורו בקובץ ה־YAML.

---

## 🧩 מיקום במערכת

```mermaid
flowchart TD
    A[canonical metrics<br/>(normalized from aliases.yaml)] --> B[validator.evaluate_availability]
    B --> C[scoring.calc_score_yaml.score_criteria]
    C --> D[vote()]
    D --> E[report.report_builder.build_payload]
    E --> F[Admin UI / Feedback]
```

---

## 📦 קבצים מעורבים

| קובץ                       | תפקיד                                          |
| -------------------------- | ---------------------------------------------- |
| `calc_score_yaml.py`       | מנוע הציון עצמו — מחשב per-criterion ו־overall |
| `validator.py`             | בודק זמינות מדדים (`available=True/False`)     |
| `runtime/runtime.py`       | מפעיל את מנוע הציונים בזמן אמת                 |
| `report/report_builder.py` | יוצר את הפלט הסופי עם הציון, האיכות וה־hints   |

---

## ⚙️ מבנה החישוב

1. **Normalize** – כל המדדים עוברים נירמול לשמות אחידים (aliases.yaml)
2. **Validator** – מזהה אילו קריטריונים זמינים לפי `requires`
3. **Scoring** – מחשב ציון לכל קריטריון לפי הספים ב־YAML
4. **Vote** – מבצע שקלול משוקלל של הציונים הקיימים
5. **Report** – מחזיר אובייקט מסודר עם `overall`, `quality`, ו־`criteria`

---

## 📘 מבנה ה־YAML הרלוונטי

כל תרגיל (base או variant) מגדיר את הקריטריונים שנמדדים בו:

```yaml
criteria:
  posture:
    requires: [torso_forward_deg]
  depth:
    requires: [knee_left_deg, knee_right_deg]
  tempo:
    requires: [rep.timing_s]
  stance_width:
    requires: [features.stance_width_ratio]
  knee_valgus:
    requires: [knee_foot_alignment_left_deg, knee_foot_alignment_right_deg]

critical: [posture, depth]  # חובה לניקוד
thresholds:
  posture:      { max_good_deg: 15, max_ok_deg: 25, max_bad_deg: 45 }
  depth:        { knee_target_deg: 110, knee_cutoff_deg: 155 }
  tempo:        { min_s: 0.7, max_s: 2.5, min_cutoff_s: 0.4, max_cutoff_s: 4.0 }
  stance_width: { min_ok: 0.9, max_ok: 1.2, min_cutoff: 0.7, max_cutoff: 1.5 }
  knee_valgus:  { ok_deg: 5, warn_deg: 10, bad_deg: 20 }

weights_override:
  tempo: 0.5
  stance_width: 0.5
  knee_valgus: 1.0
```

---

## 🧠 לוגיקת הציון לכל קריטריון

| קריטריון         | פרמטרים עיקריים                      | מה נחשב טוב                    |
| ---------------- | ------------------------------------ | ------------------------------ |
| **posture**      | `torso_forward_deg`                  | כמה שפחות הטיה קדימה           |
| **depth**        | `knee_left_deg`, `knee_right_deg`    | עומק גדול יותר (זווית קטנה)    |
| **tempo**        | `rep.timing_s`                       | טווח זמן מאוזן (0.7–2.5 שניות) |
| **stance_width** | `features.stance_width_ratio`        | 0.9–1.2 יחס רוחב תקין          |
| **knee_valgus**  | `knee_foot_alignment_left/right_deg` | סטייה קטנה מהקו האמצעי         |

---

## 🔢 נוסחאות ניקוד

להלן הלוגיקה הפנימית של כל שופט (Scorer):

### posture

```text
≤ max_good_deg → 1.0
max_ok_deg..max_bad_deg → יורד לינארית מ-1.0 ל-0.0
≥ max_bad_deg → 0.0
```

### depth

```text
≤ knee_target_deg → 1.0
≥ knee_cutoff_deg → 0.0
ביניהם → ירידה לינארית
```

### tempo

```text
min_s ≤ t ≤ max_s → 1.0
t < min_s → יורד לינארית עד min_cutoff_s
t > max_s → יורד לינארית עד max_cutoff_s
```

### stance_width

```text
min_ok ≤ r ≤ max_ok → 1.0
מחוץ לטווח → ירידה לינארית עד cutoff
```

### knee_valgus

```text
≤ ok_deg → 1.0
ok_deg..warn_deg → יורד ל-0.6
warn_deg..bad_deg → יורד ל-0.0
≥ bad_deg → 0.0
```

---

## 🧩 שקלול (Vote)

אחרי שכל הקריטריונים חושבו:

```python
overall = Σ(score_i * weight_i) / Σ(weight_i)
```

* אם אין אף קריטריון זמין → `overall=None`, `quality="poor"`
* אם יש פחות מ-3 קריטריונים → `quality="partial"`
* אחרת → `quality="full"`

---

## 🧾 מבנה הפלט

```python
@dataclass
class CriterionScore:
    id: str
    available: bool
    score: Optional[float]
    reason: Optional[str]

@dataclass
class VoteResult:
    overall: Optional[float]
    quality: Optional[str]
    used_criteria: List[str]
    skipped_criteria: List[str]
```

**runtime** מוסיף זאת לדוח הסופי (`report_builder`) וממיר את הציון לאחוזים (`score_pct`).

---

## 🧰 שימוש מתוך runtime

קטע מתוך `runtime/runtime.py`:

```python
availability = evaluate_availability(ex, canonical)
is_unscored, reason, _ = decide_unscored(ex, availability)

if not is_unscored:
    per_crit = calc_score_yaml.score_criteria(exercise=ex, canonical=canonical, availability=availability)
    vote_res = calc_score_yaml.vote(exercise=ex, per_criterion=per_crit)
else:
    per_crit = {c: CriterionScore(id=c, available=False, score=None) for c in ex.criteria}

report = build_payload(
    exercise=ex,
    canonical=canonical,
    availability=availability,
    overall_score=vote_res.overall,
    overall_quality=vote_res.quality,
    hints=generate_hints(exercise=ex, canonical=canonical, per_criterion_scores=per_crit),
)
```

---

## 🧾 דוגמת פלט JSON

```json
{
  "exercise": "squat.bodyweight",
  "scoring": {
    "score": 0.86,
    "quality": "full",
    "criteria": [
      {"id": "posture", "score": 0.8, "score_pct": 80},
      {"id": "depth", "score": 0.83, "score_pct": 83},
      {"id": "tempo", "score": 1.0, "score_pct": 100},
      {"id": "stance_width", "score": 1.0, "score_pct": 100},
      {"id": "knee_valgus", "score": 0.7, "score_pct": 70}
    ]
  }
}
```

---

## 🛠️ טיפול בשגיאות ו־Diagnostics

* `criterion_unavailable` – חסר נתון ב־canonical
* `criterion_scored` – קריטריון חושב בהצלחה
* `vote_computed` – שקלול בוצע
* כל האירועים נשלחים ל־`monitoring/diagnostics.py` אם זמין.

---

## 🚀 הרחבות עתידיות (TODO)

* תמיכה בקריטריונים חדשים (כמו `symmetry`, `bar_path`)
* תמיכה ב־`formula:` בתוך YAML לנוסחאות מותאמות אישית
* קריטריונים מבוססי יחסים (לדוגמה: טווח תנועה בין פריימים)
* חיבור ישיר למודול `feedback.explain` לטיפים חכמים בזמן אמת

---

## ✅ סיכום קצר

| רכיב                 | תפקיד                   |
| -------------------- | ----------------------- |
| `calc_score_yaml.py` | חישוב ציונים לפי YAML   |
| `validator.py`       | קובע זמינות של מדדים    |
| `runtime.py`         | מפעיל את המנוע בזמן אמת |
| `report_builder.py`  | מרכיב את דו״ח התוצאה    |

---

📄 מומלץ לשמור קובץ זה כ־
`exercise_engine/scoring/README.md`

כך שכל מי שעובד על הקוד יבין **איך הציון מחושב, על מה הוא מבוסס, ומה מקור האמת (YAML).**

---

רוצה שאמשיך עכשיו עם README דומה גם ל־**דו״חות (report_builder.py)**?
זה יהיה הקובץ השלישי שיסגור לך את שלושת השלבים של הזרימה: Loader → Scoring → Report.
