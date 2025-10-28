מעולה. הנה **איפיון מלא, כללי ולכל התרגילים** — כולל מבנה נתונים, זרימה, חוזים, ודגשים להצגה “סופר-מפורטת” ברמת סט וברמת חזרה (per-rep), עם שילוב **משפחה (base)** + **וריאציה (variant)**, שימוש ב-`aliases.yaml` ו-`phrases.yaml`, וסדרי עדיפויות ברורים. אפשר לשמור כ-
`docs/REPORTS_AND_AUTO_DETAIL.md` (מומלץ), או לפצל לפי הצעת המבנה בסוף.

---

# 📑 Auto-Detail Reports v2 — איפיון מערכת הדו"חות המפורטים

מסמך זה מגדיר **איך לבנות ולהציג דו״ח עשיר, אמין ורלוונטי** לכל תרגיל, מבלי לגעת ידנית בכל קובץ תרגיל. הלוגיקה שואבת אוטומטית את המדדים והיעדים מ-**base+variant**, מנרמלת בעזרת `aliases.yaml`, יוצרת טבלת ערכים “קריטיים + רלוונטיים”, ומייצרת משפטים קצרים מתוך `phrases.yaml`. בנוסף — תמיכה מלאה ב-**תצוגת חזרות (per-rep)**.

---

## 🎯 מטרות

* **אמינות ומקצועיות**: מציגים מספרים אמיתיים (מעלות/שניות/יחסים) + יעד להשוואה.
* **רלוונטיות חכמה**: בחירת מדדים מתוך `criteria.requires` של התרגיל (base+variant) — לא מציגים “ידיים בתרגיל רגליים”.
* **שפה אחידה**: משפטים קצרים מתוך `phrases.yaml` (כולל placeholders).
* **סקייל לכל התרגילים**: עובד לכל תרגיל שיש לו YAML (גם עם `inherits` מרובות).
* **per-rep אמיתי**: לכל חזרה — טמפו, ROM, זוויות רלוונטיות, דגלים, וטקסט.

---

## 🧭 מיקום בזרימה

```
aliases.normalize  →  loader.resolve(base+variant)  →  scoring (optional)
                              │
                              └─→ build_auto_metrics_detail()
                                           │
                                 report_builder.attach()
                                           │
                                   Admin UI (Set + Rep views)
```

* **לא מחליף** את מנוע הציון — מוסיף עליו שכבת “פרטי מדידה” להצגה.
* אם הציון לא רץ (למשל ניתוח offline) — אפשר להציג רק את ה-Auto-Detail.

---

## 📦 עקרונות נתונים

### 1) רזולוציית Base+Variant

* טוענים את ה-variant YAML.
* עוקבים אחרי `inherits` עד ה-base (אפשר כמה שכבות).
* מאחדים:

  * `targets`: ה-variant **גובר** על ה-base.
  * `criteria`: מאחדים לפי מזהה; ה-variant **גובר** על שדות קיימים (weight/rule/enable_when).
  * `phrases.namespace`: נעדיף namespace של ה-variant, אחרת של ה-base, אחרת קטגוריות כלליות.

### 2) נירמול שמות (aliases)

* כל מפתח מחולץ דרך `aliases.yaml` → **שם קנוני** + **יחידה**.
* התייחסות לטולרנסים (`tolerances`) רק לצורך קונפליקטים/מיזוג ערכים.

### 3) בחירת “מועמדים להצגה”

* **רשימת requires** מכל ה-criteria (base+variant).
* **Core קבועים** (אם קיימים בפועל):
  `torso_forward_deg`, `spine_flexion_deg`, `features.stance_width_ratio`,
  `rep.timing_s` / `rep.ecc_s` / `rep.con_s`,
  למדדי lower: `knee_*_deg`, `hip_*_deg`, `knee_foot_alignment_*_deg`.
* סינון כפילויות; מציגים **רק** מה שקיים בפועל ב-`metrics`.

---

## 🧰 פונקציה מרכזית (חוזה)

> (תיעוד איפיוני — המימוש יבוא אחר כך)

**`build_auto_metrics_detail(exercise_id, metrics) -> dict`**

קלט:

* `exercise_id: str`
* `metrics: dict` (פיילוד מדידה מזקיף/מנוע החזרות/זיהוי)

פלט (נוסף לדו״ח תחת `metrics_detail`):

