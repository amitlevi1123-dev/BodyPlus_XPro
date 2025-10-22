/**
 * Compare Tab – BodyPlus Admin (patched)
 * -------------------------------------
 * Snapshot1 / Snapshot2 → compare numeric-overlapping keys → render table + stats + export.
 */

(() => {
  const $ = (sel) => document.querySelector(sel);

  // Controls & Status
  const btnSnap1 = $("#captureSnapshot1");
  const btnSnap2 = $("#captureSnapshot2");
  const btnClear = $("#clearSnapshots");
  const status1  = $("#snapshot1Status .status-content");
  const status2  = $("#snapshot2Status .status-content");
  const box1     = $("#snapshot1Status");
  const box2     = $("#snapshot2Status");

  // View containers
  const comparisonContent = $("#comparisonContent");
  const statsWrap  = $("#comparisonStats");
  const exportWrap = $("#exportSection");

  // Stats counters
  const commonCnt    = $("#commonMetricsCount");
  const improvedCnt  = $("#improvedCount");
  const worsenedCnt  = $("#worsenedCount");
  const unchangedCnt = $("#unchangedCount");

  // Export buttons
  const btnExportJSON = $("#exportComparisonJSON");
  const btnExportCSV  = $("#exportComparisonCSV");

  // State
  let snapshot1 = null;
  let snapshot2 = null;
  let lastComparison = null;

  // -------- utilities --------
  const wait = (ms) => new Promise(r => setTimeout(r, ms));

  async function withTimeout(promise, ms = 4000) {
    let t; const timeout = new Promise((_, rej) => t = setTimeout(() => rej(new Error("timeout")), ms));
    try { return await Promise.race([promise, timeout]); }
    finally { clearTimeout(t); }
  }

  // keep only simple values; flatten single level of nested objects
  function flattenBasics(root) {
    const out = {};
    if (!root || typeof root !== "object") return out;

    const putIfBasic = (k, v) => {
      if (v == null) return;
      const t = typeof v;
      if (t === "number" || t === "string" || t === "boolean") out[k] = v;
    };

    for (const [k, v] of Object.entries(root)) {
      if (v && typeof v === "object" && !Array.isArray(v)) {
        for (const [k2, v2] of Object.entries(v)) putIfBasic(`${k}.${k2}`, v2);
      } else {
        putIfBasic(k, v);
      }
    }
    return out;
  }

  // convert value to number if possible (strips non-numeric chars, keeps + - . e E)
  function toNumber(val) {
    if (typeof val === "number") return Number.isFinite(val) ? val : null;
    if (val == null) return null;
    const s = String(val).trim().replace(/[^0-9+\-eE.]/g, "");
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  function fmt1(n) {
    try { return Number(n).toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 }); }
    catch { return String(n); }
  }

  function setExportsEnabled(on) {
    if (btnExportJSON) btnExportJSON.disabled = !on;
    if (btnExportCSV)  btnExportCSV.disabled  = !on;
  }

  function updateStatusBoxes() {
    if (box1 && status1) {
      if (snapshot1) { box1.classList.add("has-data");  status1.textContent = "נשמר ✓"; }
      else           { box1.classList.remove("has-data"); status1.textContent = "לא נשמר"; }
    }
    if (box2 && status2) {
      if (snapshot2) { box2.classList.add("has-data");  status2.textContent = "נשמר ✓"; }
      else           { box2.classList.remove("has-data"); status2.textContent = "לא נשמר"; }
    }
  }

  function renderNoComparison(msg = "צלם שני מצבים כדי לראות השוואה בין המדדים") {
    if (comparisonContent) {
      comparisonContent.innerHTML = `
        <div class="no-comparison">
          <div class="no-comparison-message">
            <h4>לא זמינה השוואה</h4>
            <p>${msg}</p>
          </div>
        </div>
      `;
    }
    statsWrap && statsWrap.classList.add("hidden");
    exportWrap && exportWrap.classList.add("hidden");
    setExportsEnabled(false);
    lastComparison = null;

    // reset stats display
    if (commonCnt)    commonCnt.textContent = "0";
    if (improvedCnt)  improvedCnt.textContent = "0";
    if (worsenedCnt)  worsenedCnt.textContent = "0";
    if (unchangedCnt) unchangedCnt.textContent = "0";
  }

  // -------- data fetching (robust) --------
  async function fetchPayload() {
    // 1) in-memory source (metricsManager)
    try {
      if (window.metricsManager && typeof window.metricsManager.getLatest === "function") {
        const m = window.metricsManager.getLatest();
        const flat = flattenBasics(m && (m.metrics || m));
        if (Object.keys(flat).length) return flat;
      }
    } catch (e) { console.warn("metricsManager source failed:", e); }

    // 2) proxy
    try {
      const backend = localStorage.getItem("ADMIN_BACKEND");
      if (backend) {
        const url = `/proxy/payload?backend=${encodeURIComponent(backend)}`;
        const r = await withTimeout(fetch(url, { cache: "no-store" }), 4000);
        if (r.ok) {
          const j = await r.json();
          const root = j && (j.data || j.metrics || j);
          const flat = flattenBasics(root);
          if (Object.keys(flat).length) return flat;
        } else {
          console.warn("proxy payload http", r.status);
        }
      }
    } catch (e) { console.warn("proxy payload failed:", e); }

    // 3) direct
    try {
      const r = await withTimeout(fetch("/payload", { cache: "no-store" }), 4000);
      if (!r.ok) throw new Error(`payload http ${r.status}`);
      const j = await r.json();
      const root = j && (j.data || j.metrics || j);
      return flattenBasics(root);
    } catch (e) {
      console.error("fallback /payload failed:", e);
      return {};
    }
  }

  // -------- compare logic --------
  function compareSnapshots(a, b) {
    if (!a || !b) return { rows: [], stats: { common: 0, improved: 0, worsened: 0, unchanged: 0 } };

    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])]
      .filter(k => a[k] !== undefined && b[k] !== undefined);

    const rows = [];
    let improved = 0, worsened = 0, unchanged = 0;

    for (const k of keys) {
      const v1n = toNumber(a[k]);
      const v2n = toNumber(b[k]);
      if (v1n === null || v2n === null) continue;

      const diff = v2n - v1n;
      let cls = "neutral";
      if (diff > 0) { cls = "positive"; improved++; }
      else if (diff < 0) { cls = "negative"; worsened++; }
      else { unchanged++; }

      rows.push({ metric: k, v1: v1n, v2: v2n, diff, cls });
    }

    rows.sort((r1, r2) => Math.abs(r2.diff) - Math.abs(r1.diff));
    return { rows, stats: { common: rows.length, improved, worsened, unchanged } };
  }

  function renderComparison(comp) {
    if (!comp || comp.rows.length === 0) {
      renderNoComparison("אין מפתחות משותפים מספריים להשוואה.");
      return;
    }

    const header = `
      <div class="comparison-header">
        <div>מדד</div><div>מצב 1</div><div>מצב 2</div><div>הפרש</div>
      </div>
    `;

    const rowsHtml = comp.rows.map(r => `
      <div class="comparison-row">
        <div class="comparison-metric">${r.metric}</div>
        <div class="comparison-value">${fmt1(r.v1)}</div>
        <div class="comparison-value">${fmt1(r.v2)}</div>
        <div class="comparison-diff ${r.cls}">
          ${r.diff > 0 ? "▲" : (r.diff < 0 ? "▼" : "•")} ${fmt1(r.diff)}
        </div>
      </div>
    `).join("");

    if (comparisonContent) {
      comparisonContent.innerHTML = `<div class="comparison-view">${header}${rowsHtml}</div>`;
    }

    statsWrap && statsWrap.classList.remove("hidden");
    exportWrap && exportWrap.classList.remove("hidden");
    setExportsEnabled(true);

    if (commonCnt)    commonCnt.textContent    = String(comp.stats.common);
    if (improvedCnt)  improvedCnt.textContent  = String(comp.stats.improved);
    if (worsenedCnt)  worsenedCnt.textContent  = String(comp.stats.worsened);
    if (unchangedCnt) unchangedCnt.textContent = String(comp.stats.unchanged);

    lastComparison = comp;
  }

  // -------- export --------
  function exportJSON() {
    if (!lastComparison) return;
    const blob = new Blob([JSON.stringify(lastComparison, null, 2)], { type: "application/json;charset=utf-8" });
    const url  = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "comparison.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportCSV() {
    if (!lastComparison) return;
    const head = ["metric","v1","v2","diff"];
    const lines = [head.join(",")];
    for (const r of lastComparison.rows) lines.push([r.metric, r.v1, r.v2, r.diff].join(","));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url  = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "comparison.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  // -------- events --------
  btnSnap1 && btnSnap1.addEventListener("click", async () => {
    snapshot1 = await fetchPayload();
    updateStatusBoxes();
    if (snapshot1 && snapshot2) renderComparison(compareSnapshots(snapshot1, snapshot2));
  });

  btnSnap2 && btnSnap2.addEventListener("click", async () => {
    snapshot2 = await fetchPayload();
    updateStatusBoxes();
    if (snapshot1 && snapshot2) renderComparison(compareSnapshots(snapshot1, snapshot2));
  });

  btnClear && btnClear.addEventListener("click", () => {
    snapshot1 = null;
    snapshot2 = null;
    updateStatusBoxes();
    renderNoComparison();
  });

  btnExportJSON && btnExportJSON.addEventListener("click", exportJSON);
  btnExportCSV  && btnExportCSV.addEventListener("click", exportCSV);

  // -------- init --------
  updateStatusBoxes();
  renderNoComparison();
})();
