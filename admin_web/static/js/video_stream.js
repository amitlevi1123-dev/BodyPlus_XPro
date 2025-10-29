/* static/js/video_stream.js — MJPEG + Overlay Pose/OD + HUD + התאוששות */
(function () {
  'use strict';

  // ---- אלמנטים (IDs קיימים) ----
  const img    = document.getElementById('vs-img');
  const ph     = document.getElementById('vs-ph');
  const dot    = document.getElementById('vs-dot');
  const txt    = document.getElementById('vs-txt');
  const fitSel = document.getElementById('vs-fit');
  const hudChk = document.getElementById('vs-hud'); // משמש גם כמתג Overlay

  if (!img) return;

  // ---- יצירת קנבס אוטומטי מעל הווידאו ----
  const CANVAS_ID = 'vs-canvas';
  let canvas = document.getElementById(CANVAS_ID);
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = CANVAS_ID;
    canvas.style.position = 'absolute';
    canvas.style.left = '0';
    canvas.style.top = '0';
    canvas.style.pointerEvents = 'none';
    const parent = img.parentElement;
    if (parent) {
      const cs = getComputedStyle(parent);
      if (cs.position === 'static') parent.style.position = 'relative';
      parent.appendChild(canvas);
    }
  }
  const ctx = canvas.getContext('2d');

  // ---- זרם MJPEG + התאוששות ----
  const SRC_MJPEG = '/video/stream.mjpg';
  let reconnectTimer = null;
  const RECONNECT_DELAY_MS  = 2000;
  const PERIODIC_REFRESH_MS = 120000;

  function setConnUI(active){
    if (dot) { dot.classList.toggle('ok', !!active); dot.classList.toggle('warn', !active); }
    if (txt) txt.textContent = active ? 'זרם פעיל' : 'אין זרם';
  }
  function setPlaceholder(show){
    if (ph) ph.style.display = show ? 'flex' : 'none';
    setConnUI(!show);
  }
  function withHud(url){
    const u = new URL(url, window.location.origin);
    if (hudChk && hudChk.checked) u.searchParams.set('hud', '1'); else u.searchParams.delete('hud');
    u.searchParams.set('t', Date.now()); // anti-cache
    return u.toString();
  }
  function setImgSrc(){ img.src = withHud(SRC_MJPEG); }
  function scheduleReconnect(){
    clearTimeout(reconnectTimer);
    setPlaceholder(true);
    reconnectTimer = setTimeout(setImgSrc, RECONNECT_DELAY_MS);
  }

  img.addEventListener('load',  () => setPlaceholder(false));
  img.addEventListener('error', () => scheduleReconnect());

  if (fitSel) {
    const applyFit = () => { img.style.objectFit = fitSel.value || 'contain'; };
    fitSel.addEventListener('change', applyFit);
    applyFit();
  }
  if (hudChk) {
    hudChk.addEventListener('change', () => { setImgSrc(); /* שולט גם באוברליי */ });
  }

  setInterval(() => { if (!document.hidden) setImgSrc(); }, PERIODIC_REFRESH_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) setImgSrc(); });

  setPlaceholder(true);
  setImgSrc();

  // ---- התאמת קנבס לגודל התמונה ----
  function fitCanvasToImage(){
    const w = img.clientWidth || img.naturalWidth || 0;
    const h = img.clientHeight || img.naturalHeight || 0;
    const dpr = window.devicePixelRatio || 1;
    if (!w || !h) return { w:0, h:0, dpr };
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    canvas.width  = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    return { w, h, dpr };
  }
  let canvasSize = fitCanvasToImage();
  const ro = new ResizeObserver(() => { canvasSize = fitCanvasToImage(); });
  ro.observe(img);

  // ---- שלד + אובייקטים (מ-/api/payload_last) ----
  const POLL_MS = 120;      // ~8Hz
  const LINE_W  = 3;
  const PT_R    = 3.5;

  // קישורים עיקריים לפוז
  const CONNS = []
    .concat([[11,13],[13,15]])   // יד שמאל
    .concat([[12,14],[14,16]])   // יד ימין
    .concat([[23,25],[25,27],[27,29],[29,31]]) // רגל שמאל
    .concat([[24,26],[26,28],[28,30],[30,32]]) // רגל ימין
    .concat([[11,12],[11,23],[12,24],[23,24]]) // גו
    .concat([[0,2],[2,7],[0,5],[5,8]]);        // ראש

  async function fetchPayload(){
    try{
      const res = await fetch('/api/payload_last', { cache: 'no-store' });
      if(!res.ok) return null;
      return await res.json();
    }catch(e){ return null; }
  }

  function drawOverlay(payload){
    const { w, h, dpr } = canvasSize;
    if (!w || !h) return;
    ctx.save();
    ctx.clearRect(0,0,canvas.width, canvas.height);
    ctx.scale(dpr, dpr);

    const overlayOn = hudChk ? !!hudChk.checked : true;

    // --- Pose (mp.landmarks) ---
    if (overlayOn) {
      const mp = payload && payload.mp;
      const lms = mp && mp.landmarks;
      if (Array.isArray(lms) && lms.length >= 17) {
        const mirrored = !!(mp && mp.mirror_x);
        const pts = lms.map(p => {
          let x = (p.x ?? 0) * w;
          const y = (p.y ?? 0) * h;
          if (mirrored) x = w - x;
          return { x, y };
        });

        // קווים
        ctx.lineWidth = LINE_W;
        ctx.strokeStyle = 'rgba(0, 200, 255, 0.9)';
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        for (const [a,b] of CONNS){
          const pa = pts[a], pb = pts[b];
          if (!pa || !pb) continue;
          ctx.moveTo(pa.x, pa.y);
          ctx.lineTo(pb.x, pb.y);
        }
        ctx.stroke();

        // נקודות
        ctx.fillStyle = 'rgba(255, 80, 80, 0.95)';
        for (const p of pts){
          ctx.beginPath();
          ctx.arc(p.x, p.y, PT_R, 0, Math.PI*2);
          ctx.fill();
        }
      }

      // --- Object Detection (אם קיים) ---
      const od = payload && payload.objdet;
      const objs = od && Array.isArray(od.objects) ? od.objects : [];
      if (objs.length) {
        ctx.lineWidth = 2;
        ctx.strokeStyle = 'rgba(0,255,120,0.9)';
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.font = '12px ui-sans-serif, system-ui';
        for (const o of objs){
          const bb = Array.isArray(o.bbox) ? o.bbox : null; // [x,y,w,h] בפיקסלים
          if (!bb || bb.length < 4) continue;
          const x = bb[0], y = bb[1], ww = bb[2], hh = bb[3];
          ctx.strokeRect(x, y, ww, hh);
          const label = (o.label || 'obj') + (o.conf ? ` ${(o.conf*100).toFixed(0)}%` : '');
          const tw = ctx.measureText(label).width + 8;
          ctx.fillRect(x, Math.max(0, y - 16), tw, 16);
          ctx.fillStyle = '#fff';
          ctx.fillText(label, x + 4, Math.max(12, y - 4));
          ctx.fillStyle = 'rgba(0,0,0,0.6)';
        }
      }
    }

    // --- HUD קטן ---
    const fps = payload?.meta?.fps ?? 0;
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.fillRect(8,8,130,28);
    ctx.fillStyle = '#fff';
    ctx.font = '14px ui-sans-serif, system-ui';
    ctx.fillText(`FPS: ${Number(fps).toFixed(1)}`, 14, 28);

    ctx.restore();
  }

  async function tick(){
    const payload = await fetchPayload();
    if (payload) drawOverlay(payload);
    setTimeout(tick, POLL_MS);
  }
  tick();

  // להתאים קנבס כשיש טעינת תמונה
  img.addEventListener('load', () => { canvasSize = fitCanvasToImage(); });
})();
