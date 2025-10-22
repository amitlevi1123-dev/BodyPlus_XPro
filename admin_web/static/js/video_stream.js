/* eslint-disable no-console */
// static/js/video_stream.js — הזרמת MJPEG עם אפשרות החלפת מקור בזמן ריצה
(function () {
  const img = document.getElementById("video-stream");
  const placeholder = document.getElementById("video-placeholder");
  if (!img) return;

  // ========================
  // מקורות אפשריים
  // ========================
  const SRC_CAMERA = "/video/stream.mjpg";
  const SRC_FILE   = "/video/stream_file.mjpg";

  // מצב גלובלי קטן כדי שסקריפטים אחרים יוכלו לבדוק
  window.__videoSource = window.__videoSource || {
    url: SRC_CAMERA,
    name: "camera",
  };

  // ========================
  // כלי עזר
  // ========================
  let reconnectTimer = null;
  const RECONNECT_DELAY_MS   = 2000;   // ניסיון רה-קונקט כל 2 שניות
  const PERIODIC_REFRESH_MS  = 120000; // רענון כל 2 דקות

  function showPlaceholder(show) {
    if (placeholder) placeholder.style.display = show ? "flex" : "none";
  }

  function setImgSrc(url) {
    // cache-bust
    img.src = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  }

  function startStream() {
    clearTimeout(reconnectTimer);
    showPlaceholder(false);
    setImgSrc(window.__videoSource.url);
    console.log("[video_stream] ▶ streaming:", window.__videoSource.name, window.__videoSource.url);
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    showPlaceholder(true);
    reconnectTimer = setTimeout(startStream, RECONNECT_DELAY_MS);
  }

  // ========================
  // מאזינים לאירועים
  // ========================
  img.addEventListener("load",  () => showPlaceholder(false));
  img.addEventListener("error", () => {
    console.warn("[video_stream] stream error — reconnecting...");
    scheduleReconnect();
  });

  // רענון מחזורי ומעבר בין טאבים
  setInterval(() => { if (!document.hidden) setImgSrc(window.__videoSource.url); }, PERIODIC_REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) setImgSrc(window.__videoSource.url); });

  // ========================
  // API פנימי: החלפת מקור
  // ========================
  function switchTo(url, name) {
    if (!url || url === window.__videoSource.url) return;
    window.__videoSource.url  = url;
    window.__videoSource.name = name || url;
    startStream();
  }

  // חשיפה גלובלית (אם תרצה לקרוא ידנית ממקום אחר)
  window.setStreamSource = function setStreamSource(url) {
    switchTo(url, url.includes("stream_file") ? "file" : "camera");
  };
  window.useFileStream   = () => switchTo(SRC_FILE, "file");
  window.useCameraStream = () => switchTo(SRC_CAMERA, "camera");

  // ========================
  // קבלת פקודות ממסכים אחרים
  // ========================
  // 1) BroadcastChannel
  try {
    const ch = window.__bpVideoSourceChannel || new BroadcastChannel('bp_video_source');
    ch.onmessage = (ev) => {
      const d = ev && ev.data;
      if (d === 'use_file_stream')   window.useFileStream();
      if (d === 'use_camera_stream') window.useCameraStream();
    };
  } catch (_) {}

  // 2) window.postMessage (fallback)
  window.addEventListener('message', (ev) => {
    const d = ev && ev.data || {};
    if (d && d.type === 'use_file_stream')   window.useFileStream();
    if (d && d.type === 'use_camera_stream') window.useCameraStream();
  });

  // ========================
  // התחלה
  // ========================
  // ברירת מחדל מצלמה, עד שיגיע טריגר מהטאב של “העלאת וידאו”
  window.useCameraStream();
})();
