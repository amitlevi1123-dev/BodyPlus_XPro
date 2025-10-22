# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# payload_push_diagnoser.py — אבחון עומק ל- /api/payload_push (Timeouts)
# -----------------------------------------------------------------------------
# מטרת הקובץ (בקצרה):
#   קובץ בדיקה "הכול כלול" שמטרתו לעזור לך להבין ולבודד למה מתקבלים
#   WARNING: payload_push timeout בלוג של השרת. התסריט מריץ סדרת בדיקות
#   סיסטמטיות ובסוף יוצר דו"ח מסודר (TXT + JSON + CSV) עם הסברים,
#   תובנות, והמלצות.
#
# למה נועד האבחון הזה ("למה זה עושה את זה"):
#   • לבדוק אם /api/payload_push איטי בפני עצמו (גם כששולחים JSON קטן).
#   • לבדוק אם יש בעיית עומס/הצפה (קצב שליחה גבוה מדי => תור מתמלא/Rate limit).
#   • לבדוק אם השרת עושה עיבוד כבד בתוך הראוט במקום להחזיר מהר.
#   • לבדוק אם גודל ה-JSON מוגזם או אם יש ערכים בעייתיים (NaN/Inf) שמייצרים תקלה.
#   • לבדוק תנאי תחרות/נעילות (שליחה מקבילית) שיכולים לעכב תגובה.
#
# איך משתמשים (שלבים):
#   1) ודאו שהשרת שלכם רץ מקומית (ברירת מחדל: http://127.0.0.1:5000).
#   2) אם ה-EndPoint שונה, עדכנו BASE_URL ו-PUSH_PATH למטה.
#   3) הרצאה:
#        python payload_push_diagnoser.py
#      אפשרויות:
#        python payload_push_diagnoser.py --url http://127.0.0.1:5000 --path /api/payload_push --hz 10
#        python payload_push_diagnoser.py --concurrency 8 --duration 10
#   4) בסוף ייווצרו קבצים בתקיית ./diagnostics_output:
#        - payload_push_report.txt     (דו"ח קריא בעברית)
#        - payload_push_report.json    (תקציר ממוכן)
#        - payload_push_samples.csv    (כל המדידות לדיבוג)
#
# עקרונות חשובים:
#   • מודדים "זמן סוף-סוף" (client-side) ומסיקים האם יש Return-Fast.
#   • בודקים גם תחת הצפה והקבלה מקבילית.
#   • נותנים הסבר "למה זה קורה" על סמך הדאטה שנמדד, לא ניחוש.
#
# התאמה לקוד שלך:
#   • אם השרת מחזיר dt_ms — נשתמש בו.
#   • אם השרת מחזיר skipped="rate_limited" / error="queue_full" — נזהה ונציג.
#
# דרישות:
#   • Python 3.8+
#   • עדיף 'requests'. אם אין — נשתמש ב-urllib.
# -----------------------------------------------------------------------------

from __future__ import annotations
import argparse, json, math, os, random, string, threading, time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# --------------- הגדרות ברירת מחדל (ניתן לשנות דרך CLI) -----------------
BASE_URL   = "http://127.0.0.1:5000"
PUSH_PATH  = "/api/payload_push"

# בדיקות עומס
DEFAULT_HZ          = 10     # קצב שליחה בבדיקה הרציפה (לחץ קל)
DEFAULT_DURATION_S  = 6      # משך בכל שלב (שניות)
DEFAULT_CONCURRENCY = 4      # מספר תהליכי שליחה מקביליים
SLOW_MS_THRESHOLD   = 200    # מתי נחשיב תשובה כ"אטית"
VERY_SLOW_MS        = 500    # מתי נחשיב כ"מאוד איטית"

# גדלי מטען לדוגמה
SMALL_PAYLOAD = {"ping": True, "ts": None, "note": "small"}

