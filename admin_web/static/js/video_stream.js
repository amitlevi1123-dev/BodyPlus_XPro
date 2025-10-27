/* eslint-disable no-console */
/*
 * static/js/video_stream.js
 * ------------------------------------------------------------
 * קובץ מאוחד לטאב "וידאו":
 * 1) IMG יחיד שמחובר ל-/video/stream.mjpg (או לקובץ אם בוחרים).
 * 2) Capture בדפדפן ששולח ל-/api/ingest_frame.
 * אין יצירה דינמית של IMG נוסף → לא יהיו שני חלונות וידאו.
 * ------------------------------------------------------------
 */
(function () {
  'use strict';

  // ========================
  // --- חלק 1: סטרים MJPEG
  // ========================
  const img          = document.getElementById('video-stream');
  const placeholder  = document.getElementById('video-placeholder');
  const dot          = document.getElementById('dotConnected');
  const txt          = document.getElementById('txtConnected');

  const SRC_CAMERA = '/video/stream.mjpg';
  const SRC_FILE   = '/video/stream_file.mjpg';

  if (img) {
    window.__videoSource = window.__videoSource || { url: SRC_CAMERA, name: 'camera' };

    let reconnectTimer = null;
    const RECONNECT_DELAY_MS   = 2000;
    const PERIODIC_REFRESH_MS  = 120000;

    function setConnUI(active){
      if (!dot || !txt) return;
      dot.classList.toggle('bg-green-500', !!active);
      dot.classList.toggle('bg-gray-300', !active);
      txt.textContent = active ? 'זרם פעיל' : 'אין זרם פעיל';
    }
    function showPlaceholder(show){
      if (placeholder) placeholder.style.display = show ? 'flex' : 'none';
      setConnUI(!show);
    }
    function setImgSrc(url){
      img.src = url + (url.includes('?') ? '&' : '?') + 't=' + Date.now();
    }
    function startStream(){
      clearTimeout(reconnectTimer);
      showPlaceholder(false);
      setImgSrc(window.__videoSource.url);
      console.log('[video_stream] ▶ streaming:', window.__videoSource.name, window.__videoSource.url);
    }
    function scheduleReconnect(){
      clearTimeout(reconnectTimer);
      showPlaceholder(true);
      reconnectTimer = setTimeout(startStream, RECONNECT_DELAY_MS);
    }

    img.addEventListener('load',  () => showPlaceholder(false));
    img.addEventListener('error', () => {
      console.warn('[video_stream] stream error — reconnecting...');
      scheduleReconnect();
    });

    setInterval(() => { if (!document.hidden) setImgSrc(window.__videoSource.url); }, PERIODIC_REFRESH_MS);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) setImgSrc(window.__videoSource.url); });

    function switchTo(url, name){
      if (!url || url === window.__videoSource.url) return;
      window.__videoSource.url  = url;
      window.__videoSource.name = name || url;
      try {
        const ch = window.__bpVideoSourceChannel;
        if (ch) ch.postMessage(name === 'file' ? 'use_file_stream' : 'use_camera_stream');
      } catch(_) {}
      startStream();
    }

    // API גלובלי לכפתורים/טאבים
    window.setStreamSource = function(url){ switchTo(url, url.includes('stream_file') ? 'file' : 'camera'); };
    window.useFileStream   = () => switchTo(SRC_FILE,   'file');
    window.useCameraStream = () => switchTo(SRC_CAMERA, 'camera');

    // תקשורת בין טאבים (אופציונלי)
    try {
      const ch = window.__bpVideoSourceChannel || new BroadcastChannel('bp_video_source');
      ch.onmessage = (ev) => {
        const d = ev && ev.data;
        if (d === 'use_file_stream')   window.useFileStream();
        if (d === 'use_camera_stream') window.useCameraStream();
      };
      window.__bpVideoSourceChannel = ch;
    } catch(_) {}

    window.addEventListener('message', (ev) => {
      const d = (ev && ev.data) || {};
      if (d && d.type === 'use_file_stream')   window.useFileStream();
      if (d && d.type === 'use_camera_stream') window.useCameraStream();
    });

    // התחלה: ברירת מחדל — מצלמה (הזרם החדש)
    window.useCameraStream();
  }

  // ========================
  // --- חלק 2: Capture → /api/ingest_frame
  // ========================
  const $ = (id) => document.getElementById(id);

  const vEl   = $('cap-video');
  const cEl   = $('cap-canvas');
  const stEl  = $('cap-state');
  const txEl  = $('cap-txfps');
  const latEl = $('cap-lat');
  const rLbl  = $('cap-reslbl');
  const sentEl= $('cap-sent');
  const errEl = $('cap-err');

  const selCam = $('cap-camera');
  const selRes = $('cap-res');
  const inFps  = $('cap-fps');
  const inQ    = $('cap-jpgq');
  const inTok  = $('cap-token');
  const chkMir = $('cap-mirror');

  const bStart = $('cap-start');
  const bStop  = $('cap-stop');

  if (vEl && cEl && bStart && bStop) {
    let stream = null;
    let sending = false;
    let txTimes = [];
    let sentCount = 0;

    function setState(s){ if (stEl) stEl.textContent = s; }
    function setErr(msg){
      if (!errEl) return;
      if (!msg){ errEl.classList.add('hidden'); errEl.textContent=''; }
      else     { errEl.classList.remove('hidden'); errEl.textContent=msg; }
    }
    function updateTxFps(){
      const now = performance.now();
      txTimes.push(now);
      while (txTimes.length && (now - txTimes[0]) > 2000) txTimes.shift();
      const fps = txTimes.length >= 2 ? (txTimes.length-1) / ((txTimes[txTimes.length-1]-txTimes[0])/1000) : 0;
      if (txEl) txEl.textContent = fps.toFixed(1);
    }
    const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
    function parseRes(val){
      const [w,h]=(val||'1280x720').split('x').map(v=>parseInt(v,10));
      return {width:w||1280, height:h||720};
    }

    async function listCameras() {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const cams = devices.filter(d => d.kind === 'videoinput');
      selCam.innerHTML = '';
      cams.forEach((d, i) => {
        const o = document.createElement('option');
        o.value = d.deviceId;
        o.textContent = d.label || `מצלמה ${i+1}`;
        selCam.appendChild(o);
      });
      const back = cams.find(d => /back|rear/i.test(d.label));
      if (back) selCam.value = back.deviceId;
    }

    async function openCamera() {
      const {width, height} = parseRes(selRes.value);
      const deviceId = selCam.value || undefined;
      const constraints = {
        audio:false,
        video:{
          width:{ideal:width}, height:{ideal:height},
          frameRate:{ideal:30, max:60},
          ...(deviceId ? { deviceId:{ exact: deviceId } } : {}),
          facingMode: deviceId ? undefined : { ideal:'environment' }
        }
      };
      if (stream) { stream.getTracks().forEach(t=>t.stop()); stream=null; }
      try{
        setErr('');
        const s = await navigator.mediaDevices.getUserMedia(constraints);
        stream = s; vEl.srcObject = s; await vEl.play();
        const vw = vEl.videoWidth, vh = vEl.videoHeight;
        cEl.width = vw; cEl.height = vh;
        if (rLbl) rLbl.textContent = `${vw}×${vh}`;
      }catch(e){
        console.error(e);
        setErr('לא ניתן לפתוח מצלמה. ודא HTTPS והרשאות מצלמה.');
        throw e;
      }
    }

    function drawToCanvas(){
      const ctx = cEl.getContext('2d');
      const vw = vEl.videoWidth || cEl.width;
      const vh = vEl.videoHeight || cEl.height;
      cEl.width = vw; cEl.height = vh;
      ctx.save();
      if (chkMir?.checked) { ctx.scale(-1,1); ctx.drawImage(vEl,-vw,0,vw,vh); }
      else { ctx.drawImage(vEl,0,0,vw,vh); }
      ctx.restore();
    }

    async function sendLoop(){
      const endpoint = '/api/ingest_frame';
      const targetFps = Math.max(1, Math.min(60, parseInt(inFps?.value||'15',10)));
      const frameInterval = 1000 / targetFps;
      const quality = Math.max(40, Math.min(95, parseInt(inQ?.value||'80',10))) / 100;

      setState(`SENDING @ ${targetFps} FPS`);
      while (sending){
        const t0 = performance.now();
        try{
          drawToCanvas();
          const blob = await new Promise(res => cEl.toBlob(res,'image/jpeg', quality));
          const ab = await blob.arrayBuffer();
          const headers = { 'Content-Type':'image/jpeg' };
          const tok = (inTok?.value||'').trim(); if (tok) headers['X-Ingest-Token']=tok;

          const r = await fetch(endpoint, { method:'POST', headers, body:ab, keepalive:true });
          if (!r.ok) {
            let msg = `${r.status} ${r.statusText}`;
            try{ const j = await r.json(); if (j?.error) msg += ` | ${j.error}`; }catch(_){}
            throw new Error(msg);
          }
          const j = await r.json();
          const serverTs = j.ts_ms || 0;
          if (serverTs && latEl){ latEl.textContent = Math.max(0, Date.now() - serverTs); }

          sentCount += 1; if (sentEl) sentEl.textContent = String(sentCount);
          updateTxFps(); setErr('');
        }catch(e){
          console.error('send error', e);
          setErr('שליחת פריים נכשלה: ' + (e?.message || e));
          await sleep(200);
        }
        const elapsed = performance.now() - t0;
        const wait = Math.max(0, frameInterval - elapsed);
        if (wait>0) await sleep(wait);
      }
      setState('IDLE');
    }

    async function start(){
      try{
        await openCamera();
        sending = true; sentCount=0; txTimes=[];
        bStart.disabled = true; bStop.disabled = false;
        await sendLoop();
      }catch(_){
        sending = false; bStart.disabled=false; bStop.disabled=true;
      }
    }
    function stop(){
      sending = false;
      bStop.disabled=true; bStart.disabled=false;
      if (stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; }
    }

    bStart.addEventListener('click', start);
    bStop .addEventListener('click', stop);
    selRes.addEventListener('change', async ()=>{ if (!sending) return; await openCamera(); });
    selCam.addEventListener('change', async ()=>{ if (!sending) return; await openCamera(); });

    // הכנה ראשונית
    (async ()=>{
      try{ await navigator.mediaDevices.getUserMedia({video:true, audio:false}); }catch(_){}
      try{ await listCameras(); }catch(e){ console.warn(e); }
      setState('IDLE');
    })();

    window.addEventListener('beforeunload', ()=>{ sending=false; if (stream) stream.getTracks().forEach(t=>t.stop()); });
  }

})();
