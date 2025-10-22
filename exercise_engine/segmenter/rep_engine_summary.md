מוכן להדבקה ישירה כ־`docs/REPS_SETS_ONEPAGER.md` – עם כל התיקונים שבוצעו בפועל בקוד (runtime + reps + set_counter), כך שכל הסעיפים תואמים למה שבאמת קורה במערכת העדכנית שלך.

---

# דף אפיון — ספירת חזרות וסטים (Reps & Sets)

**גרסה:** v1.1
**עודכן:** אוקטובר 2025
**תחום:** BodyPlus_XPro / Exercise Engine
**מטרה:** ספירה אמינה, פשוטה וחסינה רעשים של חזרות וסטים, לכל התרגילים, עם מינימום ספים ויכולת כיוונון ברורה.

---

## 1) מה המערכת עושה בקצרה

1. **בחירת תרגיל (Classifier)** — חייב להיות תרגיל **נעול** לפני ספירה.
2. **מנוע חזרות (FSM)** — מזהה חזרה במחזור: `start → towards → turn → away → close`.
3. **שער סגירה (Gate)** — נבדקים ארבעה תנאים (זמן, היפוך, קרבה למוצא, ROM).
4. **איכות** — `good` / `partial` (נספרות) או `short/fast/slow/incomplete` (לא נספרות).
5. **SetCounter** — סט נפתח אוטומטית בחזרה הראשונה ונסגר ב־timeout או ידנית.
6. **החלפת תרגיל באמצע** — אם עברנו את ה־`turn`, סוגרים חזרה אחת (on-switch), נספרת אך לא מנוקדת.

---

## 2) תרשים זרימה כולל

```
Frame
  └─ Normalize (aliases) ──► Classifier picks exercise
                               │
                               ├─ אין נעילה → לא סופרים (rep.* ניטרלי)
                               └─ יש נעילה → Reps FSM
                                     start → towards → turn → away
                                                │
                                                └─ Close Gate (4 תנאים)
                                                    ├─ עבר → rep_event (good/partial)
                                                    └─ לא עבר → לא נספר (short/fast/slow/incomplete)
                                     ▼
                                  SetCounter
                                   • set.begin / rep_event / timeout / set.end
                                     ▼
                                  Report (מזריק rep.* + set.*)
```

---

## 3) הגדרת סיגנל (Rep Signal)

### 3.1 איפה מוגדר

ב־`*.base.yaml` של משפחת התרגיל, תחת `rep_signal`.

### 3.2 דוגמה טיפוסית

```yaml
rep_signal:
  source: "angle|min|knee_left_deg,knee_right_deg"
  target: "min"
  units: "deg"
  thresholds:
    phase_delta: 5
    min_turn_ms: 100
    min_rep_ms: 500
    max_rep_ms: 6000
    min_rom_good: 25
    min_rom_partial: 18
```

**הסבר קצר:**

* **source** – מאיזה מדדים נבנה הסיגנל ואיך מאחדים.
* **target** – הכיוון הראשון (“למטה” או “למעלה”) לפי יעד min/max.
* **units** – מעלות / ratio / px.
* **thresholds** – ספים לתנועה אמיתית, זמנים ו־ROM.

> אם אין `rep_signal`, מופעל Auto-Pick (ברך/ירך/מרפק/כתף → יבחר min angle או y_px) ויגיע `rep.warnings.auto_target_used=true`.

---

## 4) מכונת מצבים (FSM)

### 4.1 מצבים

* **start** — חוסר תנועה משמעותית.
* **towards** — תנועה עקבית לעבר ה־target.
* **turn** — היפוך כיוון עם השהייה (`min_turn_ms`).
* **away** — תנועה חזרה כלפי top_like.
* **close** — Gate → `rep_event`.

### 4.2 מעברים

* start→towards — שינוי כיוון משמעותי (≥ phase_delta).
* towards→turn — שינוי מגמה + רישום turn_ts.
* turn→away — עמידה ≥ min_turn_ms.
* away→close — Gate עומד בכל התנאים (להלן סעיף 5).

---

## 5) שער סגירה (Gate)

חזרה נחשבת תקפה (rep_event) רק אם מתקיימים כל התנאים:

| תנאי               | תיאור                                                                                         | תוצאה אם נכשל |                                |            |
| ------------------ | --------------------------------------------------------------------------------------------- | ------------- | ------------------------------ | ---------- |
| **1. זמן כולל**    | `min_rep_ms ≤ timing ≤ max_rep_ms`                                                            | fast / slow   |                                |            |
| **2. היפוך אמיתי** | השהייה ≥ min_turn_ms                                                                          | incomplete    |                                |            |
| **3. חזרה למוצא**  | `                                                                                             | Δ_to_top      | ≤ max(phase_delta, 0.4 × ROM)` | incomplete |
| **4. ROM**         | `ROM ≥ min_rom_good` → good<br>`min_rom_partial ≤ ROM < min_rom_good` → partial<br>אחרת short | short         |                                |            |

---

## 6) החלפת תרגיל בזמן חזרה

