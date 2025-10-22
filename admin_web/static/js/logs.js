// admin_web/static/js/logs.js
// ------------------------------------------------------------
// BodyPlus XPro — Real-Time Logs Panel (Anti-Spam, Batched Render)
// ------------------------------------------------------------
(function () {
  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);
  const box = $('log-container');
  const emptyState = $('empty-state');
  const rowTpl = $('log-row-template');

  const levelSel = $('log-level');
  const queryInp = $('log-query');
  const autoChk  = $('auto-refresh');
  const followTailChk = $('follow-tail');
  const hidePayloadPushChk = $('hide-payload-push');

  const btnClear = $('btn-clear');
  const btnDown  = $('btn-download');

  const stat = {
    ERROR: $('stat-error'),
    WARNING: $('stat-warn'),
    INFO:  $('stat-info'),
    TOTAL: $('stat-total'),
  };

  // ---------- Config ----------
  // נקרא פרמטרים מה-DOM (מסונכרן עם server.py)
  const INIT  = Number(box?.dataset.init || 50);
  const BURST = Number(box?.dataset.burst || 20);
  const PING  = Number(box?.dataset.ping || 15000);

  // מקסימום רשומות בזיכרון (לרינדור מהיר)
  const MAX_ROWS = 1000;      // תצוגה
  const HARD_CAP = MAX_ROWS*3; // זיכרון

  // צבעים לפי רמה
  const COLORS = {
    ERROR: 'text-red-400',
    WARNING: 'text-yellow-300',
    INFO: 'text-blue-300',
    DEBUG: 'text-gray-400',
  };

  // ---------- State ----------
  /** @type {{ts:number, level:string, msg:string, repeat?:number}[]} */
  let rows = [];
  let lastTs = 0;

  // ספריות רינדור
  let renderScheduled = false;
  let lastRenderedIndex = 0; // כמה כבר צויר

  // ---------- Ignore Rules ----------
  const IGNORE_PATTERNS_BASE = [
    /\bheartbeat\b/i,
    /\bheart[-\s]*beat\b/i,
    /\bheartbeet\b/i,
    /\bkeep[-\s]*alive\b/i,
    /\bhealth\s*check\b/i,
    /\bhealthcheck\b/i,
    /\bping\b/i,
  ];
  const PAYLOAD_PUSH_RX = /\/api\/payload_push.*received payload keys:\s*\[/i;

  function shouldIgnore(level, msg) {
    const s = String(msg || '').trim();
    if (!s) return false;

    // payload_push — נסתיר רק אם סומן
    if (hidePayloadPushChk?.checked && PAYLOAD_PUSH_RX.test(s)) return true;

    // רעשים כלליים — לא מסתיר הודעות משמעותיות
    for (const rx of IGNORE_PATTERNS_BASE) {
      if (rx.test(s)) {
        const meaningful = /(error|warn|fail|timeout|fps|detector|camera|pose|hands)/i.test(s);
        if (!meaningful) return true;
      }
    }

    if (/^hb:?$/i.test(s) || /^hb\s+\d+$/i.test(s)) return true;
    if (/^ok$/i.test(s) && /(DEBUG|INFO)/.test(level)) return true;

    return false;
  }

  // ---------- Utils ----------
  function normalizeLevel(lvl) {
    const s = String(lvl || 'INFO').toUpperCase();
    if (s === 'WARN') return 'WARNING';
    return (['ERROR','WARNING','INFO','DEBUG'].includes(s)) ? s : 'INFO';
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function isNearBottom(elem) {
    if (!elem) return true;
    const threshold = 40;
    return (elem.scrollHeight - elem.scrollTop - elem.clientHeight) < threshold;
  }

  box?.addEventListener('scroll', () => {
    if (!isNearBottom(box) && followTailChk) {
      followTailChk.checked = false;
    }
  });

  // ---------- Filters ----------
  function applyFilters(list) {
    const lvl = (levelSel?.value || 'ALL').toUpperCase();
    const q = (queryInp?.value || '').trim().toLowerCase();
    return list.filter(r => {
      const okLevel = (lvl === 'ALL') || (r.level === lvl);
      const okQuery = !q || String(r.msg).toLowerCase().includes(q);
      return okLevel && okQuery;
    });
  }

  // ---------- Rendering (Batched & Incremental) ----------
  function createRowEl(r) {
    const tpl = rowTpl?.content?.firstElementChild;
    let el;
    if (tpl) {
      el = tpl.cloneNode(true);
      const tsMs = Math.round((r.ts || Date.now()/1000) * 1000);
      el.querySelector('.log-ts').textContent = `[${new Date(tsMs).toLocaleString('he-IL')}]`;
      const lvlEl = el.querySelector('.log-level');
      lvlEl.textContent = `[${r.level}]`;
      lvlEl.classList.add(COLORS[r.level] || 'text-gray-400');
      el.querySelector('.log-msg').innerHTML = escapeHtml(r.msg ?? '');
      const rep = el.querySelector('.log-repeat');
      if (r.repeat && r.repeat > 0) rep.textContent = `×${r.repeat+1}`;
    } else {
      // fallback (אם template לא נטען מסיבה כלשהי)
      const wrap = document.createElement('div');
      const tsMs = Math.round((r.ts || Date.now()/1000) * 1000);
      wrap.className = 'log-line whitespace-pre leading-5';
      wrap.innerHTML = `
        <span class="log-ts text-gray-400">[${new Date(tsMs).toLocaleString('he-IL')}]</span>
        <span class="log-level font-semibold ml-2 ${COLORS[r.level] || 'text-gray-400'}">[${r.level}]</span>
        <span class="log-msg">${escapeHtml(r.msg ?? '')}</span>
        ${r.repeat ? `<span class="log-repeat text-gray-400 ml-2">×${r.repeat+1}</span>` : ''}
      `;
      el = wrap;
    }
    return el;
  }

  function scheduleRender() {
    if (renderScheduled) return;
    renderScheduled = true;
    requestAnimationFrame(doRender);
  }

  function doRender() {
    renderScheduled = false;
    if (!box) return;

    // פילטרים
    const filtered = applyFilters(rows);

    // סטטיסטיקות
    const counts = { INFO:0, WARNING:0, ERROR:0 };
    for (const r of filtered) {
      if (counts[r.level] !== undefined) counts[r.level]++;
    }
    stat.INFO.textContent = counts.INFO;
    stat.WARNING.textContent = counts.WARNING;
    stat.ERROR.textContent = counts.ERROR;
    stat.TOTAL.textContent = filtered.length;

    // מצב ריק
    if (emptyState) {
      if (filtered.length === 0) {
        emptyState.style.display = '';
      } else {
        emptyState.style.display = 'none';
      }
    }

    // לגלילה חלקה
    const atBottom = isNearBottom(box) || (followTailChk?.checked ?? true);

    // רינדור אינקרמנטלי:
    // אם הפילטר השתנה (נזהה ע"י reset של lastRenderedIndex), נבנה הכל מחדש.
    if (doRender.forceFull) {
      box.innerHTML = '';
      lastRenderedIndex = 0;
      doRender.forceFull = false;
    }

    const start = Math.max(0, filtered.length - MAX_ROWS);
    // אם start > lastRenderedIndex — נבנה מחדש כי היסטוריה ירדה
    if (start > lastRenderedIndex) {
      box.innerHTML = '';
      lastRenderedIndex = start;
    }

    // הוספת פריטים חדשים בלבד
    const frag = document.createDocumentFragment();
    for (let i = lastRenderedIndex; i < filtered.length; i++) {
      const el = createRowEl(filtered[i]);
      frag.appendChild(el);
    }
    if (frag.childNodes.length) box.appendChild(frag);
    lastRenderedIndex = filtered.length;

    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  // בכל שינוי פילטרים – נכריח רינדור מלא בפעם הבאה
  function forceFullRender() { doRender.forceFull = true; scheduleRender(); }

  // ---------- Data flow ----------
  function pushRows(arr) {
    let added = 0;
    for (const r of arr) {
      const level = normalizeLevel(r.level);
      const msg = r.msg || '';
      if (shouldIgnore(level, msg)) continue;

      const tsSec = typeof r.ts === 'number' ? r.ts : (Date.now()/1000);
      const item = { ts: tsSec, level, msg };
      if (typeof r.repeat === 'number' && r.repeat > 0) item.repeat = r.repeat;

      rows.push(item);
      if (tsSec > lastTs) lastTs = tsSec;
      added++;
    }

    // ניקוי זיכרון (חיתוך זנב)
    if (rows.length > HARD_CAP) rows = rows.slice(-MAX_ROWS);

    // אינדיקציה ל-LED
    if (typeof window.__logPing === 'function') window.__logPing();

    if (added) scheduleRender();
  }

  // ---------- Polling (fallback) ----------
  async function pollOnce() {
    const url = '/api/logs?since=' + encodeURIComponent(lastTs || 0);
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (data && Array.isArray(data.items) && data.items.length) pushRows(data.items);
  }

  function startPolling() {
    // פולינג עדין: כל 2ש׳׳
    const id = setInterval(async () => {
      if (!autoChk || autoChk.checked) {
        try { await pollOnce(); } catch {}
      }
    }, 2000);
    return () => clearInterval(id);
  }

  // ---------- SSE with backoff ----------
  function startSSE() {
    let es;
    let stopPolling = null;
    let tries = 0;
    const mkUrl = () => `/api/logs/stream?init=${encodeURIComponent(INIT)}&burst=${encodeURIComponent(BURST)}&ping_ms=${encodeURIComponent(PING)}`;

    function open() {
      try {
        es = new EventSource(mkUrl());
      } catch {
        fallback();
        return;
      }

      es.onmessage = (ev) => {
        tries = 0; // קיבלנו נתונים — מתחילים מחדש ספירת תקלות
        try {
          const obj = JSON.parse(ev.data);
          pushRows(Array.isArray(obj) ? obj : [obj]);
        } catch {
          // במקרה שמתקבלת שורה טקסטואלית
          pushRows([{ ts: Date.now()/1000, level: 'INFO', msg: String(ev.data || '') }]);
        }
      };

      es.onerror = () => {
        try { es.close(); } catch {}
        // backoff עם חסם (מינימום 500ms, מקסימום ~10s) + jitter
        tries++;
        const delay = Math.min(10000, Math.max(500, Math.pow(2, Math.min(tries, 6)) * 250)) * (0.75 + Math.random()*0.5);
        setTimeout(() => {
          if (tries >= 3 && !stopPolling) {
            // אחרי כמה נסיונות — נפעיל גם פולינג כגיבוי
            stopPolling = startPolling();
          }
          open();
        }, delay);
      };

      // אם SSE עלה — נבטל פולינג גיבוי אם היה
      es.onopen = () => {
        if (stopPolling) { stopPolling(); stopPolling = null; }
      };
    }

    function fallback() {
      // אם EventSource לא זמין — פולינג בלבד
      if (!stopPolling) stopPolling = startPolling();
    }

    open();
  }

  // ---------- UI / Events ----------
  levelSel?.addEventListener('change', () => forceFullRender());
  queryInp?.addEventListener('input', () => {
    clearTimeout(queryInp._t);
    queryInp._t = setTimeout(forceFullRender, 150);
  });

  followTailChk?.addEventListener('change', () => {
    if (followTailChk.checked && box) box.scrollTop = box.scrollHeight;
  });

  hidePayloadPushChk?.addEventListener('change', () => forceFullRender());

  btnClear?.addEventListener('click', async () => {
    try { await fetch('/api/logs/clear', { method: 'POST' }); } catch {}
    rows = []; lastTs = 0; lastRenderedIndex = 0;
    doRender.forceFull = true;
    scheduleRender();
  });

  btnDown?.addEventListener('click', (e) => {
    e?.preventDefault?.();
    const url = '/api/logs/download';
    fetch(url).then(r => {
      if (r.ok) window.location = url;
      else throw new Error();
    }).catch(() => {
      const filtered = applyFilters(rows);
      const text = filtered.map(r => {
        const ts = new Date(Math.round(r.ts * 1000)).toISOString();
        const rep = r.repeat ? ` ×${r.repeat+1}` : '';
        return `[${ts}] [${r.level}] ${r.msg}${rep}`;
      }).join('\n');
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'logs.txt';
      a.click();
      URL.revokeObjectURL(a.href);
    });
  });

  // ---------- Boot ----------
  startSSE(); // יפעיל פולינג כגיבוי אם נופל
})();
