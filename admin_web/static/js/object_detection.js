// -------------------------------------------------------
// Object Detection UI bridge (client-side)
// -------------------------------------------------------
(() => {
  // ===== SETTINGS =====
  const ENDPOINTS = {
    START:   "/api/objdet/start",
    STOP:    "/api/objdet/stop",
    STATUS:  "/api/objdet/status",
    PAYLOAD: "/payload",
    ODCFG:   "/api/od/config"
  };

  // ברירות מחדל קשיחות (fallback)
  const DEFAULT_CFG = {
    threshold:   0.35,
    overlap:     0.60,
    max_objects: 20,
    period_ms:   150,
    imgsz:       640
  };

  const HELP = {
    threshold: "סף בטחון (0–1). גבוה = מחמיר (פחות זיהויים). נמוך = מתירני.",
    overlap:   "NMS IoU (0–1). כמה קופסאות חופפות נחשבות אותו אובייקט.",
    max_objects: "כמה אובייקטים לכל פריים לכל היותר.",
    period_ms: "מרווח בין הרצות (מילישניות). קטן יותר = יותר עומס/יותר FPS.",
    imgsz:     "רזולוציית קלט לרשת (למשל 640). גדול = דיוק טוב, איטי יותר."
  };

  const SKEY = "od_ui_cfg_v1";

  // ===== DOM =====
  const $ = id => document.getElementById(id);

  const elToggle     = $("toggle-od");
  const elToggleLbl  = $("toggle-od-label");
  const elStatus     = $("od-status");
  const elDot        = $("od-dot");

  const elCount      = $("od-count");
  const elFps        = $("od-fps");
  const elLat        = $("od-lat");
  const elAngle      = $("od-angle");
  const elList       = $("od-list");

  const elDbgPanel   = $("dbg-panel");
  const elDbgBtn     = $("dbg-toggle");
  const elDbgHealth  = $("dbg-health");
  const elDbgStatus  = $("dbg-status");
  const elDbgPayload = $("dbg-payload");

  const elSave       = $("od-save");
  const elReset      = $("od-reset");

  const elTh         = $("od-threshold");
  const elOv         = $("od-overlap");
  const elMax        = $("od-max-objects");
  const elPeriod     = $("od-period");
  const elImgSz      = $("od-imgsz");

  const elHelpTh     = $("help-threshold");
  const elHelpOv     = $("help-overlap");
  const elHelpMax    = $("help-max");
  const elHelpPeriod = $("help-period");
  const elHelpImgSz  = $("help-imgsz");

  const elImg        = $("mjpeg");
  const canvasPath   = $("path");
  const canvasObj    = $("obj");
  const elProfile    = $("od-profile"); // span דינמי להצגת פרופיל פעיל

  // ===== Utils =====
  const fmt1 = v => (v==null || Number.isNaN(v)) ? "—" : Number(v).toFixed(1);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clamp = (n,min,max) => Math.max(min, Math.min(max, n));

  const setDot = ok => { if (elDot) elDot.className = "w-2 h-2 rounded-full " + (ok? "bg-green-500":"bg-gray-300"); };
  const setStatus = (text, ok=null) => {
    if (elStatus) elStatus.innerHTML =
      `<span id="od-dot" class="w-2 h-2 rounded-full ${ok===true?"bg-green-500": ok===false?"bg-red-500":"bg-gray-300"}"></span> ${text}`;
    const d = $("od-dot");
    if (d) d.className = "w-2 h-2 rounded-full " + (ok===true?"bg-green-500": ok===false?"bg-red-500":"bg-gray-300");
  };
  const disableToggle = (dis) => {
    if (!elToggle) return;
    elToggle.disabled = dis;
    if (elToggleLbl) elToggleLbl.textContent = dis ? "מבצע…" : (elToggle.checked ? "פועל" : "מכובה");
  };
  const disableConfig = (dis, reason="") => {
    [elTh, elOv, elMax, elPeriod, elImgSz, elSave, elReset].forEach(el=>{
      if (!el) return;
      el.disabled = dis;
      el.title = dis ? (reason||"") : "";
    });
  };

  // ===== Canvas sync =====
  function syncCanvasSize(){
    if (!elImg) return;
    const r = elImg.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width));
    const h = Math.max(1, Math.round(r.height));
    [canvasPath, canvasObj].forEach(c=>{
      if (!c) return;
      c.width = w; c.height = h;
      c.style.width = w+"px"; c.style.height = h+"px";
    });
  }
  window.addEventListener("resize", syncCanvasSize);
  elImg?.addEventListener("load", syncCanvasSize);

  // ===== Help tooltips =====
  function applyHelp(){
    if (elTh) { elTh.title = HELP.threshold; if (elHelpTh) elHelpTh.textContent = HELP.threshold; }
    if (elOv) { elOv.title = HELP.overlap;   if (elHelpOv) elHelpOv.textContent = HELP.overlap; }
    if (elMax){ elMax.title= HELP.max_objects; if (elHelpMax) elHelpMax.textContent = HELP.max_objects; }
    if (elPeriod){ elPeriod.title = HELP.period_ms; if (elHelpPeriod) elHelpPeriod.textContent = HELP.period_ms; }
    if (elImgSz){ elImgSz.title = HELP.imgsz; if (elHelpImgSz) elHelpImgSz.textContent = HELP.imgsz; }
  }

  // ===== Config state =====
  let serverDefaults = null;
  let current = null;

  function readForm(){
    return {
      threshold:   Number.parseFloat(elTh?.value || DEFAULT_CFG.threshold),
      overlap:     Number.parseFloat(elOv?.value || DEFAULT_CFG.overlap),
      max_objects: Number.parseInt(elMax?.value || DEFAULT_CFG.max_objects),
      period_ms:   Number.parseInt(elPeriod?.value || DEFAULT_CFG.period_ms),
      imgsz:       Number.parseInt(elImgSz?.value || DEFAULT_CFG.imgsz)
    };
  }
  function writeForm(cfg){
    if (!cfg) return;
    if (elTh) elTh.value       = cfg.threshold;
    if (elOv) elOv.value       = cfg.overlap;
    if (elMax) elMax.value     = cfg.max_objects;
    if (elPeriod) elPeriod.value = cfg.period_ms;
    if (elImgSz) elImgSz.value = cfg.imgsz;
  }

  function saveSession(cfg){ try { sessionStorage.setItem(SKEY, JSON.stringify(cfg)); } catch(_){} }
  function loadSession(){ try { const s = sessionStorage.getItem(SKEY); return s ? JSON.parse(s) : null; } catch(_){ return null; } }
  function clearSession(){ try { sessionStorage.removeItem(SKEY); } catch(_){} }

  async function fetchServerDefaults(){
    try{
      const r = await fetch(ENDPOINTS.ODCFG, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      const cfg = await r.json();
      serverDefaults = {
        threshold:   Number(cfg.threshold ?? DEFAULT_CFG.threshold),
        overlap:     Number(cfg.overlap   ?? DEFAULT_CFG.overlap),
        max_objects: Number(cfg.max_objects ?? DEFAULT_CFG.max_objects),
        period_ms:   Number(cfg.period_ms ?? DEFAULT_CFG.period_ms),
        imgsz:       Number(cfg.imgsz     ?? DEFAULT_CFG.imgsz)
      };
      if (elProfile) elProfile.textContent = (cfg.profile || `${cfg.provider||"yolo"}_${cfg.device||"cpu"}_${cfg.imgsz||640}`);
      disableConfig(false);
      if (elDbgHealth) elDbgHealth.textContent = JSON.stringify({ od_config: serverDefaults }, null, 2);
      return true;
    }catch(_e){
      serverDefaults = null;
      disableConfig(true, "שרת לא מספק /api/od/config (אופציונלי)");
      if (elDbgHealth) elDbgHealth.textContent = JSON.stringify({ od_config: "unavailable" }, null, 2);
      return false;
    }
  }

  function applyDefaultsToForm(){
    const base = serverDefaults || DEFAULT_CFG;
    current = { ...base };
    writeForm(current);
  }
  function applySessionIfExists(){
    const s = loadSession();
    if (s) { current = { ...s }; writeForm(current); }
  }

  // ===== START/STOP / STATUS =====
  async function startOD(){
    disableToggle(true);
    try{
      setStatus("מפעיל זיהוי…", null);
      const r = await fetch(ENDPOINTS.START, { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      setStatus("פועל", true);
      return true;
    }catch(e){
      console.error(e);
      setStatus("שגיאה בהפעלה (ה־worker המקומי כבוי כברירת מחדל)", false);
      if (elToggle) elToggle.checked = false;
      return false;
    }finally{
      disableToggle(false);
    }
  }
  async function stopOD(){
    disableToggle(true);
    try{
      setStatus("מכבה זיהוי…", null);
      const r = await fetch(ENDPOINTS.STOP, { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      setStatus("מכובה", null);
      return true;
    }catch(e){
      console.error(e);
      setStatus("שגיאה בכיבוי", false);
      if (elToggle) elToggle.checked = true;
      return false;
    }finally{
      disableToggle(false);
    }
  }
  async function pollStatus(){
    try{
      const r = await fetch(ENDPOINTS.STATUS, { cache: "no-store" });
      if (!r.ok) throw new Error(r.statusText);
      const s = await r.json();
      const running = !!s?.running;
      if (elToggle) elToggle.checked = running;
      if (elToggleLbl) elToggleLbl.textContent = running ? "פועל" : "מכובה";
      setDot(running);
      setStatus(running ? "פועל" : "ממתין…", running || null);
      if (elFps && s?.fps!=null) elFps.textContent = fmt1(s.fps);
      if (elDbgStatus) elDbgStatus.textContent = JSON.stringify(s, null, 2);
      if (s && s.enabled_by_env === false) {
        // ה-worker הפנימי כבוי — ננעל את המתג כדי לא לבלבל
        if (elToggle) elToggle.disabled = true;
        if (elToggleLbl) elToggleLbl.textContent = "כבוי כברירת מחדל";
        elStatus.title = "ה־worker המקומי כבוי (ENABLE_LOCAL_YOLO_WORKER=0). הזיהוי מגיע מהמנוע הראשי.";
      }
    }catch(_e){
      setDot(false);
      setStatus("לא זמין", false);
    }finally{
      setTimeout(pollStatus, 1200);
    }
  }

  // ===== SAVE / RESET =====
  async function saveConfig(){
    const cfg = readForm();
    current = { ...cfg };
    saveSession(current);
    if (elSave) elSave.disabled = true;

    try{
      if (serverDefaults === null) {
        setStatus("ההגדרות עודכנו (לוקלי בלבד)", true);
      } else {
        const r = await fetch(ENDPOINTS.ODCFG, {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify(cfg)
        });
        if (!r.ok) throw new Error(await r.text());
        setStatus("ההגדרות נשמרו (שרת)", true);
      }
      await sleep(400);
      setStatus(elToggle?.checked ? "פועל" : "ממתין…", elToggle?.checked || null);
    }catch(e){
      console.error(e);
      setStatus("שגיאה בשמירת הגדרות", false);
    }finally{
      if (elSave) elSave.disabled = false;
    }
  }

  async function resetToDefaults(){
    clearSession();
    applyDefaultsToForm();

    if (serverDefaults !== null) {
      try{
        const r = await fetch(ENDPOINTS.ODCFG, {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify(serverDefaults)
        });
        if (!r.ok) throw new Error(await r.text());
        setStatus("חזר לברירת-מחדל", true);
      }catch(e){
        console.error(e);
        setStatus("שגיאה בהחזרה לברירת-מחדל (שרת)", false);
      }
    } else {
      setStatus("חזר לברירת-מחדל (לוקלי)", true);
    }
  }

  // ===== PAYLOAD (ציור וקונסול) =====
  const normalizeBox = (obj) => {
    if (!obj) return null;
    const b = obj.box ?? obj.bbox ?? null;
    if (!b) return null;

    if (Array.isArray(b) && b.length>=4) {
      const [a,b1,c,d] = b.map(Number);
      if (c > a && d > b1) return { x1:a, y1:b1, x2:c, y2:d };
      const x=a, y=b1, w=c, h=d;
      return { x1:x, y1:y, x2:x+w, y2:y+h };
    }
    if (typeof b === "object") {
      if ("x1" in b && "y1" in b && "x2" in b && "y2" in b)
        return { x1:+b.x1, y1:+b.y1, x2:+b.x2, y2:+b.y2 };
      if ("x" in b && "y" in b && "w" in b && "h" in b) {
        const x=+b.x, y=+b.y, w=+b.w, h=+b.h;
        return { x1:x, y1:y, x2:x+w, y2:y+h };
      }
    }
    return null;
  };

  function drawBoxes(objs, frameW=null, frameH=null){
    if (!canvasObj || !elImg) return;
    const ctx = canvasObj.getContext("2d"); if (!ctx) return;
    const cw = canvasObj.width, ch = canvasObj.height;
    ctx.clearRect(0,0,cw,ch);

    const sx = frameW ? (cw / frameW) : 1.0;
    const sy = frameH ? (ch / frameH) : 1.0;

    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(59,130,246,0.95)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillStyle = "rgba(0,0,0,0.6)";

    (Array.isArray(objs)?objs:[]).slice(0,50).forEach(o=>{
      const nb = normalizeBox(o); if (!nb) return;
      const x1 = clamp(Math.round(nb.x1 * sx), 0, cw-1);
      const y1 = clamp(Math.round(nb.y1 * sy), 0, ch-1);
      const x2 = clamp(Math.round(nb.x2 * sx), 0, cw-1);
      const y2 = clamp(Math.round(nb.y2 * sy), 0, ch-1);
      const w = Math.max(0, x2-x1), h = Math.max(0, y2-y1);
      ctx.strokeRect(x1, y1, w, h);
      const label = (o.label ?? o.name ?? "obj") + (o.score!=null?` ${Number(o.score).toFixed(2)}`:"");
      const tw = ctx.measureText(label).width + 6;
      const top = Math.max(0, y1 - 14);
      ctx.fillRect(x1, top, tw, 14);
      ctx.fillStyle = "white"; ctx.fillText(label, x1+3, top+11);
      ctx.fillStyle = "rgba(0,0,0,0.6)";
    });
  }

  async function pollPayload(){
    try{
      const ctrl = new AbortController();
      const t = setTimeout(()=> ctrl.abort(), 3000);
      const r = await fetch(ENDPOINTS.PAYLOAD, { cache: "no-store", signal: ctrl.signal });
      clearTimeout(t);
      if (!r.ok) throw new Error(r.statusText);
      const data = await r.json();

      const fps = data?.objdet?.detector_state?.fps ?? data?.perf?.fps ?? data?.fps ?? null;
      const lat = data?.perf?.latency_ms ?? data?.dt_ms ?? null;
      if (elFps) elFps.textContent = fmt1(fps);
      if (elLat) elLat.textContent = fmt1(lat);

      const objs = (data?.objdet?.objects ?? data?.objects) || [];
      if (elCount) elCount.textContent = Array.isArray(objs) ? objs.length : 0;

      if (elList){
        elList.innerHTML = (!Array.isArray(objs) || objs.length===0)
          ? `<div class="text-gray-400">אין נתונים עדיין…</div>`
          : objs.slice(0,20).map(o=>{
              const name = o.label ?? o.name ?? "obj";
              const sc = (o.score!=null) ? Number(o.score).toFixed(2) :
                         (o.conf!=null)   ? Number(o.conf).toFixed(2) : "—";
              const nb = normalizeBox(o);
              const boxTxt = nb ? `[${nb.x1|0}, ${nb.y1|0}, ${nb.x2|0}, ${nb.y2|0}]` : "";
              return `<div class="flex items-center justify-between"><span>${name}</span><span class="text-gray-500">${sc} ${boxTxt}</span></div>`;
            }).join("");
      }

      const angle = data?.objdet?.frame?.angle ?? data?.measurements?.last_angle ?? data?.features?.last_angle ?? null;
      if (elAngle) elAngle.textContent = (angle==null) ? "—" : Number(angle).toFixed(1);

      if (elDbgPayload) elDbgPayload.textContent = JSON.stringify(data?.objdet ?? data, null, 2);

      const f = data?.objdet?.frame ?? data?.frame ?? {};
      const fw = Number(f.w) || null;
      const fh = Number(f.h) || null;
      drawBoxes(objs, fw, fh);
    }catch(_e){
      // שקט
    }finally{
      setTimeout(pollPayload, 300);
    }
  }

  // ===== Events =====
  elToggle?.addEventListener("change", async () => {
    if (elToggle.checked) await startOD(); else await stopOD();
  });
  elSave?.addEventListener("click", saveConfig);
  elReset?.addEventListener("click", resetToDefaults);

  [elTh, elOv, elMax, elPeriod, elImgSz].forEach(el=>{
    el?.addEventListener("change", ()=> {
      current = readForm();
      saveSession(current);
    });
  });

  elDbgBtn?.addEventListener("click", ()=> elDbgPanel?.classList.toggle("hidden"));

  // ===== Boot =====
  (async function boot(){
    syncCanvasSize();
    applyHelp();
    pollStatus();
    pollPayload();

    await fetchServerDefaults();   // 1) נסה להביא דיפולט מהשרת
    applyDefaultsToForm();         // 2) מלא את הטופס
    applySessionIfExists();        // 3) שחזר התאמות אם יש בסשן
  })();
})();