```json
{
  "exercise": { "id": "family.variant", "family": "family", "namespace": "ns.variant|ns.family|general" },
  "phases":   { "rep_s": 1.82, "ecc_s": 0.92, "con_s": 0.90, "approx": false },
  "targets":  { "rep_time_s_min": 0.7, "rep_time_s_max": 2.5, "elbow_rom_deg_target": 90 },
  "core":     [ { "key": "torso_forward_deg", "label": "זווית גב מול אנך", "value": 8.0, "unit": "°" }, ... ],
  "relevant": [ { "key": "elbow_left_deg", "label": "מרפק שמאל", "value": 62.0, "unit": "°", "weight": 1.0 }, ... ],
  "sentences":[ "קצב מצוין — 1.82s (ירידה 0.92s / עלייה 0.90s).", "ROM 78° — כוון ל≈90°." ],
  "audit":    {
    "source": "variant+base+defaults",
    "criteria_seen": ["tempo","range_of_motion","posture", "..."],
    "keys_seen": ["rep.timing_s","elbow_left_deg","spine_flexion_deg"]
  }
}
```

הערות:

* **לא מציפים** מפתח שלא קיים בפועל במדידה.
* `phases.approx=true` אם נגזר ECC/CON בצורה משוערת (למשל מחלק יחסי).

---

## 🎯 Targets — היררכיית יעדים

1. יעדים שהוגדרו ב-**variant**
2. יעדים מה-**base**
3. אם אין — מציגים ערכי מידע ללא “יעד”

יעדים טיפוסיים להצגה:

* **Tempo**: `rep_time_s_min/max`, `fast_cutoff_s`, `min_turn_ms`
* **ROM**: `*_rom_deg_target/partial/cutoff`
* **Posture/Spine**: `*_ok/warn/bad`
* **Stance/Valgus**: `min_ok/max_ok`, `ok_deg/warn_deg/bad_deg`

---

## 🗂️ סדרי עדיפויות להצגה

* **Core (תמידיים)** — אם קיימים במדידה.
* **Relevant** — מדדים מתוך `criteria.requires`:

  1. מסודרים לפי **weight** (אם יש ב-`scoring.criteria`), מהגבוה לנמוך.
  2. השאר — אלפביתית.
* **לא מציגים** את מה שלא נמדד בפועל (אין “חורים” מבלבלים).

---

## 🧩 משפטים (Phrases)

* חיפוש לפי סדר: `variant.namespace` → `base.namespace` → קטגוריות כלליות (`tempo`, `range_of_motion`, `posture`, `spine_rounding`, `knee_alignment`, …).
* בחירה חכמה בין `rep_good` / `rep_weak` / `rep_missing` בהתאם לערך מול היעד.
* מילוי placeholders מתוך:

  * `metrics_detail.phases` (למשל `rep_s`, `ecc_s`, `con_s`)
  * `metrics_detail.targets` (למשל `min_s`, `max_s`, `target_deg`)
  * ערכים מ-`core/relevant` (למשל `knee_min_deg`, `valgus_deg`, …)

> כלל זהב: 3–6 משפטים קצרים, ענייניים, **ללא ספאם**.

דוגמה:

* “קצב מצוין — בתוך היעד (1.84s; 0.98s/0.86s).”
* “ROM 78° — כוון ל≈90°.”
* “זווית גב 14° — בטווח תקין.”
* “קריסה פנימה בברך {{valgus_deg}}° — דחוף החוצה.”

---

## 📊 פורמט תצוגה (UI)

### כותרת קצרה (סט)

* **Tempo**: `1.84s` · `0.98s ↓` / `0.86s ↑`  *(סימן חץ עדין בלבד)*
* אם `approx`: תווית קטנה “≈” ליד ה-ECC/CON.

### Core (טבלה קומפקטית)

| 🔎 מדד           | ערך     |
| ---------------- | ------- |
| זווית גב מול אנך | 8°      |
| עגילת גב (פלשן)  | 6°      |
| רוחב עמידה       | 1.05×SW |

### Relevant (טבלה לפי חשיבות)

| 🎯 מדד (קריטריון) | ערך | יעד/טווח         |
| ----------------- | --- | ---------------- |
| ROM חזרה (מרפק)   | 78° | ≈90°             |
| כתף מקס׳          | 22° | ≤10° (אזהרה 15°) |
| שורש כף יד מקס׳   | 12° | ±15°             |

> **סמלים**: להשתמש במעט — 🔎, 🎯 בלבד (קריא, לא מצועצע).

### Sentences (רשימה)

* 3–6 משפטים מה־`phrases`, לפי הקריטריונים הכי חשובים.

### כפתור “Audit”

* פותח מודאל קטן עם `criteria_seen`, `keys_seen`, ו-`source` (“variant+base+defaults”).

---

## 🔁 תצוגת חזרות (Per-Rep)

