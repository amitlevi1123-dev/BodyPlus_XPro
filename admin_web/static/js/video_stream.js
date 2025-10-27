/* static/js/video_stream.js — תצוגת MJPEG אחת + HUD + התאוששות */
(function () {
  'use strict';

  const img = document.getElementById('vs-img');
  const ph  = document.getElementById('vs-ph');
  const dot = document.getElementById('vs-dot');
  const txt = document.getElementById('vs-txt');
  const fitSel = document.getElementById('vs-fit');
  const hudChk = document.getElementById('vs-hud');

  if (!img) return;

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

  function setImgSrc(){
    img.src = withHud(SRC_MJPEG);
  }

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
    hudChk.addEventListener('change', setImgSrc);
  }

  setInterval(() => { if (!document.hidden) setImgSrc(); }, PERIODIC_REFRESH_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) setImgSrc(); });

  setPlaceholder(true);
  setImgSrc();
})();
