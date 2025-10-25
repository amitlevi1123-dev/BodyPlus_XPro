// -*- coding: utf-8 -*-
// -----------------------------------------------------------------------------
// system.js — עמוד "מצב מערכת"
// מה הקובץ עושה?
// • דוגם את /api/system כל שנייה ומרענן את הערכים במסך (CPU/RAM/GPU/FPS/דיסק/רשת/ENV).
// • עמיד לשגיאות רשת — במקרה כשל משאיר את הערכים הקיימים וממשיך לדגום.
// • אם קיים מסלול /_proxy/health, מציג תגית Cloud ירוקה/אדומה לפי מצב חיבור לענן.
// איך משתמשים?
// • ודא שהטמפלייט system.html כולל את האלמנטים עם ה-IDs המופיעים כאן.
// • טען את הקובץ בסוף העמוד (defer). אין תלות בספריות חיצוניות.
// -----------------------------------------------------------------------------

(function () {
  const POLL_MS = 1000;      // דגימת מערכת
  const HEALTH_MS = 3000;    // דגימת חיבור לענן (אם קיים /_proxy/health)

  // ---------- helpers ----------
  function fmtPercent(v) {
    if (v == null || isNaN(v)) return "--%";
    return `${Number(v).toFixed(0)}%`;
  }
  function fmtTempC(v) {
    if (v == null || isNaN(v)) return "--°C";
    return `${Number(v).toFixed(0)}°C`;
  }
  function fmtGB(v) {
    if (v == null || isNaN(v)) return "-- GB";
    return `${Number(v).toFixed(2)} GB`;
  }
  function fmtBps(v) {
    if (v == null || isNaN(v)) return "--";
    let x = Number(v), i = 0;
    const units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"];
    while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
    return `${x.toFixed(1)} ${units[i]}`;
  }
  function secsToHMS(sec) {
    if (sec == null || isNaN(sec)) return "—";
    sec = Math.max(0, Math.floor(sec));
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    const dd = d ? d + "d " : "";
    const hh = String(h).padStart(2, "0");
    const mm = String(m).padStart(2, "0");
    const ss = String(s).padStart(2, "0");
    return `${dd}${hh}:${mm}:${ss}`;
  }
  function setBadgeBg(el, percent) {
    if (!el) return;
    if (percent == null || isNaN(percent)) { el.style.background = ""; return; }
    el.style.background = percent < 70 ? "#d1fae5" : (percent < 90 ? "#fef3c7" : "#fee2e2");
  }
  const qs = (id) => document.getElementById(id);

  // ---------- DOM refs ----------
  const el = {
    chipCPU: qs("chip-cpu"),
    chipRAM: qs("chip-ram"),
    chipGPU: qs("chip-gpu"),
    chipFPS: qs("chip-fps"),
    cloudBadge: qs("cloud-badge"),

    cpuMain: qs("sys-cpu"),
    cpuTemp: qs("sys-cpu-temp"),
    ramMain: qs("sys-ram"),
    ramUsed: qs("sys-ram-used"),
    gpuMain: qs("sys-gpu"),
    gpuSub: qs("sys-gpu-sub"),
    fpsMain: qs("sys-fps"),

    procCPU: qs("proc-cpu"),
    procMem: qs("proc-mem"),

    diskUsage: qs("disk-usage"),
    diskR: qs("disk-r"),
    diskW: qs("disk-w"),

    netRx: qs("net-rx"),
    netTx: qs("net-tx"),

    envDocker: qs("env-docker-badge"),
    envHost: qs("env-host"),
    envOS: qs("env-os"),
    envPy: qs("env-py"),
    envPID: qs("env-pid"),
    envUptime: qs("env-uptime"),
    envGPUFlags: qs("env-gpu-flags"),

    details: qs("sys-details"),
  };

  // ---------- main system poll ----------
  async function pullAndRender() {
    try {
      const r = await fetch("/api/system", { cache: "no-store" });
      if (!r.ok) throw new Error(`system http ${r.status}`);
      const data = await r.json();

      // CPU
      const cpuP = data?.cpu?.percent_total ?? null;
      const cpuT = data?.cpu?.temp_c ?? null;
      if (el.cpuMain) el.cpuMain.textContent = fmtPercent(cpuP);
      if (el.cpuTemp) el.cpuTemp.textContent = `טמפ': ${fmtTempC(cpuT)}`;
      if (el.chipCPU) { el.chipCPU.textContent = `CPU: ${fmtPercent(cpuP)}`; setBadgeBg(el.chipCPU, cpuP); }

      // RAM
      const ramP = data?.ram?.percent ?? null;
      const usedGB = data?.ram?.used_gb ?? null;
      const totalGB = data?.ram?.total_gb ?? null;
      if (el.ramMain) el.ramMain.textContent = fmtPercent(ramP);
      if (el.ramUsed) el.ramUsed.textContent = `${fmtGB(usedGB)} / ${fmtGB(totalGB)}`;
      if (el.chipRAM) { el.chipRAM.textContent = `RAM: ${fmtPercent(ramP)}`; setBadgeBg(el.chipRAM, ramP); }

      // GPU
      const gpuAvail = !!data?.gpu?.available;
      const gpuP = data?.gpu?.percent ?? null;
      const gpuName = data?.gpu?.name || (gpuAvail ? "GPU זמין" : "אין GPU");
      const gpuTemp = data?.gpu?.temp ?? null;
      const gpuMemP = data?.gpu?.mem_percent ?? null;
      const viaNVML = !!data?.gpu?.via_nvml;
      const viaCUDA = !!data?.gpu?.via_cuda;

      if (el.gpuMain) el.gpuMain.textContent = gpuAvail ? (gpuP == null ? "N/A" : fmtPercent(gpuP)) : "אין GPU";
      if (el.gpuSub) {
        const parts = [gpuName];
        if (gpuTemp != null) parts.push(`טמפ' ${fmtTempC(gpuTemp)}`);
        if (gpuMemP != null && !isNaN(gpuMemP)) parts.push(`זיכרון ${gpuMemP.toFixed(0)}%`);
        parts.push(`NVML:${viaNVML ? "✓" : "×"} / CUDA:${viaCUDA ? "✓" : "×"}`);
        el.gpuSub.textContent = parts.join(" · ");
      }
      if (el.chipGPU) {
        el.chipGPU.textContent = gpuAvail ? (gpuP == null ? "GPU: N/A" : `GPU: ${gpuP.toFixed(0)}%`) : "GPU: אין";
        setBadgeBg(el.chipGPU, gpuAvail ? gpuP : null);
      }

      // FPS
      const fps = data?.fps ?? null;
      if (el.fpsMain) el.fpsMain.textContent = (fps == null || isNaN(fps)) ? "--" : Number(fps).toFixed(1);
      if (el.chipFPS) el.chipFPS.textContent = `FPS: ${(fps == null || isNaN(fps)) ? "--" : Number(fps).toFixed(1)}`;

      // Process
      const procCPU = data?.proc?.cpu_percent ?? null;
      const procMem = data?.proc?.rss_gb ?? null;
      if (el.procCPU) el.procCPU.textContent = procCPU == null ? "—" : `${Number(procCPU).toFixed(0)}%`;
      if (el.procMem) el.procMem.textContent = fmtGB(procMem);

      // Disk
      const duP = data?.disk?.usage?.percent ?? null;
      const rBps = data?.disk?.r_bps ?? null;
      const wBps = data?.disk?.w_bps ?? null;
      if (el.diskUsage) el.diskUsage.textContent = fmtPercent(duP);
      if (el.diskR) el.diskR.textContent = fmtBps(rBps);
      if (el.diskW) el.diskW.textContent = fmtBps(wBps);

      // Net
      const rx = data?.net?.recv_bps ?? null;
      const tx = data?.net?.sent_bps ?? null;
      if (el.netRx) el.netRx.textContent = fmtBps(rx);
      if (el.netTx) el.netTx.textContent = fmtBps(tx);

      // ENV
      const host = data?.env?.host || "—";
      const osStr = data?.env?.platform || (data?.env?.os ? `${data.env.os.system} ${data.env.os.release}` : "—");
      const py = data?.env?.python || "—";
      const pid = data?.env?.pid ?? "—";
      const uptime = data?.env?.uptime_sec ?? null;
      const isDocker = !!data?.env?.is_docker;
      if (el.envHost) el.envHost.textContent = host;
      if (el.envOS) el.envOS.textContent = osStr;
      if (el.envPy) el.envPy.textContent = py;
      if (el.envPID) el.envPID.textContent = String(pid);
      if (el.envUptime) el.envUptime.textContent = secsToHMS(uptime || 0);
      if (el.envGPUFlags) el.envGPUFlags.textContent = `NVML:${viaNVML ? "✓" : "×"} / CUDA:${viaCUDA ? "✓" : "×"}`;
      if (el.envDocker) { (isDocker ? el.envDocker.classList.remove("hidden") : el.envDocker.classList.add("hidden")); }

      // Full JSON
      if (el.details) el.details.textContent = JSON.stringify(data, null, 2);
    } catch (_) {
      // שקט — ננסה שוב בסבב הבא
    } finally {
      setTimeout(pullAndRender, POLL_MS);
    }
  }

  // ---------- optional: cloud health via proxy ----------
  async function pollCloudHealth() {
    const badge = el.cloudBadge;
    if (!badge) return; // אין תגית — דלג
    try {
      const r = await fetch("/_proxy/health", { cache: "no-store" });
      if (!r.ok) throw new Error(`health http ${r.status}`);
      const j = await r.json();
      if (j && j.ok) {
        badge.textContent = `Cloud: Connected (${j.status})`;
        badge.style.background = "#d1fae5"; // ירוק
      } else {
        badge.textContent = "Cloud: Down";
        badge.style.background = "#fee2e2"; // אדום
      }
    } catch (_) {
      // ייתכן שאין את המסלול הזה — השאר ניטרלי
      badge.textContent = "Cloud: —";
      badge.style.background = "#f3f4f6"; // אפור
    } finally {
      setTimeout(pollCloudHealth, HEALTH_MS);
    }
  }

  // ---------- start ----------
  document.addEventListener("DOMContentLoaded", () => {
    pullAndRender();
    pollCloudHealth(); // לא מזיק גם אם אין /_proxy/health
    // כפתור "העתק" מופעל בתוך ה-HTML עצמו (inline script)
  });
})();