* אם **לא פעיל rep** → אין שינוי.
* אם פעיל ו**עבר turn** → סוגרים מייד (on-switch).

  * `rep.flags.closed_on_switch=true`
  * נספרת לסט, לא לניקוד תרגיל.
* אם **לפני turn** → מתבטל, לא נספר.

---

## 7) מנגנון הסטים (SetCounter)

* **start**: ב־rep הראשון או `set.begin=true`.
* **end**: לאחר `reset_timeout_s` שניות בלי חזרה, או `set.end=true`.
* **min_reps**: ברירת מחדל 1 – מונע איבוד סטים קצרים.

שדות חיים:

```
rep.set_active, rep.set_index, rep.set_reps, rep.set_total,
rep.set_last_ok, rep.set_last_reps, rep.set_last_duration_s
```

ב־runtime, הסטים מעודכנים בכל frame דרך:

```python
SETS.handle_signals(raw_metrics, now_ms)
SETS.update(rep_event, now_ms)
SETS.inject(canonical)
```

---

## 8) ערכי ברירת מחדל מעודכנים

| פרמטר                   |      `deg` |    `ratio` |       `px` |
| ----------------------- | ---------: | ---------: | ---------: |
| phase_delta             |         5° |       0.03 |          4 |
| min_turn_ms             |        100 |        100 |        100 |
| min_rep_ms / max_rep_ms | 500 / 6000 | 500 / 6000 | 500 / 6000 |
| min_rom_good            |        25° |       0.12 |         35 |
| min_rom_partial         |        18° |       0.08 |         24 |
| reset_timeout_s (סט)    |          7 |          7 |          7 |

---

## 9) שינויי פרמטרים (כיוונון)

### ברמת YAML

```yaml
rep_signal:
  thresholds:
    phase_delta: 4
    min_turn_ms: 120
    min_rom_good: 22
    min_rom_partial: 16
    min_rep_ms: 450
    max_rep_ms: 5500
```

### הנחיות:

* מפספס חזרות → הורד `phase_delta` / `min_rom_partial`.
* סופר רעש → העלה `phase_delta` / `min_turn_ms`.
* מהיר מדי / איטי מדי → כוונן `min_rep_ms` / `max_rep_ms`.

---

## 10) דוגמה — סקוואט

**Signal:** `angle|min|knee_left_deg,knee_right_deg`, `target=min`, `units=deg`.

רצף:
`start(180°) → towards(↓) → turn(≈90°, ≥100ms) → away(↑) → close`

תוצאות:

* `ROM=80°, timing=2.0s` → good
* `ROM=20°, timing=1.5s` → partial
* `ROM=10°` → short
* החלפת תרגיל אחרי turn → נסגר on-switch → נספר, לא מנוקד.

---

## 11) לוגים מומלצים (QA)

* `rep.quality`
* `rep.close_reason`
* `rep.errors.*`
* `rep.signal_key`
* `rep.distance_to_top_at_close`
* `rep.flags.closed_on_switch`
* `rep.set_*`

---

## 12) בדיקות מומלצות

1. חזרה אחת טובה → נספרת (`good`).
2. חזרה חלקית → נספרת (`partial`).
3. חזרה קצרה / מהירה מדי → לא נספרת (`short/fast`).
4. `set.begin/set.end` סוגרים סט ידנית.
5. סט נסגר אוטומטית אחרי timeout (7s).
6. כל השדות `rep.*` + `set.*` מופיעים ב־report.

---

## 13) למה זה יציב

* **FSM פשוט** — 4 מצבים בלבד, אין תלות בתרגיל.
* **SetCounter עצמאי** — מונע אובדן סטים.
* **סף min_turn_ms** מונע false turn.
* **phase_delta + ROM יחסי** מונעים רעש.
* **on-switch handling** — מעבר תרגיל לא מאבד חזרה.

---

### נספח — מפת מפתחות עיקריים

| מפתח                                                          | יחידה        | הסבר                                    |
| ------------------------------------------------------------- | ------------ | --------------------------------------- |
| rep.state                                                     | text         | start/towards/turn/away                 |
| rep.active                                                    | bool         | חזרה פעילה                              |
| rep.dir                                                       | text         | inc/dec                                 |
| rep.rom                                                       | deg/ratio/px | טווח תנועה                              |
| rep.progress                                                  | ratio        | 0–1                                     |
| rep.timing_s / rep.ecc_s / rep.con_s                          | s            | זמני חזרה                               |
| rep.rest_s                                                    | s            | מנוחה מאז חזרה אחרונה                   |
| rep.quality                                                   | text         | good/partial/short/fast/slow/incomplete |
| rep.rep_id                                                    | count        | מונה חזרות                              |
| rep.set_active / rep.set_index / rep.set_reps / rep.set_total | —            | פרטי סט בזמן אמת                        |

---

### הערה אחרונה

המנוע לא ישתנה — רק הכוונונים (`thresholds`) ישתנו לפי משפחה.
הליבה נשמרת יציבה ומובנת.

---

רוצה שאוסיף גרסה מקוצרת שלו (לשימוש בתיעוד תוך־מערכת או בעמוד Admin Help)?