כל חזרה מקבלת מבנה דומה, **רק ממוזער**:

```json
"rep_detail": {
  "rep_id": 4,
  "phases": { "rep_s": 1.76, "ecc_s": 0.95, "con_s": 0.81, "approx": false },
  "angles": [
    { "key":"knee_left_deg_min",  "label":"ברך שמאל (מינ׳)", "value": 84.0,  "unit":"°" },
    { "key":"knee_right_deg_min", "label":"ברך ימין (מינ׳)", "value": 86.0,  "unit":"°" },
    { "key":"torso_forward_deg_max","label":"גב (מקס׳)",     "value": 16.0,  "unit":"°" }
  ],
  "rom": { "rep.rom": 78.0, "unit":"°" },
  "flags": { "quality": "good|fast|slow|short|incomplete", "warnings": ["auto_target_used"] },
  "sentences": [ "קצב תקין", "ROM 78° — כמעט יעד" ]
}
```

כללי per-rep:

* **ROM**: מ-`rep.rom` אם קיים; או נגזרת (אם יש פוליגונים של מפרק מוביל באותו תרגיל).
* **Angles**: רק **מפתחות רלוונטיים לתרגיל** (מ-`criteria.requires` של base+variant).
  נציג min/max לפי היגיון (למשל עומק — מינימום ברך; גב — מקס׳ הטיה).
* **Tempo**: `rep.timing_s`, ואם יש — `rep.ecc_s`/`rep.con_s`.
* **Flags**: מ-`rep.quality` ו-`rep.errors.*`/`rep.warnings.*`.
* **Phrases**: קצרצר — לכל חזרה עד 2–3 שורות.

UI:

* רשימת חזרות בצד, בחירה פותחת כרטיס עם הטבלה המוקטנת (כמו לעיל).
* אפשרות “העתקה” של כרטיס חזרה ל-clipboard (טקסטואלי).

---

## 🧱 “תמיד מתועדים” (Core קבועים)

אם קיימים בפועל:

* יציבה/גב: `torso_forward_deg`, `spine_flexion_deg`
* טמפו: `rep.timing_s` ± `rep.ecc_s`/`rep.con_s`
* עמידה: `features.stance_width_ratio`
* Lower: `knee_*_deg`, `hip_*_deg`, `knee_foot_alignment_*_deg`

> לא מציגים “חסר”. מציגים **רק** מה שיש.

---

## 🔒 כללים שמבטיחים “מקצועיות”

* **לא מציפים** מדדים לא רלוונטיים לתרגיל (נשענים על `criteria.requires`).
* **הצגת יעד יחד עם ערך** כשזמין: “78° (יעד ≈90°)”.
* **שפה** מתוך `phrases.yaml` בלבד (אחידות; placeholders מולאו בערכים).
* **Audit** זמין בלחיצה — שקיפות מלאה.

---

## 🧪 התאמה למנוע הציונים (לא חובה לרוץ יחד)

* אם רץ Scoring — ניתן לשלב עמדה: בשורת ה-Relevant להראות גם `score_pct` ליד הקריטריונים החשובים (קטן ועדין).
* אם לא רץ — Auto-Detail עומד בפני עצמו.

---

## 🧱 חוזים בין שכבות (תקציר)

| שכבה           | חוזה                                                                                                        |
| -------------- | ----------------------------------------------------------------------------------------------------------- |
| Loader         | `resolve(exercise_id) -> {base+variant merged}` כולל `criteria`, `targets`, `phrases.namespace`, `inherits` |
| Aliases        | `normalize(metrics) -> canonical` + `units` + `tolerances`                                                  |
| Auto-Detail    | `build_auto_metrics_detail(exercise_id, metrics) -> dict`                                                   |
| Report Builder | `attach(detail)` אל דו״ח הסט/החזרה                                                                          |
| UI             | מרנדר `phases / core / relevant / sentences` + per-rep                                                      |

---

## 📁 היכן לשים את הקוד/מסמכים

מומלץ:

```
exercise_engine/
  reporting/
    auto_detail.py          # build_auto_metrics_detail(...)
    labels.py               # מיפוי label+unit לשמות קנוניים (טבלה קטנה)
    selectors.py            # לוגיקת בחירת keys (criteria.requires + Core)
    targets.py              # מיזוג Targets מ-base+variant
    phrases.py              # איתור namespace + מילוי placeholders
    README.md               # (מסמך זה מקוצר) או קישור
```

ובנוסף:

* עדכון קטן ל-`report/report_builder.py` כדי לצרף `metrics_detail` ל-payload.
* ב-Admin UI:

  * תצוגת סט: Phases + Core + Relevant + Sentences + Audit
  * תצוגת per-rep: רשימת חזרות → כרטיס חזרה

