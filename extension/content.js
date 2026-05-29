// ===== YouTube AI Dubbing — content script =====
let cfg = { targetLang: "vi", geminiApiKey: "", backendUrl: "http://localhost:8788" };
let dubAudio = null;            // <audio> element playing the dubbed track
let syncRaf = null;             // drift-correction interval id
let currentVideoId = null;
let isDubActive = false;

function getVideoId() {
  return new URLSearchParams(location.search).get("v");
}

function getVideo() {
  return document.querySelector("video");
}

function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["targetLang", "geminiApiKey", "backendUrl"], (d) => {
      cfg.targetLang = d.targetLang || "vi";
      cfg.geminiApiKey = d.geminiApiKey || "";
      cfg.backendUrl = (d.backendUrl || "http://localhost:8788").replace(/\/$/, "");
      resolve(cfg);
    });
  });
}

// ---------- UI ----------
function createOverlay() {
  let el = document.getElementById("yt-dub-overlay");
  if (el) return el;
  el = document.createElement("div");
  el.id = "yt-dub-overlay";
  el.innerHTML = `
    <button class="close" title="Đóng">×</button>
    <h4>🎙️ AI Lồng tiếng</h4>
    <button id="ytd-start">Lồng tiếng video này</button>
    <div class="bar"><div id="ytd-fill"></div></div>
    <div class="status" id="ytd-status">Sẵn sàng</div>
    <div class="row"><span>Âm lượng lồng tiếng</span><input type="range" id="ytd-vol" min="0" max="1" step="0.05" value="1"></div>
    <div class="row"><span>Giữ tiếng gốc</span><input type="range" id="ytd-orig" min="0" max="1" step="0.05" value="0"></div>
  `;
  document.body.appendChild(el);
  el.querySelector(".close").addEventListener("click", () => (el.style.display = "none"));
  el.querySelector("#ytd-start").addEventListener("click", startDubbing);
  el.querySelector("#ytd-vol").addEventListener("input", (e) => {
    if (dubAudio) dubAudio.volume = parseFloat(e.target.value);
  });
  el.querySelector("#ytd-orig").addEventListener("input", (e) => {
    const v = getVideo();
    if (v) { v.volume = parseFloat(e.target.value); v.muted = parseFloat(e.target.value) === 0; }
  });
  return el;
}

function setStatus(msg, pct) {
  const s = document.getElementById("ytd-status");
  const f = document.getElementById("ytd-fill");
  if (s) s.textContent = msg;
  if (f && typeof pct === "number") f.style.width = `${pct}%`;
}

// ---------- Dub trigger ----------
async function startDubbing() {
  const videoId = getVideoId();
  if (!videoId) { setStatus("Không tìm thấy video.", 0); return; }
  const startBtn = document.getElementById("ytd-start");
  startBtn.disabled = true;
  currentVideoId = videoId;

  try {
    const r = await fetch(`${cfg.backendUrl}/dub`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId, lang: cfg.targetLang, geminiApiKey: cfg.geminiApiKey || null }),
    });
    const j = await r.json();
    if (j.status === "done") {
      setStatus("Đã có bản lồng tiếng (cache).", 100);
      attachDubAudio(videoId);
    } else {
      listenProgress(videoId);
    }
  } catch {
    setStatus("Không kết nối được backend. Hãy chạy run.ps1.", 0);
    startBtn.disabled = false;
  }
}

function listenProgress(videoId) {
  const es = new EventSource(`${cfg.backendUrl}/progress/${videoId}/${cfg.targetLang}`);
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.status) {
      es.close();
      if (d.status === "done") {
        setStatus("Hoàn tất! Đang phát lồng tiếng...", 100);
        attachDubAudio(videoId);
      } else {
        setStatus("Lỗi: " + (d.error || "không rõ"), 0);
        document.getElementById("ytd-start").disabled = false;
      }
      return;
    }
    setStatus(d.message || d.stage, d.percent);
  };
  es.onerror = () => {
    es.close();
    setStatus("Mất kết nối tiến trình.", 0);
    document.getElementById("ytd-start").disabled = false;
  };
}

// ---------- Audio overlay + sync ----------
function attachDubAudio(videoId) {
  const video = getVideo();
  if (!video) return;
  detachDubAudio();

  dubAudio = new Audio(`${cfg.backendUrl}/audio/${videoId}/${cfg.targetLang}`);
  dubAudio.preload = "auto";
  const volEl = document.getElementById("ytd-vol");
  dubAudio.volume = volEl ? parseFloat(volEl.value) : 1.0;

  video.muted = true;          // silence original (vocals removed track plays instead)
  isDubActive = true;

  const syncNow = () => { try { dubAudio.currentTime = video.currentTime; } catch {} };
  dubAudio.addEventListener("loadedmetadata", () => {
    syncNow();
    if (!video.paused) dubAudio.play().catch(() => {});
  });

  // Event-driven sync
  video.addEventListener("play", onPlay);
  video.addEventListener("pause", onPause);
  video.addEventListener("seeking", onSeek);
  video.addEventListener("seeked", onSeek);
  video.addEventListener("ratechange", onRate);

  // Drift correction every 500ms
  syncRaf = setInterval(() => {
    if (!isDubActive || !dubAudio || video.paused) return;
    if (Math.abs(dubAudio.currentTime - video.currentTime) > 0.25) syncNow();
  }, 500);
}

function onPlay() { if (dubAudio) { dubAudio.currentTime = getVideo().currentTime; dubAudio.play().catch(() => {}); } }
function onPause() { if (dubAudio) dubAudio.pause(); }
function onSeek() { if (dubAudio) { try { dubAudio.currentTime = getVideo().currentTime; } catch {} } }
function onRate() { if (dubAudio) dubAudio.playbackRate = getVideo().playbackRate; }

function detachDubAudio() {
  const video = getVideo();
  if (video) {
    video.removeEventListener("play", onPlay);
    video.removeEventListener("pause", onPause);
    video.removeEventListener("seeking", onSeek);
    video.removeEventListener("seeked", onSeek);
    video.removeEventListener("ratechange", onRate);
  }
  if (syncRaf) { clearInterval(syncRaf); syncRaf = null; }
  if (dubAudio) { dubAudio.pause(); dubAudio.src = ""; dubAudio = null; }
  isDubActive = false;
}

// ---------- SPA navigation ----------
function onNavigate() {
  const vid = getVideoId();
  if (vid !== currentVideoId) {
    detachDubAudio();
    const btn = document.getElementById("ytd-start");
    if (btn) btn.disabled = false;
    setStatus("Sẵn sàng", 0);
    currentVideoId = vid;
  }
}
window.addEventListener("yt-navigate-finish", onNavigate);

// ---------- Init ----------
(async function init() {
  await loadConfig();
  if (location.pathname === "/watch") createOverlay();
  window.addEventListener("yt-navigate-finish", async () => {
    await loadConfig();
    if (location.pathname === "/watch") createOverlay();
  });
})();
