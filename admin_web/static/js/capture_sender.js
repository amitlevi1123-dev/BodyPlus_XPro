/* static/js/capture_sender.js — Capture מהדפדפן → /api/ingest_frame */
(function () {
  'use strict';

  const $ = (id)=>document.getElementById(id);

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
  const chkPreview = $('cap-show-preview');

  const bStart = $('cap-start');
  const bStop  = $('cap-stop');

  if (!vEl || !cEl || !bStart || !bStop) return;

  let stream = null;
  let sending = false;
  let txTimes = [];
  let sentCount = 0;

  const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
  const parseRes=(v)=>{ const [w,h]=(v||'1280x720').split('x').map(n=>parseInt(n,10)); return {width:w||1280,height:h||720}; };

  function setState(s){ if(stEl) stEl.textContent = s; }
  function setErr(m){ if(!errEl) return; if(!m){ errEl.classList.add('hidden'); errEl.textContent=''; } else { errEl.classList.remove('hidden'); errEl.textContent=m; } }
  function updateTx(){
    const now=performance.now(); txTimes.push(now);
    while(txTimes.length && (now - txTimes[0]) > 2000) txTimes.shift();
    const fps=txTimes.length>=2? (txTimes.length-1)/((txTimes[txTimes.length-1]-txTimes[0])/1000) : 0;
    if (txEl) txEl.textContent = fps.toFixed(1);
  }
  function applyPreviewVisibility(){
    const wrap = vEl?.parentElement;
    if (!wrap || !chkPreview) return;
    wrap.style.display = chkPreview.checked ? '' : 'none';
  }

  async function listCams(){
    const dev = await navigator.mediaDevices.enumerateDevices();
    const cams = dev.filter(d=>d.kind==='videoinput');
    selCam.innerHTML = '';
    cams.forEach((d,i) => {
      const o = document.createElement('option');
      o.value = d.deviceId;
      o.textContent = d.label || `מצלמה ${i+1}`;
      selCam.appendChild(o);
    });
    const back=cams.find(d=>/back|rear/i.test(d.label||'')); if (back) selCam.value = back.deviceId;
  }

  async function openCam(){
    const {width,height}=parseRes(selRes.value);
    const deviceId = selCam.value || undefined;
    if (stream){ try{ stream.getTracks().forEach(t=>t.stop()); }catch(_){ } stream=null; }
    setErr('');
    const constraints = {
      audio:false,
      video:{
        width:{ideal:width}, height:{ideal:height},
        frameRate:{ideal:30,max:60},
        ...(deviceId? { deviceId:{ exact: deviceId } } : {}),
        facingMode: deviceId ? undefined : { ideal:'environment' }
      }
    };
    const s = await navigator.mediaDevices.getUserMedia(constraints);
    stream = s; vEl.srcObject = s; await vEl.play();
    const vw = vEl.videoWidth, vh = vEl.videoHeight;
    cEl.width = vw; cEl.height = vh; if (rLbl) rLbl.textContent = `${vw}×${vh}`;
  }

  function draw(){
    const ctx = cEl.getContext('2d', { willReadFrequently:true });
    const vw = vEl.videoWidth || cEl.width;
    const vh = vEl.videoHeight || cEl.height;
    cEl.width = vw; cEl.height = vh;
    ctx.save();
    if (chkMir && chkMir.checked){ ctx.scale(-1,1); ctx.drawImage(vEl,-vw,0,vw,vh); }
    else { ctx.drawImage(vEl,0,0,vw,vh); }
    ctx.restore();
  }

  async function setActiveSource(name){
    try{
      await fetch('/api/source/set', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ source: name })
      });
    }catch(_){}
  }

  async function pingStatus(){
    try{
      const r = await fetch('/api/video/status', { cache:'no-store' });
      if (!r.ok) return;
      const j = await r.json();
      if (j?.frame?.age_ms != null && latEl) latEl.textContent = j.frame.age_ms;
    }catch(_){}
  }

  async function loop(){
    const endpoint = '/api/ingest_frame';
    const targetFps = Math.max(1, Math.min(60, parseInt(inFps?.value||'15',10)));
    const frameInterval = 1000 / targetFps;
    const quality = Math.max(40, Math.min(95, parseInt(inQ?.value||'80',10))) / 100;

    setState(`SENDING @ ${targetFps} FPS`);
    while (sending){
      const t0 = performance.now();
      try {
        draw();
        const blob = await new Promise(res => cEl.toBlob(res,'image/jpeg', quality));
        const ab = await blob.arrayBuffer();
        const headers = { 'Content-Type':'image/jpeg' };
        const tok = (inTok?.value||'').trim(); if (tok) headers['X-Ingest-Token']=tok;

        const r = await fetch(endpoint, { method:'POST', headers, body:ab, keepalive:true });
        if (!r.ok){
          let msg = `${r.status} ${r.statusText}`;
          try{ const j = await r.json(); if (j?.error) msg += ` | ${j.error}`; }catch(_){}
          throw new Error(msg);
        }
        const j = await r.json();
        const ts = j.ts_ms || 0;
        if (ts && latEl) latEl.textContent = Math.max(0, Date.now() - ts);

        sentCount += 1; if (sentEl) sentEl.textContent = String(sentCount);
        updateTx(); setErr('');
      } catch(e){
        console.warn('send error', e);
        setErr('שליחת פריים נכשלה: ' + (e?.message || e));
        await sleep(200);
      }
      const wait = Math.max(0, frameInterval - (performance.now()-t0));
      if (wait>0) await sleep(wait);
    }
    setState('IDLE');
  }

  async function start(){
    try {
      await openCam();
      sending = true; sentCount=0; txTimes=[];
      bStart.disabled = true; bStop.disabled = false;
      await setActiveSource('capture');
      await loop();
    } catch(e){
      setErr(e?.message || String(e));
      sending=false; bStart.disabled=false; bStop.disabled=true;
    }
  }
  function stop(){
    sending = false;
    bStop.disabled = true; bStart.disabled = false;
    try{
      setActiveSource('none');
      if (stream){ stream.getTracks().forEach(t=>t.stop()); }
    }catch(_){}
    stream=null;
  }

  bStart.addEventListener('click', start);
  bStop .addEventListener('click', stop);
  selRes && selRes.addEventListener('change', async ()=>{ if (sending) await openCam(); });
  selCam && selCam.addEventListener('change', async ()=>{ if (sending) await openCam(); });
  if (chkPreview) chkPreview.addEventListener('change', applyPreviewVisibility);

  (async ()=>{
    try{ await navigator.mediaDevices.getUserMedia({video:true,audio:false}); }catch(_){}
    try{ await listCams(); }catch(_){}
    setState('IDLE');
    applyPreviewVisibility();
  })();

  window.addEventListener('beforeunload', ()=>{ sending=false; try{ if(stream){ stream.getTracks().forEach(t=>t.stop()); } }catch(_){ } });
  setInterval(pingStatus, 1500);
})();
