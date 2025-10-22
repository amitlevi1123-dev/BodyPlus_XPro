/* ---------------------------------------------------------------------------
video_controls.js — שליטה על מצלמה ורזולוציה
מתחבר ל־/api/camera/settings ומאפשר לבחור פרופילים ורזולוציות קבועות.
--------------------------------------------------------------------------- */

;(function () {
  'use strict';

  // ===== עזר בסיסי =====
  function _byId(id) { return document.getElementById(id); }
  function isFiniteNumber(v) { return typeof v === 'number' && isFinite(v); }
  function parseIntSafe(v) { if (v == null) return NaN; var n = parseInt(v, 10); return isFinite(n) ? n : NaN; }

  // ===== בקשות =====
  function postJson(url, body, timeoutMs) {
    if (timeoutMs == null) timeoutMs = 5000;
    var ctrl = new AbortController();
    var t = setTimeout(function(){ try{ ctrl.abort(); }catch(_){ } }, timeoutMs);
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify(body || {}),
      signal: ctrl.signal
    })
    .then(function(r){
      return r.text().then(function(text){
        var data = null;
        try { data = JSON.parse(text); } catch(_){}
        clearTimeout(t);
        return { ok: r.ok, status: r.status, data: data || null, raw: text };
      });
    })
    .catch(function(e){
      clearTimeout(t);
      return { ok:false, status:0, data:null, raw:String(e) };
    });
  }

  function getJson(url, timeoutMs) {
    if (timeoutMs == null) timeoutMs = 4000;
    var ctrl = new AbortController();
    var t = setTimeout(function(){ try{ ctrl.abort(); }catch(_){ } }, timeoutMs);
    return fetch(url, { cache:'no-store', signal: ctrl.signal })
      .then(function(r){
        if (!r.ok) throw new Error('HTTP '+r.status);
        return r.json();
      })
      .then(function(j){
        clearTimeout(t);
        return j;
      })
      .catch(function(){
        clearTimeout(t);
        return null;
      });
  }

  // ===== התחלה =====
  function init() {
    var inTargetFps  = _byId('inTargetFps');
    var btnApply     = _byId('btnApplyParams');
    var applyStatus  = _byId('applyStatus');

    var stEffSize    = _byId('stEffSize');
    var stEffFps     = _byId('stEffFps');
    var stUpdatedAt  = _byId('stUpdatedAt');

    var btnResMenu   = _byId('btnResMenu');
    var resMenu      = _byId('resMenu');
    var profileButtons = document.querySelectorAll('[data-profile]');

    var RES_PRESETS = {
      low:    { width: 640,  height: 360  },
      medium: { width: 1280, height: 720  },
      high:   { width: 1920, height: 1080 }
    };

    var PROFILE_MAP = {
      'eco':      { width: 640,  height: 360,  fps: 12 },
      'balanced': { width: 1280, height: 720,  fps: 20 },
      'quality':  { width: 1920, height: 1080, fps: 30 }
    };

    // ===== רענון מצב מצלמה =====
    function renderStatus(s) {
      if (!s || s.ok === false) return;
      if (Array.isArray(s.size) && s.size.length === 2) {
        stEffSize.textContent = s.size[0] + '×' + s.size[1];
      } else {
        stEffSize.textContent = '—';
      }
      stEffFps.textContent = s.fps != null ? s.fps : '—';
      stUpdatedAt.textContent = new Date().toLocaleTimeString();
    }

    function refreshState() {
      getJson('/api/video/status', 3000).then(function(s){
        if (s && s.ok) renderStatus(s);
      });
    }

    // ===== פעולות =====
    function applyProfile(name) {
      var preset = PROFILE_MAP[name];
      if (!preset) return;
      applyStatus.textContent = 'מיישם פרופיל...';
      postJson('/api/camera/settings', preset).then(function(res){
        if (res.ok && res.data && res.data.ok) {
          applyStatus.textContent = 'הוחל ✓';
        } else {
          applyStatus.textContent = 'שגיאה בהחלה';
        }
        setTimeout(refreshState, 500);
      });
    }

    function applyManual() {
      var fps = parseIntSafe(inTargetFps ? inTargetFps.value : null);
      var body = {};
      if (isFiniteNumber(fps)) body.fps = fps;
      if (!Object.keys(body).length) {
        applyStatus.textContent = 'אין מה להחיל';
        return;
      }
      applyStatus.textContent = 'מיישם ידני...';
      postJson('/api/camera/settings', body).then(function(res){
        if (res.ok && res.data && res.data.ok) {
          applyStatus.textContent = 'הוחל ✓';
        } else {
          applyStatus.textContent = 'שגיאה בהחלה';
        }
        setTimeout(refreshState, 500);
      });
    }

    function toggleResMenu(forceShow) {
      if (!resMenu) return;
      var show = (typeof forceShow === 'boolean') ? forceShow : resMenu.classList.contains('hidden');
      if (show) resMenu.classList.remove('hidden');
      else resMenu.classList.add('hidden');
    }

    function applyResolutionPreset(key) {
      var preset = RES_PRESETS[key];
      if (!preset) return;
      applyStatus.textContent = 'מחליף רזולוציה ל-' + preset.width + '×' + preset.height + '...';
      postJson('/api/camera/settings', preset).then(function(r){
        if (r.ok && r.data && r.data.ok) {
          applyStatus.textContent = 'רזולוציה הוחלה ✓';
        } else {
          applyStatus.textContent = 'שגיאה בהחלת רזולוציה';
        }
        toggleResMenu(false);
        setTimeout(refreshState, 700);
      });
    }

    // ===== אירועים =====
    for (var i = 0; i < profileButtons.length; i++) {
      (function(btn){
        btn.addEventListener('click', function(){
          applyProfile(btn.getAttribute('data-profile'));
        });
      })(profileButtons[i]);
    }

    if (btnApply) btnApply.addEventListener('click', applyManual);
    if (btnResMenu) btnResMenu.addEventListener('click', function(e){ e.stopPropagation(); toggleResMenu(); });

    if (resMenu) {
      var resBtns = resMenu.querySelectorAll('[data-res]');
      for (var j = 0; j < resBtns.length; j++) {
        (function(b){
          b.addEventListener('click', function(){
            applyResolutionPreset(b.getAttribute('data-res'));
          });
        })(resBtns[j]);
      }
      document.addEventListener('click', function(e){
        if (!resMenu.contains(e.target) && e.target !== btnResMenu) toggleResMenu(false);
      });
    }

    // ===== התחלה =====
    refreshState();
    setInterval(refreshState, 2000);
  }

  // ===== מריץ רק אחרי טעינת DOM =====
  document.addEventListener('DOMContentLoaded', init);

})(); // ← סוגר ומריץ את הפונקציה
