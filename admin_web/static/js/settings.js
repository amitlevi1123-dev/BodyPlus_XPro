// Settings page logic (Backend URL, Camera default, Mirror toggle)
// Keys in localStorage:
//  - ADMIN_BACKEND   : string (e.g., "http://127.0.0.1:5000")
//  - VIDEO_DEVICE_ID : string (MediaDeviceInfo.deviceId)
//  - VIDEO_MIRROR    : "true"/"false"

(function () {
  const $ = (s) => document.querySelector(s);

  const inpBackend = $("#backendUrl");
  const btnTest    = $("#btnTestBackend");
  const btnSaveB   = $("#btnSaveBackend");
  const statusEl   = $("#backendStatus");

  const selCam     = $("#cameraSelect");
  const btnRefresh = $("#btnRefreshCams");
  const btnSaveCam = $("#btnSaveCam");

  const mirrorChk  = $("#mirrorToggle");

  const btnReset   = $("#btnReset");
  const btnShow    = $("#btnShow");
  const toastEl    = $("#toast");

  // ---- utils ----
  function toast(msg = "נשמר ✔") {
    toastEl.textContent = msg;
    toastEl.classList.remove("hidden");
    setTimeout(() => toastEl.classList.add("hidden"), 1500);
  }

  function getLS(key, def = null) {
    try { const v = localStorage.getItem(key); return v === null ? def : v; } catch { return def; }
  }
  function setLS(key, val) {
    try { localStorage.setItem(key, val); } catch {}
  }
  function delLS(key) {
    try { localStorage.removeItem(key); } catch {}
  }

  function normUrl(u) {
    if (!u) return "";
    let s = String(u).trim();
    if (s.endsWith("/")) s = s.slice(0, -1);
    return s;
  }

  // ---- backend ----
  async function testBackend(url) {
    statusEl.textContent = "בודק חיבור…";
    statusEl.className = "mt-3 text-sm text-gray-600";
    const backend = normUrl(url || inpBackend.value);
    if (!backend) {
      statusEl.textContent = "נא להזין כתובת Backend";
      statusEl.className = "mt-3 text-sm text-red-600";
      return;
    }
    try {
      const r = await fetch(`/proxy/payload?backend=${encodeURIComponent(backend)}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json().catch(() => ({}));
      statusEl.textContent = "החיבור עובד ✓";
      statusEl.className = "mt-3 text-sm text-green-600";
    } catch (e) {
      statusEl.textContent = `נכשל: ${e.message || e}`;
      statusEl.className = "mt-3 text-sm text-red-600";
    }
  }

  // ---- camera ----
  async function listCameras() {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
        selCam.innerHTML = `<option value="">דפדפן לא תומך enumerateDevices</option>`;
        return;
      }
      const devices = await navigator.mediaDevices.enumerateDevices();
      const cams = devices.filter(d => d.kind === "videoinput");
      if (!cams.length) {
        selCam.innerHTML = `<option value="">לא נמצאו מצלמות</option>`;
        return;
      }
      const selectedId = getLS("VIDEO_DEVICE_ID", "");
      selCam.innerHTML = cams.map(d => {
        const label = d.label || `מצלמה ${d.deviceId.slice(-4)}`;
        const sel = d.deviceId === selectedId ? "selected" : "";
        return `<option value="${d.deviceId}" ${sel}>${label}</option>`;
      }).join("");
    } catch (e) {
      selCam.innerHTML = `<option value="">שגיאה בקבלת מצלמות</option>`;
      console.warn("listCameras failed:", e);
    }
  }

  // ---- init ----
  function loadFromStorage() {
    const b = getLS("ADMIN_BACKEND", "");
    if (b) inpBackend.value = b;

    const mirror = getLS("VIDEO_MIRROR", "false") === "true";
    mirrorChk.checked = mirror;
  }

  // ---- events ----
  btnSaveB?.addEventListener("click", () => {
    const backend = normUrl(inpBackend.value);
    if (!backend) {
      statusEl.textContent = "כתובת לא תקינה";
      statusEl.className = "mt-3 text-sm text-red-600";
      return;
    }
    setLS("ADMIN_BACKEND", backend);
    statusEl.textContent = `נשמר: ${backend}`;
    statusEl.className = "mt-3 text-sm text-green-600";
    toast();
  });

  btnTest?.addEventListener("click", () => testBackend());

  btnRefresh?.addEventListener("click", () => listCameras());

  btnSaveCam?.addEventListener("click", () => {
    const id = selCam.value || "";
    setLS("VIDEO_DEVICE_ID", id);
    toast(id ? "מצלמה נשמרה ✔" : "נוקה ערך מצלמה");
  });

  mirrorChk?.addEventListener("change", () => {
    setLS("VIDEO_MIRROR", mirrorChk.checked ? "true" : "false");
    toast("מצב מראה נשמר ✔");
  });

  btnReset?.addEventListener("click", () => {
    delLS("ADMIN_BACKEND");
    delLS("VIDEO_DEVICE_ID");
    delLS("VIDEO_MIRROR");
    inpBackend.value = "";
    mirrorChk.checked = false;
    selCam.selectedIndex = -1;
    statusEl.textContent = "";
    toast("הגדרות אופסו");
  });

  btnShow?.addEventListener("click", () => {
    const data = {
      ADMIN_BACKEND: getLS("ADMIN_BACKEND", ""),
      VIDEO_DEVICE_ID: getLS("VIDEO_DEVICE_ID", ""),
      VIDEO_MIRROR: getLS("VIDEO_MIRROR", "false"),
    };
    alert("Current settings:\n" + JSON.stringify(data, null, 2));
  });

  // ---- bootstrap ----
  loadFromStorage();
  listCameras();
})();
