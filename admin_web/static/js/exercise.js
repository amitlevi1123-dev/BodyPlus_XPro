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
    // header / language + labels
    langSelect:  $('#langSelect'),
    exNameHe:    $('#exNameHe'),
    exNameEn:    $('#exNameEn'),
    familyHe:    $('#familyHe'),
    familyEn:    $('#familyEn'),
    equipHe:     $('#equipHe'),
    equipEn:     $('#equipEn'),
    familyKey:   $('#familyKey'),
    equipmentKey:$('#equipmentKey'),
    exerciseId:  $('#exerciseId'),

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

    // measured-vs-target tables
    setTargetsTable: $('#setTargetsTable'),
    repTargetsTable: $('#repTargetsTable'),

    // set summary (under set table)
    setSummaryHe:  $('#setSummaryHe'),
    setSummaryEn:  $('#setSummaryEn'),

    // simulator
    simSets:   $('#simSets'),
    simReps:   $('#simReps'),
    simMode:   $('#simMode'),
    simNoise:  $('#simNoise'),
    btnRun:    $('#btnSimRun'),
    btnClear:  $('#btnSimClear'),
    btnServerScore:  $('#btnServerScore'),
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

  // דו־לשוני
  let LANG = 'he';
  let LABELS = {}; // ייטען מתוך report.ui.labels אם קיים

  function applyLanguage(){
    LANG = (el.langSelect?.value==='en') ? 'en' : 'he';
    const html = document.documentElement;
    if (LANG==='en'){ html.setAttribute('dir','ltr'); html.setAttribute('lang','en'); }
    else { html.setAttribute('dir','rtl'); html.setAttribute('lang','he'); }
    if (LAST_REPORT) fillHeaderFromReport(LAST_REPORT);
  }
  el.langSelect?.addEventListener('change', applyLanguage);

  function setDualText(domHe, domEn, labels, fallbackHe='—', fallbackEn='—'){
    try{
      const he = labels?.he ?? fallbackHe;
      const en = labels?.en ?? fallbackEn;
      if(domHe) domHe.textContent = he;
      if(domEn) domEn.textContent = en;
    }catch{}
  }

  function fillHeaderFromReport(rep){
    try{
      const ui = rep?.ui || {};
      const labs = ui.labels || rep?.labels || null;
      if (labs && typeof labs==='object') LABELS = { ...LABELS, ...labs };

      const exId   = rep?.exercise?.id || '—';
      const famKey = rep?.exercise?.family || '—';
      const eqKey  = rep?.exercise?.equipment || '—';

      el.exerciseId && (el.exerciseId.textContent = exId);
      el.familyKey  && (el.familyKey.textContent  = famKey);
      el.equipmentKey && (el.equipmentKey.textContent = eqKey);

      setDualText(el.exNameHe, el.exNameEn, LABELS.exercise || {he: rep?.exercise?.display_name || exId, en: exId}, exId, exId);
      setDualText(el.familyHe, el.familyEn, LABELS.family   || {he: famKey, en: famKey}, famKey, famKey);
      setDualText(el.equipHe,  el.equipEn,  LABELS.equipment|| {he: eqKey,  en: eqKey},  eqKey,  eqKey);
    }catch{}
  }

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

  // ---------- Rep badge (colored circle per rep) ----------
  function scoreColor(p){
    if (p == null) return '#9ca3af';
    if (p < 60) return '#ef4444';
    if (p < 75) return '#f59e0b';
    return '#22c55e';
  }
  function repBadge(pct, idx){
    const color = scoreColor(pct);
    const title = pct!=null ? `${pct}%` : '—';
    return `<span title="ציון חזרה: ${title}" style="display:inline-flex;align-items:center;gap:.35rem;padding:.1rem .55rem;border-radius:9999px;font-size:.8rem;background:#f1f5f9;border:1px solid #e5e7eb">
              <span style="width:9px;height:9px;border-radius:9999px;background:${color}"></span><span>${idx}</span>
            </span>`;
  }

  // ---------- Modal Tabs ----------
  function activateTab(name){
    el.tabs.forEach(t=>{
      const n = t.getAttribute('data-tab');
      t.classList.toggle('active', n===name);
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

    const t = criteriaTooltipText(rep);
    el.gaugeRep?.setAttribute('title', t);
    el.gaugeSet?.setAttribute('title', t);

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

  // ---------- Measured-vs-Target tables ----------
  function tbodyOf(tableEl){
    if(!tableEl) return null;
    let tb = tableEl.querySelector('tbody');
    if(!tb){ tb = document.createElement('tbody'); tableEl.appendChild(tb); }
    return tb;
  }
  function clearTable(tableEl, cols){
    const tb = tbodyOf(tableEl);
    if(!tb) return;
    tb.innerHTML = `<tr><td colspan="${cols}" class="py-6 text-center text-gray-400">— אין נתונים —</td></tr>`;
  }
  clearTable(el.setTargetsTable, 5);
  clearTable(el.repTargetsTable, 6);

  function formatTargetCell(rep, critId){
    try{
      const t = rep?.metrics_detail?.targets;
      if(!t || typeof t!=='object') return '—';
      if (critId && t[critId]){
        const v = t[critId];
        return (typeof v==='object') ? escapeHtml(safeJSON(v)) : escapeHtml(String(v));
      }
      const keys = Object.keys(t);
      if(!keys.length) return '—';
      const first = keys[0];
      const v = t[first];
      if (typeof v==='object'){
        const flats = Object.entries(v).filter(([_,x])=> typeof x==='number').slice(0,3)
          .map(([k,x])=> `${k}:${fmtNum(x)}`).join(', ');
        return flats || escapeHtml(first);
      }
      return escapeHtml(`${first}: ${v}`);
    }catch{ return '—'; }
  }

  function formatMeasuredCell(rep, critId){
    try{
      const cList = Array.isArray(rep?.scoring?.criteria) ? rep.scoring.criteria : [];
      const c = cList.find(x=> String(x.id)===String(critId));
      if (c && c.score_pct!=null) return `${c.score_pct}%`;
      if (c && c.score!=null)    return `${Math.round(Number(c.score)*100)}%`;
      return '—';
    }catch{ return '—'; }
  }

  // !!! NEW: includes repPct and colored badge
  function appendRepTargetsRow(setIdx, repIdx, repPct, crit){
    const tb = tbodyOf(el.repTargetsTable);
    if(!tb) return;
    const firstPlaceholder = tb.querySelector('td[colspan]');
    if (firstPlaceholder) tb.innerHTML = '';

    const pct = (crit?.score_pct!=null) ? `${crit.score_pct}%`
              : (crit?.score!=null) ? `${Math.round(Number(crit.score)*100)}%` : '—';

    const measured = formatMeasuredCell({ scoring:{criteria:[crit]} }, crit?.id);
    const target   = formatTargetCell(LAST_REPORT, crit?.id);

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="py-2 px-3">${setIdx}</td>
      <td class="py-2 px-3">${repBadge(repPct, repIdx)}</td>
      <td class="py-2 px-3">${escapeHtml(crit?.id || '—')}</td>
      <td class="py-2 px-3">${escapeHtml(measured)}</td>
      <td class="py-2 px-3">${escapeHtml(target)}</td>
      <td class="py-2 px-3">${pct}</td>`;
    tb.appendChild(tr);
  }

  function refreshSetTargetsTable(setIdx, repReports){
    const tb = tbodyOf(el.setTargetsTable);
    if(!tb) return;
    tb.innerHTML = '';

    const agg = new Map(); // id -> {sum, n, targ}
    for (const rep of repReports){
      const list = Array.isArray(rep?.scoring?.criteria) ? rep.scoring.criteria : [];
      for (const c of list){
        const id = String(c.id||'');
        if(!id) continue;
        const pct = (c.score_pct!=null) ? Number(c.score_pct) :
                    (c.score!=null) ? Math.round(Number(c.score)*100) : null;
        const tStr = formatTargetCell(rep, id);
        const e = agg.get(id) || {sum:0, n:0, targ:tStr};
        if (pct!=null && isFinite(pct)) { e.sum += pct; e.n += 1; }
        if (!e.targ || e.targ==='—') e.targ = tStr;
        agg.set(id, e);
      }
    }

    if (agg.size===0){
      tb.innerHTML = '<tr><td colspan="5" class="py-6 text-center text-gray-400">— אין נתונים —</td></tr>';
      return;
    }

    Array.from(agg.entries()).sort(([a],[b])=> a.localeCompare(b)).forEach(([id, st])=>{
      const avg = st.n ? Math.round(st.sum / st.n) : null;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="py-2 px-3">${escapeHtml(id)}</td>
        <td class="py-2 px-3">${avg!=null? `${avg}%`:'—'}</td>
        <td class="py-2 px-3">${escapeHtml(st.targ || '—')}</td>
        <td class="py-2 px-3">${avg!=null? `${avg}%`:'—'}</td>
        <td class="py-2 px-3">${avg!=null && avg<70 ? 'דורש שיפור' : ''}</td>`;
      tb.appendChild(tr);
    });

    // שורה מסכמת (טקסטי)
    const all = Array.from(agg.values()).filter(x=>x.n>0).map(x=> Math.round(x.sum/x.n));
    const overall = all.length ? Math.round(all.reduce((a,b)=>a+b,0)/all.length) : null;
    const trSum = document.createElement('tr');
    trSum.className='bg-gray-50';
    trSum.innerHTML = `
      <td class="py-2 px-3 font-semibold">סיכום סט #${setIdx}</td>
      <td class="py-2 px-3 font-semibold">${overall!=null? overall+'%':'—'}</td>
      <td class="py-2 px-3 text-gray-500">—</td>
      <td class="py-2 px-3 text-gray-500">—</td>
      <td class="py-2 px-3 text-gray-500">${overall!=null && overall<70 ? 'מומלץ לעבוד על עומק/טמפו' : ''}</td>`;
    tb.appendChild(trSum);
  }

  // ---------- Details: open ----------
  function openDetailsFromRow(setIdx, repIdx, repObj){
    openDetails(repObj, { setIdx, repIdx });
  }

  // ---------- Simulation + rows ----------
  function setGaugesAndHeader(rep){
    LAST_REPORT = rep;
    setGaugesFromReport(rep);
    fillHeaderFromReport(rep);
    const t = criteriaTooltipText(rep);
    el.gaugeRep?.setAttribute('title', t);
    el.gaugeSet?.setAttribute('title', t);
  }

  function pushRow(setIdx, repIdx, rep){
    // סימולטור
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

    tr.querySelector('button[data-json]')?.addEventListener('click', (ev)=>{
      const id = ev.currentTarget.getAttribute('data-json');
      const report = REP_STORE.get(id);
      if(!report) return;
      downloadJSON(report, `report_s${setIdx}_r${repIdx}.json`);
    });

    tr.querySelector('button[data-rid]')?.addEventListener('click', (ev)=>{
      const btn = ev.currentTarget;
      const id  = btn.getAttribute('data-rid');
      const set = Number(btn.getAttribute('data-set'));
      const rix = Number(btn.getAttribute('data-rep'));
      const report = REP_STORE.get(id);
      openDetailsFromRow(set, rix, report);
    });

    el.simTB.appendChild(tr);

    // טבלת “חזרה — נמדד מול יעד”
    const crits = Array.isArray(rep?.scoring?.criteria) ? rep.scoring.criteria : [];
    if (crits.length){
      const repPct = repScorePct(rep);
      for (const c of crits){
        appendRepTargetsRow(setIdx, repIdx, repPct, c);
      }
    }

    // gauges + header
    setGaugesAndHeader(rep);
  }

  function updateSetSummaryDisplay(setIdx, avgPct, repLike){
    try{
      const exLbl = LABELS?.exercise || { he: repLike?.exercise?.display_name || repLike?.exercise?.id || '—',
                                          en: repLike?.exercise?.id || '—' };
      const famLbl = LABELS?.family   || { he: repLike?.exercise?.family || '—',
                                          en: repLike?.exercise?.family || '—' };
      const he = `${exLbl.he} — משפחה: ${famLbl.he} · סט #${setIdx} · ממוצע: ${avgPct!=null? avgPct+'%':'—'}`;
      const en = `${exLbl.en} — family: ${famLbl.en} · set #${setIdx} · avg: ${avgPct!=null? avgPct+'%':'—'}`;
      if (el.setSummaryHe) el.setSummaryHe.textContent = he;
      if (el.setSummaryEn) el.setSummaryEn.textContent = en;
    }catch(_){}
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
    if(mode==='shallow'){ base[0].score_pct = 25; base[0].reason = 'shallow_depth'; return base; }
    if(mode==='missing'){ base[0].available = false; base[0].reason='missing_critical: depth'; return base; }
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
    const metrics_detail = {
      groups:{
        joints:{ knee_left_deg:160, knee_right_deg:158, torso_forward_deg:15, spine_flexion_deg:8 },
        stance:{ "features.stance_width_ratio":1.05, toe_angle_left_deg:8, toe_angle_right_deg:10, heels_grounded:true },
        other:{}
      },
      rep_tempo_series:[{rep_id:1,timing_s:1.6,ecc_s:0.8,con_s:0.8,pause_top_s:0.0,pause_bottom_s:0.0}],
      targets:{ tempo:{min_s:0.7,max_s:2.5} },
      stats:{}
    };
    return {
      ui_ranges: { color_bar: [{label:'red',from_pct:0,to_pct:60},{label:'orange',from_pct:60,to_pct:75},{label:'green',from_pct:75,to_pct:100}] },
      exercise: { id: SAMPLE_EX, family:'squat', equipment:'bodyweight', display_name:'סקוואט גוף' },
      scoring: {
        score: ov.score, quality: ov.quality,
        unscored_reason: criteria.some(c=>!c.available && String(c.reason||'').includes('missing_critical')) ? 'missing_critical' : null,
        criteria: criteria.map(c=>({ id:c.id, available:!!c.available, score_pct:c.score_pct, reason:c.reason||null })),
        criteria_breakdown_pct: Object.fromEntries(criteria.map(c=>[c.id, c.score_pct ?? null])),
      },
      hints,
      metrics_detail,
      ui: {
        labels: {
          exercise: { he: 'סקוואט גוף', en: 'Bodyweight Squat' },
          family:   { he: 'סקוואט', en: 'Squat' },
          equipment:{ he: 'משקל גוף', en: 'Bodyweight' },
        }
      }
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

    function newSetCollector(){ return { list: [] }; }
    let collector = newSetCollector();

    try {
      const sim = await serverSimulate({ sets, reps, mode, noise });
      LAST_COLOR_RANGES = sim?.ui_ranges?.color_bar || LAST_COLOR_RANGES;

      for (const s of (sim.sets || [])) {
        const setIdx = s.set ?? 1;
        collector = newSetCollector();

        const repArr = Array.isArray(s.reps) ? s.reps : [];
        for (const r of repArr) {
          const criteria = Array.isArray(r.criteria) ? r.criteria : [];
          const repLike = {
            ui_ranges: sim.ui_ranges || null,
            exercise: { id: r.exercise_id || s.exercise_id || 'squat.bodyweight', family: sim.exercise?.family, equipment: sim.exercise?.equipment, display_name: sim.exercise?.display_name },
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
            metrics_detail: r.metrics_detail || sim.metrics_detail || null,
            ui: sim.ui || null
          };

          pushRow(setIdx, r.rep ?? (repArr.indexOf(r)+1), repLike);
          collector.list.push(repLike);

          await new Promise(res=>setTimeout(res, 60));
        }

        const setScores = collector.list.map(x=> repScorePct(x)).filter(x=> x!=null);
        const setPct = setScores.length ? Math.round(setScores.reduce((a,b)=>a+b,0)/setScores.length) : null;
        setGauge(gSet, setPct, LAST_COLOR_RANGES);

        const lastRepLike = collector.list.slice(-1)[0] || null;
        updateSetSummaryDisplay(setIdx, setPct, lastRepLike);
        refreshSetTargetsTable(setIdx, collector.list);
      }
    } catch(e) {
      console.warn('serverSimulate failed, local fallback:', e);
      for(let s=1; s<=sets; s++){
        collector = newSetCollector();
        for(let r=1; r<=reps; r++){
          const pickedMode = (mode==='mixed')
            ? (Math.random()<.33?'good':(Math.random()<.5?'shallow':'missing'))
            : mode;
          const rep = fakeReport({mode: pickedMode, noisePct:noise});
          pushRow(s, r, rep);
          collector.list.push(rep);
          await new Promise(res=>setTimeout(res, 80));
        }
        const setScores = collector.list.map(x=> repScorePct(x)).filter(x=> x!=null);
        const setPct = setScores.length ? Math.round(setScores.reduce((a,b)=>a+b,0)/setScores.length) : null;
        setGauge(gSet, setPct, LAST_COLOR_RANGES);

        const lastRepLike = collector.list.slice(-1)[0] || null;
        updateSetSummaryDisplay(s, setPct, lastRepLike);
        refreshSetTargetsTable(s, collector.list);
      }
    } finally {
      simRunning = false;
      el.btnRun?.removeAttribute('disabled');
    }
  }
  el.btnRun?.addEventListener('click', runSimulation);

  el.btnClear?.addEventListener('click', ()=>{
    el.simTB.innerHTML='<tr><td colspan="9" class="py-6 text-center text-gray-400">נוקה.</td></tr>';
    clearTable(el.repTargetsTable, 6);
    clearTable(el.setTargetsTable, 5);
    if (el.setSummaryHe) el.setSummaryHe.textContent = '—';
    if (el.setSummaryEn) el.setSummaryEn.textContent = '—';
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
      setGaugesAndHeader(j);

      const rid = `r${REP_AUTO_ID++}`;
      REP_STORE.set(rid, j);
      pushRow(1, REP_AUTO_ID, j);
      updateSetSummaryDisplay(1, repScorePct(j), j);
      refreshSetTargetsTable(1, [j]);
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

  // init language on load
  applyLanguage();
})();
