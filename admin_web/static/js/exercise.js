/* eslint-disable */
(function(){
  "use strict";

  // ---------- Shortcuts ----------
  const $  = (sel,root)=> (root||document).querySelector(sel);
  const $$ = (sel,root)=> Array.from((root||document).querySelectorAll(sel));
  const escapeHtml = (s)=>String(s??'').replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  const safeJSON   = (obj)=> { try{ return JSON.stringify(obj,null,2) } catch{ return '—' } };
  const clamp      = (v,min,max)=> Math.max(min, Math.min(max, v));
  const fmtNum     = (v)=> (v==null || !isFinite(Number(v))) ? '—' : String(Number(v).toFixed(3)).replace(/\.?0+$/,'');

  // ---------- Elements ----------
  const el = {
    // video + status
    videoFeed: $('#videoFeed'),
    vidSource: $('#vidSource'),
    vidFps:    $('#vidFps'),
    vidSize:   $('#vidSize'),
    dot:       $('#exerciseStatusDot'),
    // health/ready
    healthDot:  $('#healthDot'),
    readyDot:   $('#readyDot'),
    healthInfo: $('#healthInfo'),
    readyInfo:  $('#readyInfo'),
    // gauges
    gaugeRep:  $('#gaugeRep'),
    gaugeSet:  $('#gaugeSet'),
    // simulator
    simSets:   $('#simSets'),
    simReps:   $('#simReps'),
    simMode:   $('#simMode'),
    simNoise:  $('#simNoise'),
    btnRun:    $('#btnSimRun'),
    btnClear:  $('#btnSimClear'),
    btnServerScore: $('#btnServerScore'),
    btnOpenLastJson: $('#btnOpenLastJson'),
    simTB:     $('#simTbody'),
    // diag
    btnDiagStart: $('#btnDiagStart'),
    btnDiagStop:  $('#btnDiagStop'),
    btnDiagSnap:  $('#btnDiagSnap'),
    diagBox:      $('#diagBox'),
    // Modal
    detailsModal: $('#details-modal'),
    detailsClose: $('#details-close'),
    detailsSub:   $('#details-sub'),
    detailsChips: $('#details-chips'),
    detailsRaw:   $('#details-raw'),
    detailsLists: $('#details-lists'),
    // Modal tabs & metrics detail
    tabs:        $$('.modal-tab'),
    tabCrit:     $('#tab-crit'),
    tabMetrics:  $('#tab-metrics'),
    tabRaw:      $('#tab-raw'),
    mdTempo:     $('#md-tempo-table'),
    mdJoints:    $('#md-joints'),
    mdStance:    $('#md-stance'),
    mdOther:     $('#md-other'),
    mdTargets:   $('#md-targets'),
  };

  // ---------- State ----------
  const REP_STORE = new Map();   // rid -> report
  let REP_AUTO_ID = 1;
  let LAST_COLOR_RANGES = null;  // מהשרת (ui_ranges.color_bar)
  let simRunning = false;
  let LAST_REPORT = null;

  // ---------- Status Poll ----------
  async function pollStatus(){
    try{
      const s = await fetch('/api/session/status',{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null);
      if(s){
        el.dot?.classList.toggle('connected', !!(s.opened || s.running));
        el.vidFps.textContent    = s.fps!=null? s.fps : '—';
        el.vidSize.textContent   = Array.isArray(s.size)? `${s.size[0]}×${s.size[1]}`: (s.size||'—');
        el.vidSource.textContent = s.source || '—';
      }else{
        el.dot?.classList.remove('connected');
      }
    }catch(_){ el.dot?.classList.remove('connected'); }
  }
  pollStatus(); setInterval(pollStatus, 2000);

  // ---------- Health/Ready Poll ----------
  async function pollHealth(){
    try{
      const [h, r] = await Promise.all([
        fetch('/healthz',{cache:'no-store'}).then(x=>x.ok?x.json():null).catch(()=>null),
        fetch('/readyz',{cache:'no-store'}).then(x=>x.ok?x.json():null).catch(()=>null),
      ]);

      // healthz
      if(h){
        const ok = !!h.ok;
        el.healthDot?.classList.toggle('connected', ok);
        const age = h?.payload?.age_sec!=null ? `· גיל payload ${h.payload.age_sec}s` : '';
        const vid = h?.video?.running ? 'וידאו רץ' : (h?.video?.opened ? 'וידאו פתוח' : 'וידאו כבוי');
        el.healthInfo.textContent = `${ok?'OK':'NOT OK'} · ${vid} ${age}`;
      }else{
        el.healthDot?.classList.remove('connected');
        el.healthInfo.textContent = '—';
      }

      // readyz
      if(r){
        const ok = !!r.ok;
        el.readyDot?.classList.toggle('connected', ok);
        const t = r.templates?'OK':'X';
        const s = r.static?'OK':'X';
        el.readyInfo.textContent = `${ok?'Ready':'Not ready'} · templates:${t} · static:${s}`;
      }else{
        el.readyDot?.classList.remove('connected');
        el.readyInfo.textContent = '—';
      }
    }catch(_){
      el.healthDot?.classList.remove('connected');
      el.readyDot?.classList.remove('connected');
      el.healthInfo.textContent = '—';
      el.readyInfo.textContent = '—';
    }
  }
  pollHealth(); setInterval(pollHealth, 4000);

  // ---------- Gauges (SVG donuts) ----------
  function makeGauge(root, label){
    const R = 52, C = 2*Math.PI*R;
    root.innerHTML = `
      <svg viewBox="0 0 140 140" class="block">
        <circle cx="70" cy="70" r="${R}" fill="none" stroke-width="12" class="bg" style="stroke:#e5e7eb"></circle>
        <circle cx="70" cy="70" r="${R}" fill="none" stroke-width="12" class="fg" stroke-dasharray="${C}" stroke-dashoffset="${C}" style="stroke:#9ca3af"></circle>
        <text x="70" y="62" class="value" text-anchor="middle" style="font-size:22px;font-weight:700;fill:#111827">—</text>
        <text x="70" y="84" class="label" text-anchor="middle" style="font-size:14px;fill:#6b7280">${escapeHtml(label||'Score')}</text>
      </svg>`;
    return { R, C, root, fg:root.querySelector('.fg'), val:root.querySelector('.value') };
  }
  const gRep = makeGauge(el.gaugeRep, 'חזרה');
  const gSet = makeGauge(el.gaugeSet, 'סט');

  // טווחי צבעים מהשרת (fallback לדיפולט)
  function colorFromRanges(pct, ranges) {
    if (pct == null) return '#9ca3af';
    if (Array.isArray(ranges) && ranges.length) {
      for (const r of ranges) {
        const from = Number(r.from_pct ?? 0), to = Number(r.to_pct ?? 100);
        if (pct >= from && pct < to) {
          if (r.label === 'red')    return '#ef4444';
          if (r.label === 'orange') return '#f97316';
          if (r.label === 'green')  return '#22c55e';
        }
      }
    }
    if (pct < 60) return '#ef4444';
    if (pct < 75) return '#f97316';
    return '#22c55e';
  }
  function setGauge(g, pct, colorRanges){
    if (pct==null || !isFinite(pct)) {
      g.fg.style.strokeDashoffset = String(g.C);
      g.fg.style.stroke = '#9ca3af';
      g.val.textContent = '—';
      return;
    }
    const p = clamp(Number(pct)||0, 0, 100);
    const off = g.C * (1 - p/100);
    g.fg.style.strokeDashoffset = String(off);
    g.fg.style.stroke = colorFromRanges(p, colorRanges || LAST_COLOR_RANGES);
    g.val.textContent = `${p}%`;
  }
  setGauge(gRep, null); setGauge(gSet, null);

  // ---------- Helpers ----------
  const repScorePct = (rep)=> {
    const s = rep?.scoring?.score;
    if(s==null) return null;
    const v = Number(s);
    return isFinite(v) ? Math.round(v * 100) : null;
  };

  function severityScore(item){
    const unavailable = !item?.available;
    const reason = String(item?.reason||'').toLowerCase();
    const badReason = reason.includes('missing_critical') || reason.includes('missing');
    const pct = (item?.score_pct!=null) ? Number(item.score_pct) : (item?.score!=null ? Number(item.score)*100 : null);

    if (unavailable || badReason) return { bucket:'critical', order: (pct!=null? pct: 0) };
    if (pct==null) return { bucket:'major', order: 0 };
    if (pct < 60)  return { bucket:'major', order: pct };
    if (pct < 85)  return { bucket:'minor', order: pct };
    return { bucket:'good', order: -pct };
  }
  function bucketizeCriteria(rep){
    const out = { critical:[], major:[], minor:[], good:[] };
    const list = Array.isArray(rep?.scoring?.criteria) ? rep.scoring.criteria : [];
    for(const it of list){
      const s = severityScore(it);
      out[s.bucket].push({ ...it, _order:s.order });
    }
    out.critical.sort((a,b)=>a._order-b._order);
    out.major.sort((a,b)=>a._order-b._order);
    out.minor.sort((a,b)=>a._order-b._order);
    out.good.sort((a,b)=>a._order-b._order);
    return out;
  }
  const chip = (html)=> `<span class="chip">${html}</span>`;

  // Tooltip פירוק קריטריונים
  function criteriaTooltipText(rep) {
    try {
      const br = rep?.scoring?.criteria_breakdown_pct;
      let entries = br && typeof br === 'object' ? Object.entries(br) : null;

      if (!entries || !entries.length) {
        const list = Array.isArray(rep?.scoring?.criteria) ? rep.scoring.criteria : [];
        entries = list
          .filter(c => c?.score_pct != null || c?.score != null)
          .map(c => [String(c.id), c.score_pct!=null ? Number(c.score_pct) : Math.round(Number(c.score)*100)]);
      }

      entries = entries
        .filter(([_, v]) => v != null && isFinite(Number(v)))
        .sort((a,b)=> Number(a[1])-Number(b[1]));

      if (!entries.length) return 'אין פירוק קריטריונים זמין';
      return entries.map(([k,v])=> `${k}: ${v}%`).join('\n');
    } catch {
      return 'אין פירוק קריטריונים זמין';
    }
  }

  // ---------- Modal Tabs ----------
  function activateTab(name){
    el.tabs.forEach(t=>{
      const n = t.getAttribute('data-tab');
      const active = (n===name);
      t.classList.toggle('active', active);
    });
    el.tabCrit.style.display    = name==='crit'    ? '' : 'none';
    el.tabMetrics.style.display = name==='metrics' ? '' : 'none';
    el.tabRaw.style.display     = name==='raw'     ? '' : 'none';
  }
  el.tabs.forEach(t=>{
    t.addEventListener('click', ()=> activateTab(t.getAttribute('data-tab')));
  });

  // ---------- Metrics Detail renderers ----------
  function renderKVGrid(container, obj){
    if(!container) return;
    container.innerHTML = '';
    if(!obj || typeof obj!=='object' || !Object.keys(obj).length){
      container.innerHTML = '<div class="text-sm text-gray-500">—</div>';
      return;
    }
    const fr = new DocumentFragment();
    for(const [k,v] of Object.entries(obj)){
      const dvk = document.createElement('div'); dvk.className='kv-key'; dvk.textContent = k;
      const dvv = document.createElement('div'); dvv.className='kv-val'; dvv.textContent = typeof v==='boolean' ? (v?'כן':'לא') : fmtNum(v);
      fr.appendChild(dvk); fr.appendChild(dvv);
    }
    container.appendChild(fr);
  }

  function renderTempoTable(container, rows){
    if(!container) return;
    if(!Array.isArray(rows) || !rows.length){
      container.innerHTML = '<div class="text-sm text-gray-500">אין נתוני טמפו per-rep.</div>';
      return;
    }
    const table = document.createElement('table');
    table.className='mtable';
    table.innerHTML = `
      <thead><tr>
        <th class="text-right">חזרה</th>
        <th class="text-right">timing_s</th>
        <th class="text-right">ecc_s</th>
        <th class="text-right">con_s</th>
        <th class="text-right">pause_top_s</th>
        <th class="text-right">pause_bottom_s</th>
      </tr></thead>
      <tbody></tbody>`;
    const tb = table.querySelector('tbody');
    rows.forEach(r=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escapeHtml(r.rep_id ?? '—')}</td>
        <td class="mono">${fmtNum(r.timing_s)}</td>
        <td class="mono">${fmtNum(r.ecc_s)}</td>
        <td class="mono">${fmtNum(r.con_s)}</td>
        <td class="mono">${fmtNum(r.pause_top_s)}</td>
        <td class="mono">${fmtNum(r.pause_bottom_s)}</td>`;
      tb.appendChild(tr);
    });
    container.innerHTML = '';
    container.appendChild(table);
  }

  function renderMetricsDetail(rep){
    try{
      const md = rep?.metrics_detail || {};
      renderTempoTable(el.mdTempo, md.rep_tempo_series || []);
      renderKVGrid(el.mdJoints, md.groups?.joints || {});
      renderKVGrid(el.mdStance, md.groups?.stance || {});
      renderKVGrid(el.mdOther,  md.groups?.other  || {});
      el.mdTargets.textContent = (md.targets && Object.keys(md.targets||{}).length)
        ? safeJSON(md.targets)
        : '—';
    }catch(e){
      el.mdTempo.innerHTML  = '<div class="text-sm text-gray-500">שגיאה בהצגה.</div>';
      el.mdJoints.innerHTML = el.mdStance.innerHTML = el.mdOther.innerHTML = '<div class="text-sm text-gray-500">—</div>';
      el.mdTargets.textContent = '—';
    }
  }

  // ---------- Details Modal ----------
  function openDetails(rep, meta){
    el.detailsSub.textContent = `סט ${meta?.setIdx||'—'} · חזרה ${meta?.repIdx||'—'}`;

    const health = rep?.report_health?.status;
    const healthChip = health ? chip(`בריאות דוח: ${escapeHtml(health)}`) : '';

    el.detailsChips.innerHTML = [
      chip(`תרגיל: ${escapeHtml(rep?.exercise?.id||'—')}`),
      chip(`ציון: ${repScorePct(rep) ?? '—'}%`),
      chip(`איכות: ${escapeHtml(rep?.scoring?.quality||'—')}`),
      chip(`Unscored: ${escapeHtml(rep?.scoring?.unscored_reason||'—')}`),
      healthChip,
    ].filter(Boolean).join(' ');

    el.detailsRaw.textContent = safeJSON(rep);

    const buckets = bucketizeCriteria(rep);
    const sections = [
      { key:'critical', title:'קריטי', cls:'crit-bad' },
      { key:'major',    title:'חשוב',  cls:'crit-warn' },
      { key:'minor',    title:'מינורי',cls:'crit-minor' },
      { key:'good',     title:'עבר',   cls:'crit-good' },
    ];
    function row(it, cls){
      const pct = it?.score_pct!=null? `${it.score_pct}%` : (it?.score!=null? (Math.round(it.score*100)+'%') : '—');
      const reason = escapeHtml(it?.reason||'');
      return `<div class="crit-item ${cls}">
        <div><span class="pill pill-k">${escapeHtml(it?.id||'קריטריון')}</span> ${reason? `<span class="pill pill-r">${reason}</span>`:''}</div>
        <div class="text-sm text-gray-600">${it?.available? 'זמין':'לא זמין'}</div>
        <div class="text-sm font-semibold">${pct}</div>
      </div>`;
    }
    const html = sections.map(sec=>{
      const arr = buckets[sec.key];
      if(!arr || !arr.length) return '';
      return `<div>
        <h5>${sec.title}</h5>
        <div class="space-y-2">
          ${arr.map(it=>row(it, sec.cls)).join('')}
        </div>
      </div>`;
    }).join('');
    el.detailsLists.innerHTML = html || '<div class="text-sm text-gray-500">אין פרטים להצגה.</div>';

    // tooltip breakdown על המדדים
    const t = criteriaTooltipText(rep);
    el.gaugeRep?.setAttribute('title', t);
    el.gaugeSet?.setAttribute('title', t);

    // Metrics detail
    renderMetricsDetail(rep);
    activateTab('crit');
    el.detailsModal.classList.add('show');
  }
  function closeDetails(){ el.detailsModal.classList.remove('show'); }
  el.detailsClose?.addEventListener('click', closeDetails);
  el.detailsModal?.addEventListener('click', (ev)=>{ if(ev.target===el.detailsModal) closeDetails(); });
  window.addEventListener('keydown', (e)=>{ if(e.key==='Escape') closeDetails(); });

  // ---------- JSON Helpers ----------
  function openJSONInNewTab(obj){
    try{
      const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      window.open(url, '_blank');
    }catch(e){ alert('פתיחת JSON נכשלה: '+e); }
  }
  function downloadJSON(obj, filename='report.json'){
    try{
      const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=> URL.revokeObjectURL(url), 2000);
    }catch(e){ alert('הורדת JSON נכשלה: '+e); }
  }

  // ---------- Server endpoints ----------
  async function serverSimulate({sets, reps, mode, noise}) {
    const res = await fetch('/api/exercise/simulate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ sets, reps, mode, noise })
    });
    if (!res.ok) throw new Error(`simulate HTTP ${res.status}`);
    return res.json();
  }
  async function serverScore(metricsObj) {
    const res = await fetch('/api/exercise/score', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ metrics: metricsObj || { demo:true } })
    });
    if (!res.ok) throw new Error(`score HTTP ${res.status}`);
    return res.json();
  }

  // ---------- Gauges setter ----------
  function setGaugesFromReport(rep){
    const pct = repScorePct(rep);
    const ranges = rep?.ui_ranges?.color_bar || null;
    if (ranges) LAST_COLOR_RANGES = ranges;

    setGauge(gRep, pct, ranges);
    setGauge(gSet, pct, ranges);

    const tooltip = criteriaTooltipText(rep);
    el.gaugeRep?.setAttribute('title', tooltip);
    el.gaugeSet?.setAttribute('title', tooltip);
  }

  // ---------- Table row + set summary ----------
  function pushRow(setIdx, repIdx, rep){
    if(el.simTB.querySelector('td[colspan]')) el.simTB.innerHTML='';
    const tr=document.createElement('tr');
    const pct = repScorePct(rep);
    const rid = `r${REP_AUTO_ID++}`;
    REP_STORE.set(rid, rep);
    LAST_REPORT = rep;

    tr.innerHTML = `<td class="py-2 px-3">${setIdx}</td>
      <td class="py-2 px-3">${repIdx}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.exercise?.id||'—')}</td>
      <td class="py-2 px-3">${pct!=null? pct+'%':'—'}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.scoring?.quality||'—')}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.scoring?.unscored_reason||'—')}</td>
      <td class="py-2 px-3 text-gray-500">${(rep?.hints && rep.hints[0])? escapeHtml(rep.hints[0]) : ''}</td>
      <td class="py-2 px-3">
        <button class="px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-sm" data-json="${rid}">JSON</button>
      </td>
      <td class="py-2 px-3">
        <button class="px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-sm" data-rid="${rid}" data-set="${setIdx}" data-rep="${repIdx}">פירוט</button>
      </td>`;

    // JSON button
    tr.querySelector('button[data-json]')?.addEventListener('click', (ev)=>{
      const id = ev.currentTarget.getAttribute('data-json');
      const report = REP_STORE.get(id);
      if(!report) return;
      downloadJSON(report, `report_s${setIdx}_r${repIdx}.json`);
    });

    // Details button
    tr.querySelector('button[data-rid]')?.addEventListener('click', (ev)=>{
      const btn = ev.currentTarget;
      const id  = btn.getAttribute('data-rid');
      const set = Number(btn.getAttribute('data-set'));
      const rix = Number(btn.getAttribute('data-rep'));
      const report = REP_STORE.get(id);
      openDetails(report, { setIdx:set, repIdx:rix });
    });

    el.simTB.appendChild(tr);
  }

  function pushSetSummary(setIdx, repLikeForSummary){
    const buckets = bucketizeCriteria(repLikeForSummary||{});
    const topBad = [...(buckets.critical||[]), ...(buckets.major||[])].slice(0,3).map(x=>x.id).filter(Boolean);
    const summary = topBad.length ? ('מוקדים לשיפור: ' + topBad.join(', ')) : 'ביצוע נקי יחסית בסט זה.';
    const tr = document.createElement('tr');
    tr.className='bg-white';
    tr.innerHTML = `<td colspan="9" class="py-2 px-3 text-sm text-gray-600">סט ${setIdx}: ${escapeHtml(summary)}</td>`;
    el.simTB.appendChild(tr);
  }

  // ---------- Local Simulation (fallback) ----------
  const SAMPLE_EX = 'squat.bodyweight';
  function randf(a=0,b=1){ return a + Math.random()*(b-a); }
  function jitter(v,noise){ return clamp(v + (randf(-noise,noise)*100), 0, 100); }
  function makeCriteria(mode){
    const base = [
      { id:'depth',        available:true,  score_pct: 85 },
      { id:'knees',        available:true,  score_pct: 90 },
      { id:'torso_angle',  available:true,  score_pct: 88 },
      { id:'stance_width', available:true,  score_pct: 92 },
      { id:'tempo',        available:true,  score_pct: 86 },
    ];
    if(mode==='good') return base;
    if(mode==='shallow'){
      base[0].score_pct = 25; base[0].reason = 'shallow_depth';
      return base;
    }
    if(mode==='missing'){
      base[0].available = false; base[0].reason='missing_critical: depth';
      return base;
    }
    // mixed
    base[0].score_pct = 60+Math.round(Math.random()*30);
    base[1].score_pct = 50+Math.round(Math.random()*40);
    return base;
  }
  function criteriaToOverall(criteria){
    const avail = criteria.filter(c=>c.available && c.score_pct!=null);
    if(!avail.length) return {score: null, quality: null};
    const avg = avail.reduce((s,c)=>s+c.score_pct,0)/avail.length;
    const quality = avg>=85?'full':(avg>=70?'partial':'poor');
    return {score: avg/100, quality};
  }
  function fakeReport({mode, noisePct}){
    const criteria = makeCriteria(mode).map(c=> ({...c, score_pct: c.score_pct!=null? Math.round(jitter(c.score_pct, noisePct)) : c.score_pct }));
    const ov = criteriaToOverall(criteria);
    const hints = [];
    const bad = criteria.filter(c=>c.available && (c.score_pct??0)<70).sort((a,b)=>a.score_pct-b.score_pct);
    if(bad[0]) hints.push(`שפר ${bad[0].id} (כעת ${bad[0].score_pct}%)`);
    // demo metrics_detail minimal
    const metrics_detail = {
      groups:{
        joints:{ knee_left_deg:160, knee_right_deg:158, torso_forward_deg:15, spine_flexion_deg:8 },
        stance:{ "features.stance_width_ratio":1.05, toe_angle_left_deg:8, toe_angle_right_deg:10, heels_grounded:true },
        other:{}
      },
      rep_tempo_series:[{rep_id:1,timing_s:1.6,ecc_s:0.8,con_s:0.8,pause_top_s:0.0,pause_bottom_s:0.0}],
      targets:{ upper:{}, tempo:{min_s:0.7,max_s:2.5} },
      stats:{}
    };
    return {
      ui_ranges: { color_bar: [{label:'red',from_pct:0,to_pct:60},{label:'orange',from_pct:60,to_pct:75},{label:'green',from_pct:75,to_pct:100}] },
      exercise: { id: SAMPLE_EX },
      scoring: {
        score: ov.score, quality: ov.quality,
        unscored_reason: criteria.some(c=>!c.available && String(c.reason||'').includes('missing_critical')) ? 'missing_critical' : null,
        criteria: criteria.map(c=>({ id:c.id, available:!!c.available, score_pct:c.score_pct, reason:c.reason||null })),
        criteria_breakdown_pct: Object.fromEntries(criteria.map(c=>[c.id, c.score_pct ?? null])),
      },
      hints,
      metrics_detail
    };
  }

  // ---------- Simulation run ----------
  async function runSimulation(){
    if (simRunning) return;
    simRunning = true;
    el.btnRun?.setAttribute('disabled','disabled');

    const sets  = clamp(parseInt(el.simSets.value||'2',10),1,10);
    const reps  = clamp(parseInt(el.simReps.value||'5',10),1,30);
    const mode  = el.simMode.value || 'mixed';
    const noise = clamp(Number(el.simNoise.value||0.25), 0, 0.5);

    try {
      // שרת
      const sim = await serverSimulate({ sets, reps, mode, noise });
      LAST_COLOR_RANGES = sim?.ui_ranges?.color_bar || LAST_COLOR_RANGES;

      for (const s of (sim.sets || [])) {
        const setIdx = s.set ?? 1;
        const repArr = Array.isArray(s.reps) ? s.reps : [];
        let setScores = [];
        let lastRepLike = null;

        for (const r of repArr) {
          const criteria = Array.isArray(r.criteria) ? r.criteria : [];
          const repLike = {
            ui_ranges: sim.ui_ranges || null,
            exercise: { id: r.exercise_id || s.exercise_id || 'squat.bodyweight' },
            scoring: {
              score: (r.score_pct!=null ? r.score_pct/100 : (r.score ?? null)),
              quality: r.quality || (r.score_pct!=null ? (r.score_pct>=85?'full':(r.score_pct>=70?'partial':'poor')) : null),
              unscored_reason: r.unscored_reason ?? null,
              criteria: criteria,
              criteria_breakdown_pct: r.criteria_breakdown_pct || (criteria.length
                ? Object.fromEntries(criteria.map(c => [c.id, c.score_pct ?? (c.score!=null? Math.round(c.score*100): null)]))
                : null),
            },
            hints: (r.notes||[]).map(n=> n.text || n.crit || ''),
            metrics_detail: r.metrics_detail || null
          };

          pushRow(setIdx, r.rep ?? (repArr.indexOf(r)+1), repLike);
          const rpct = repScorePct(repLike);
          setGauge(gRep, rpct, LAST_COLOR_RANGES);
          const t = criteriaTooltipText(repLike);
          el.gaugeRep?.setAttribute('title', t);
          el.gaugeSet?.setAttribute('title', t);
          setScores.push(rpct ?? 0);
          lastRepLike = repLike;
          await new Promise(res=>setTimeout(res, 60));
        }

        const setPct = s.set_score_pct!=null ? s.set_score_pct : Math.round(setScores.reduce((a,b)=>a+b,0)/Math.max(1,setScores.length));
        setGauge(gSet, setPct, LAST_COLOR_RANGES);
        pushSetSummary(setIdx, lastRepLike);
      }
    } catch(e) {
      console.warn('serverSimulate failed, local fallback:', e);
      // Fallback: סימולציה מקומית
      for(let s=1; s<=sets; s++){
        let setScores = [];
        let lastRepLike = null;
        for(let r=1; r<=reps; r++){
          const pickedMode = (mode==='mixed')
            ? (Math.random()<.33?'good':(Math.random()<.5?'shallow':'missing'))
            : mode;
          const rep = fakeReport({mode: pickedMode, noisePct:noise});
          LAST_COLOR_RANGES = rep?.ui_ranges?.color_bar || LAST_COLOR_RANGES;
          pushRow(s, r, rep);
          const rpct = repScorePct(rep);
          setGauge(gRep, rpct, LAST_COLOR_RANGES);
          const t = criteriaTooltipText(rep);
          el.gaugeRep?.setAttribute('title', t);
          el.gaugeSet?.setAttribute('title', t);
          setScores.push(rpct ?? 0);
          lastRepLike = rep;
          await new Promise(res=>setTimeout(res, 100));
        }
        const setPct = Math.round(setScores.reduce((a,b)=>a+b,0)/setScores.length);
        setGauge(gSet, setPct, LAST_COLOR_RANGES);
        pushSetSummary(s, lastRepLike);
      }
    } finally {
      simRunning = false;
      el.btnRun?.removeAttribute('disabled');
    }
  }
  el.btnRun?.addEventListener('click', runSimulation);

  el.btnClear?.addEventListener('click', ()=>{
    el.simTB.innerHTML='<tr><td colspan="9" class="py-6 text-center text-gray-400">נוקה.</td></tr>';
    setGauge(gRep,null);
    setGauge(gSet,null);
    el.gaugeRep?.removeAttribute('title');
    el.gaugeSet?.removeAttribute('title');
  });

  // ---------- Diagnostics SSE ----------
  let diagES = null;
  el.btnDiagStart?.addEventListener('click', ()=>{
    if(diagES) return;
    diagES = new EventSource('/api/exercise/diag/stream?ping_ms=15000');
    el.diagBox.textContent = 'מתחבר...';
    diagES.onmessage = (ev)=>{ try{
      const o = JSON.parse(ev.data);
      const line = (Array.isArray(o)? o:[o]).map(x=>JSON.stringify(x)).join('\n');
      el.diagBox.textContent += '\n'+ line;
      el.diagBox.scrollTop = el.diagBox.scrollHeight;
    }catch{} };
    diagES.onerror = ()=>{ try{diagES.close()}catch{}; diagES=null; el.diagBox.textContent += '\n[התנתק]'; };
  });
  el.btnDiagStop?.addEventListener('click', ()=>{ if(diagES){ try{diagES.close()}catch{}; diagES=null; }});
  el.btnDiagSnap?.addEventListener('click', async ()=>{
    try{
      const r = await fetch('/api/exercise/diag',{cache:'no-store'});
      const j = await r.json();
      el.diagBox.textContent = safeJSON(j);
    }catch(e){ el.diagBox.textContent = String(e); }
  });

  // ---------- Server score (button) ----------
  el.btnServerScore?.addEventListener('click', async ()=>{
    try{
      const j = await serverScore({ demo:true });
      LAST_COLOR_RANGES = j?.ui_ranges?.color_bar || LAST_COLOR_RANGES;
      setGaugesFromReport(j);
      LAST_REPORT = j;

      const rid = `r${REP_AUTO_ID++}`;
      REP_STORE.set(rid, j);
      pushRow(1, REP_AUTO_ID, j);
    }catch(e){
      alert('קריאת score מהשרת נכשלה — ממשיכים מקומי. '+e);
    }
  });

  // ---------- Open last JSON ----------
  el.btnOpenLastJson?.addEventListener('click', ()=>{
    const rep = LAST_REPORT || [...REP_STORE.values()].slice(-1)[0];
    if(!rep){ alert('אין דו״ח זמין עדיין. הרץ סימולציה או דוח שרת.'); return; }
    openJSONInNewTab(rep);
  });

})();
