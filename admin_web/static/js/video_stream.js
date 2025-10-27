/* static/js/video.js — סטרים MJPEG + Capture + סטטוס/Health/Payload + בקרות איכות/תצוגה לסטרים */
(function () {
  'use strict';

  // ===== A) סטרים MJPEG =====
  const img = document.getElementById('vs-img');
  const ph  = document.getElementById('vs-ph');
  const dot = document.getElementById('vs-dot');
  const txt = document.getElementById('vs-txt');
  const fitSel = document.getElementById('vs-fit');
  const hudChk = document.getElementById('vs-hud');
  const applyFileBtn = document.getElementById('vs-apply-file');
  const inFileFps = document.getElementById('vs-file-fps');
  const inFileQ   = document.getElementById('vs-file-q');

  const SRC_CAMERA = '/video/stream.mjpg';
  const SRC_FILE   = '/video/stream_file.mjpg';

  function setConnUI(active){
    if (!dot || !txt) return;
    dot.classList.toggle('ok', !!active);
    dot.classList.toggle('warn', !active);
    txt.textContent = active ? 'זרם פעיל' : 'אין זרם';
  }
  function setPlaceholder(show){ if (ph) ph.style.display = show ? 'flex' : 'none'; setConnUI(!show); }

  // עידכון ה-URL עם ?hud=1 לפי הצ'קבוקס
  function withHud(url){
    const u = new URL(url, window.location.origin);
    if (hudChk && hudChk.checked) u.searchParams.set('hud', '1'); else u.searchParams.delete('hud');
    // anti-cache
    u.searchParams.set('t', Date.now());
    return u.toString();
  }

  // שליטה במקור סטרים
  function setStreamSource(url, name){
    if (!img) return;
    window.__videoSource = { url, name };
    img.src = withHud(url);
  }
  window.useCameraStream = () => setStreamSource(SRC_CAMERA, 'camera');
  window.useFileStream   = () => setStreamSource(SRC_FILE,   'file');

  // עצירת סטרים קובץ בצד שרת (אם יש את הראוט הזה)
  window.stopFileStream = async () => {
    try { await fetch('/api/video/stop_file', {method:'POST'}); } catch(_) {}
  };

  if (img) {
    img.addEventListener('load',  () => setPlaceholder(false));
    img.addEventListener('error', () => { setPlaceholder(true); setTimeout(()=>{ if (window.__videoSource) img.src = withHud(window.__videoSource.url); }, 2000); });

    // שינוי התאמת תצוגה
    if (fitSel) {
      const applyFit = () => { img.style.objectFit = fitSel.value || 'contain'; };
      fitSel.addEventListener('change', applyFit); applyFit();
    }

    // שינוי HUD → טוען מחדש את ה-IMG עם הפרמטר
    if (hudChk) {
      hudChk.addEventListener('change', () => {
        if (window.__videoSource) img.src = withHud(window.__videoSource.url);
      });
    }

    // החלת איכות/קצב למצב "קובץ" ע"י API צד שרת (אם קיים: routes_upload_video.py)
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
          // רענון מהיר של ה-IMG
          if (window.__videoSource && window.__videoSource.url.includes('stream_file')) {
            img.src = withHud(window.__videoSource.url);
          }
        }catch(e){ console.warn('apply file stream params failed', e); }
      });
    }

    // התחלה: מצלמה
    window.useCameraStream();
    setPlaceholder(true);
  }

  // ===== B) Capture → /api/ingest_frame =====
  const $ = (id)=>document.getElementById(id);
  const vEl=$('cap-video'), cEl=$('cap-canvas'), stEl=$('cap-state'), txEl=$('cap-txfps'),
        latEl=$('cap-lat'), rLbl=$('cap-reslbl'), sentEl=$('cap-sent'), errEl=$('cap-err');
  const selCam=$('cap-camera'), selRes=$('cap-res'), inFps=$('cap-fps'), inQ=$('cap-jpgq'),
        inTok=$('cap-token'), chkMir=$('cap-mirror'), bStart=$('cap-start'), bStop=$('cap-stop');

  if (vEl && cEl && bStart && bStop) {
    let stream=null, sending=false, txTimes=[], sent=0;
    const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
    const parseRes=(v)=>{ const [w,h]=(v||'1280x720').split('x').map(n=>parseInt(n,10)); return {width:w||1280,height:h||720}; };
    function setState(s){ if(stEl) stEl.textContent=s; }
    function setErr(m){ if(!errEl) return; if(!m){ errEl.classList.add('hidden'); errEl.textContent=''; } else { errEl.classList.remove('hidden'); errEl.textContent=m; } }
    function updateTx(){ const now=performance.now(); txTimes.push(now); while(txTimes.length&&(now-txTimes[0])>2000) txTimes.shift();
      const fps=txTimes.length>=2? (txTimes.length-1)/((txTimes[txTimes.length-1]-txTimes[0])/1000):0; if(txEl) txEl.textContent=fps.toFixed(1); }
    async function listCams(){ const dev=await navigator.mediaDevices.enumerateDevices(); const cams=dev.filter(d=>d.kind==='videoinput');
      selCam.innerHTML=''; cams.forEach((d,i)=>{ const o=document.createElement('option'); o.value=d.deviceId; o.textContent=d.label||`מצלמה ${i+1}`; selCam.appendChild(o); });
      const back=cams.find(d=>/back|rear/i.test(d.label)); if(back) selCam.value=back.deviceId; }
    async function openCam(){ const {width,height}=parseRes(selRes.value); const deviceId=selCam.value||undefined;
      if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; }
      const constraints={ audio:false, video:{ width:{ideal:width}, height:{ideal:height}, frameRate:{ideal:30,max:60}, ...(deviceId?{deviceId:{exact:deviceId}}:{}), facingMode: deviceId?undefined:{ideal:'environment'} } };
      const s=await navigator.mediaDevices.getUserMedia(constraints); stream=s; vEl.srcObject=s; await vEl.play();
      const vw=vEl.videoWidth, vh=vEl.videoHeight; cEl.width=vw; cEl.height=vh; if(rLbl) rLbl.textContent=`${vw}×${vh}`; }
    function draw(){ const ctx=cEl.getContext('2d'); const vw=vEl.videoWidth||cEl.width; const vh=vEl.videoHeight||cEl.height;
      cEl.width=vw; cEl.height=vh; ctx.save(); if(chkMir?.checked){ ctx.scale(-1,1); ctx.drawImage(vEl,-vw,0,vw,vh);} else { ctx.drawImage(vEl,0,0,vw,vh);} ctx.restore(); }
    async function loop(){ const endpoint='/api/ingest_frame';
      const targetFps=Math.max(1,Math.min(60, parseInt(inFps?.value||'15',10))); const frameInterval=1000/targetFps;
      const quality=Math.max(40,Math.min(95, parseInt(inQ?.value||'80',10)))/100; setState(`SENDING @ ${targetFps} FPS`);
      while(sending){ const t0=performance.now();
        try{ draw(); const blob=await new Promise(r=>cEl.toBlob(r,'image/jpeg',quality)); const ab=await blob.arrayBuffer();
          const headers={'Content-Type':'image/jpeg'}; const tok=(inTok?.value||'').trim(); if(tok) headers['X-Ingest-Token']=tok;
          const r=await fetch(endpoint,{method:'POST',headers,body:ab,keepalive:true}); if(!r.ok){ let msg=`${r.status} ${r.statusText}`;
            try{ const j=await r.json(); if(j?.error) msg+=` | ${j.error}`; }catch(_){ } throw new Error(msg); }
          const j=await r.json(); const ts=j.ts_ms||0; if(ts&&latEl){ latEl.textContent = Math.max(0, Date.now()-ts); }
          sent+=1; if(sentEl) sentEl.textContent=String(sent); updateTx(); setErr('');
        }catch(e){ console.warn('send error', e); setErr('שליחת פריים נכשלה: '+(e?.message||e)); await sleep(200); }
        const wait=Math.max(0, frameInterval - (performance.now()-t0)); if(wait>0) await sleep(wait);
      } setState('IDLE'); }
    async function start(){ try{ await openCam(); sending=true; sent=0; txTimes=[]; bStart.disabled=true; bStop.disabled=false; await loop(); }
      catch{ sending=false; bStart.disabled=false; bStop.disabled=true; } }
    function stop(){ sending=false; bStop.disabled=true; bStart.disabled=false; if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; } }
    bStart.addEventListener('click', start); bStop.addEventListener('click', stop);
    selRes.addEventListener('change', async ()=>{ if(sending) await openCam(); });
    selCam.addEventListener('change', async ()=>{ if(sending) await openCam(); });
    (async()=>{ try{ await navigator.mediaDevices.getUserMedia({video:true,audio:false}); }catch(_){} try{ await listCams(); }catch(_){}
      setState('IDLE'); })();
    window.addEventListener('beforeunload', ()=>{ sending=false; if(stream) stream.getTracks().forEach(t=>t.stop()); });
  }

  // ===== C) ווידג'ט סטטוס/בריאות/פיילוד =====
  (function(){
    const root=document.getElementById('video-status-widget'); if(!root) return;
    const q =(k)=> root.querySelector('[data-id="'+k+'"]');
    const set=(k,v)=>{ const el=q(k); if(el) el.textContent = (v??'—'); };
    async function j(url, tms){ const c=new AbortController(); const t=setTimeout(()=>c.abort(),tms||4000);
      try{ const r=await fetch(url,{cache:'no-store',signal:c.signal}); if(!r.ok) throw 0; return await r.json(); }catch{ return null; } finally{ clearTimeout(t); } }
    function setVideo(s){ set('v-state',s?.state||'—'); set('v-opened',String(!!s?.opened)); set('v-running',String(!!s?.running));
      set('v-fps',s?.fps??'—'); set('v-size', Array.isArray(s?.size)&&s.size.length===2 ? (s.size[0]+'×'+s.size[1]) : '—');
      set('v-source',s?.source||'—'); set('v-light',s?.light_mode||'—'); set('v-preview',String(!!s?.preview_window_open));
      set('v-error', s?.error? String(s.error).trim():'—'); set('v-updated', new Date().toLocaleTimeString()); }
    function setHealth(h){ set('h-ok', (h && (h.ok===true||h.ok==='true'))?'OK':'NOT OK'); set('h-ver', h?.ver||h?.version||'{{ app_version|default("dev", true) }}');
      set('h-now', h?.now ? new Date((h.now*1000)||Date.now()).toLocaleTimeString() : new Date().toLocaleTimeString());
      const up=(h?.uptime_sec??h?.uptime); set('h-uptime', Number.isFinite(up)? String(up):'—'); }
    function setPayload(p){ p=p||{}; set('p-ver',p.payload_version??'—'); set('p-ts', p.ts? String(p.ts):'—');
      const od=(p.objdet&&typeof p.objdet==='object')?p.objdet:{}; const objs=Array.isArray(od.objects)?od.objects.length:0; const trks=Array.isArray(od.tracks)?od.tracks.length:0;
      const mp=(p.mp&&typeof p.mp==='object')?p.mp:{}; const lms=Array.isArray(mp.landmarks)?mp.landmarks.length:0;
      set('p-obj', String(objs)); set('p-trk', String(trks)); set('p-lms', String(lms)); set('p-fps', (p.fps ?? p?.meta?.fps_est ?? '—'));
      const pre=q('p-json'); if(pre){ try{ pre.textContent = JSON.stringify(p,null,2);}catch{ pre.textContent='—'; } } }
    async function tick(){ const st=await j('/api/video/status',3000); if(st) setVideo(st);
                           const h =await j('/healthz',3000);        if(h)  setHealth(h);
                           const p =await j('/payload',3000);        if(p)  setPayload(p); }
    tick(); setInterval(tick, 1500);
  })();
})();