---

## 🧾 דוגמת JSON — סט מלא (תקציר)

```json
{
  "set_id": 12,
  "exercise_id": "squat.bodyweight",
  "metrics": { "...": "..." },
  "metrics_detail": {
    "exercise": { "id": "squat.bodyweight", "family": "squat", "namespace": "squat.bodyweight|squat.common" },
    "phases":   { "rep_s": 2.02, "ecc_s": 1.22, "con_s": 0.80, "approx": false },
    "targets":  { "rep_time_s_min": 1.5, "rep_time_s_max": 3.5, "knee_min_deg_target": 95 },
    "core":     [
      { "key":"torso_forward_deg", "label":"זווית גב מול אנך", "value": 12.0, "unit":"°" },
      { "key":"spine_flexion_deg", "label":"עגילת גב (פלשן)", "value": 7.0, "unit":"°" }
    ],
    "relevant": [
      { "key":"knee_left_deg_min", "label":"ברך שמאל (מינ׳)", "value": 92.0, "unit":"°", "weight":1.5 },
      { "key":"knee_right_deg_min","label":"ברך ימין (מינ׳)", "value": 94.0, "unit":"°", "weight":1.5 },
      { "key":"features.stance_width_ratio","label":"רוחב עמידה","value":1.08,"unit":"×SW","weight":0.6 }
    ],
    "sentences":[
      "קצב מצוין — 2.02s (1.22s/0.80s).",
      "העומק כמעט יעד: 92°–94°; כוון ל≈90°.",
      "רוחב עמידה 1.08× — בתוך הטווח 0.9–1.2."
    ],
    "audit": { "source":"variant+base+defaults", "criteria_seen":["tempo","depth","stance_width"], "keys_seen":["knee_left_deg","knee_right_deg","rep.timing_s"] }
  },
  "reps": [
    {
      "rep_id": 1,
      "rep_detail": {
        "phases": { "rep_s": 2.10, "ecc_s": 1.25, "con_s": 0.85, "approx": false },
        "angles": [
          { "key":"knee_left_deg_min", "label":"ברך שמאל (מינ׳)", "value": 90.0, "unit":"°" },
          { "key":"knee_right_deg_min","label":"ברך ימין (מינ׳)", "value": 93.0, "unit":"°" },
          { "key":"torso_forward_deg_max","label":"גב (מקס׳)", "value": 15.0, "unit":"°" }
        ],
        "rom": { "rep.rom": 85.0, "unit":"°" },
        "flags": { "quality":"good", "warnings":[] },
        "sentences":[ "קצב בתוך היעד.", "עומק מצוין (90°–93°)." ]
      }
    }
  ]
}
```

---

## 🧩 הנחיות עיצוב (UI)

* **ניקיון וחיסכון**: 3–6 משפטים; טבלאות קומפקטיות; סמלים מינימליים (🔎, 🎯).
* **מספרים לפני הכל**: בכל שורה — הערך המספרי קודם, היעד אחריו.
* **תוויות יחידה**: `°`, `s`, `×SW`.
* **תיעדוף לפי חשיבות**: קודם Core, אח״כ Relevant לפי weight.
* **תצוגת per-rep**: גלריה של חזרות מנווטת, כרטיס נקי לכל חזרה.

---

## ✅ בדיקות קבלה (Acceptance)

* **לכל תרגיל** שיש לו YAML: נבנית רשימת Relevant מתוך `criteria.requires` המאוחדים (base+variant).
* **לא מוצגים** מדדים שאינם קיימים ב-`metrics`.
* **Targets מאוחדים** ורק אז מוצגים.
* **Phases**: אם חסר ECC/CON — מופיע `approx=true` וסימון “≈”.
* **Phrases**: לפחות 2, עד 6; בלי קטגוריה מתאימה → מדלגים (לא מציפים טקסט כללי מדי).
* **Audit**: שקיפות מלאה — מה ראינו, ומה מקור הערכים/היעדים.

---

## 🗺️ Roadmap קצר

* Phase 2: הצגת **score_pct** עדין ליד שורות רלוונטיות כשמנוע הציונים פעיל.
* Phase 3: הרחבת per-rep עם גרף מיני (מיני-ספרק) ל-ECC/CON/ROM.
* Phase 4: “Export Rep” — יצוא כרטיס חזרה ל-JSON/CSV.

---

אם זה טוב לך, אגבש את זה ל-`README.md` ייעודי + שלד קבצים (namespaces לעיל) כדי שתוכל **להדביק לפרויקט אחד-לאחד**.
