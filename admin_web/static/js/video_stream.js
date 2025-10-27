/* static/js/video_stream.js — תצוגת MJPEG + HUD + מקור סטרים + סנכרון בין טאבים (ללא Capture) */
(function () {
  'use strict';

  const img = document.getElementById('vs-img');
  const ph  = document.getElementById('vs-ph');
  const dot = document.getElementById('vs-dot');
  const txt = document.getElementById('vs-txt');
  const fitSel = document.getElementById('vs-fit');
  const hudChk = document.getElementById('vs-hud');
  const applyFileBtn = document.getElementById('vs-apply-file');
  const inFileFps = document.getElementById('vs-file-fps');
  const inFileQ   = document.getElementById('vs-file-q');

  if (!img) return; // בדף שאין בו תצוגת וידאו – אין עבודה

  const SRC_CAMERA = '/video/stream.mjpg';
  const SRC_FILE   = '/video/stream_file.mjpg';
  let reconnectTimer = null;
  const RECONNECT_DELAY_MS  = 2000;
  const PERIODIC_REFRESH_MS = 120000;

  // ערוץ בין טאבים (אופציונלי)
  let channel = null;
  try { channel = new BroadcastChannel('bp_video_source'); } catch(_) {}

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

  function setImgSrc(url){
    img.src = withHud(url);
  }

  function scheduleReconnect(){
    clearTimeout(reconnectTimer);
    setPlaceholder(true);
    reconnectTimer = setTimeout(() => {
      if (window.__videoSource) setImgSrc(window.__videoSource.url);
    }, RECONNECT_DELAY_MS);
  }

  function startStream(){
    clearTimeout(reconnectTimer);
    setPlaceholder(false);
    if (window.__videoSource) setImgSrc(window.__videoSource.url);
  }

  function switchTo(url, name){
    if (!url) return;
    if (!window.__videoSource) window.__videoSource = { url, name };
    const same = window.__videoSource.url === url;
    window.__videoSource.url  = url;
    window.__videoSource.name = name || url;
    if (!same) startStream();
    try { channel && channel.postMessage(name === 'file' ? 'use_file_stream' : 'use_camera_stream'); } catch(_){}
  }

  // ממשק גלובלי (לכפתורים ב־HTML)
  window.useCameraStream = () => switchTo(SRC_CAMERA, 'camera');
  window.useFileStream   = () => switchTo(SRC_FILE,   'file');
  window.stopFileStream  = async () => { try { await fetch('/api/video/stop_file', {method:'POST'}); } catch(_) {} };

  // אירועים
  img.addEventListener('load',  () => setPlaceholder(false));
  img.addEventListener('error', () => scheduleReconnect());

  if (fitSel) {
    const applyFit = () => { img.style.objectFit = fitSel.value || 'contain'; };
    fitSel.addEventListener('change', applyFit);
    applyFit();
  }

  if (hudChk) {
    hudChk.addEventListener('change', () => { if (window.__videoSource) setImgSrc(window.__videoSource.url); });
  }

  if (applyFileBtn && inFileFps && inFileQ) {
    applyFileBtn.addEventListener('click', async () => {
      const fps = Math.max(1, Math.min(60, parseInt(inFileFps.value || '25', 10)));
      const q   = Math.max(2, Math.min(31, parseInt(inFileQ.value   || '8', 10)));
      try{
        const r = await fetch('/api/video/use_file', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ fps, quality: q })
        });
        if (!r.ok) throw new Error('HTTP '+r.status);
        if (window.__videoSource && window.__videoSource.url.includes('stream_file')) {
          setImgSrc(window.__videoSource.url);
        }
      }catch(e){ console.warn('apply file stream params failed', e); }
    });
  }

  // סנכרון בין טאבים
  if (channel) {
    channel.onmessage = (ev) => {
      const d = ev && ev.data;
      if (d === 'use_file_stream')   switchTo(SRC_FILE,   'file');
      if (d === 'use_camera_stream') switchTo(SRC_CAMERA, 'camera');
    };
  }
  window.addEventListener('message', (ev) => {
    const d = (ev && ev.data) || {};
    if (d && d.type === 'use_file_stream')   switchTo(SRC_FILE,   'file');
    if (d && d.type === 'use_camera_stream') switchTo(SRC_CAMERA, 'camera');
  });

  // רענון תקופתי (למקרה שהחיבור “קופא”)
  setInterval(() => { if (!document.hidden && window.__videoSource) setImgSrc(window.__videoSource.url); }, PERIODIC_REFRESH_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && window.__videoSource) setImgSrc(window.__videoSource.url); });

  // התחלה: מצלמה (ברירת מחדל אחידה לכל הטאבים)
  window.__videoSource = window.__videoSource || { url: SRC_CAMERA, name: 'camera' };
  setPlaceholder(true);
  startStream();
})();
