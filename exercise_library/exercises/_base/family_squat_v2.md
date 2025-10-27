בשמחה ✅
הנה קובץ **Markdown תיעודי מלא** עבור `squat.base.yaml`, מוכן לשמירה כ־
`docs/exercises/families/squat_base.md`
(או בכל מיקום דוקומנטציה אחר שלך).

---

````markdown
# 🧠 squat.base.yaml — משפחת סקוואט (Base)

## 🎯 מטרת הקובץ
הקובץ `squat.base.yaml` מגדיר את **החוקים הבסיסיים והקריטריונים של משפחת ה־Squat**.  
הוא **לא נבחר ישירות באימון**, אלא משמש בסיס שממנו יורשים כל הוריאנטים:
- `squat_bodyweight.yaml`  
- `squat_dumbbell.yaml`  
- `squat_barbell.yaml`

הקובץ כולל את כללי הניקוד, ספי בטיחות, וספירת החזרות המשותפים לכל סוגי הסקוואט.

---

## 🧩 תפקיד במערכת
1. **Pose + ObjDet** יוצרים נתונים גולמיים (keypoints + ציוד).
2. **Normalizer + aliases.yaml** ממפים אותם לשמות קנוניים (canonical).
3. המסווג (`classifier.pick`) מסיק ציוד → בוחר את הווריאנט הנכון לפי `match_hints`.
4. מנוע הציון (`scoring engine`) מחשב ניקוד לפי הקריטריונים והחוקים המוגדרים כאן.

---

## ⚙️ פרטי המטא (Meta)
| שדה | ערך | הסבר |
|------|------|------|
| `id` | `squat.base` | מזהה ייחודי למשפחה |
| `family` | `squat` | שם המשפחה |
| `meta.selectable` | `false` | לא נבחר באימון |
| `meta.display_name` | `"Squat (Base)"` | שם תצוגה כללי |

---

## 📊 קריטריונים
הקריטריונים מחולקים לשלוש קבוצות:

### 1. בטיחות (Safety)
| שם | דרישות נתונים | תיאור |
|------|----------------|--------|
| `spine_rounding` | `spine_flexion_deg` | עגילת גב – עמוד השדרה אמור להישאר ניטרלי |
| `knee_valgus` | `knee_foot_alignment_left_deg`, `knee_foot_alignment_right_deg` | קריסת ברכיים פנימה |
| `spine_sidebend` | `spine_curvature_side_deg` | עיקום צדדי של הגב |

### 2. טכניקה (Technique)
| שם | דרישות נתונים | תיאור |
|------|----------------|--------|
| `depth` | `knee_left_deg`, `knee_right_deg` | עומק הירידה – כמה קרוב ל־90° |
| `stance_width` | `features.stance_width_ratio` | יחס רוחב עמידה לכתפיים |
| `foot_angle` | `toe_angle_left_deg`, `toe_angle_right_deg` | פישון קל של הרגליים החוצה |
| `head_alignment` | `head_pitch_deg`, `spine_flexion_deg` | הראש בקו עם עמוד השדרה |
| `heels_grounded` | `heel_lift_left`, `heel_lift_right` | עקבים צריכים להישאר צמודים לקרקע |
| `tempo` | `rep.timing_s` | מהירות החזרה – לא מהירה מדי ולא איטית מדי |

### 3. מידע נוסף (Feedback)
| שם | דרישות נתונים | תיאור |
|------|----------------|--------|
| `posture` | `torso_forward_deg` | מידע כללי על זווית הגו |
| `dorsiflexion` | `ankle_dorsi_left_deg`, `ankle_dorsi_right_deg` | טווח תנועה בקרסול (לפידבק בלבד) |

---

## ⚠️ קריטריונים קריטיים
אם חסר אחד מהקריטריונים הבאים → לא ניתן לחשב ציון:
```yaml
critical: [spine_rounding, knee_valgus, depth]
````

אלו נבחרו כי הם מייצגים **בטיחות ועומק תנועה**, שני מדדים חיוניים לכל סקוואט.

---

## 🧮 מדיניות הניקוד (scoring.policy)

```yaml
policy:
  missing: skip
  min_criteria_for_full_quality: 3
```

* קריטריונים חסרים שאינם קריטיים → מדולגים (לא מורידים ציון).
* אם פחות מ־3 קריטריונים זמינים → איכות כוללת נחשבת חלקית (partial).

---

## ⚖️ כללי הניקוד (scoring.criteria)

### בטיחות

| קריטריון         | כלל                        | משמעות                      |
| ---------------- | -------------------------- | --------------------------- |
| `spine_rounding` | `linear_band` בין 0–35°    | מעל 35° עגילה חריגה         |
| `knee_valgus`    | `symmetric_threshold` ±20° | סטייה מעל 10° מסוכנת        |
| `spine_sidebend` | `symmetric_threshold` ±20° | עיקום צדדי גבוה מוריד ניקוד |

### טכניקה

| קריטריון         | כלל                          | משמעות                            |
| ---------------- | ---------------------------- | --------------------------------- |
| `depth`          | `threshold_window` 90°–150°  | עד 90° ציון מלא, מעבר לכך לא משפר |
| `stance_width`   | `band_center` 0.9–1.2        | רוחב עמידה מאוזן לכתפיים          |
| `foot_angle`     | `band_center` 8°–20°         | פישון טבעי של הרגליים             |
| `head_alignment` | `symmetric_threshold` ±10°   | הראש והגב באותו קו                |
| `heels_grounded` | `boolean_flag`               | עקבים צמודים לקרקע = טוב          |
| `tempo`          | `tempo_window` 0.7–2.5 שניות | מהירות תנועה תקינה                |

### פידבק בלבד

| קריטריון       | כלל                         | משמעות                       |
| -------------- | --------------------------- | ---------------------------- |
| `dorsiflexion` | `threshold_window` מינ׳ 25° | מידע בלבד, לא משפיע על הציון |

---

## 🧮 שקלול סופי

```yaml
aggregate:
  method: weighted_mean
  weights_source: inline
