/* eslint-disable no-console */
(function () {
  const $ = (s) => document.querySelector(s);
  const btnStart = $("#btn-start");
  const btnStop  = $("#btn-stop");
  const wrap     = $("#video-wrap");
  const slot     = $("#video-slot");
  const reasonEl = $("#reason");

  const camDot   = $("#cam-dot");
  const camText  = $("#cam-text");
  const viewDot  = $("#view-dot");
  const viewText = $("#view-text");
  const fpsVal   = $("#fps-val");
  const sizeVal  = $("#size-val");

  // אינדיקציות תחתונות
  const ind = {
    camDot: $("#ind-cam-dot"), camText: $("#ind-cam-text"),
    payDot: $("#ind-payload-dot"), payText: $("#ind-payload-text"),
    odDot: $("#ind-od-dot"), odText: $("#ind-od-text"),
    fps: $("#ind-fps"), size: $("#ind-size"), up: $("#ind-uptime"),
    odFPS: $("#ind-od-fps"), odLAT: $("#ind-od-lat"), odOBJ: $("#ind-od-obj"),
    mShoulder: $("#ind-shoulder"), mElbow: $("#ind-elbow"), mKnee: $("#ind-knee"), mTorso: $("#ind-torso"),
  };

  const skelBox = $("#skel-box");
  const videoHolder = $("#video-holder");
  let statusTimer = null;
  let lastAttachTs = 0;

  // ---------- helpers ----------
  function showWrap() { if (wrap) wrap.style.display = "block"; }
  function hideWrap() { if (wrap) wrap.style.display = "none"; }
  function setText(el, t){ if (el) el.textContent = t; }

  function setDots({ camRunning, viewShown }) {
    const camOn  = !!camRunning;
    const viewOn = !!viewShown;
    if (camDot) camDot.className = "inline-block w-2.5 h-2.5 rounded-full " + (camOn? "bg-green-500":"bg-gray-400");
    if (camText) camText.textContent = camOn ? "פעילה" : "לא פעילה";
    if (viewDot) viewDot.className = "inline-block w-2.5 h-2.5 rounded-full " + (viewOn? "bg-green-500":"bg-gray-400");
    if (viewText) viewText.textContent = viewOn ? "מוצג" : "לא מוצג";
  }

  function setReason(msg) { setText(reasonEl, msg || ""); }

  function setMetrics(fps, sizeArr) {
    setText(fpsVal, (fps == null ? "—" : fps));
    if (Array.isArray(sizeArr) && sizeArr.length === 2) {
      setText(sizeVal, `${sizeArr[0]}×${sizeArr[1]}`);
    } else {
      setText(sizeVal, "—");
    }
  }

  function disableBtns(disabled) { if (btnStart) btnStart.disabled = disabled; if (btnStop) btnStop.disabled = disabled; }

  function setDot(dot, textEl, ok, msgOK="תקין", msgBad="כבוי/לא זמין") {
    if (!dot || !textEl) return;
    dot.className = "w-2.5 h-2.5 rounded-full " + (ok ? "bg-green-500" : "bg-red-500");
    textEl.textContent = ok ? msgOK : msgBad;
  }

  // ---------- התאמת גובה שלד לגובה הווידאו ----------
  function syncHeights() {
    try {
      const img = document.getElementById('video-stream');
      const h = img?.clientHeight || videoHolder?.clientHeight || 0;
      if (skelBox && h > 0) {
        skelBox.style.minHeight = h + "px";
        skelBox.style.maxHeight = h + "px";
      }
    } catch(_) {}
  }
  window.addEventListener('resize', syncHeights);
  try { new ResizeObserver(syncHeights).observe(videoHolder); } catch(_) {}

  // ---------- API ----------
  async function apiStart(cameraIndex = 0) {
    const r = await fetch("/api/video/start", {
      method: "POST",
      headers: { "Content-Type":"application/json" },
      body: JSON.stringify({ camera_index: cameraIndex, show_preview: false })
    });
    const j = await r.json().catch(()=>({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  async function apiStop() {
    const r = await fetch("/api/video/stop", { method: "POST" });
    const j = await r.json().catch(()=>({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  async function apiStatus() {
    const r = await fetch("/api/video/status", { cache: "no-store" });
    return r.json().catch(()=> ({}));
  }

  async function checkStreamHeaders(timeoutMs = 1200) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const r = await fetch("/video/stream.mjpg?head=" + Date.now(), { signal: ctl.signal });
      const ct = r.headers.get("Content-Type") || "";
      const ok = r.ok && ct.includes("multipart/x-mixed-replace");
      if (!ok && (r.status === 503 || r.status === 500)) {
        let reason = "";
        try { const j = await r.clone().json(); if (j && (j.reason || j.error)) reason = (j.reason || j.error); } catch (_) {}
        return { ok: false, ct, http: r.status, reason };
      }
      return { ok, ct, http: r.status };
    } catch (e) {
      return { ok: false, error: String(e) };
    } finally { clearTimeout(t); }
  }

  // ---------- IMG lifecycle ----------
  function detachImg() {
    if (!slot) return;
    slot.innerHTML = '<div id="video-placeholder" class="text-gray-400 py-24">אין זרם</div>';
    syncHeights();
  }

  function attachImg() {
    if (!slot) return;
    const img = document.createElement("img");
    img.id = "video-stream";
    img.alt = "stream";
    img.style.maxWidth = "100%";
    img.style.height = "auto";      // הגובה הטבעי קובע
    img.style.objectFit = "contain";
    img.src = "/video/stream.mjpg?ts=" + Date.now();
    img.onload = () => { const ph = document.querySelector("#video-placeholder"); if (ph) ph.style.display = "none"; syncHeights(); };
    img.onerror = () => { const ph = document.querySelector("#video-placeholder"); if (ph) ph.style.display = ""; syncHeights(); };
    slot.innerHTML = "";
    slot.appendChild(img);
    lastAttachTs = Date.now();
    syncHeights();
  }

  // ---------- START / STOP ----------
  async function startFlow() {
    setReason(""); disableBtns(true);
    try {
      showWrap();
      try { await apiStop(); } catch(_) {}
      await new Promise(r => setTimeout(r, 300));
      try { await apiStart(0); }
      catch (e) { setDots({ camRunning: false, viewShown: true }); setReason("נכשל בהפעלת מצלמה: " + (e?.message || e)); return; }

      const st = await apiStatus();
      const running = !!st.running;
      setDots({ camRunning: running, viewShown: true });
      setMetrics(st.fps, st.size);
      if (!running) { setReason("המצלמה לא דיווחה כ'פועלת'."); return; }

      const head = await checkStreamHeaders(1200);
      if (!head.ok) { const why = head.reason ? (" (" + head.reason + ")") : ""; setReason("זרם MJPEG לא זמין" + why + "."); return; }
      attachImg();
    } finally { disableBtns(false); }
  }

  async function stopFlow() {
    setReason(""); disableBtns(true);
    try { detachImg(); try { await apiStop(); } catch(_) {} hideWrap(); setDots({ camRunning: false, viewShown: false }); setMetrics(null, null); syncHeights(); }
    finally { disableBtns(false); }
  }

  // ---------- Poll לסטטוס + התאוששות ----------
  async function tickStatus() {
    try {
      const st = await apiStatus();
      const running = !!st.running;
      setMetrics(st.fps, st.size);
      if (running) {
        if (wrap && wrap.style.display === "none") showWrap();
        const hasImg = !!document.querySelector("#video-stream");
        if (!hasImg && Date.now() - lastAttachTs > 1000) {
          const head = await checkStreamHeaders(800);
          if (head.ok) { attachImg(); setDots({ camRunning: true, viewShown: true }); setReason(""); }
          else { setDots({ camRunning: true, viewShown: false }); setReason("מצלמה פועלת, אך הווידאו לא התחבר."); }
        } else { setDots({ camRunning: true, viewShown: hasImg }); syncHeights(); }
      } else {
        setDots({ camRunning: false, viewShown: false });
      }
    } catch (_) { /* שקט */ }
  }

  function startStatusTimer() { if (statusTimer) clearInterval(statusTimer); statusTimer = setInterval(tickStatus, 2000); }

  // אירועים
  btnStart && btnStart.addEventListener("click", startFlow);
  btnStop  && btnStop .addEventListener("click", stopFlow);

  // מצב התחלתי
  setDots({ camRunning: false, viewShown: false });
  setMetrics(null, null);
  startStatusTimer();
  tickStatus();
  syncHeights();

  // =========================
  // אינדיקציות מערכת (תחתון)
  // =========================
  async function pollVideoIndicators(){
    // MJPEG
    checkStreamHeaders(800).then(h=>{
      setDot(ind.camDot, ind.camText, !!h.ok, "תקין", "כבוי/לא זמין");
    });

    // נתוני וידאו
    try{
      const r = await fetch("/api/video/status", { cache:"no-store" });
      if (!r.ok) throw 0;
      const s = await r.json();
      setText(ind.fps,  (s.fps!=null? s.fps : "—"));
      setText(ind.size, (Array.isArray(s.size)? (s.size[0]+"×"+s.size[1]) : "—"));
      setText(ind.up,   (s.uptime_sec!=null? Math.floor(s.uptime_sec/60)+" דק׳" : "—"));
    }catch(_){
      setText(ind.fps,"—"); setText(ind.size,"—"); setText(ind.up,"—");
    }
  }

  function num(x){ return Number.isFinite(+x) ? +x : NaN; }
  function fmt2(a,b){ const A=Number.isFinite(a)? a.toFixed(0)+"°":"–"; const B=Number.isFinite(b)? b.toFixed(0)+"°":"–"; return A+" / "+B; }

  function torsoTiltFromLM(lm, mirrored){
    if (!lm || lm.length<29) return NaN;
    const conv = p=>{ let x=p.x, y=p.y; if (mirrored) x = 1 - x; return {x,y,v:p.visibility ?? p.v ?? 1}; };
    const L11=conv(lm[11]), L12=conv(lm[12]), L23=conv(lm[23]), L24=conv(lm[24]);
    const chest={x:(L11.x+L12.x)/2,y:(L11.y+L12.y)/2}, hip={x:(L23.x+L24.x)/2,y:(L23.y+L24.y)/2};
    const dx=chest.x-hip.x, dy=chest.y-hip.y; if (!isFinite(dx)||!isFinite(dy)) return NaN;
    return Math.abs(Math.atan2(dx, dy)*180/Math.PI);
  }

  async function pollPayloadIndicators(){
    try{
      const r = await fetch("/payload", { cache:"no-store" });
      if (!r.ok) throw 0;
      const j = await r.json();
      setDot(ind.payDot, ind.payText, true, "תקין", "כבוי/לא זמין");

      const m = j.measurements || {};
      const shL=num(m.shoulder_left_deg),  shR=num(m.shoulder_right_deg);
      const elL=num(m.elbow_left_deg),     elR=num(m.elbow_right_deg);
      const knL=num(m.knee_left_deg),      knR=num(m.knee_right_deg);
      const torso = torsoTiltFromLM(j?.mp?.landmarks, j?.frame?.mirrored||j?.mp?.mirror_x);

      setText(ind.mShoulder, fmt2(shL, shR));
      setText(ind.mElbow,    fmt2(elL, elR));
      setText(ind.mKnee,     fmt2(knL, knR));
      setText(ind.mTorso,    Number.isFinite(torso)? torso.toFixed(0)+"°" : "—");
    }catch(_){
      setDot(ind.payDot, ind.payText, false, "תקין", "כבוי/לא זמין");
      setText(ind.mShoulder,"—"); setText(ind.mElbow,"—"); setText(ind.mKnee,"—"); setText(ind.mTorso,"—");
    }
  }

  // OD: ירוק "תקין" כשפועל (מכסה פורמטים שונים)
  async function pollODIndicators(){
    try{
      const r = await fetch("/api/od/status", { cache:"no-store" });
      if (!r.ok) throw 0;
      const s = await r.json();

      const running = !!(s.running || s.ok || s.enabled || s.active || (s.status && String(s.status).toLowerCase()==="running"));
      setDot(ind.odDot, ind.odText, running, "תקין", "כבוי/לא זמין");

      setText(ind.odFPS, (s.fps != null ? s.fps : "—"));
      setText(ind.odLAT, (s.latency_ms != null ? (s.latency_ms + " ms") : "—"));

      const objCount =
        Array.isArray(s.objects) ? s.objects.length :
        (s.objects != null ? s.objects : (s.count != null ? s.count : "—"));
      setText(ind.odOBJ, objCount);
    }catch(_){
      setDot(ind.odDot, ind.odText, false, "תקין", "כבוי/לא זמין");
      setText(ind.odFPS,"—"); setText(ind.odLAT,"—"); setText(ind.odOBJ,"—");
    }
  }

  // פולינג קל
  setInterval(pollVideoIndicators, 2000);
  setInterval(pollPayloadIndicators, 700);
  setInterval(pollODIndicators, 2000);

  // הפעלה ראשונה
  pollVideoIndicators(); pollPayloadIndicators(); pollODIndicators();

})();
