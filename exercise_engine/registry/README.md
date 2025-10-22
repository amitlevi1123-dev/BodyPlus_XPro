מצוין — זה מבנה מעולה למסמכי התיעוד שלך 🔥
כדי להתאים את ה־`README.md` הזה לכל השינויים שביצענו במערכת ובמנוע הציונים, הנה הגרסה **המעודכנת והמדויקת ביותר**.
היא כוללת את כל השדרוגים, את שמות הקבצים הנוכחיים, ואת ההקשר המדויק בתוך מבנה הספריות שלך.

---

# 📘 סקירת ספריית התרגילים (Library Loader · Schema · Preflight)

מסמך זה מסביר **בצורה ברורה ופשוטה** את המערכת שאחראית לטעינת התרגילים —
שלושת הקבצים המרכזיים שמבצעים את כל ניהול ה־YAML, האימותים וההכנה למנוע הציונים:

* `loader.py` – טעינה ובנייה של ספריית התרגילים (כולל ירושה וגרסאות)
* `schema.py` – ולידציה לוגית וסכמטית של כל רכיבי הספרייה
* `preflight.py` – בדיקות "לפני טעינה" (Pre-Reload) למניעת ספרייה שבורה בזמן אמת

---

## 🎯 מטרת המערכת

להבטיח שכל קבצי ה־YAML של התרגילים —
(`aliases.yaml`, `phrases.yaml`, ו־`exercises/`)
ייטענו בצורה יציבה, תקינה וללא ניגודים,
כך שמנוע הציונים וה־runtime יוכלו לעבוד **רצוף וללא שגיאות**.

---

## 🧩 תפקידי הקבצים

### 🟩 `loader.py` — טעינת ספריית התרגילים

**מטרה:**
לקרוא את כל רכיבי הספרייה מתוך `exercise_library/`,
לבצע **מיזוג ירושה חכם** (`extends`), ולבנות אובייקט `Library` מוכן לשימוש במנוע.

**קורא:**

* `aliases.yaml` – מפתחות קנוניים, אליאסים ויחידות מדידה
* `phrases.yaml` – משפטים/טיפים לפי שפה
* `exercises/` – כל קובצי ה־YAML של משפחות ווריאנטים

**בונה:**

* מבנה אחיד של כל התרגילים אחרי `extends`
* שדות נורמליים:

  * `criteria`, `critical`, `thresholds`, `weights`
  * `meta`, `family`, `display_name`
* אינדקסים: לפי **ID** ולפי **family**
* גרסה (`version`) מחושבת (hash מכל הקבצים)
* **fingerprint** לכל קובץ (SHA256)

**התנהגות בשגיאה:**

* זורק `RuntimeError` עם תיאור מלא:

  * YAML לא תקין
  * `id` כפול
  * מעגלי `extends`
  * קריטריונים לא חוקיים

---

### 🟨 `schema.py` — ולידציה לוגית וסכמטית

**מטרה:**
לוודא שכל רכיב במערכת עומד בכללי המבנה וההיגיון.
בדיקות אלו רצות גם בזמן טעינה וגם לפני הפעלה במנוע.

**בודק:**

* **aliases.yaml:**

  * קיום מפתחות `canonical_keys`
  * טיפוסי נתונים תקינים (`unit`, `aliases`, `tolerances`)
* **phrases.yaml:**

  * מבנה תקין לפי שפה (`he`, `en`)
  * אזהרה על משפטים כפולים/שגויים
* **exercises/:**

  * לכל תרגיל יש `id` תקף (ללא רווחים)
  * `criteria` הוא מילון (dict) בלבד
  * `critical` ⊆ `criteria`
  * `thresholds` ערכים מספריים בלבד
  * `weights_override` חיוביים
  * כל `requires` הוא רשימת מחרוזות
  * אין כפילויות `id` או `family`
* בדיקה מתקדמת:

  * כל מפתח ב־`requires` ללא נקודה (למשל `knee_left_deg`) קיים ב־`aliases.yaml`

**פלט:**
`ValidationReport(errors, warnings)` — תואם לממשק של `preflight`.

---

### 🟦 `preflight.py` — בדיקות לפני טעינה

