// ===== BodyPlus — Metrics (One-Page) with Alerts + Confidence + Skeleton =====
(function () {
  const $ = (id) => document.getElementById(id);

  // ========== Labels & Descriptions ==========
  const L = {
    torso_forward_deg:'Torso forward (°)', torso_vs_vertical_deg:'Torso forward vs vertical (°)',
    torso_vs_horizontal_deg:'Torso lean vs horizontal (°)', spine_flexion_deg:'Spine flexion (°)',
    spine_curvature_side_deg:'Spine curvature (°)', pelvis_tilt_deg:'Pelvis tilt (°)',
    pelvis_rotation_deg:'Pelvis rotation (°)', com_x_norm:'COM-X', com_y_norm:'COM-Y', balance_score:'Balance score',
    shoulder_left_deg:'Shoulder L (°)', shoulder_right_deg:'Shoulder R (°)', elbow_left_deg:'Elbow L (°)', elbow_right_deg:'Elbow R (°)',
    hand_orientation_left:'Left hand orientation', hand_orientation_right:'Right hand orientation',
    wrist_flex_ext_left_deg:'Wrist flex/ext L (°)', wrist_flex_ext_right_deg:'Wrist flex/ext R (°)',
    hip_left_deg:'Hip L (°)', hip_right_deg:'Hip R (°)', knee_left_deg:'Knee L (°)', knee_right_deg:'Knee R (°)',
    knee_foot_alignment_left_deg:'Knee–Foot L (°)', knee_foot_alignment_right_deg:'Knee–Foot R (°)',
    ankle_dorsi_left_deg:'Ankle dorsiflex L (°)', ankle_dorsi_right_deg:'Ankle dorsiflex R (°)',
    toe_angle_left_deg:'Toe angle L / FPA (°)', toe_angle_right_deg:'Toe angle R / FPA (°)',
    head_yaw_deg:'Head yaw (°)', head_pitch_deg:'Head pitch (°)', head_roll_deg:'Head roll (°)',
    head_confidence:'Head confidence', head_ok:'Head OK (0/1)',
    foot_contact_left:'Foot contact L (0/1)', foot_contact_right:'Foot contact R (0/1)',
    heel_lift_left:'Heel lift L (0/1)', heel_lift_right:'Heel lift R (0/1)',
    shoulders_width_px:'Shoulders width (px)', feet_width_px:'Feet width (px)', grip_width_px:'Grip width (px)',
    feet_w_over_shoulders_w:'Feet / Shoulders (×)', grip_w_over_shoulders_w:'Grip / Shoulders (×)',
    knee_delta_deg:'Knee Δ (°)', hip_delta_deg:'Hip Δ (°)', shoulders_delta_px:'Shoulders Δ (px)', hips_delta_px:'Hips Δ (px)',
    fps:'FPS', dt_ms:'Latency (ms)', confidence:'Pose confidence', average_visibility:'Avg visibility',
    view_mode:'View', view_score:'View score', 'frame.w':'Frame width', 'frame.h':'Frame height', camera:'Camera',
    model_version:'Model', app_uptime_s:'App uptime (s)', uptime_s:'Uptime (s)', quality_score:'Quality score',
    visible_points_count:'Visible points (n)', low_confidence:'low_confidence', 'meta.detected':'Meta detected',
    'meta.updated_at':'Meta updated_at', 'meta.age_ms':'Meta age (ms)'
  };
  const D = {
    torso_forward_deg:'כמה פלג הגוף העליון נוטה קדימה ביחס לנייטרלי (°).',
    torso_vs_vertical_deg:'זווית פלג גוף עליון מול האנך (°).',
    torso_vs_horizontal_deg:'זווית פלג גוף עליון מול האופק (°).',
    spine_flexion_deg:'כיפוף/יישור עמוד שדרה (°): גבוה = כפיפה.',
    pelvis_tilt_deg:'נטיית האגן קדימה/אחורה (°).',
    pelvis_rotation_deg:'סיבוב אגן סביב ציר אנכי (°).',
    elbow_left_deg:'זווית מרפק שמאל (°).', elbow_right_deg:'זווית מרפק ימין (°).',
    knee_left_deg:'זווית ברך שמאל (°).', knee_right_deg:'זווית ברך ימין (°).',
    head_confidence:'אמון זיהוי ראש (0..1).', foot_contact_left:'מגע כף רגל שמאל (0/1).',
  };

  // ========== Sections ==========
  const SECTIONS = {
    posture:['torso_forward_deg','torso_vs_vertical_deg','torso_vs_horizontal_deg','spine_flexion_deg','spine_curvature_side_deg','pelvis_tilt_deg','pelvis_rotation_deg','com_x_norm','com_y_norm','balance_score'],
    upper:['shoulder_left_deg','shoulder_right_deg','elbow_left_deg','elbow_right_deg','hand_orientation_left','hand_orientation_right','wrist_flex_ext_left_deg','wrist_flex_ext_right_deg'],
    lower:['hip_left_deg','hip_right_deg','knee_left_deg','knee_right_deg','knee_foot_alignment_left_deg','knee_foot_alignment_right_deg','ankle_dorsi_left_deg','ankle_dorsi_right_deg','toe_angle_left_deg','toe_angle_right_deg'],
    head_contacts:['head_yaw_deg','head_pitch_deg','head_roll_deg','head_confidence','head_ok','foot_contact_left','foot_contact_right','heel_lift_left','heel_lift_right','shoulders_width_px','feet_width_px','grip_width_px','feet_w_over_shoulders_w','grip_w_over_shoulders_w'],
    tech:['knee_delta_deg','hip_delta_deg','shoulders_delta_px','hips_delta_px'],
  };

  // ========== Helpers ==========
  const fmt1 = (n)=>Number.isFinite(n)?(Math.round(n*10)/10).toFixed(1):'—';
  const toNum = (v)=> (v===null||v===undefined||v==='')?NaN:Number(v);
  const inferUnit = (name)=>{
    const n=(name||'').toLowerCase();
    if(n.includes('deg')||n.endsWith('_deg'))return '°';
    if(n.endsWith('_ms')||n==='dt_ms'||n.includes('latency'))return 'ms';
    if(n.endsWith('_px'))return 'px';
    if(n.endsWith('_s')||n.includes('uptime'))return 's';
    if(n.includes('/'))return '×';
    return '';
  };
  const fmtVal=(name,v)=>{
    if(typeof v==='boolean')return v?'1':'0';
    if(typeof v==='string' && v.trim() && isNaN(Number(v)))return v;
    const n=toNum(v); if(!Number.isFinite(n))return '—';
    const u=inferUnit(name); return u?`${fmt1(n)}${u==='°'?'°':u}`:fmt1(n);
  };

  // flatten payload → flat map
  function flatten(p){
    const out={};
    if(!p||typeof p!=='object')return out;
    if(p.metrics&&typeof p.metrics==='object')Object.assign(out,p.metrics);
    if(p.measurements&&typeof p.measurements==='object')Object.assign(out,p.measurements);
    if(p.frame){ if(p.frame.w!=null)out['frame.w']=p.frame.w; if(p.frame.h!=null)out['frame.h']=p.frame.h; }
    // Fallbacks
    if(p.meta){ if(p.meta.image_w!=null && out['frame.w']==null) out['frame.w']=p.meta.image_w;
                if(p.meta.image_h!=null && out['frame.h']==null) out['frame.h']=p.meta.image_h; }
    Object.entries(p).forEach(([k,v])=>{ if(typeof v!=='object') out[k]=v; });
    return out;
  }

  // build rows once
  function makeRow(key){
    const wrap=document.createElement('div'); wrap.className='row';
    const lab=document.createElement('div'); lab.className='label';
    lab.textContent=L[key]||key;
    const info=document.createElement('span'); info.className='info'; info.textContent='i';
    const tip=D[key]; if(tip){ lab.title=tip; info.title=tip; }
    lab.appendChild(info);
    const val=document.createElement('div'); val.className='val ltr-num'; val.dataset.k=key;
    const conf=document.createElement('span'); conf.className='conf-badge hidden'; conf.dataset.confFor=key;
    val.appendChild(document.createTextNode('—')); val.appendChild(conf);
    wrap.appendChild(lab); wrap.appendChild(val); return wrap;
  }
  function ensureSection(containerId, keys){
    const root=$(containerId); if(!root || root.childElementCount) return;
    keys.forEach(k=> root.appendChild(makeRow(k)));
  }
  function paintSection(containerId, flat){
    const root=$(containerId); if(!root) return;
    root.querySelectorAll('.val').forEach(v=>{
      const k=v.dataset.k; v.firstChild.nodeValue = fmtVal(k, flat[k]);
      paintConfidence(k, flat);
    });
  }

  // table
  function renderTable(flat){
    const tb=$('metrics-table'); if(!tb) return;
    const term=( $('q')?.value || '' ).toLowerCase().trim();
    tb.innerHTML=''; let cnt=0;
    Object.keys(flat).sort().forEach(name=>{
      const disp=`${(L[name]||name)} (${name})`;
      if(term && !disp.toLowerCase().includes(term)) return;
      const tr=document.createElement('tr');
      const td1=document.createElement('td'); td1.textContent=disp; if(D[name])td1.title=D[name];
      const td2=document.createElement('td'); td2.className='ltr-num'; td2.textContent=fmtVal(name, flat[name]); if(D[name])td2.title=D[name];
      tr.appendChild(td1); tr.appendChild(td2); tb.appendChild(tr); cnt++;
    });
    $('filtered-count').textContent=cnt;
  }

  // KPIs (robust)
  function renderKPI(p, flat){
    const fps = toNum(flat.fps ?? p?.meta?.fps_est);
    const lat = toNum(flat.dt_ms ?? flat.latency_ms ?? flat.dt);
    const pose= toNum(flat.confidence ?? flat.average_visibility);
    const hand= toNum(flat.hands_confidence);
    const w   = toNum(flat['frame.w'] ?? p?.frame?.w ?? p?.meta?.image_w);
    const h   = toNum(flat['frame.h'] ?? p?.frame?.h ?? p?.meta?.image_h);
    const cam = flat.camera ?? p?.camera ?? '';
    const upt = toNum(flat.app_uptime_s ?? flat.uptime_s ?? flat.uptime);
    const mdl = flat.model_version ?? '';
    const view= p?.view_mode ?? p?.view?.primary ?? flat.view_mode ?? '';

    $('kpi_fps').textContent        = Number.isFinite(fps)?fmt1(fps):'—';
    $('kpi_latency').textContent    = Number.isFinite(lat)?`${fmt1(lat)}ms`:'—';
    $('kpi_pose_conf').textContent  = Number.isFinite(pose)?fmt1(pose):'—';
    $('kpi_hands_conf').textContent = Number.isFinite(hand)?fmt1(hand):'—';
    $('kpi_resolution').textContent = (Number.isFinite(w)&&Number.isFinite(h))?`${w}×${h}`:'—';
    $('kpi_camera').textContent     = cam || '—';
    $('kpi_uptime').textContent     = Number.isFinite(upt)?fmt1(upt):'—';
    $('kpi_model').textContent      = mdl || '—';
    $('kpi_view').textContent       = view || '—';
    $('lastUpdate').textContent     = new Date().toLocaleTimeString('he-IL',{hour12:false});
  }

  // Confidence badge logic
  let showConfidence=false;
  function paintConfidence(name, flat){
    const el = document.querySelector(`.conf-badge[data-conf-for="${name}"]`);
    if(!el) return;
    const q = toNum(flat[`${name}.quality`]);
    if(!showConfidence || !Number.isFinite(q)){ el.classList.add('hidden'); return; }
    el.classList.remove('hidden');
    el.textContent = `conf ${fmt1(q)}`;
    el.classList.remove('conf-low','conf-mid','conf-high');
    if(q < 0.33) el.classList.add('conf-low');
    else if(q < 0.66) el.classList.add('conf-mid');
    else el.classList.add('conf-high');
  }

  // Alerts
  const TH = {
    minFPS:5, maxLatencyMs:120, minPoseConf:0.5, minVisPts:15, minHeadConf:0.4,
    maxFreezeMs: 2500,
  };
  let lastStamp=null, lastStampAt=0;
  function addAlert(list, level, title, detail){
    const el=document.createElement('div'); el.className='alert';
    const b=document.createElement('span'); b.className=`badge ${level}`; b.textContent=(level==='err'?'שגיאה':(level==='warn'?'אזהרה':'OK'));
    const t=document.createElement('div'); t.innerHTML=`<strong>${title}</strong>${detail?` · <span class="muted">${detail}</span>`:''}`;
    el.appendChild(b); el.appendChild(t); list.push(el);
  }
  function outOfRange(name, val){
    const n=toNum(val); if(!Number.isFinite(n)) return false;
    if(name.endsWith('_deg') || name.includes('deg')){
      // חריג: מחוץ לטווח סביר של זוויות
      return (n < -10 || n > 360) || Math.abs(n) > 200;
    }
    if(name.endsWith('_ms') || name==='dt_ms' || name.includes('latency')) return n<0 || n>2000;
    if(name.endsWith('_px')) return n<0 || n>5000;
    if(name.endsWith('_s') || name.includes('uptime')) return n<0;
    if(name.includes('confidence')||name.endsWith('.quality')) return n<0 || n>1;
    return false;
  }
  function renderAlerts(p, flat){
    const holder=$('alerts'); if(!holder) return;
    holder.innerHTML=''; const items=[];
    const now=Date.now();
    const stamp = toNum(flat.ts_ms ?? flat.ts ?? flat['meta.updated_at']);
    if(Number.isFinite(stamp)){
      if(stamp===lastStamp){ if(now - lastStampAt > TH.maxFreezeMs) addAlert(items,'err','payload לא מתעדכן','חותמת זמן לא זזה'); }
      else { lastStamp=stamp; lastStampAt=now; }
    }

    const fps=toNum(flat.fps ?? p?.meta?.fps_est);
    if(Number.isFinite(fps) && fps < TH.minFPS) addAlert(items,'warn','FPS נמוך', `~${fmt1(fps)}`);

    const lat=toNum(flat.dt_ms ?? flat.latency_ms);
    if(Number.isFinite(lat) && lat > TH.maxLatencyMs) addAlert(items,'warn','לטנטיות גבוהה', `${fmt1(lat)}ms`);

    const conf=toNum(flat.confidence ?? flat.average_visibility);
    if(Number.isFinite(conf) && conf < TH.minPoseConf) addAlert(items,'err','אמון שלד נמוך', fmt1(conf));

    const vpts=toNum(flat.visible_points_count);
    if(Number.isFinite(vpts) && vpts < TH.minVisPts) addAlert(items,'warn','מעט נקודות שלד נראות', fmt1(vpts));

    const hconf=toNum(flat.head_confidence);
    if(Number.isFinite(hconf) && hconf < TH.minHeadConf) addAlert(items,'warn','אמון זיהוי ראש נמוך', fmt1(hconf));

    if((flat.view_mode||p?.view_mode)==='unknown') addAlert(items,'warn','תצוגה לא מזוהה','view=unknown');

    // ערכים חסרים/חריגים
    let missing=0, outRange=0;
    Object.entries(flat).forEach(([k,v])=>{
      if(v===null || v===undefined || v==='') missing++;
      else if(outOfRange(k,v)) outRange++;
    });
    if(missing>0) addAlert(items,'warn','ערכים חסרים', `${missing} שדות`);
    if(outRange>0) addAlert(items,'warn','ערכים חריגים', `${outRange} שדות`);

    // frame 0x0?
    const fw=toNum(flat['frame.w']), fh=toNum(flat['frame.h']);
    if((fw===0||fh===0) && (toNum(p?.meta?.image_w)>0 || toNum(p?.meta?.image_h)>0))
      addAlert(items,'warn','Frame width/height = 0','בדוק מקור resolution');

    if(!items.length) addAlert(items,'ok','הכל נראה תקין','אין אינדיקציות חריגות');
    items.forEach(el=>holder.appendChild(el));
  }

  // Misc Tiles (unassigned)
  const RAW_PREFIXES=['pose2d.','pose2d_','pose_','pose3d.','pnp_','frame.pose','meta.','ui.','view.','frame.'];
  function tile(name,value){
    const el=document.createElement('div'); el.className='tile';
    const n=document.createElement('div'); n.className='name'; n.textContent=L[name]||name; if(D[name]) n.title=D[name];
    const v=document.createElement('div'); v.className='val ltr-num'; v.textContent=fmtVal(name,value);
    el.appendChild(n); el.appendChild(v); return el;
  }
  function renderMiscTiles(flat){
    const used=new Set([
      ...SECTIONS.posture, ...SECTIONS.upper, ...SECTIONS.lower, ...SECTIONS.head_contacts, ...SECTIONS.tech,
      'fps','dt_ms','confidence','average_visibility','view_mode','camera','model_version','app_uptime_s','uptime_s','uptime',
      'frame.w','frame.h','quality_score','visible_points_count','low_confidence','meta.detected','meta.updated_at','meta.age_ms','view_score'
    ]);
    const showRaw=$('toggle_show_raw')?.checked===true;
    const grid=$('misc-grid'); if(!grid) return; grid.innerHTML='';
    Object.keys(flat).sort().forEach(name=>{
      if(used.has(name))return;
      const isRaw=RAW_PREFIXES.some(p=>name.startsWith(p));
      if(!showRaw && isRaw) return;
      grid.appendChild(tile(name, flat[name]));
    });
  }

  // Build static rows
  ensureSection('sec-posture', SECTIONS.posture);
  ensureSection('sec-upper',   SECTIONS.upper);
  ensureSection('sec-lower',   SECTIONS.lower);
  ensureSection('sec-head-contacts', SECTIONS.head_contacts);
  ensureSection('sec-tech',    SECTIONS.tech);

  // Poll
  const REFRESH=500;
  let forceNow=false;
  async function fetchPayload(){
    const r=await fetch('/payload', {cache:'no-store'});
    if(!r.ok) throw new Error(r.statusText);
    return r.json();
  }
  async function tick(){
    try{
      const payload = await fetchPayload();
      const flat = flatten(payload);

      paintSection('sec-posture', flat);
      paintSection('sec-upper', flat);
      paintSection('sec-lower', flat);
      paintSection('sec-head-contacts', flat);
      paintSection('sec-tech', flat);

      renderKPI(payload, flat);
      renderAlerts(payload, flat);
      renderMiscTiles(flat);
      renderTable(flat);

      if(!$('rawDataBox')?.classList.contains('hidden')){
        $('rawDataJSON').textContent = JSON.stringify(payload, null, 2);
      }
    }catch(_e){ /* שקט */ }
    finally{ setTimeout(tick, forceNow? 50 : REFRESH); forceNow=false; }
  }

  // UI events
  $('q')?.addEventListener('input', ()=>{/* table רענון בטיק הבא */});
  $('toggleRawData')?.addEventListener('click', ()=> $('rawDataBox')?.classList.toggle('hidden'));
  $('toggle_show_raw')?.addEventListener('change', ()=>{/* יתעדכן בטיק הבא */});
  $('btnCheckNow')?.addEventListener('click', ()=>{ forceNow=true; });
  $('btnToggleConf')?.addEventListener('click', (e)=>{
    showConfidence=!showConfidence;
    e.target.classList.toggle('ghost', !showConfidence);
    forceNow = true; // הצג/הסתר מיידית את באדג'י האמון
  });
  $('btnToggleSkeleton')?.addEventListener('click', (e)=>{
    const wrap = $('skeleton_wrap');
    const isHidden = wrap?.classList.toggle('hidden');
    e.target.classList.toggle('ghost', !!isHidden);
    // הווידג'ט עצמו מבצע polling עצמאי (skeleton_widget.js על .bp-skeleton)
  });

  tick();
})();
