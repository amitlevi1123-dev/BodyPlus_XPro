/* eslint-disable */
(function(){
  "use strict";

  // ---------- Shortcuts ----------
  const $  = (sel,root)=> (root||document).querySelector(sel);
  const $$ = (sel,root)=> Array.from((root||document).querySelectorAll(sel));
  const escapeHtml = (s)=>String(s??'').replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  const safeJSON   = (obj)=> { try{ return JSON.stringify(obj,null,2) } catch{ return '—' } };
  const clamp      = (v,min,max)=> Math.max(min, Math.min(max, v));

  // ---------- Elements ----------
  const el = {
    // video + status
    videoFeed: $('#videoFeed'),
    vidSource: $('#vidSource'),
    vidFps:    $('#vidFps'),
    vidSize:   $('#vidSize'),
    dot:       $('#exerciseStatusDot'),
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
  };

  // אחסון דוחות (key -> report)
  const REP_STORE = new Map();
  let REP_AUTO_ID = 1;

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

  // ---------- Gauges (SVG donuts) ----------
  function makeGauge(root, label){
    const R = 52, C = 2*Math.PI*R;
    root.innerHTML = `
      <svg viewBox="0 0 140 140" class="block">
        <circle cx="70" cy="70" r="${R}" fill="none" stroke-width="12" class="bg"></circle>
        <circle cx="70" cy="70" r="${R}" fill="none" stroke-width="12" class="fg" stroke-dasharray="${C}" stroke-dashoffset="${C}"></circle>
        <text x="70" y="62" class="value" text-anchor="middle">—</text>
        <text x="70" y="84" class="label" text-anchor="middle">${escapeHtml(label||'Score')}</text>
      </svg>`;
    return { R, C, fg:root.querySelector('.fg'), val:root.querySelector('.value') };
  }
  const gRep = makeGauge(el.gaugeRep, 'חזרה');
  const gSet = makeGauge(el.gaugeSet, 'סט');

  // מדרג צבעים: 0–49 אדום · 50–64 כתום · 65–74 צהוב · 75–89 ירוק · 90–100 ירוק כהה
  function colorForPct(p){
    if(p==null) return '#9ca3af';
    if(p <= 49) return '#ef4444';      // red
    if(p <= 64) return '#f97316';      // orange
    if(p <= 74) return '#eab308';      // yellow
    if(p <= 89) return '#22c55e';      // green
    return '#16a34a';                  // dark green
  }
  function setGauge(g, pct){
    const p = clamp(Number(pct)||0, 0, 100);
    const off = g.C * (1 - p/100);
    g.fg.style.strokeDashoffset = String(off);
    g.fg.style.stroke = colorForPct(p);
    g.val.textContent = isFinite(p)? `${p}%` : '—';
  }
  setGauge(gRep, null); setGauge(gSet, null);

  // ---------- Helpers: score/grade ----------
  function gradeForPct(p){
    if(p==null) return '—';
    if(p>=90) return 'A';
    if(p>=80) return 'B';
    if(p>=70) return 'C';
    if(p>=60) return 'D';
    return 'E';
  }
  const repScorePct = (rep)=> {
    const s = rep?.scoring?.score;
    if(s==null) return null;
    return Math.round( (Number(s)||0) * 100 );
  };

  // ---------- Criticality bucketing ----------
  function severityScore(item){
    const unavailable = !item.available;
    const reason = String(item.reason||'').toLowerCase();
    const badReason = reason.includes('missing_critical') || reason.includes('missing');
    const pct = (item.score_pct!=null) ? Number(item.score_pct) : (item.score!=null ? Number(item.score)*100 : null);

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

  // ---------- Details Modal ----------
  function openDetails(rep, meta){
    $('#details-sub').textContent = `סט ${meta?.setIdx||'—'} · חזרה ${meta?.repIdx||'—'}`;
    $('#details-chips').innerHTML = [
      chip(`תרגיל: ${escapeHtml(rep?.exercise?.id||'—')}`),
      chip(`ציון: ${repScorePct(rep) ?? '—'}%`),
      chip(`דרוג: ${escapeHtml(rep?.scoring?.grade||'—')}`),
      chip(`איכות: ${escapeHtml(rep?.scoring?.quality||'—')}`),
      chip(`Unscored: ${escapeHtml(rep?.scoring?.unscored_reason||'—')}`),
    ].join(' ');
    $('#details-raw').textContent = safeJSON(rep);

    const buckets = bucketizeCriteria(rep);
    const sections = [
      { key:'critical', title:'קריטי', cls:'crit-bad' },
      { key:'major',    title:'חשוב',  cls:'crit-warn' },
      { key:'minor',    title:'מינורי',cls:'crit-minor' },
      { key:'good',     title:'עבר',   cls:'crit-good' },
    ];
    function row(it, cls){
      const pct = it.score_pct!=null? `${it.score_pct}%` : (it.score!=null? (Math.round(it.score*100)+'%') : '—');
      const reason = escapeHtml(it.reason||'');
      return `<div class="crit-item ${cls}">
        <div><span class="pill pill-k">${escapeHtml(it.id||'קריטריון')}</span> ${reason? `<span class="pill pill-r">${reason}</span>`:''}</div>
        <div class="text-sm text-gray-600">${it.available? 'זמין':'לא זמין'}</div>
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
    $('#details-lists').innerHTML = html || '<div class="text-sm text-gray-500">אין פרטים להצגה.</div>';
    $('#details-modal').classList.add('show');
  }
  function closeDetails(){ $('#details-modal').classList.remove('show'); }
  el.detailsClose?.addEventListener('click', closeDetails);
  el.detailsModal?.addEventListener('click', (ev)=>{ if(ev.target===el.detailsModal) closeDetails(); });

  // ---------- Simulator: local fake generation ----------
  const SAMPLE_EX = 'squat.bodyweight';
  function randf(a=0,b=1){ return a + Math.random()*(b-a); }
  function jitter(v,noise){ return clamp(v + (randf(-noise,noise)*100), 0, 100); }
  function makeCriteria(mode){
    const base = [
      { id:'depth',        available:true,  score_pct: 85 },
      { id:'knee_valgus',  available:true,  score_pct: 90 },
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
    const quality = avg>=85?'good':(avg>=70?'ok':'weak');
    return {score: avg/100, quality};
  }
  function fakeReport({mode, noisePct}){
    const criteria = makeCriteria(mode).map(c=> ({...c, score_pct: c.score_pct!=null? Math.round(jitter(c.score_pct, noisePct)) : c.score_pct }));
    const ov = criteriaToOverall(criteria);
    const grade = gradeForPct(Math.round((ov.score||0)*100));
    const hints = [];
    const bad = criteria.filter(c=>c.available && (c.score_pct??0)<70).sort((a,b)=>a.score_pct-b.score_pct);
    if(bad[0]) hints.push(`שפר ${bad[0].id} (כעת ${bad[0].score_pct}%)`);
    return {
      exercise: { id: SAMPLE_EX },
      scoring: {
        score: ov.score, quality: ov.quality, grade,
        unscored_reason: criteria.some(c=>!c.available && String(c.reason||'').includes('missing_critical')) ? 'missing_critical' : null,
        criteria: criteria.map(c=>({ id:c.id, available:!!c.available, score_pct:c.score_pct, reason:c.reason||null }))
      },
      hints
    };
  }

  // ---------- Server simulate/score ----------
  async function serverSimulate({sets, reps, mean, std}) {
    const res = await fetch('/api/exercise/simulate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ sets, reps, mean_score: mean, std })
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

  // ---------- Table row + set summary ----------
  function pushRow(setIdx, repIdx, rep){
    if(el.simTB.querySelector('td[colspan]')) el.simTB.innerHTML='';
    const tr=document.createElement('tr');
    const pct = repScorePct(rep);
    const rid = `r${REP_AUTO_ID++}`;
    REP_STORE.set(rid, rep);

    tr.innerHTML = `<td class="py-2 px-3">${setIdx}</td>
      <td class="py-2 px-3">${repIdx}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.exercise?.id||'—')}</td>
      <td class="py-2 px-3">${pct!=null? pct+'%':'—'}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.scoring?.grade||'—')}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.scoring?.quality||'—')}</td>
      <td class="py-2 px-3">${escapeHtml(rep?.scoring?.unscored_reason||'—')}</td>
      <td class="py-2 px-3 text-gray-500">${(rep?.hints && rep.hints[0])? escapeHtml(rep.hints[0]) : ''}</td>
      <td class="py-2 px-3">
        <button class="px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-sm" data-rid="${rid}" data-set="${setIdx}" data-rep="${repIdx}">פירוט</button>
      </td>`;
    tr.querySelector('button')?.addEventListener('click', (ev)=>{
      const btn = ev.currentTarget;
      const id  = btn.getAttribute('data-rid');
      const set = Number(btn.getAttribute('data-set'));
      const rix = Number(btn.getAttribute('data-rep'));
      const report = REP_STORE.get(id);
      openDetails(report, { setIdx:set, repIdx:rix });
    });
    el.simTB.appendChild(tr);
  }
  function pushSetSummary(setIdx){
    const lastBtn = el.simTB.querySelector('tr:last-child button');
    const rep = lastBtn ? REP_STORE.get(lastBtn.getAttribute('data-rid')) : null;
    const buckets = bucketizeCriteria(rep||{});
    const topBad = [...(buckets.critical||[]), ...(buckets.major||[])].slice(0,3).map(x=>x.id).filter(Boolean);
    const summary = topBad.length ? ('מוקדים לשיפור: ' + topBad.join(', ')) : 'ביצוע נקי יחסית בסט זה.';
    const tr = document.createElement('tr');
    tr.className='bg-white';
    tr.innerHTML = `<td colspan="9" class="py-2 px-3 text-sm text-gray-600">סט ${setIdx}: ${escapeHtml(summary)}</td>`;
    el.simTB.appendChild(tr);
  }

  // ---------- Simulation run (prefers server, fallback to local) ----------
  async function runSimulation(){
    const sets = clamp(parseInt(el.simSets.value||'2',10),1,10);
    const reps = clamp(parseInt(el.simReps.value||'5',10),1,30);
    const mode = el.simMode.value || 'mixed';
    const noise = clamp(Number(el.simNoise.value||0.25), 0, 0.5);

    try {
      const sim = await serverSimulate({ sets, reps, mean: 0.75, std: noise });
      for (const s of sim.sets || []) {
        const setIdx = s.set ?? 1;
        const repArr = Array.isArray(s.reps) ? s.reps : [];
        let setScores = [];
        for (const r of repArr) {
          const reportLike = {
            exercise: { id: 'squat.bodyweight' },
            scoring: {
              score: (r.score_pct!=null ? r.score_pct/100 : r.score ?? 0.7),
              grade: gradeForPct(r.score_pct ?? Math.round((r.score ?? 0.7)*100)),
              quality: ((r.score_pct ?? 70) >= 85 ? 'good' : ((r.score_pct ?? 70) >= 70 ? 'ok' : 'weak')),
              unscored_reason: null,
              criteria: []
            },
            hints: (r.notes||[]).map(n=> n.text || n.crit || '')
          };
          pushRow(setIdx, r.rep ?? (repArr.indexOf(r)+1), reportLike);
          const rpct = repScorePct(reportLike);
          setGauge(gRep, rpct);
          setScores.push(rpct ?? 0);
          await new Promise(res=>setTimeout(res, 80));
        }
        const setPct = s.set_score_pct!=null ? s.set_score_pct : Math.round(setScores.reduce((a,b)=>a+b,0)/Math.max(1,setScores.length));
        setGauge(gSet, setPct);
        pushSetSummary(setIdx);
      }
      return; // הצליח מהשרת
    } catch(e) {
      console.warn('serverSimulate failed, falling back to local fake:', e);
    }

    // Fallback: סימולציה מקומית
    for(let s=1; s<=sets; s++){
      let setScores = [];
      for(let r=1; r<=reps; r++){
        const rep = fakeReport({mode: mode==='mixed'? (Math.random()<.33?'good':(Math.random()<.5?'shallow':'missing')):mode, noisePct:noise});
        pushRow(s, r, rep);
        const rpct = repScorePct(rep);
        setGauge(gRep, rpct);
        setScores.push(rpct ?? 0);
        await new Promise(res=>setTimeout(res, 120));
      }
      const setPct = Math.round(setScores.reduce((a,b)=>a+b,0)/setScores.length);
      setGauge(gSet, setPct);
      pushSetSummary(s);
    }
  }
  el.btnRun?.addEventListener('click', runSimulation);
  el.btnClear?.addEventListener('click', ()=>{ el.simTB.innerHTML='<tr><td colspan="9" class="py-6 text-center text-gray-400">נוקה.</td></tr>'; setGauge(gRep,null); setGauge(gSet,null); });

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
      const pct = Math.round((j?.scoring?.score || 0) * 100);
      setGauge(gRep, pct);
      setGauge(gSet, pct);

      const rep = j || {};
      const rid = `r${REP_AUTO_ID++}`;
      REP_STORE.set(rid, rep);
      pushRow(1, REP_AUTO_ID, rep);
    }catch(e){
      alert('קריאת score מהשרת נכשלה — ממשיכים מקומי. '+e);
    }
  });

})();
