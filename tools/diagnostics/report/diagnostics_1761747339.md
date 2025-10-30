# 🧪 Pipeline Diagnostics Report

- Generated: 2025-10-29 16:15:39

## תוצאות בדיקות

| בדיקה | תוצאה | פירוט | מה עושים |
|---|---|---|---|
| Flask /health | FAIL | שגיאת חיבור: HTTPConnectionPool(host='127.0.0.1', port=5000): Max retries exceeded with url: /health (Caused by ConnectTimeoutError(<urllib3.connection.HTTPConnection object at 0x0000014939941810>, 'Connection to 127.0.0.1 timed out. (connect timeout=1.5)')) | בדוק שהשרת רץ (Gunicorn/Flask), כתובת/פורט נכונים, Firewall |

## סיכום סביבה
```json
{
  "base": "http://127.0.0.1:5000",
  "python": "3.11.9",
  "cwd": "C:\\Users\\Owner\\Desktop\\BodyPlus\\BodyPlus_XPro\\tools\\diagnostics",
  "has_pil": true
}
```

## /api/video/status (תקציר)
```json
{}
```

## דוגמת Payload (אם התקבלה)
```json
{}
```

## מסקנות מהירות
- נראה שאין פריימים נכנסים. ודא שהדפדפן/טלפון שולח ל־POST /api/ingest_frame וה־main לא חוסם.