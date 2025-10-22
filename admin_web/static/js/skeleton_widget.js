/* skeleton_widget.js — וידג'ט שלד לפי מדידות (<700 שורות)
   שינויי מפתח:
   • אין ציור ראש.
   • Wrist/Flex-Ext נלקחים אך ורק מה-kinematics (payload.measurements).
   • אופציונלי: הצגת Radial/Ulnar אם קיים ב-measurements (wrist_radul_*_deg).
   • OVERLAY_MIN_CHANGE להפחתת ריצודים במספרים על הקשתות.
   • throttle לסטטוס/טבלת המדידות.
   • טבלת המדידות בצבעים ניטרליים בלבד (ללא ירוק/אדום).
   שימוש:
   <div class="bp-skeleton" data-endpoint="/payload" data-autostart="true">
     <input type="checkbox" class="bp-skel-toggle">
     <div class="bp-skel-status"></div>
     <canvas class="bp-skel-canvas"></canvas>
     <label><input type="checkbox" class="bp-show-angles"> זוויות (מודל)</label>
     <label><input type="checkbox" class="bp-show-pose"> Pose</label>
     <label><input type="checkbox" class="bp-show-hands"> ידיים</label>
     <label><input type="checkbox" class="bp-toggle-angles-overlay"> זוויות על השלד</label>
     <div class="bp-measurements"></div>
     <span class="bp-delta" data-k="shoulder_left"></span>
     ...
   </div>
*/
(function(){
  "use strict";

  // ---------------- Config ----------------
  const POLL_MS = 120;
  const ALPHA = 0.25;                // EMA לזוויות
  const UI_MEAS_UPDATE_MS = 300;     // עדכון טבלת מדידות
  const UI_STATUS_UPDATE_MS = 500;   // עדכון סטטוס עליון
  const OVERLAY_MIN_CHANGE = 0.8;    // סף שינוי להצגת מספר על קשת

  // ---------------- Boot ----------------
  document.querySelectorAll(".bp-skeleton").forEach(initWidget);

  function fitCanvasToBox(canvas){
    if (!canvas) return;
    const r = canvas.getBoundingClientRect();
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const w = Math.max(1, Math.round(r.width  * dpr));
    const h = Math.max(1, Math.round(r.height * dpr));
    if (canvas.width !== w || canvas.height !== h){
      canvas.width = w; canvas.height = h;
    }
  }

  function initWidget(root){
    const endpoint = root.getAttribute("data-endpoint") || "/payload";
    const auto = (root.getAttribute("data-autostart")||"false").toLowerCase()==="true";

    const canvas   = root.querySelector(".bp-skel-canvas");
    const ctx      = canvas ? canvas.getContext("2d") : null;
    const elToggle = root.querySelector(".bp-skel-toggle");
    const elStatus = root.querySelector(".bp-skel-status");
    const elDeltas = root.querySelectorAll(".bp-delta");
    const elMeas   = root.querySelector(".bp-measurements");

    // מתגים אופציונליים
    const elShowAngles   = root.querySelector(".bp-show-angles");
    const elShowPose     = root.querySelector(".bp-show-pose");
    const elShowHands    = root.querySelector(".bp-show-hands");
    const elAnglesOverlay= root.querySelector(".bp-toggle-angles-overlay");

    if (!canvas || !ctx || !elToggle || !elStatus){
      console.warn("[bp-skeleton] missing required elements (.bp-skel-canvas/.bp-skel-toggle/.bp-skel-status)");
      return;
    }

    fitCanvasToBox(canvas);
    try { new ResizeObserver(()=>fitCanvasToBox(canvas)).observe(canvas.parentElement || canvas); } catch(_){}

    // מצב זיכרון (כיבוי/הדלקה)
    const idx = Array.from(document.querySelectorAll(".bp-skeleton")).indexOf(root);
    const kEnabled = "bp_skeleton_enabled_"+idx;
    let enabled = (localStorage.getItem(kEnabled) ?? (auto ? "1" : "0")) === "1";
    elToggle.checked = enabled;
    elToggle.addEventListener("change", ()=>{
      enabled = elToggle.checked;
      localStorage.setItem(kEnabled, enabled?"1":"0");
      if (enabled) start(); else stop();
    });

    // שמירת מצבים למתגים (אם קיימים)
    const states = initToggle(elShowAngles, "bp_show_angles_"+idx, true);
    Object.assign(states, initToggle(elShowPose,   "bp_show_pose_"+idx,   true));
    Object.assign(states, initToggle(elShowHands,  "bp_show_hands_"+idx,  true));
    Object.assign(states, initToggle(elAnglesOverlay, "bp_show_overlay_"+idx, false));

    let raf = null, lastRaw = null, emaAngles = {};
    let lastMeasDOM = "", lastMeasAt = 0, lastStatusText = "", lastStatusAt = 0;
    const lastOverlayVals = new Map();

    function start(){ setStatus("פועל"); poll(); drawLoop(); }
    function stop(){ setStatus("כבוי"); if (raf) cancelAnimationFrame(raf); raf=null; clear(); }
    if (enabled) start(); else stop();

    // ----- data polling -----
    async function poll(){
      if (!enabled) return;
      try {
        const r = await fetch(endpoint, { cache: "no-store" });
        if (r.ok) lastRaw = await r.json();
        else setStatus("שגיאת endpoint ("+r.status+")");
      } catch(e){ setStatus("שגיאת רשת"); }
      setTimeout(poll, POLL_MS);
    }

    function drawLoop(){ if (!enabled) return; drawOnce(); raf = requestAnimationFrame(drawLoop); }

    // ----- main draw -----
    function drawOnce(){
      clear();
      const p = normalizePayload(lastRaw);
      renderIndicators(elStatus, p);
      if (!p) return;

      const W = canvas.width, H = canvas.height;
      const anchor = { x: W*0.5, y: H*0.62 }, scale = Math.min(W,H)*0.45;

      const ang = smoothAngles(p.pose.angles_deg, emaAngles);
      const seg = Object.assign({humerus:0.28,ulna:0.24,femur:0.34,tibia:0.30,torso:0.30}, p.pose.segments_norm||{});

      // --- שלד (מודל) ---
      let Jcalc = null;
      if (states.show_angles) {
        Jcalc = buildSkeleton(ang, seg, anchor, scale);
        drawSkeleton(ctx, Jcalc, "#111", 3);
      }

      // --- Pose (אם קיים) ---
      let JM = null, lmkPose = null, deltas = null;
      if (states.show_pose && p.mp && Array.isArray(p.mp.landmarks) && p.mp.landmarks.length>=33){
        lmkPose = projectPoseLandmarks(p.mp.landmarks, p.frame, W, H);
        JM = pickBasicJoints(lmkPose);
        drawSkeleton(ctx, JM, "rgba(0,0,0,0.35)", 1.5, [5,4]);
        deltas = calcAngleDeltas(ang, JM);
        updateDeltaUI(elDeltas, deltas);
      } else {
        updateDeltaUI(elDeltas, null);
      }

      // --- ידיים (ציור נקודות/קווים בסיסי, לא חובה) ---
      if (states.show_hands) {
        const handSets = extractHandsArrays(p.mp);
        if (handSets && handSets.length){
          const projected = handSets.map(arr => projectGenericLandmarks(arr, p.frame, W, H));
          for (const hand of projected){
            drawHand(ctx, hand, { stroke:"#222", lineW:2, pointR:2.2 });
            drawPalmBase(ctx, hand);
          }
        }
      }

      // --- זוויות על השלד (קשת+מספר) — Wrist המספר מגיע מהמדידה בלבד ---
      if (states.show_overlay){
        if (Jcalc) drawJointAngleOverlay(ctx, Jcalc, { color:"#0f766e", label:"#064e3b" }, lastOverlayVals, ang);
        if (JM)    drawJointAngleOverlay(ctx, JM,   { color:"rgba(0,0,0,0.45)", label:"rgba(0,0,0,0.75)" }, lastOverlayVals, ang);
      }

      renderMeasurements(elMeas, ang, deltas, p);
    }

    function setStatus(t){ elStatus.textContent = t; }
    function clear(){ ctx.clearRect(0,0,canvas.width, canvas.height); }

    function initToggle(el, key, def){
      const out = {};
      if (!el) return out;
      const saved = localStorage.getItem(key);
      const val = saved==null ? (def?"1":"0") : saved;
      el.checked = (val==="1");
      const prop = key.replace(/\W+/g,'_').replace(/^bp_/,'').replace(/_\d+$/,'');
      out[prop] = el.checked;
      el.addEventListener("change", ()=>{ localStorage.setItem(key, el.checked?"1":"0"); out[prop] = el.checked; });
      return out;
    }

    // ---------- UI יציב (throttle) ----------
    function renderIndicators(elStatus, p){
      if (!elStatus){ return; }
      if (!p){ elStatus.textContent = "אין payload"; return; }
      const now = performance.now();
      if (now - lastStatusAt < UI_STATUS_UPDATE_MS) return;
      lastStatusAt = now;

      const poseOK  = !!(p.mp && Array.isArray(p.mp.landmarks) && p.mp.landmarks.length>=33);
      const hands   = extractHandsArrays(p.mp);
      const handsN  = hands ? hands.length : 0;
      const conf    = p.pose.confidence;

      const chips = [];
      chips.push(poseOK ? "Pose: ✔" : "Pose: –");
      chips.push(`Hands: ${handsN}`);
      if (Number.isFinite(conf)) chips.push(`conf: ${conf.toFixed(2)}`);

      const txt = chips.join(" · ");
      if (txt !== lastStatusText){ lastStatusText = txt; elStatus.textContent = txt; }
    }

    // ---------- Measurements (ניטרלי, בלי ירוק/אדום) ----------
    function renderMeasurements(el, ang, deltas, p){
      if (!el) return;
      const now = performance.now();
      if (now - lastMeasAt < UI_MEAS_UPDATE_MS) return;
      lastMeasAt = now;

      const wrFlexL = pickMeas(p.meas, ["wrist_flex_ext_left_deg"]);
      const wrFlexR = pickMeas(p.meas, ["wrist_flex_ext_right_deg"]);
      const wrRadL  = pickMeas(p.meas, ["wrist_radul_left_deg","wrist_rad_uln_left_deg","wrist_radial_ulnar_left_deg"]);
      const wrRadR  = pickMeas(p.meas, ["wrist_radul_right_deg","wrist_rad_uln_right_deg","wrist_radial_ulnar_right_deg"]);

      const rows = [
        row("Shoulder L", ang.shoulder_left,  deltas?.shoulder_left),
        row("Shoulder R", ang.shoulder_right, deltas?.shoulder_right),
        row("Elbow L",    ang.elbow_left,     deltas?.elbow_left),
        row("Elbow R",    ang.elbow_right,    deltas?.elbow_right),
        row("Wrist Flex L", wrFlexL, NaN),
        row("Wrist Flex R", wrFlexR, NaN),
        // בטל/הפעל לפי רצונך:
        // row("Wrist Rad/Uln L", wrRadL, NaN),
        // row("Wrist Rad/Uln R", wrRadR, NaN),
        row("Knee L",     ang.knee_left,      deltas?.knee_left),
        row("Knee R",     ang.knee_right,     deltas?.knee_right),
      ];

      const html = `
        <div class="bp-meas-grid" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;">
          ${rows.map(htmlChipNeutral).join("")}
        </div>`;
      if (html !== lastMeasDOM){ lastMeasDOM = html; el.innerHTML = html; }

      function row(name, angle, delta){
        return {name, a: Number.isFinite(angle) ? angle : NaN, d: Number.isFinite(delta) ? delta : NaN};
      }

      // ניטרלי: אפור/כחול עדין בלבד (ללא אדום/ירוק)
      function htmlChipNeutral(r){
        const bg = "#f5f6f8";      // אפור עדין
        const col= "#1f2937";      // טקסט כהה
        const badgeBg = "#e8eefc"; // כחלחל עדין
        const badgeTx = "#1e40af"; // כחול כהה
        const a  = Number.isFinite(r.a) ? r.a.toFixed(0)+"°" : "–";
        const d  = Number.isFinite(r.d) ? `<span style="background:${badgeBg};color:${badgeTx};padding:2px 6px;border-radius:999px;font-size:11px;margin-inline-start:8px;">Δ${r.d.toFixed(1)}</span>` : "";
        return `<div style="background:${bg};color:${col};padding:8px 10px;border-radius:10px;font-size:12px;display:flex;align-items:center;justify-content:space-between;">
          <span>${r.name}</span>
          <span style="font-variant-numeric:tabular-nums;display:inline-flex;align-items:center;gap:6px;min-width:8ch;justify-content:flex-end">${a}${d}</span>
        </div>`;
      }

      function pickMeas(meas, names){
        if (!meas) return NaN;
        for (const n of names) if (Number.isFinite(+meas[n])) return +meas[n];
        return NaN;
      }
    }
  }

  // ---------------- Normalization ----------------
  function normalizePayload(raw){
    if (!raw || typeof raw !== "object") return null;

    const mirrored =
      (raw?.frame?.mirrored === true) ||
      (raw?.mp?.mirror_x === true) ||
      (raw?.objdet?.frame?.mirrored === true) || false;

    const fw = raw?.frame?.w ?? raw?.["frame.w"] ?? raw?.frame?.width ?? raw?.video?.width  ?? null;
    const fh = raw?.frame?.h ?? raw?.["frame.h"] ?? raw?.frame?.height ?? raw?.video?.height ?? null;

    const meas = (raw.measurements && typeof raw.measurements === "object") ? raw.measurements : {};
    const m = (k)=> Number.isFinite(+meas[k]) ? +meas[k] : (Number.isFinite(+raw[k]) ? +raw[k] : NaN);

    // מפרקים עיקריים (Wrist מהמדידה בלבד)
    const angles = {
      shoulder_left:  m("shoulder_left_deg"),
      shoulder_right: m("shoulder_right_deg"),
      elbow_left:     m("elbow_left_deg"),
      elbow_right:    m("elbow_right_deg"),
      hip_left:       m("hip_left_deg"),
      hip_right:      m("hip_right_deg"),
      knee_left:      m("knee_left_deg"),
      knee_right:     m("knee_right_deg"),
      wrist_left:     m("wrist_flex_ext_left_deg"),
      wrist_right:    m("wrist_flex_ext_right_deg"),
    };

    const mp = raw?.mp || raw?.mediapipe || null;
    if (mp && mp.mirror_x == null) mp.mirror_x = mirrored;

    return {
      frame: { w: fw, h: fh, mirrored, ts_ms: raw?.ts_ms ?? raw?.meta?.finalized_at_ms ?? Date.now() },
      pose: {
        angles_deg: angles,
        segments_norm: { humerus:0.28, ulna:0.24, femur:0.34, tibia:0.30, torso:0.30 },
        confidence: Number.isFinite(+raw.confidence) ? +raw.confidence :
                    Number.isFinite(+meas.confidence) ? +meas.confidence : 1,
      },
      mp,
      meas
    };
  }

  // ---------------- Math / Draw helpers ----------------
  function smoothAngles(a, ema){
    const out={}, keys=["shoulder_left","shoulder_right","elbow_left","elbow_right","hip_left","hip_right","knee_left","knee_right","wrist_left","wrist_right"];
    for (const k of keys){
      const v = Number(a[k]); if (!isFinite(v)) continue;
      out[k] = (ema[k]==null) ? v : (ALPHA*v + (1-ALPHA)*ema[k]);
      ema[k]=out[k];
    }
    return out;
  }

  function buildSkeleton(ang, seg, A, S){
    const rad = d=>d*Math.PI/180, vec=(L,D)=>({x:L*Math.cos(rad(D)), y:L*Math.sin(rad(D))});
    const hip = {x:A.x, y:A.y}, chest = {x:A.x, y:A.y - S*seg.torso};
    const shL=chest, shR=chest;

    const vHL=vec(S*seg.humerus, -ang.shoulder_left);
    const elL={x:shL.x+vHL.x,y:shL.y+vHL.y};
    const vUL=vec(S*seg.ulna, -ang.shoulder_left + (180 - ang.elbow_left));
    const wrL={x:elL.x+vUL.x,y:elL.y+vUL.y};

    const vHR=vec(S*seg.humerus, -ang.shoulder_right);
    const elR={x:shR.x+vHR.x,y:shR.y+vHR.y};
    const vUR=vec(S*seg.ulna, -ang.shoulder_right - (180 - ang.elbow_right));
    const wrR={x:elR.x+vUR.x,y:elR.y+vUR.y};

    const vFL=vec(S*seg.femur, 90 - ang.hip_left);
    const knL={x:hip.x+vFL.x,y:hip.y+vFL.y};
    const vTL=vec(S*seg.tibia, 90 - ang.hip_left + (180 - ang.knee_left));
    const anL={x:knL.x+vTL.x,y:knL.y+vTL.y};

    const vFR=vec(S*seg.femur, 90 - ang.hip_right);
    const knR={x:hip.x+vFR.x,y:hip.y+vFR.y};
    const vTR=vec(S*seg.tibia, 90 - ang.hip_right - (180 - ang.knee_right));
    const anR={x:knR.x+vTR.x,y:knR.y+vTR.y};

    return { chest, hip, shL, shR, elL, elR, wrL, wrR, knL, knR, anL, anR };
  }

  function drawSkeleton(ctx, J, stroke="black", width=2, dash=null){
    ctx.save();
    ctx.lineWidth = width;
    if (dash) ctx.setLineDash(dash);
    ctx.strokeStyle = stroke; ctx.fillStyle = stroke;

    const bones = [
      [J.hip, J.chest],
      [J.chest, J.shL], [J.chest, J.shR],
      [J.shL, J.elL], [J.elL, J.wrL],
      [J.shR, J.elR], [J.elR, J.wrR],
      [J.hip, J.knL], [J.knL, J.anL],
      [J.hip, J.knR], [J.knR, J.anR],
    ];
    for (const [a,b] of bones) if (a && b){ ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); }
    const joints = [J.chest,J.hip,J.shL,J.shR,J.elL,J.elR,J.wrL,J.wrR,J.knL,J.knR,J.anL,J.anR];
    for (const p of joints) if (p){ ctx.beginPath(); ctx.arc(p.x,p.y,width*1.2,0,Math.PI*2); ctx.fill(); }
    ctx.restore();
  }

  // --- זוויות על השלד (קשת+מספר) — Wrist מציג מספר מהמדידה בלבד ---
  function drawJointAngleOverlay(ctx, J, opt={}, cacheMap, anglesMap){
    const color = opt.color || "#0f766e";
    const label = opt.label || "#064e3b";
    const rBase = opt.r || 26;

    const defs = [
      {a:J.chest, b:J.shL, c:J.elL, key:"shoulder_L"},
      {a:J.chest, b:J.shR, c:J.elR, key:"shoulder_R"},
      {a:J.shL,   b:J.elL, c:J.wrL, key:"elbow_L"},
      {a:J.shR,   b:J.elR, c:J.wrR, key:"elbow_R"},
      {a:J.chest, b:J.hip, c:J.knL, key:"hip_L"},
      {a:J.chest, b:J.hip, c:J.knR, key:"hip_R"},
      {a:J.hip,   b:J.knL, c:J.anL, key:"knee_L"},
      {a:J.hip,   b:J.knR, c:J.anR, key:"knee_R"},
      // Wrist: קשת גיאומטרית, אבל המספר נלקח מה-anglesMap.wrist_*
      {a:J.elL, b:J.wrL, c: J.wrL && J.elL ? {x: J.wrL.x + (J.wrL.x - J.elL.x)*0.35, y: J.wrL.y + (J.wrL.y - J.elL.y)*0.35} : null, key:"wrist_L", wristKey:"wrist_left"},
      {a:J.elR, b:J.wrR, c: J.wrR && J.elR ? {x: J.wrR.x + (J.wrR.x - J.elR.x)*0.35, y: J.wrR.y + (J.wrR.y - J.elR.y)*0.35} : null, key:"wrist_R", wristKey:"wrist_right"},
    ];

    ctx.save();
    ctx.lineWidth = 2;
    ctx.strokeStyle = color;
    ctx.fillStyle = label;
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";

    for (const d of defs){
      if (!d.a||!d.b||!d.c) continue;

      // ערך גיאומטרי ברירת מחדל
      let val = angleAt(d.a, d.b, d.c);
      // Wrist → עדיפות לערך מדוד
      if (d.wristKey && anglesMap && Number.isFinite(anglesMap[d.wristKey])) val = anglesMap[d.wristKey];
      if (!Number.isFinite(val)) continue;

      // סף שינוי להצגת מספר
      if (cacheMap){
        const prev = cacheMap.get(d.key);
        if (prev!=null && Math.abs(prev - val) < OVERLAY_MIN_CHANGE){
          // נשארת הקשת בלבד
        } else {
          cacheMap.set(d.key, val);
        }
      }

      const a1 = Math.atan2(d.a.y - d.b.y, d.a.x - d.b.x);
      const a2 = Math.atan2(d.c.y - d.b.y, d.c.x - d.b.x);
      const r = Math.max(16, Math.min(rBase, (dist(d.b,d.a)+dist(d.b,d.c))*0.25));

      const {s,e,ccw} = shortArc(a1, a2);
      ctx.beginPath(); ctx.arc(d.b.x, d.b.y, r, s, e, ccw); ctx.stroke();

      const showLabel = !cacheMap || Math.abs((cacheMap.get(d.key)||val) - val) >= OVERLAY_MIN_CHANGE;
      if (showLabel){
        const mid = midAngle(s, e, ccw);
        const tx = d.b.x + Math.cos(mid) * (r + 10);
        const ty = d.b.y + Math.sin(mid) * (r + 10);
        ctx.fillText(val.toFixed(0)+"°", tx, ty);
      }
    }
    ctx.restore();

    function angleAt(a,b,c){
      const v1={x:a.x-b.x,y:a.y-b.y}, v2={x:c.x-b.x,y:c.y-b.y};
      const d=v1.x*v2.x+v1.y*v2.y, m=Math.hypot(v1.x,v1.y)*Math.hypot(v2.x,v2.y);
      if (m===0) return NaN;
      const cos=Math.max(-1,Math.min(1,d/m));
      return Math.acos(cos)*180/Math.PI;
    }
    function dist(p,q){ return Math.hypot(p.x-q.x, p.y-q.y); }
    function norm(a){ while(a<=-Math.PI) a+=2*Math.PI; while(a>Math.PI) a-=2*Math.PI; return a; }
    function shortArc(a,b){
      let s=a,e=b,d=norm(e-s),ccw=false;
      if (Math.abs(d) > Math.PI){ if (d > 0){ s = e; e = a; d = norm(e - s); } }
      ccw = d < 0; return {s,e,ccw};
    }
    function midAngle(s,e,ccw){
      let d = e - s;
      if (ccw && d>0) d -= 2*Math.PI;
      if (!ccw && d<0) d += 2*Math.PI;
      return s + d/2;
    }
  }

  // ---------- Pose landmarks ----------
  function projectPoseLandmarks(lmk, frame, W, H){
    const mirrored = !!frame?.mirrored;
    return lmk.map(pt => { let x = pt.x * W, y = pt.y * H; if (mirrored) x = W - x; return { x, y, v: pt.v ?? pt.visibility ?? 1 }; });
  }

  // ---------- Hands (21 נק' לכל יד) ----------
  function extractHandsArrays(mp){
    if (!mp) return [];
    if (mp.hands && Array.isArray(mp.hands.multiHandLandmarks)) return mp.hands.multiHandLandmarks;
    if (Array.isArray(mp.hands)) return mp.hands;
    if (Array.isArray(mp.multiHandLandmarks)) return mp.multiHandLandmarks;
    return [];
  }

  function projectGenericLandmarks(lmkArr, frame, W, H){
    const mirrored = !!frame?.mirrored;
    return lmkArr.map(pt=>{ let x = pt.x * W, y = pt.y * H; if (mirrored) x = W - x; return { x, y, v: pt.v ?? pt.visibility ?? 1 }; });
  }

  function drawPalmBase(ctx, pts){
    const wrist = pts[0], indexMCP = pts[5], pinkyMCP = pts[17];
    if (!wrist || !indexMCP || !pinkyMCP) return;
    ctx.save();
    ctx.strokeStyle="rgba(0,0,0,0.5)";
    ctx.lineWidth=2;
    ctx.beginPath();
    ctx.moveTo(indexMCP.x, indexMCP.y);
    ctx.quadraticCurveTo(wrist.x, wrist.y, pinkyMCP.x, pinkyMCP.y);
    ctx.stroke();
    ctx.restore();
  }

  function drawHand(ctx, pts, opt={}){
    const stroke = opt.stroke || "#222";
    const lineW  = opt.lineW || 2;
    const r      = opt.pointR || 2.2;

    const C = {
      WRIST: 0,
      THUMB: [1,2,3,4],
      INDEX: [5,6,7,8],
      MIDDLE:[9,10,11,12],
      RING:  [13,14,15,16],
      PINKY: [17,18,19,20]
    };

    function line(a,b){ if (!a||!b) return; ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); }

    ctx.save();
    ctx.lineWidth = lineW;
    ctx.strokeStyle = stroke;
    ctx.fillStyle = stroke;

    const w = pts[C.WRIST];
    const mcp = [5,9,13,17].map(i=>pts[i]).filter(Boolean);
    for (const p of mcp) line(w, p);
    for (let i=0;i<mcp.length-1;i++) line(mcp[i], mcp[i+1]);

    for (const chain of [C.THUMB,C.INDEX,C.MIDDLE,C.RING,C.PINKY]){
      let prev = w;
      for (const idx of chain){
        const p = pts[idx]; if (!p) continue;
        line(prev, p); prev = p;
      }
    }

    for (const p of pts){
      if (!p) continue;
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI*2); ctx.fill();
    }
    ctx.restore();
  }

  // ---------- joints & deltas ----------
  function pickBasicJoints(lmk){
    const mid=(a,b)=>({x:(a.x+b.x)/2,y:(a.y+b.y)/2,v:Math.min(a.v,b.v)});
    const chest = mid(lmk[11], lmk[12]);
    const hip   = mid(lmk[23], lmk[24]);
    return {
      chest, hip,
      shL: lmk[11], elL: lmk[13], wrL: lmk[15],
      shR: lmk[12], elR: lmk[14], wrR: lmk[16],
      knL: lmk[25], anL: lmk[27],
      knR: lmk[26], anR: lmk[28],
    };
  }

  function calcAngleDeltas(angles, JM){
    const out = {};
    out.elbow_left  = delta( angleAt(JM.shL, JM.elL, JM.wrL),  angles.elbow_left  );
    out.elbow_right = delta( angleAt(JM.shR, JM.elR, JM.wrR),  angles.elbow_right );
    out.knee_left   = delta( angleAt(JM.hip,  JM.knL, JM.anL), angles.knee_left   );
    out.knee_right  = delta( angleAt(JM.hip,  JM.knR, JM.anR), angles.knee_right  );
    out.shoulder_left  = delta( angleAt(JM.chest, JM.shL, JM.elL), angles.shoulder_left );
    out.shoulder_right = delta( angleAt(JM.chest, JM.shR, JM.elR), angles.shoulder_right );
    out.wrist_left = NaN;  // ערך אמת מגיע מהמדידה
    out.wrist_right = NaN;
    return out;

    function angleAt(a,b,c){
      if (!a||!b||!c) return NaN;
      const v1={x:a.x-b.x,y:a.y-b.y}, v2={x:c.x-b.x,y:c.y-b.y};
      const d=v1.x*v2.x+v1.y*v2.y, m=Math.hypot(v1.x,v1.y)*Math.hypot(v2.x,v2.y);
      if (m===0) return NaN;
      const cos=Math.max(-1,Math.min(1,d/m));
      return Math.acos(cos)*180/Math.PI;
    }
    function delta(measured, truth){
      if (!Number.isFinite(measured) || !Number.isFinite(truth)) return NaN;
      return Math.abs(measured - truth);
    }
  }

  function updateDeltaUI(spans, d){
    const fmt = (x)=> Number.isFinite(x) ? x.toFixed(1) : "–";
    spans.forEach(sp=>{ const k = sp.getAttribute("data-k"); sp.textContent = d ? fmt(d[k]) : "–"; });
  }

})();
