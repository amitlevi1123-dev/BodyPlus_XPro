להלן מסמך איפיון מלא בפורמט **Markdown** — מקצועי, קריא, וידידותי, עם טבלאות, דוגמאות, תרשימי זרימה טקסטואליים, בדיקות קבלה, והצעות לשיפור עתידי. ניתן להדבקה כ-`docs/reporting-spec.md`.

---

# 🧾 BodyPlus XPro — איפיון מודול דוחות: נרמול, תרגום, “נמדד מול יעד”, וביקורת סט/חזרות

**גרסה:** 1.0
**אחריות:** exercise_engine · admin_web · UI
**מטרה:** יצירת שכבה אחידה שמייצרת דו״ח קריא ומסודר לממשק המשתמש — כולל שמות ידידותיים, יחידות, פירוק קריטריונים, “נמדד מול יעד”, ביקורת ברמת חזרה וברמת סט, ודיווח בריאות הדו״ח.

---

## תוכן העניינים

1. [רקע ומטרות](#רקע-ומטרות)
2. [עקרונות תכנון](#עקרונות-תכנון)
3. [תלותים וקלטים](#תלותים-וקלטים)
4. [פלט הדו״ח (Payload) — סכימה ודוגמאות](#פלט-הדוח-payload--סכימה-ודוגמאות)
5. [נרמול ותרגום (i18n) מתוך `aliases.yaml`](#נרמול-ותרגום-i18n-מתוך-aliasesyaml)
6. [חישוב “נמדד מול יעד”](#חישוב-נמדד-מול-יעד)
7. [ביקורת חזרה (Rep Critique)](#ביקורת-חזרה-rep-critique)
8. [ביקורת סט (Set Critique)](#ביקורת-סט-set-critique)
9. [בריאות דו״ח (OK/WARN/FAIL)](#בריאות-דוח-okwarnfail)
10. [UX/UI — עקרונות, טבלאות, והתנהגות RTL/LTR](#uxui--עקרונות-טבלאות-והתנהגות-rtlltr)
11. [תרשים זרימת נתונים](#תרשים-זרימת-נתונים)
12. [מקרי קצה ושגיאות](#מקרי-קצה-ושגיאות)
13. [ביצועים, ניטור ולוגים](#ביצועים-ניטור-ולוגים)
14. [בדיקות קבלה (QA Checklist)](#בדיקות-קבלה-qa-checklist)
15. [Roadmap — שיפורים עתידיים](#roadmap--שיפורים-עתידיים)
16. [עמדת העורך (המלצות ודגשים)](#עמדת-העורך-המלצות-ודגשים)

---

## רקע ומטרות

* **האתגר:** פלטי הניתוח מגיעים במפתחות קנוניים/טכניים, ללא שמות תצוגה, ללא יעדים ברורים וללא ביקורת מקובצת ברמת סט/חזרה.
* **הפתרון:** שכבת “בונה דו״ח” שמסכמת את הכל במבנה אחיד, מתורגם ומוכן לתצוגה.
* **רווח למשתמש:** דף תרגיל מסודר, ברור, עם “מה נמדד”, “מה היעד”, “איפה טעיתי”, “מה לשפר עכשיו”.

---

## עקרונות תכנון

* **ללא קבצים חדשים**: משתמשים ב־`aliases.yaml`, `phrases.yaml`, ו־YAML של התרגילים (thresholds/criteria).
* **דו־לשוניות**: `display_lang` = `he`/`en`, עם fallback חכם.
* **אי־פגיעה בלוגיקה קיימת**: הדו״ח עוטף את תוצאות הניתוח — לא משנה חישובי ציון קיימים.
* **UI מינימליסטי**: טבלה קריאה, גלגלי ציון, ו-Modal לפירוט — עם overflow-x מסודר.

---

## תלותים וקלטים

| מקור           | מה מספק                                                                       | הערות                                  |
| -------------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `aliases.yaml` | שמות תצוגה דו-לשוניים למדדים/תרגילים/משפחות/ציוד; יחידות; הגדרות pass-through | מקור האמת לשפה ותוויות                 |
| `phrases.yaml` | משפטים (tips/hints) לפי מזהי קריטריונים/מצבים                                 | אופציונלי; יש fallback אוטומטי         |
| Exercise YAMLs | `criteria`, `weights`, `thresholds` (יעדים)                                   | thresholds משמשים ליעד (min/max/range) |
| מנוע הניתוח    | `overall_score`, `per_criterion_scores`, `availability`, `canonical`          | אינפוט לדו״ח                           |
| מצלמה          | `camera_summary`                                                              | נושא איכות צילום/אזהרות                |

---

## פלט הדו״ח (Payload) — סכימה ודוגמאות

### שדות חובה ומומלצים

| שדה                          | טיפוס           | חובה      | הסבר                               |
| ---------------------------- | --------------- | --------- | ---------------------------------- |
| `meta.generated_at`          | string(ISO)     | ✓         | זמן יצירת הדו״ח                    |
| `payload_version`            | string          | ✓         | גרסת payload (למשל `1.2.0`)        |
| `library_version`            | string          | ✓         | גרסת ספריה מה־loader               |
| `display_lang`               | enum(`he`,`en`) | ✓         | שפת תצוגה מועדפת                   |
| `exercise`                   | object          | ✓         | `id/family/equipment/display_name` |
| `ui.lang_labels`             | object          | ✓         | שמות תרגיל/משפחה/ציוד לפי `he/en`  |
| `ui_ranges.color_bar`        | array           | ✓         | מדרג צבעים ל־Gauges                |
| `scoring`                    | object          | ✓         | ציון כולל + פירוק קריטריונים       |
| `coverage`                   | object          | ✓         | כיסוי מדדים/חוסרים קריטיים         |
| `rep_critique`               | array           | מומלץ     | ביקורת פר חזרה                     |
| `set_critique`               | array           | מומלץ     | ביקורת פר סט                       |
| `hints`                      | array           | מומלץ     | הערות כלליות                       |
| `report_health`              | object          | ✓         | OK/WARN/FAIL + issues              |
| `camera`                     | object          | מומלץ     | סיכום תנאי צילום                   |
| `canonical/rep/measurements` | object          | אופציונלי | שקיפות נתונים                      |

### דוגמה (מקוצרת)

```json
{
  "meta": {"generated_at": "2025-10-29T14:10:00Z", "payload_version": "1.2.0", "library_version": "e3a1f2c"},
  "display_lang": "he",
  "exercise": {"id":"squat.bodyweight.md","family":"squat","equipment":"bodyweight","display_name":"Bodyweight Squat"},
  "ui": {
    "lang_labels": {
      "exercise":{"he":"סקוואט משקל גוף","en":"Bodyweight Squat"},
      "family":{"he":"סקוואט","en":"Squat"},
      "equipment":{"he":"משקל גוף","en":"Bodyweight"}
    }
  },
  "ui_ranges":{"color_bar":[{"label":"red","from_pct":0,"to_pct":60},{"label":"orange","from_pct":60,"to_pct":75},{"label":"green","from_pct":75,"to_pct":100}]},
  "scoring":{
    "score":0.82,"score_pct":82,"quality":"partial","unscored_reason":null,"applied_caps":[],
    "criteria":[
      {"id":"depth","available":true,"reason":null,"score":0.88,"score_pct":88},
      {"id":"stance_width","available":true,"reason":null,"score":0.74,"score_pct":74}
    ],
    "criteria_breakdown_pct":{"depth":88,"stance_width":74}
  },
  "coverage":{"available_pct":90,"available_count":9,"total_criteria":10,"missing_critical":[],"missing_reasons_top":[]},
  "rep_critique":[
    {
      "set_index":1,"rep_index":1,
      "criteria":[
        {"id":"depth","name_he":"עומק","name_en":"Depth","unit":"°","measured":115,"target_he":"יעד ≥ 100°","target_en":"Target ≥ 100°","score_pct":88,"note_he":"ביצוע נקי","note_en":"Clean execution"},
        {"id":"stance_width","name_he":"רוחב עמידה","name_en":"Stance width","unit":"","measured":1.25,"target_he":"טווח 1.2–1.5","target_en":"Range 1.2–1.5","score_pct":74,"note_he":"שפר רוחב עמידה","note_en":"Improve stance width"}
      ],
      "summary_he":"מוקדי שיפור: רוחב עמידה","summary_en":"Focus: Stance width"
    }
  ],
  "set_critique":[{"set_index":1,"set_score_pct":80,"rep_count":8,"top_issues":[{"id":"stance_width","name_he":"רוחב עמידה","worst_rep_pct":60,"avg_pct":72}],"summary_he":"בסט זה רוחב עמידה היה צוואר בקבוק.","summary_en":"Stance width was the bottleneck."}],
  "report_health":{"status":"OK","issues":[]},
  "camera":{"visibility_risk":false,"severity":"LOW","message":"המדידה תקינה","stats":{}}
}
```

---

## נרמול ותרגום (i18n) מתוך `aliases.yaml`

### מבנה מומלץ ב־`aliases.yaml`

```yaml
names:
  exercises:
    squat.bodyweight: { he: "סקוואט משקל גוף", en: "Bodyweight Squat" }
  families:
    squat: { he: "סקוואט", en: "Squat" }
  equipment:
    bodyweight: { he: "משקל גוף", en: "Bodyweight" }

labels:
  depth:              { he: "עומק", en: "Depth", unit: "°" }
  features.stance_width_ratio: { he: "רוחב עמידה", en: "Stance width", unit: "" }
  knee_left_deg:      { he: "ברך שמאל (°)", en: "Left knee (°)", unit: "°" }
```

### כללי תרגום

1. אם יש `names.*[id][display_lang]` — מציגים.
2. אם חסר ב־`display_lang` – נופלים ל־שפה השנייה → ואז ל־`id`.
3. תוויות מדדים מ־`labels.<key>`; אם חסר — מציגים את המפתח הקנוני (fallback).

---

## חישוב “נמדד מול יעד”

* יעדים נשלפים מ־`exercise.thresholds[crit]`.
* טבלאות אפשריות:

  * **min**: יעד ≥ `min`
  * **max**: יעד ≤ `max`
  * **range**: `min`–`max`
* הואיל ו־`canonical` שטוח, **measured** = `canonical[crit_id]` (אם קיים, אחרת “—”).
* עימוד:

  * מציגים יחידות מ־`aliases.labels[crit_id].unit`.
  * ניסוח יעד דו־לשוני:

    * he: “יעד ≥ 100°”, “יעד ≤ 30°”, “טווח 1.2–1.5”
    * en: “Target ≥ 100°”, “Target ≤ 30°”, “Range 1.2–1.5”
* אם אין סף — מציגים “—”.

---

## ביקורת חזרה (Rep Critique)

**מטרה:** להראות למשתמש, לכל חזרה, מה היה טוב ומה לשפר.

### בנייה

* עבור כל `rep`:

  1. עוברים על `scoring.criteria` → לכל קריטריון:

     * `name_he/en` — מ־`aliases.labels`.
     * `measured` — מ־`canonical[crit_id]` (אם רלוונטי).
     * `target_*` — לפי `thresholds`.
     * `score_pct` — מהדו״ח.
     * `note_*` —

       * אם יש `phrases` — משתמשים לפי כלל.
       * אחרת:

         * `≥85%` → “ביצוע נקי / Clean execution”
         * `70–84%` → “אפשר לשפר X / Could improve X”
         * `<70%` → “שפר X (יעד …) / Improve X (target …)”
  2. **Summary**: לוקחים 1–3 הקריטריונים החלשים ביותר ומרכיבים משפט “מוקדי שיפור”.

### דוגמה פירוט חזרה (טבלה)

| קריטריון   | נמדד |     יעד | % ציון | הערה           |
| ---------- | ---: | ------: | -----: | -------------- |
| עומק       | 115° |  ≥ 100° |    88% | ביצוע נקי      |
| רוחב עמידה | 1.25 | 1.2–1.5 |    74% | שפר רוחב עמידה |

---

## ביקורת סט (Set Critique)

**מטרה:** להראות “צווארי בקבוק” חוזרים בסט.

### בנייה

* עבור סט:

  * אוספים לכל קריטריון: **ממוצע אחוזי ציון** + **החזרה הגרועה ביותר**.
  * ממיינים מהחלש לחזק; לוקחים Top 1–3.
  * מרכיבים **summary** קצר (he/en).

### דוגמה פירוט סט (טבלה)

| קריטריון   | ממוצע % | גרוע ביותר % | הערה                                   |
| ---------- | ------: | -----------: | -------------------------------------- |
| רוחב עמידה |     72% |          60% | צוואר בקבוק — יש חוסר עקביות בין חזרות |

---

## בריאות דו״ח (OK/WARN/FAIL)

* חוקים (דוגמאות):

  * אין תרגיל → `FAIL`
  * `unscored_reason` → `WARN`
  * `coverage.available_pct < 60` → `WARN`
  * `missing_critical` לא ריק → `FAIL`
  * `camera.visibility_risk` → `WARN`
  * `scoring.quality == "poor"` → `WARN`
* הפלט:

  ```json
  {"status":"OK|WARN|FAIL","issues":[{"code":"LOW_COVERAGE","level":"WARN","message":"…"}]}
  ```

---

## UX/UI — עקרונות, טבלאות, והתנהגות RTL/LTR

### מבנה מסך

1. **Header**: שם תרגיל/משפחה/ציוד (לפי שפה) + חיווי חיבור/Health/Ready.
2. **Gauges**: חזרה אחרונה / סט אחרון — שואבים `ui_ranges.color_bar`.
3. **כרטיס “הכול במקום אחד”**:

   * ציון כולל (%), איכות, unscored_reason.
   * טבלת “נמדד מול יעד”.
   * “מוקדי שיפור בסט”.
4. **Modal פירוט חזרה**:

   * טבלת: קריטריון | נמדד | יעד | % | הערה.
   * סידור לפי חומרה (קריטי/חשוב/מינורי/עבר).

### כללי פריסה

* עטיפת טבלאות ב־`.table-wrap { overflow-x:auto }`.
* `min-width: 720px` לטבלת הקריטריונים כדי שלא “תברח שמאלה”.
* RTL/LTR: להחיל `dir="rtl"` בעמודים עבריים, וליישר מספרים לימין.

---

## תרשים זרימת נתונים

```
Video → Pose/OD → canonical + per_criterion_scores
                  ↓
           availability (requires)
                  ↓
           report_builder
             ├─ i18n (aliases.names/labels)
             ├─ thresholds → targets
             ├─ rep_critique / set_critique
             └─ report_health + camera
                  ↓
                 UI
```

---

## מקרי קצה ושגיאות

| מקרה                     | טיפול                                        |
| ------------------------ | -------------------------------------------- |
| אין thresholds לקריטריון | מציג “—” ביעד; הערה כללית (“ביצוע נקי/שפר…”) |
| missing_critical         | `unscored_reason` + `report_health: FAIL`    |
| ערך מדידה לא מספרי       | מציג “—”, לא מכשיל את הדו״ח                  |
| העדר תווית ב־aliases     | fallback למפתח הקנוני                        |
| אין phrases              | הערות אוטומטיות לפי אחוז ציון                |

---

## ביצועים, ניטור ולוגים

* **O(מס’ קריטריונים × מס’ חזרות)** — זניח ביחס ל-CV.
* לוגים:

  * `report_builder` מוציא שורת INFO עם `exercise.id`, `score_pct`, `health.status`.
  * אזהרות: שדה חסר ב־`aliases`/`thresholds` → WARN (לא עוצר).

---

## בדיקות קבלה (QA Checklist)

### פונקציונל

* [ ] שמות תרגיל/משפחה/ציוד מוצגים לפי שפה.
* [ ] “נמדד מול יעד” מתמלא בכל חזרה/סט.
* [ ] צבעי Gauges לפי `ui_ranges`.
* [ ] `rep_critique` מופיע עם הערות הגיוניות.
* [ ] `set_critique` מציג צווארי בקבוק נכונים.
* [ ] `report_health` תואם מצבים (missing_critical → FAIL וכו’).

### לוקליזציה

* [ ] מעבר `display_lang` משנה את כל הכיתובים הרלוונטיים.
* [ ] RTL נקי: מספרים מיושרים נכון, הטבלה לא “בורחת”.

### חוסן

* [ ] דו״ח לא נופל כשחסר threshold/label.
* [ ] ערכי מדידה חריגים לא שוברים את העמודה/החישוב.

---

## Roadmap — שיפורים עתידיים

1. **משקלי תרומה פר-קריטריון ב-Tooltip**: לצבוע לפי משקל ולא רק לפי אחוז.
2. **Benchmarks אישיים**: יעד דינמי לפי היסטוריה (PRs).
3. **Coach Hints חכמים**: חוקים מותנים זמן/רצף (למשל 3 חזרות רצופות shallow).
4. **סיכום אימון יומי/שבועי**: גרפים מסכמים ב-UI.
5. **A/B לטקסטים**: ניסוח הערות מותאם לאישיות/העדפות.
6. **נגישות (a11y)**: קריינות/קונטרסט, קיצורי מקלדת ל-Modal.

---

## עמדת העורך (המלצות ודגשים)

* **הדבר הכי חשוב למשתמש** הוא לראות מהר: *מה יצא לי? ומה לשפר עכשיו?*
  הטבלה “נמדד מול יעד” + “מוקדי שיפור בסט” עונות בדיוק על השאלות האלה.
* **אל תעמיסו טקסט**: עדיף משפט אחד ברור לכל קריטריון (עם יעד).
* **היסטוריית ביצועים** תעלה משמעותית ערך — אבל תשמרו על שכבה נקייה עכשיו, ותבנו אח״כ עמוד “סיכום אימון”.
* **איכות צילום** משפיעה ישירות על אמון — שימרו הודעת מצלמה תמציתית וברורה תמיד.

---

## נספחים

### A. מפה תמציתית של שדות מפתח ב־Payload

| קבוצה  | שדה                            | מקור             | הערות                 |
| ------ | ------------------------------ | ---------------- | --------------------- |
| מזהים  | `exercise.id/family/equipment` | YAML תרגיל       | משמש מפתח לאיתור שמות |
| שפה    | `display_lang`                 | פרמטר            | `he`/`en`             |
| תוויות | `ui.lang_labels`               | `aliases.names`  | fallback ל-id         |
| יחידות | `labels.<key>.unit`            | `aliases.labels` | fallback ריק          |
| מדידה  | `canonical[crit]`              | מנוע             | “—” אם חסר            |
| יעד    | `thresholds[crit]`             | YAML תרגיל       | min/max/range         |
| ציון   | `scoring.criteria[].score_pct` | מנוע             | 0–100                 |
| בריאות | `report_health`                | כללי בריאות      | OK/WARN/FAIL          |

### B. כללי ניסוח הערות אוטומטיות (ברירת מחדל)

| טווח ציון | he               | en                        |
| --------- | ---------------- | ------------------------- |
| ≥ 85%     | ביצוע נקי        | Clean execution           |
| 70–84%    | אפשר לשפר {שם}   | Could improve {name}      |
| < 70%     | שפר {שם} (יעד …) | Improve {name} (target …) |

---

**סוף המסמך.**
כשתאשר — אעביר לך (בפעם אחת) את שלושת החלקים המוכנים להדבקה:

1. עדכון `report_builder.py` (בונה הדו״ח בפורמט המדויק),
2. תוספות HTML/CSS לטבלאות וה-Modal,
3. הרחבות JS (רינדור טבלת “נמדד מול יעד”, חיוויים ו־tooltips).
