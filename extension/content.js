// ===== YouTube AI Dubbing — content script (streaming clips over ducked audio) =====
let cfg = { targetLang: "vi", geminiApiKey: "", backendUrl: "http://localhost:8788" };

let currentVideoId = null;
let isDubActive = false;

const clipsByIndex = new Map();   // index -> {index, start, end, text, clip}
let sortedClips = [];             // sorted by start, rebuilt as clips arrive
let clipAudio = null;             // single reusable <audio> for the active clip
let activeIndex = -1;             // segment currently sounding (-1 = none)
let scheduler = null;             // setInterval id
let sseSource = null;

let DUB_VOLUME = 1.0;
let ORIGINAL_VOLUME = 0.12;       // duck the original audio under the dub

function getVideoId() { return new URLSearchParams(location.search).get("v"); }
function getVideo() { return document.querySelector("video"); }

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
    <div class="row"><span>Âm lượng gốc</span><input type="range" id="ytd-orig" min="0" max="1" step="0.05" value="0.12"></div>
    <div class="ytd-sub" id="ytd-sub"></div>
  `;
  document.body.appendChild(el);
  el.querySelector(".close").addEventListener("click", () => (el.style.display = "none"));
  el.querySelector("#ytd-start").addEventListener("click", startDubbing);
  el.querySelector("#ytd-vol").addEventListener("input", (e) => {
    DUB_VOLUME = parseFloat(e.target.value);
    if (clipAudio) clipAudio.volume = DUB_VOLUME;
  });
  el.querySelector("#ytd-orig").addEventListener("input", (e) => {
    ORIGINAL_VOLUME = parseFloat(e.target.value);
    const v = getVideo();
    if (v && isDubActive) { v.volume = ORIGINAL_VOLUME; v.muted = false; }
  });
  return el;
}

function setStatus(msg, pct) {
  const s = document.getElementById("ytd-status");
  const f = document.getElementById("ytd-fill");
  if (s) s.textContent = msg;
  if (f && typeof pct === "number") f.style.width = `${pct}%`;
}

function showSub(text) {
  const el = document.getElementById("ytd-sub");
  if (el) el.textContent = text || "";
}

// ---------- Dub trigger ----------
async function startDubbing() {
  const videoId = getVideoId();
  if (!videoId) { setStatus("Không tìm thấy video.", 0); return; }
  const video = getVideo();
  const startAt = video ? video.currentTime : 0;

  resetDub();
  currentVideoId = videoId;
  isDubActive = true;
  const startBtn = document.getElementById("ytd-start");
  if (startBtn) startBtn.disabled = true;

  // Duck the original audio and prepare the clip player.
  if (video) { video.muted = false; video.volume = ORIGINAL_VOLUME; }
  clipAudio = new Audio();
  clipAudio.volume = DUB_VOLUME;

  try {
    const r = await fetch(`${cfg.backendUrl}/dub`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        videoId, lang: cfg.targetLang,
        geminiApiKey: cfg.geminiApiKey || null, startAt,
      }),
    });
    await r.json();
    listenStream(videoId);
    startScheduler();
  } catch {
    setStatus("Không kết nối được backend. Hãy chạy BAT-LONG-TIENG.bat.", 0);
    isDubActive = false;
    if (startBtn) startBtn.disabled = false;
  }
}

function listenStream(videoId) {
  sseSource = new EventSource(`${cfg.backendUrl}/progress/${videoId}/${cfg.targetLang}`);
  sseSource.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.type === "segment") {
      addClip(d);
      return;
    }
    if (d.status) {
      sseSource.close();
      sseSource = null;
      if (d.status === "done") setStatus(`✓ Xong (${clipsByIndex.size} câu)`, 100);
      else setStatus("Lỗi: " + (d.error || "không rõ"), 0);
      const b = document.getElementById("ytd-start");
      if (b) b.disabled = false;
      return;
    }
    if (typeof d.percent === "number") setStatus(d.message || d.stage, d.percent);
  };
  sseSource.onerror = () => {
    if (sseSource) { sseSource.close(); sseSource = null; }
    const b = document.getElementById("ytd-start");
    if (b) b.disabled = false;
  };
}

function addClip(seg) {
  if (clipsByIndex.has(seg.index)) return;
  clipsByIndex.set(seg.index, seg);
  sortedClips.push(seg);
  sortedClips.sort((a, b) => a.start - b.start);
}

// ---------- Scheduler: play the clip matching the current playback time ----------
function findSegmentAt(t) {
  // latest segment whose start <= t and whose window hasn't fully passed
  let found = null;
  for (const s of sortedClips) {
    if (s.start <= t + 0.05) {
      if (t < s.end + 0.4) found = s; // within window (+grace)
    } else break;
  }
  return found;
}

function startScheduler() {
  if (scheduler) return;
  scheduler = setInterval(tick, 150);
}

function tick() {
  if (!isDubActive) return;
  const video = getVideo();
  if (!video || !clipAudio) return;

  if (video.paused || video.seeking) {
    if (!clipAudio.paused) clipAudio.pause();
    return;
  }

  const t = video.currentTime;
  const seg = findSegmentAt(t);
  if (!seg) return;

  if (seg.index !== activeIndex) {
    activeIndex = seg.index;
    showSub(seg.text);
    const offset = Math.max(0, t - seg.start);
    clipAudio.src = `${cfg.backendUrl}${seg.clip}`;
    clipAudio.volume = DUB_VOLUME;
    clipAudio.playbackRate = video.playbackRate || 1;
    const playFrom = () => {
      clipAudio.removeEventListener("loadedmetadata", playFrom);
      try { if (offset > 0.15) clipAudio.currentTime = offset; } catch {}
      clipAudio.play().catch(() => {});
    };
    clipAudio.addEventListener("loadedmetadata", playFrom);
    clipAudio.load();
  } else {
    if (clipAudio.paused) clipAudio.play().catch(() => {});
    const rate = video.playbackRate || 1;
    if (clipAudio.playbackRate !== rate) clipAudio.playbackRate = rate;
  }
}

function onSeeking() {
  // Stop current clip; the scheduler will pick the right one for the new time.
  activeIndex = -1;
  if (clipAudio) { try { clipAudio.pause(); } catch {} }
  showSub("");
}

// ---------- Teardown ----------
function resetDub() {
  if (scheduler) { clearInterval(scheduler); scheduler = null; }
  if (sseSource) { try { sseSource.close(); } catch {} sseSource = null; }
  if (clipAudio) { try { clipAudio.pause(); } catch {} clipAudio.src = ""; clipAudio = null; }
  clipsByIndex.clear();
  sortedClips = [];
  activeIndex = -1;
  const video = getVideo();
  if (video) video.volume = 1.0;  // restore original audio
  isDubActive = false;
  showSub("");
}

// ---------- SPA navigation ----------
function onNavigate() {
  const vid = getVideoId();
  if (vid !== currentVideoId) {
    resetDub();
    const btn = document.getElementById("ytd-start");
    if (btn) btn.disabled = false;
    setStatus("Sẵn sàng", 0);
    currentVideoId = vid;
  }
}

// ---------- Init ----------
function attachVideoListeners() {
  const video = getVideo();
  if (!video || video.__ytDubHooked) return;
  video.__ytDubHooked = true;
  video.addEventListener("seeking", onSeeking);
}

(async function init() {
  await loadConfig();
  if (location.pathname === "/watch") { createOverlay(); attachVideoListeners(); }
  window.addEventListener("yt-navigate-finish", async () => {
    await loadConfig();
    onNavigate();
    if (location.pathname === "/watch") { createOverlay(); attachVideoListeners(); }
  });
})();