**מטרה:**
למנוע טעינה של ספרייה שבורה בזמן אמת (Admin UI / Live reload).

**שלבים:**

1. מפעיל את `schema.validate_library()`
2. מריץ בדיקה יבשה (Dry run):

   * כל תרגיל מכיל לפחות קריטריון אחד
   * אין וריאנט שמצביע ל־base חסר
3. (אופציונלי) בדיקות עומק על `sample_payloads` —
   אם סופקו דגימות נתונים, מציין קריטריונים שלא הופיעו אף פעם.

**פלט:**

```python
PreflightResult(
    ok: bool,
    errors: List[str],
    warnings: List[str],
    notes: List[str]
)
```

---

## 📊 תרשים זרימה (Mermaid)

```mermaid
flowchart TD
    A[exercise_library<br/>(aliases.yaml, phrases.yaml, exercises/*.yaml)] --> B[loader.load_library]
    B -->|Library (merged + validated)| C[preflight.run_preflight]
    C -->|calls| D[schema.validate_library]
    D --> C
    C -->|ok=True| E[Live Engine / Runtime / Scoring]
    C -->|ok=False| F[Stop & Show Report in Admin UI]
```

---

## ⚙️ תהליך טיפוסי בקוד

```python
from exercise_engine.registry import loader, preflight

# 1️⃣ טעינת ספרייה מלאה
lib = loader.load_library("exercise_library")

# 2️⃣ בדיקת פרה-פלייט
ex_map = {ex.id: ex.raw for ex in lib.exercises}
report = preflight.run_preflight(
    aliases=lib.aliases,
    phrases=lib.phrases,
    exercises_merged_by_id=ex_map
)

# 3️⃣ החלטה על המשך טעינה
if report.ok:
    print("Library loaded successfully ✅")
else:
    print("Library load failed ❌")
    print("\n".join(report.errors))
```

---

## 📘 חיבור למנוע הציונים

לאחר טעינה תקינה (`lib`):

1. `runtime.runtime.run_once(...)` יקבל את הספרייה (`library=lib`)
2. `calc_score_yaml.py` ישתמש בנתונים מ־`ex.thresholds`, `ex.weights`, ו־`ex.criteria`
3. ה־`report_builder` ייצור דוח מלא על בסיס הציונים

> 💡 כלומר: **אין שום קוד קשיח בתרגילים עצמם** –
> כל הנתונים נמשכים ישירות מה־YAML שנבדק ואושר ע״י המנגנון הזה.

---

## ✅ סיכום קצר (TL;DR)

| קובץ           | תפקיד עיקרי                  | מה בודק/בונה                  | מתי רץ                 |
| -------------- | ---------------------------- | ----------------------------- | ---------------------- |
| `loader.py`    | טוען וממזג את כל קבצי ה-YAML | מבנה הספרייה המאוחד + גירסה   | בזמן עליית המנוע       |
| `schema.py`    | בודק תקינות ולוגיקה פנימית   | aliases / phrases / exercises | בזמן טעינה / preflight |
| `preflight.py` | בודק תקינות לפני הפעלה חיה   | מחזיר דו"ח שגיאות/אזהרות      | לפני reload או deploy  |

---

## 🧠 טיפ למפתחים

* שמור תמיד עותק של `exercise_family_template.yaml` ו־`exercise_variant_template.yaml`
  בתיקייה הראשית של `exercise_library/` — כך אפשר להוסיף תרגילים חדשים בקלות.
* כל שינוי ב־`aliases.yaml` או ב־`criteria` יחייב **טעינה מחדש (Reload)**.
* אם יש שגיאת YAML — אל תנסה לתקן בקוד. תקן את הקובץ, והרץ `preflight` מחדש.

---

📁 מומלץ לשים את הקובץ הזה בתיקייה:
`exercise_engine/registry/README.md`
כדי שכל מי שנכנס לקוד יבין מיד את הזרימה, את התפקיד של כל רכיב, ואיך הוא משתלב במנוע הציונים וב־runtime.

---

רוצה שאמשיך עכשיו באותו פורמט גם עם
📊 **README למנוע הציונים עצמו (`calc_score_yaml.py`)** –
כדי שיהיה תיעוד תואם אחד לשני?