def make_large_payload(target_kb: int = 128) -> dict:
    """יוצר מטען גדול (מחרוזת אקראית) לניסוי השפעת גודל ה-JSON."""
    size = target_kb * 1024
    s = ''.join(random.choices(string.ascii_letters + string.digits, k=size // 2))
    return {"blob": s, "meta": {"kb": target_kb, "ts": None, "note": "large"}}

# JSON סטנדרטי לא תומך NaN/Inf — כאן בודקים כתוספת עמידות בצד השרת.
BAD_VALUES_PAYLOAD = {"v_nan": "NaN", "v_inf": "Infinity", "v_ninf": "-Infinity", "note": "bad_values"}

# ספריות רשת: requests אם יש, אחרת urllib
try:
    import requests
    HAVE_REQUESTS = True
except Exception:
    import urllib.request
    HAVE_REQUESTS = False

# --------------- מודלי נתונים לתוצאות ----------------------------------
@dataclass
class PushResult:
    ok: bool
    status: int
    elapsed_ms: float
    server_dt_ms: Optional[float]
    note: str
    is_rate_limited: bool
    is_queue_full: bool
    raw_json: Optional[Dict[str, Any]]

@dataclass
class PhaseSummary:
    name: str
    sent: int
    ok_count: int
    err_count: int
    rate_limited: int
    queue_full: int
    slow: int
    very_slow: int
    avg_elapsed_ms: float
    p95_elapsed_ms: float
    p99_elapsed_ms: float

# --------------- עזרי רשת -----------------------------------------------
def _post_json(url: str, obj: Dict[str, Any], timeout: float = 5.0) -> Tuple[int, Dict[str, Any], float]:
    """ שולח JSON ומחזיר (status, json, elapsed_ms_client_side). """
    start = time.perf_counter()
    if HAVE_REQUESTS:
        try:
            r = requests.post(url, json=obj, timeout=timeout)
            elapsed = (time.perf_counter() - start) * 1000.0
            try:
                data = r.json()
            except Exception:
                data = {}
            return r.status_code, data, elapsed
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return 0, {"error": str(e)}, elapsed
    else:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(obj).encode('utf-8'),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
                try:
                    data = json.loads(body)
                except Exception:
                    data = {}
                status = getattr(resp, "status", 200)
            elapsed = (time.perf_counter() - start) * 1000.0
            return status, data, elapsed
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return 0, {"error": str(e)}, elapsed

def push_once(base_url: str, path: str, payload: Dict[str, Any], note: str = "") -> PushResult:
    """בקשת POST אחת לנתיב, עם איסוף מדדים והסקת דגלים שימושיים."""
    url = f"{base_url.rstrip('/')}{path}"
    payload = dict(payload)
    payload["client_ts"] = datetime.now().isoformat(timespec='seconds')

    status, data, elapsed = _post_json(url, payload, timeout=5.0)
    ok = (200 <= status < 300) and isinstance(data, dict)
    is_rate_limited = bool(isinstance(data, dict) and data.get("skipped") == "rate_limited")
    is_queue_full   = bool(isinstance(data, dict) and data.get("error") == "queue_full")
    server_dt_ms: Optional[float] = None

    if isinstance(data, dict):
        dt = data.get("dt_ms")
        if isinstance(dt, (int, float)):
            server_dt_ms = float(dt)

    return PushResult(
        ok=ok,
        status=status,
        elapsed_ms=elapsed,
        server_dt_ms=server_dt_ms,
        note=note,
        is_rate_limited=is_rate_limited,
        is_queue_full=is_queue_full,
        raw_json=data if isinstance(data, dict) else None
    )

# --------------- איסוף סטטיסטיקות ---------------------------------------
def summarize_phase(name: str, results: List[PushResult]) -> PhaseSummary:
    sent = len(results)
    ok_count = sum(1 for r in results if r.ok)
    err_count = sum(1 for r in results if not r.ok)
    rate_limited = sum(1 for r in results if r.is_rate_limited)
    queue_full   = sum(1 for r in results if r.is_queue_full)
    slow = sum(1 for r in results if r.elapsed_ms >= SLOW_MS_THRESHOLD)
    very_slow = sum(1 for r in results if r.elapsed_ms >= VERY_SLOW_MS)
    elapsed_vals = sorted([r.elapsed_ms for r in results])
    avg = (sum(elapsed_vals) / sent) if sent else 0.0

    def pct(vs: List[float], p: float) -> float:
        if not vs:
            return 0.0
        k = max(0, min(len(vs) - 1, int(math.ceil(p * len(vs)) - 1)))
        return vs[k]

    p95 = pct(elapsed_vals, 0.95)
    p99 = pct(elapsed_vals, 0.99)
    return PhaseSummary(name, sent, ok_count, err_count, rate_limited, queue_full, slow, very_slow, avg, p95, p99)

# --------------- כותרות והדפסה יפה --------------------------------------
def hline() -> str:
    return "-" * 78

def fmt_ms(v: float) -> str:
    return f"{v:.1f} ms"

def print_phase_summary(ps: PhaseSummary) -> None:
    print(hline())
    print(
        f"[{ps.name}] sent={ps.sent} | ok={ps.ok_count} | err={ps.err_count} | "
        f"rate_limited={ps.rate_limited} | queue_full={ps.queue_full}"
    )
    print(
        f"AVG={fmt_ms(ps.avg_elapsed_ms)} | P95={fmt_ms(ps.p95_elapsed_ms)} | "
        f"P99={fmt_ms(ps.p99_elapsed_ms)} | slow(≥{SLOW_MS_THRESHOLD}ms)={ps.slow} | "
        f"very_slow(≥{VERY_SLOW_MS}ms)={ps.very_slow}"
    )

# --------------- שלבי בדיקה ---------------------------------------------
def phase_smoke(base_url: str, path: str) -> List[PushResult]:
    """בדיקת עשן: 5 פושים קטנים, מוודא קונפיג ותקינות בסיסית."""
    print("\n[PHASE 1] Smoke (פושים קטנים בודדים)")
    out: List[PushResult] = []
    for i in range(5):
        payload = dict(SMALL_PAYLOAD)
        payload["ts"] = datetime.now().isoformat()
        r = push_once(base_url, path, payload, note=f"smoke#{i+1}")
        out.append(r)
        print(
            f"  - {r.note}: status={r.status} elapsed={fmt_ms(r.elapsed_ms)} "
            f"server_dt={r.server_dt_ms} rate_limited={r.is_rate_limited}"
        )
    return out

def phase_rate(base_url: str, path: str, hz: int = DEFAULT_HZ, duration_s: int = DEFAULT_DURATION_S) -> List[PushResult]:
    """בדיקת קצב קבוע: שולח בקצב נתון ובודק האם יש האטה/דילוגים."""
    print("\n[PHASE 2] Rate Test (קצב קבוע)")
    out: List[PushResult] = []
    period = 1.0 / max(1, hz)
    t_end = time.time() + max(1, duration_s)
    i = 0
    while time.time() < t_end:
        i += 1
        payload = dict(SMALL_PAYLOAD)
        payload["ts"] = datetime.now().isoformat()
        r = push_once(base_url, path, payload, note=f"rate#{i}")
        out.append(r)
        print(
            f"  - {r.note}: status={r.status} elapsed={fmt_ms(r.elapsed_ms)} "
            f"server_dt={r.server_dt_ms} skipped={r.is_rate_limited}"
        )
        # שמירה על הקצב
        left = period - (r.elapsed_ms / 1000.0)
        if left > 0:
            time.sleep(left)
    return out

def phase_large(base_url: str, path: str, kb: int = 256, hz: int = 5, duration_s: int = 5) -> List[PushResult]:
    """בדיקת מטענים גדולים: האם גודל ה-JSON גורם לעיכוב/טיימאאוט."""
    print("\n[PHASE 3] Large Payload (מטען גדול)")
    out: List[PushResult] = []
    period = 1.0 / max(1, hz)
    t_end = time.time() + max(1, duration_s)
    i = 0
    while time.time() < t_end:
        i += 1
        payload = make_large_payload(target_kb=kb)
        payload["meta"]["ts"] = datetime.now().isoformat()
        r = push_once(base_url, path, payload, note=f"large#{i}")
        out.append(r)
        print(
            f"  - {r.note}: status={r.status} elapsed={fmt_ms(r.elapsed_ms)} "
            f"server_dt={r.server_dt_ms}"
        )
        left = period - (r.elapsed_ms / 1000.0)
        if left > 0:
            time.sleep(left)
    return out

def phase_bad_values(base_url: str, path: str) -> List[PushResult]:
    """בדיקת ערכים בעייתיים (NaN/Inf כמחרוזות) — האם השרת מסתדר עם זה."""
    print("\n[PHASE 4] Bad Values (NaN/Inf כמחרוזות)")
    out: List[PushResult] = []
    for i in range(3):
        payload = dict(BAD_VALUES_PAYLOAD)
        payload["idx"] = i
        r = push_once(base_url, path, payload, note=f"badvals#{i+1}")
        out.append(r)
        print(
            f"  - {r.note}: status={r.status} elapsed={fmt_ms(r.elapsed_ms)} "
            f"server_dt={r.server_dt_ms}"
        )
    return out

def phase_concurrency(base_url: str, path: str, concurrency: int = DEFAULT_CONCURRENCY, duration_s: int = 5) -> List[PushResult]:
    """בדיקת מקביליות: כמה תהליכים במקביל => האם יש פקקים/נעילות."""
    print("\n[PHASE 5] Concurrency (שליחה מקבילית)")
    out: List[PushResult] = []
    out_lock = threading.Lock()
    stop_at = time.time() + max(1, duration_s)

    def worker(tid: int):
        i = 0
        while time.time() < stop_at:
            i += 1
            payload = {"tid": tid, "i": i, "ts": datetime.now().isoformat(), "note": "concurrent"}
            r = push_once(base_url, path, payload, note=f"t{tid}#{i}")
            with out_lock:
                out.append(r)

    threads = [threading.Thread(target=worker, args=(i + 1,), daemon=True) for i in range(max(1, concurrency))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = sum(1 for r in out if r.ok)
    errors = [r for r in out if not r.ok]
    rate_limited = sum(1 for r in out if r.is_rate_limited)
    qfull = sum(1 for r in out if r.is_queue_full)
    print(f"  - total={len(out)} ok={ok} err={len(errors)} rate_limited={rate_limited} queue_full={qfull}")
    return out

# --------------- ניתוח והסבר (למה זה קורה) ------------------------------
def reason_analysis(summaries: List[PhaseSummary]) -> List[str]:
    """מייצר רשימת הסברים/סיבות אפשריות על בסיס הנתונים שנמדדו."""
    lines: List[str] = []

    # 1) איטיות כללית גם בפינגים קטנים => כנראה עיבוד בתוך הראוט (אין Return-Fast).
    sm = next((s for s in summaries if s.name.startswith("PHASE 1")), None)
    if sm and sm.avg_elapsed_ms >= SLOW_MS_THRESHOLD:
        lines.append(
            "• כבר בבדיקת העשן (מטענים קטנים) רואים זמן תגובה איטי. "
            "כנראה שהראוט עצמו מבצע עיבוד/ולידציה כבדים לפני שמחזירים תשובה. "
            "מומלץ לעבור ל-Return-Fast + תור רקע."
        )

    # 2) קצב קבוע — rate_limited מרמז על Throttle או קצב גבוה מדי בצד הלקוח.
    rt = next((s for s in summaries if s.name.startswith("PHASE 2")), None)
    if rt:
        if rt.rate_limited > 0:
            lines.append(
                "• בבדיקת הקצב הקבוע נצפו החזרות 'rate_limited'. השרת מגביל קצב (טוב) "
                "או שהקצב הנבחר גבוה מהיכולת בפועל. הורידו ל-8–10Hz."
            )
        if rt.slow > 0 and (not sm or rt.avg_elapsed_ms > sm.avg_elapsed_ms * 1.5):
            lines.append(
                "• תחת קצב קבוע, זמן התגובה עלה משמעותית לעומת בדיקת העשן. "
                "זה נראה כמו עומס/פקק בתור. שקלו להגדיל תור רקע, או להקל על כמות/גודל הנתונים."
            )

    # 3) מטענים גדולים => כנראה סיריאליזציה/כתיבה לדיסק/עיבוד כבד.
    lg = next((s for s in summaries if s.name.startswith("PHASE 3")), None)
    if lg and lg.avg_elapsed_ms >= SLOW_MS_THRESHOLD:
        lines.append(
            "• מטענים גדולים גורמים לזמן תגובה איטי. "
            "בדקו אם כותבים לדיסק בכל פוש/ממירים מבנים גדולים. עדיף לשלוח רק מדדים הכרחיים."
        )

    # 4) ערכים בעייתיים => אם יש שגיאות — כנראה ולידציה/ניקוי לא מטופלים.
    bv = next((s for s in summaries if s.name.startswith("PHASE 4")), None)
    if bv and bv.err_count > 0:
        lines.append(
            "• ערכים בעייתיים (NaN/Inf כמחרוזות) גרמו לשגיאות. ודאו ש-JSON guard מנקה ערכים לא חוקיים."
        )

    # 5) מקביליות => האטה/שגיאות מרמזות על נעילה/אזור קריטי/put חסום.
    cc = next((s for s in summaries if s.name.startswith("PHASE 5")), None)
    if cc and (cc.slow > (cc.sent * 0.2) or cc.err_count > 0):
        lines.append(
            "• בבדיקה מקבילית נצפתה האטה/שגיאות. ייתכן שיש אזור קריטי/נעילה בקוד השרת "
            "(למשל כתיבה משותפת למבנה גלובלי ללא נעילות, או תור חסום)."
        )

    if not lines:
        lines.append(
            "• לא זוהתה סיבה יחידה מובהקת. אם עדיין מתקבלות אזהרות timeout בלוג, "
            "החזירו תשובה מהר (Return-Fast) ועבדו בתור רקע. הורידו קצב לקוח ל-8–10Hz."
        )

    return lines

# --------------- הפקת דו"ח לקבצים ---------------------------------------
def ensure_outdir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def write_report(outdir: str, summaries: List[PhaseSummary], samples: List[PushResult], reasons: List[str]) -> str:
    txt_path  = os.path.join(outdir, "payload_push_report.txt")
    json_path = os.path.join(outdir, "payload_push_report.json")
    csv_path  = os.path.join(outdir, "payload_push_samples.csv")

    # TXT
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("דו\"ח אבחון — /api/payload_push\n")
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
        f.write(hline() + "\n")
        for s in summaries:
            f.write(
                f"[{s.name}] sent={s.sent} ok={s.ok_count} err={s.err_count} "
                f"rate_limited={s.rate_limited} queue_full={s.queue_full}\n"
            )
            f.write(
                f"AVG={s.avg_elapsed_ms:.1f}ms P95={s.p95_elapsed_ms:.1f}ms P99={s.p99_elapsed_ms:.1f}ms "
                f"slow(≥{SLOW_MS_THRESHOLD})={s.slow} very_slow(≥{VERY_SLOW_MS})={s.very_slow}\n"
            )
            f.write(hline() + "\n")
        f.write("\nנימוקים/למה זה קורה:\n")
        for line in reasons:
            f.write(f"- {line}\n")

    # JSON
    j = {
        "generated_at": datetime.now().isoformat(),
        "summaries": [asdict(s) for s in summaries],
        "reasons": reasons,
        "thresholds": {"slow_ms": SLOW_MS_THRESHOLD, "very_slow_ms": VERY_SLOW_MS}
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=2)

    # CSV samples
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("note,status,ok,elapsed_ms,server_dt_ms,is_rate_limited,is_queue_full,raw_json\n")
        for r in samples:
            raw = json.dumps(r.raw_json, ensure_ascii=False) if r.raw_json is not None else ""
            # חשובה התאמה ל-Python 3.11: לא לבצע replace בתוך f-string עם גרשיים —
            # במקום זה מחשבים מראש:
            safe_raw = raw.replace('"', '""')
            f.write(
                f"{r.note},{r.status},{int(r.ok)},{r.elapsed_ms:.1f},"
                f"{'' if r.server_dt_ms is None else r.server_dt_ms},"
                f"{int(r.is_rate_limited)},{int(r.is_queue_full)},\"{safe_raw}\"\n"
            )

    return txt_path

# --------------- CLI וההרצה הראשית --------------------------------------
def main():
    global BASE_URL, PUSH_PATH
    parser = argparse.ArgumentParser(description="אבחון /api/payload_push לאיתור סיבות ל-timeout")
    parser.add_argument("--url", default=BASE_URL, help="BASE URL של השרת (ברירת מחדל: http://127.0.0.1:5000)")
    parser.add_argument("--path", default=PUSH_PATH, help="נתיב ה-API (ברירת מחדל: /api/payload_push)")
    parser.add_argument("--hz", type=int, default=DEFAULT_HZ, help="קצב בבדיקת Rate Test (ברירת מחדל: 10Hz)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_S, help="משך בבדיקות זמן (שניות)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="רמת מקביליות בבדיקת Concurrency")
    parser.add_argument("--large_kb", type=int, default=256, help="גודל מטען גדול בקילובייט לבדיקה")
    args = parser.parse_args()

    BASE_URL = args.url
    PUSH_PATH = args.path

    print(hline())
    print("אבחון /api/payload_push — מתחיל")
    print(
        f"URL: {BASE_URL}{PUSH_PATH} | HZ={args.hz} | DURATION={args.duration}s | "
        f"CONCURRENCY={args.concurrency} | LARGE={args.large_kb}KB"
    )
    print(hline())

    samples_all: List[PushResult] = []
    summaries: List[PhaseSummary] = []

    # שלב 1: בדיקת עשן
    r1 = phase_smoke(BASE_URL, PUSH_PATH)
    samples_all.extend(r1)
    s1 = summarize_phase("PHASE 1 — Smoke", r1)
    print_phase_summary(s1); summaries.append(s1)

    # שלב 2: קצב קבוע
    r2 = phase_rate(BASE_URL, PUSH_PATH, hz=args.hz, duration_s=args.duration)
    samples_all.extend(r2)
    s2 = summarize_phase("PHASE 2 — Rate Test", r2)
    print_phase_summary(s2); summaries.append(s2)

    # שלב 3: מטענים גדולים
    r3 = phase_large(BASE_URL, PUSH_PATH, kb=args.large_kb, hz=max(1, args.hz // 2), duration_s=max(3, args.duration // 2))
    samples_all.extend(r3)
    s3 = summarize_phase("PHASE 3 — Large Payload", r3)
    print_phase_summary(s3); summaries.append(s3)

    # שלב 4: ערכים בעייתיים
    r4 = phase_bad_values(BASE_URL, PUSH_PATH)
    samples_all.extend(r4)
    s4 = summarize_phase("PHASE 4 — Bad Values", r4)
    print_phase_summary(s4); summaries.append(s4)

    # שלב 5: מקביליות
    r5 = phase_concurrency(BASE_URL, PUSH_PATH, concurrency=args.concurrency, duration_s=args.duration)
    samples_all.extend(r5)
    s5 = summarize_phase("PHASE 5 — Concurrency", r5)
    print_phase_summary(s5); summaries.append(s5)

    # ניתוח סיבות
    reasons = reason_analysis(summaries)

    # כתיבת דו"ח
    outdir = os.path.join(os.getcwd(), "diagnostics_output")
    ensure_outdir(outdir)
    txt_path = write_report(outdir, summaries, samples_all, reasons)

    print(hline())
    print("הבדיקות הסתיימו.")
    print("דו\"ח מפורט נוצר ב:", txt_path)
    print("קבצים נוספים: payload_push_report.json, payload_push_samples.csv (באותה תקייה).")
    print(hline())

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nבוטל על ידי המשתמש.")
