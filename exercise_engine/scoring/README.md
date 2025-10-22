להלן איפיון **מלא, מדויק ומותאם למבנה הפרויקט שלך** – כקובץ תיעוד מוכן ל־`README.md` שמרכז רק את **מנוע הציונים** (Scoring).
מבוסס בול על העץ שסיפקת:

```
exercise_library/
  aliases.yaml
  phrases.yaml
  exercises/
    _base/squat.base.yaml
    packs/bodyweight/squat/squat_bodyweight.yaml

exercise_engine/
  scoring/calc_score_yaml.py
  runtime/runtime.py
  registry/(loader.py, preflight.py, schema.py)
  report/report_builder.py
  runtime/(validator.py, engine_settings.py, log.py)
  classifier/classifier.py
  segmenter/(reps.py, set_counter.py)
  feedback/(explain.py, camera_wizard.py)
```

---

# מנוע ציון מבוסס YAML

*Design · Contracts · זרימה · דוגמאות*

## מטרות

* חישוב ציון תרגיל **כללי** שנשלט 100% מקובצי YAML של התרגילים (ללא שינוי קוד).
* תמיכה ב־**base (משפחה)** + **variant (וריאנט ספציפי)** עם `extends`.
* היגיון ברור ל־**זמינות מדדים** (availability) ו־**Unscored** כשחסרים קריטיים.
* החזרת פלט עקבי ל־`report_builder` + שקיפות מלאה (per-criterion + vote + נימוקים).

---

## זרימת נתונים (גבוה)

```
Raw metrics  →  Normalizer (aliases.yaml)  →  canonical dict
                                   │
                                   ▼
                        registry.loader Library
                        (merged YAML docs)
                                   │
                                   ▼
              validator.evaluate_availability(ex, canonical)
                                   │
                                   ▼
              scoring.calc_score_yaml.score_criteria(...)
                                   │
                                   ▼
              scoring.calc_score_yaml.vote(...)
                                   │
                                   ▼
                      report.report_builder.build_payload(...)
```

---

## נקודות עוגן בקוד