```

כל הקריטריונים משוקללים לפי משקלם היחסי.

---

## 🛡️ תקרות בטיחות (Safety Caps)

תקרות אלו מגבילות את הציון הסופי במקרה של ביצוע מסוכן:

| תנאי                 | תקרה      |
| -------------------- | --------- |
| spine_rounding ≤ 0.6 | cap: 0.70 |
| knee_valgus ≤ 0.6    | cap: 0.75 |
| spine_sidebend ≤ 0.6 | cap: 0.80 |

---

## 🧭 רמזים לזיהוי (match_hints)

אלו מאפיינים כלליים של משפחת הסקוואט:

```yaml
match_hints:
  must_have: [pose.available]
  pose_view: ["front", "front_left", "front_right"]
  motion_pattern: ["hip_down", "knee_flexion"]
  joints_focus: ["hips", "knees", "spine"]
```

הוריאנטים (bodyweight, dumbbell, barbell) יוסיפו:

* `meta.equipment`: סוג הציוד
* `must_have`: דגל ציוד מתאים (`objdet.bar_present`, `objdet.dumbbell_present` וכו’)
* `must_not_have`: דגלי ציוד אחרים (כדי למנוע בלבול)

---

## 🔁 ספירת חזרות (rep_signal)

```yaml
rep_signal:
  source: "value|min|hip_y_px"
  thresholds:
    min_rom_good: 60
    min_rep_ms: 500
    max_rep_ms: 7000
```

המערכת משתמשת בתנועת האגן (hip_y_px) לזיהוי תחילת/סוף חזרה.

---

## 📘 סיכום קצר

| היבט      | מטרה                                                 |
| --------- | ---------------------------------------------------- |
| 🎯 עומק   | 90° מעניק ציון מלא, עומק נוסף לא מוסיף ניקוד         |
| 🦶 עקבים  | עקבים חייבים להיות צמודים לרצפה                      |
| 🦵 ברכיים | סטייה גדולה מ־10° כלפי פנים נחשבת שגיאה              |
| 🧍 יציבה  | גב ניטרלי, ראש בקו עם עמוד השדרה                     |
| ⏱️ טמפו   | חזרה בין 0.7 ל־2.5 שניות = תקין                      |
| ⚖️ בטיחות | spine_rounding / valgus / sidebend מגבילים ציון כולל |

---

## 🧩 תפקיד בקונטקסט של המערכת

* **המסווג** (`classifier.pick`) משתמש ברמזים ובציוד כדי לזהות תרגיל שייך למשפחה זו.
* **המנוע הקינמטי** מספק מדידות (`knee_left_deg`, `spine_flexion_deg`, וכו’).
* **המנוע הסקורינג** מחשב את הניקוד הכולל לפי חוקי הקובץ.
* **דוחות / Admin UI** משתמשים במידע כדי להציג פידבק בזמן אמת או בסיכום סט.

---

## 🧱 תקיות רלוונטיות

```
exercise_library/
└─ exercises/
   ├─ _base/
   │  └─ squat.base.yaml
   └─ packs/
      ├─ bodyweight/squat/squat_bodyweight.yaml
      ├─ dumbbell/squat/squat_dumbbell.yaml
      └─ barbell/squat/squat_barbell.yaml
```

---

## 💡 טיפ למפתחים

כאשר מוסיפים תרגיל חדש:

1. השתמשו בקובץ הזה כבסיס.
2. צרו קובץ חדש לווריאנט עם ציוד (equipment + match_hints).
3. בדקו שהקריטריונים תואמים ל־`aliases.yaml` הקיים.
4. הפעילו את הבדיקה:

   ```bash
   pytest -q tools/tests/test_<exercise>_detect_and_score.py
   ```
5. ודאו שכל המדדים זמינים ב־payload (`pose.available=True`, וכו’).

---

## 📎 קובץ מקושר

* [`aliases.yaml`](../../aliases.yaml) — מיפוי שמות raw → canonical
* [`exercise_engine/classifier/classifier.py`](../../exercise_engine/classifier/classifier.py) — לוגיקת הבחירה
* [`exercise_engine/scoring/scoring_core.py`](../../exercise_engine/scoring/scoring_core.py) — חישוב הציון

---

**נכתב בהתאם למודל הביומכני של סקוואט תקין:**

* גב ניטרלי
* ראש בקו עמוד השדרה
* עקבים נעוצים ברצפה
* פישון קל של כפות הרגליים
* עומק עד 90° מעניק ציון מלא
* שמירה על בטיחות מפרקי ברך ועמוד שדרה

---

```

רוצה שאבנה לך עכשיו גם את קובץ ה־MD לדוגמה עבור **`squat_bodyweight.yaml`** (כדי שהכל יהיה באותו פורמט)?
```
