# monitoring – אינדיקציות ולוגים (גרסה מצומצמת)

מודול זה מרכז את ההתראות בזמן אמת (Diagnostics) ושומרן לקובץ לוג יומי בפורמט JSON Lines. שדות חובה לאירוע: time, type, severity, message, context, tags, library_version, payload_version. הצריכה ב־Admin תתבצע דרך /api/diagnostics (אחרונים) ו-/api/metrics (סיכומים).

_נוצר אוטומטית: 2025-10-16 13:40_