* **חישוב ציון (קיים):** `exercise_engine/scoring/calc_score_yaml.py`
  זה קובץ “מנוע הציון”. הוא קורא את ה־`ExerciseDef` (שנטען ע"י ה־loader), ומחשב:

  * per-criterion scores
  * vote (שקלול משקלים)
  * איכות (quality: full/partial)
* **קריאת YAML:** `exercise_engine/registry/loader.py` + `schema.py` + `preflight.py`
* **הזרמת runtime:** `runtime/runtime.py` קורא את המנוע (`calc_score_yaml`) דרך API ברור.
* **דו"ח:** `report/report_builder.py` מרכיב את הפלט הסופי.

---

## חוזים (Contracts)

### 1) קלט ל־Scoring

* `exercise: ExerciseDef` – אחרי merge ירושה (`extends`) ע"י ה־loader.

  * שדות רלוונטיים:
    `id`, `family`, `criteria`, `critical`, `thresholds`, `weights` (+ `weights_override` ב־variant), `meta.selectable`, `match_hints` (למסווג).
* `canonical: Dict[str, Any]` – מילון קנוני אחרי Normalizer (מפתחות בדיוק מ־`aliases.yaml`).
* `availability: Dict[str, {available:bool, reason?:str}]` – תוצאת `validator.evaluate_availability(ex, canonical)`:

  * לכל `criterion` יש רשומה שמכריעה אם ניתן לנקד אותו (לפי `requires`).
  * אם **חסר** אחד הקריטיים ב־`critical` → התרגיל **Unscored** (המנוע מחזיר ציון לכל הזמינים, אבל ה־runtime מסמן Unscored ו־report מציג סיבה).

### 2) פלט מ־Scoring

```python
# calc_score_yaml.py
@dataclass
class CriterionScore:
    id: str
    available: bool
    score: Optional[float]   # 0..1 או None אם לא נמדד/לא זמין
    reason: Optional[str]    # "unavailable" | "ok" | הסבר קצר

@dataclass
class VoteResult:
    overall: Optional[float]  # 0..1 או None (אין נתונים)
    quality: Optional[str]    # "full" | "partial" | "poor"
    used_criteria: List[str]
    skipped_criteria: List[str]
```

* `score_criteria(...) -> Dict[str, CriterionScore]`
* `vote(...) -> VoteResult`

ה־runtime מזריק את זה ל־`report_builder` (כולל `score_pct` אם רלוונטי).

---

## סכמת YAML לתרגיל (תמצית שימושית למנוע הציון)

> (את הטמפלטים המלאים כבר בנית — זה רק מה שמעניין למנוע הציון)

```yaml
id: squat.bodyweight
family: squat
meta:
  selectable: true
  display_name: "Squat (Bodyweight)"

extends: squat.base  # אופציונלי

criteria:
  posture:
    requires: [torso_forward_deg]
    weight: 1.0           # אופציונלי; אפשר גם ב-weights_override
  depth:
    requires: [knee_left_deg, knee_right_deg]
    weight: 1.5
  tempo:
    requires: [rep.timing_s]
  stance_width:
    requires: [features.stance_width_ratio]
  knee_valgus:
    requires: [knee_foot_alignment_left_deg, knee_foot_alignment_right_deg]

critical: [posture, depth]

thresholds:
  posture:      { max_good_deg: 15, max_ok_deg: 25, max_bad_deg: 45 }
  depth:        { knee_target_deg: 90, knee_cutoff_deg: 150 }
  tempo:        { min_s: 0.7, max_s: 2.5, min_cutoff_s: 0.4, max_cutoff_s: 4.0 }
  stance_width: { min_ok: 0.9, max_ok: 1.2, min_cutoff: 0.7, max_cutoff: 1.5 }
  knee_valgus:  { ok_deg: 5, warn_deg: 10, bad_deg: 20 }

# לחלופין:
weights_override:
  tempo: 0.5
  stance_width: 0.5
  knee_valgus: 1.0
```

הערות חשובות:

* `requires` קובע רק **זמינות** (availability). אם חסר – הקריטריון לא ינוקד (`score=None`) ולא נכנס לשקלול.
* `critical` = רשימת קריטריונים שחובה לנקד כדי שהתרגיל **לא** יהיה Unscored (ה־runtime יחליט לפי `decide_unscored`).
* `thresholds` דוחפים את ספי הניקוד (כל שופט קורא משם, עם ברירות מחדל פנימיות אם לא סופק ב־YAML).
* `weight`: אפשר בתוך `criteria.<name>.weight` או ב־`weights_override` ברמת מסמך.

---

## שופטים (Scorers) – איך מחושב ציון לכל קריטריון

(נמצא בתוך `calc_score_yaml.py`)

1. **posture** (טיית גו — קטן=טוב)

   * `≤max_good_deg → 1.0`
   * `max_ok_deg..max_bad_deg` – ירידה לינארית `1.0 → 0.0` (עם מדרגה ל־0.6 באזור ok)
   * `≥max_bad_deg → 0.0`

2. **depth** (עומק — לפי מינימום זווית ברך משמאל/ימין)

   * `≤knee_target_deg → 1.0`
   * `knee_target_deg..knee_cutoff_deg` לינארי `1.0 → 0.0`
   * `≥knee_cutoff_deg → 0.0`

3. **tempo** (זמן חזרה בשניות — תחום טוב באמצע)

   * בתחום `[min_s..max_s] → 1.0`
   * מתחת ל־`min_s` יורד לינארית עד `min_cutoff_s` (שם `0.0`)
   * מעל `max_s` יורד לינארית עד `max_cutoff_s` (שם `0.0`)

4. **stance_width** (רוחב עמידה יחסי — תחום טוב באמצע)

   * `[min_ok..max_ok] → 1.0`
   * מחוץ לתחום – לינארי עד `min_cutoff`/`max_cutoff` (שם `0.0`)

5. **knee_valgus** (יישור ברך מול כף הרגל — קטן=טוב, משתמשים במקס' |L|,|R|)

   * `≤ok_deg → 1.0`
   * `ok_deg..warn_deg → 1.0 → 0.6`
   * `warn_deg..bad_deg → 0.6 → 0.0`
   * `≥bad_deg → 0.0`

> אין דרישה להעלות/להוריד שופטים: פשוט לא להגדירם ב־YAML (או לא יהיו זמינים לפי `requires`) — הם לא ישוקללו ב־vote.

---

## זמינות (Availability) וכללי Unscored

* `validator.evaluate_availability(ex, canonical)` מחזיר, לכל קריטריון, אם הוא **זמין**:

  * קיימים כל ה־`requires` **בקנוני** (לא None).
* אם **אחד הקריטיים** ב־`critical` אינו זמין → `decide_unscored(...)` יחזיר Unscored + סיבה (ל־report).
* גם אם Unscored, עדיין נחזיר per-criterion למה שזמין (לשקיפות ול־Hints).

---

## שקלול (Vote)

* אסיפה של כל הקריטריונים עם `available=True` ו־`score!=None`.
* משקל (`weight`) נלקח מ־`criteria.<name>.weight` או מ־`weights_override` (אם הוגדר). ברירת מחדל: `1.0`.
* `overall = clamp( sum(score_i * w_i) / sum(w_i) )`.
* `quality`:

  * `"full"` – אם שוקללו **≥3** קריטריונים.
  * `"partial"` – אחרת (יש מעט קריטריונים זמינים).
  * (כאשר לא שוקלל אף קריטריון: `overall=None, quality="poor"`)

---

## דיאגנוסטיקות (לבקרה)

* המנוע שולח אירועים (אם יש monitoring):

  * `criterion_scored` (info) – קריטריון קיבל ציון.
  * `criterion_unavailable` (warn) – חסרים נתונים/מדדים.
  * `vote_computed` (info) – חישוב שקלול.
* ה־runtime מוסיף אירועים כמו `low_pose_confidence`, `no_exercise_selected`, ועוד.

---

## אינטגרציה בתוך `runtime/runtime.py`

* אחרי בחירת תרגיל + בדיקת Grace:

  1. `availability = evaluate_availability(ex, canonical)`
  2. `is_unscored, reason, _ = decide_unscored(ex, availability)`
  3. אם **לא** Unscored:
     `per_crit = calc_score_yaml.score_criteria(exercise=ex, canonical=canonical, availability=availability)`
     `vote = calc_score_yaml.vote(exercise=ex, per_criterion=per_crit)`
  4. אם Unscored: בונים map של `CriterionScore` רק עם `available=` (לשקיפות), ללא ציון.
  5. מעבירים ל־`report_builder.build_payload(...)` יחד עם hints.

> חשוב: אין שום לוגיקה של “איך לחשב” בתוך ה־runtime. הכל נשען על YAML + `calc_score_yaml.py`.

---

## דוגמה קצרה (Squat Bodyweight)

**`exercise_library/exercises/_base/squat.base.yaml`**

* מגדיר `criteria`, `critical`, `thresholds` ו־`weights` כלליים למשפחה.

**`exercise_library/exercises/packs/bodyweight/squat/squat_bodyweight.yaml`**

* `extends: squat.base`
* עושה fine-tune ל־`thresholds`/`weights_override` לפי הצורך.

**קלט קנוני (דוגמה):**

```json
{
  "torso_forward_deg": 18.0,
  "knee_left_deg": 95.0,
  "knee_right_deg": 100.0,
  "rep.timing_s": 1.1,
  "features.stance_width_ratio": 1.05,
  "knee_foot_alignment_left_deg": 7.0,
  "knee_foot_alignment_right_deg": 9.0
}
```

**פלט לוגיקה:**

* `posture` ~ 0.8, `depth` ~ 0.83, `tempo` = 1.0, `stance_width` = 1.0, `knee_valgus` ~ 0.7
* שקלול לפי `weights` → `overall` ~ 0.86, `quality: "full"` (5 קריטריונים).

---

## איך מוסיפים תרגיל חדש (ללא שינוי קוד)

1. צור קובץ **base** למשפחה (אם אין): `exercises/_base/<family>.base.yaml`

   * הגדר `criteria`, `critical`, `thresholds` ו־משקלים בסיסיים.
2. צור **variant** תחת חבילה (pack) כלשהי:
   `exercises/packs/<pack>/<family>/<variant>.yaml`
3. ב־variant:

   * `extends: <family>.base`
   * עדכן `thresholds`/`weights_override`/`requires` ספציפי.
   * **אל תיגע בקוד**.
4. הרצת `registry/preflight.py` (או לטעון runtime) – אם יש שגיאה במסמך, תראה אותה מיד.

---

## טיפול בחוסרים/שגיאות

* **חסר מפתח קנוני ב־aliases.yaml?**

  * הוולידציה (`schema.validate_library`) מזהירה.
* **חסר ערך ב־canonical בזמן ריצה?**

  * `availability` מסמן `available=False` לקריטריון → הקריטריון נופל מהשקלול.
* **חסר קריטריון קריטי?**

  * `decide_unscored` → Unscored + reason (בדו"ח).

---

## החלטות עיצוב חשובות

* **YAML הוא מקור האמת**: ספים, משקלים, דרישות זמינות — הכל שם.
* **מנוע הציון כללי**: לא קשור לסקוואט; כל קריטריון שמופיע ב־YAML יקבל טיפול כללי:

  * אם יש לו שופט מובנה – ינוקד.
  * אם אין – פשוט לא ייכנס לשקלול (או תוסיף שופט בעתיד ב־`calc_score_yaml.py`).
* **Backward compatible**: הטמפלטים וה־aliases ששלחת כבר תואמים למנוע.

---

## To-Do (כשתרצה להרחיב)

* תוספת שופטים כלליים (לדוגמה: `hip_hinge`, `bar_path`, `symmetry`).
* תמיכה ב־**נוסחאות** בקובץ (למשל `formula: "lin_clamp(x, a, b)"`) – היום השופטים “קשיחים”, אבל קל להוסיף שכבת “formula registry”.
* החצנת **defaults** ל־`defaults.yaml` לכל משפחה (אם תרצה).

---

זהו—עם האיפיון הזה המנוע שלך “סגור” מקצה לקצה, מתאים למבנה הקיים, ועם חוזים ברורים ל־runtime ולדו״חות.
אם תרצה, אוציא עבורך עכשיו גם **README מקביל** ל־דו״חות (reporting) באותו סגנון.
