/* static/js/video_controls.js — שליטה על פרופילים/פרמטרים/רזולוציה + רענון סטטוס (בטוח גם בלי כפתורים בדף) */
(function () {
  'use strict';

  var $ = function(id){ return document.getElementById(id); };
  function isFiniteNumber(v){ return typeof v === 'number' && isFinite(v); }
  function toInt(x, fallback){ var n=parseInt(x,10); return isFinite(n)? n : fallback; }

  var inTargetFps  = $('inTargetFps');
  var btnApply     = $('btnApplyParams');
  var applyStatus  = $('applyStatus');

  var stEffSize    = $('stEffSize');
  var stEffFps     = $('stEffFps');
  var stUpdatedAt  = $('stUpdatedAt');

  var btnResMenu   = $('btnResMenu');
  var resMenu      = $('resMenu');
  var profileButtons = document.querySelectorAll('[data-profile]');

  var btnStart = document.getElementById('btn-start');
  var btnStop  = document.getElementById('btn-stop');

  var RES_PRESETS = { low:'low', medium:'medium', high:'high' };

  function postJson(url, body, timeoutMs) {
    if (timeoutMs == null) timeoutMs = 6000;
    var ctl = new AbortController();
    var t = setTimeout(function(){ try{ ctl.abort(); }catch(_){ } }, timeoutMs);
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify(body || {}),
      signal: ctl.signal
    })
    .then(function(r){ return r.text().then(function(text){
      var data = null; try{ data = JSON.parse(text); }catch(_){}
      clearTimeout(t); return { ok:r.ok, status:r.status, data:data || null, raw:text };
    });})
    .catch(function(e){ clearTimeout(t); return { ok:false, status:0, data:null, raw:String(e) }; });
  }

  function getJson(url, timeoutMs) {
    if (timeoutMs == null) timeoutMs = 4000;
    var ctl = new AbortController();
    var t = setTimeout(function(){ try{ ctl.abort(); }catch(_){ } }, timeoutMs);
    return fetch(url, { cache:'no-store', signal: ctl.signal })
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .then(function(j){ clearTimeout(t); return j; })
      .catch(function(){ clearTimeout(t); return null; });
  }

  function setApplyStatus(msg, ok){
    if (!applyStatus) return;
    applyStatus.textContent = msg || '—';
    applyStatus.className = 'text-sm ' + (ok ? 'text-green-600' : 'text-gray-600');
  }

  function renderStatus(s){
    if (!s || s.ok === false) return;
    if (Array.isArray(s.size) && s.size.length === 2) stEffSize && (stEffSize.textContent = s.size[0] + '×' + s.size[1]);
    else stEffSize && (stEffSize.textContent = '—');
    stEffFps   && (stEffFps.textContent = (s.fps != null ? s.fps : '—'));
    stUpdatedAt&& (stUpdatedAt.textContent = new Date().toLocaleTimeString());
  }

  function refreshState(){
    getJson('/api/video/status', 3000).then(function(s){
      if (s && (s.ok || (typeof s.opened !== 'undefined'))) renderStatus(s);
    });
  }

  function applyProfile(name){
    if (!name) return;
    var profile = String(name).trim().toLowerCase();
    setApplyStatus('מיישם פרופיל…', false);
    postJson('/api/video/params', { profile: profile }).then(function(res){
      setApplyStatus((res.ok && res.data && res.data.ok) ? 'פרופיל הוחל ✓' : 'שגיאה בהחלת פרופיל', !!(res.ok && res.data && res.data.ok));
      setTimeout(refreshState, 500);
    });
  }

  function applyManual(){
    var fps = toInt(inTargetFps ? inTargetFps.value : '', NaN);
    var body = {};
    if (isFiniteNumber(fps)) body.target_fps = fps;
    if (!Object.keys(body).length){ setApplyStatus('אין מה להחיל', false); return; }
    setApplyStatus('מיישם ידני…', false);
    postJson('/api/video/params', body).then(function(res){
      setApplyStatus((res.ok && res.data && res.data.ok) ? 'הוחל ✓' : 'שגיאה בהחלה', !!(res.ok && res.data && res.data.ok));
      setTimeout(refreshState, 500);
    });
  }

  function applyResolutionPreset(key){
    var preset = RES_PRESETS[String(key).toLowerCase()];
    if (!preset) return;
    setApplyStatus('מחליף רזולוציה…', false);
    postJson('/api/video/resolution', { preset: preset }).then(function(res){
      setApplyStatus((res.ok && res.data && res.data.ok) ? 'רזולוציה הוחלה ✓' : 'שגיאה בהחלת רזולוציה', !!(res.ok && res.data && res.data.ok));
      hideResMenu();
      setTimeout(refreshState, 700);
    });
  }

  function startCamera(){
    setApplyStatus('מפעיל מצלמה…', false);
    postJson('/api/video/start', { camera_index: 0, show_preview: false }).then(function(r){
      setApplyStatus(r.ok ? 'מצלמה הופעלה ✓' : 'שגיאה בהפעלה', r.ok);
      setTimeout(refreshState, 700);
    });
  }
  function stopCamera(){
    setApplyStatus('מכבה מצלמה…', false);
    postJson('/api/video/stop', {}).then(function(r){
      setApplyStatus(r.ok ? 'מצלמה כובתה ✓' : 'שגיאה בכיבוי', r.ok);
      setTimeout(refreshState, 500);
    });
  }

  function showResMenu(){ if (resMenu) resMenu.classList.remove('hidden'); }
  function hideResMenu(){ if (resMenu) resMenu.classList.add('hidden'); }
  function toggleResMenu(){
    if (!resMenu) return;
    if (resMenu.classList.contains('hidden')) showResMenu(); else hideResMenu();
  }

  // אירועים — רץ גם אם אין אלמנטים (אין קריסה)
  for (var i = 0; i < profileButtons.length; i++){
    (function(btn){ btn.addEventListener('click', function(){ applyProfile(btn.getAttribute('data-profile')); }); })(profileButtons[i]);
  }
  if (btnApply) btnApply.addEventListener('click', applyManual);
  if (btnResMenu) btnResMenu.addEventListener('click', function(e){ e.stopPropagation(); toggleResMenu(); });
  if (resMenu){
    var resBtns = resMenu.querySelectorAll('[data-res]');
    for (var j = 0; j < resBtns.length; j++){
      (function(b){ b.addEventListener('click', function(){ applyResolutionPreset(b.getAttribute('data-res')); }); })(resBtns[j]);
    }
    document.addEventListener('click', function(e){
      if (!resMenu.contains(e.target) && e.target !== btnResMenu) hideResMenu();
    });
  }
  if (btnStart) btnStart.addEventListener('click', startCamera);
  if (btnStop)  btnStop .addEventListener('click', stopCamera);

  function init(){ refreshState(); setInterval(refreshState, 2000); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
