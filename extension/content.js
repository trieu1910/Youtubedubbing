// ===== YouTube AI Dubbing — content script (streaming clips over ducked audio) =====
let cfg = { targetLang: "vi", geminiApiKey: "", backendUrl: "http://localhost:8788" };

let currentVideoId = null;
let isDubActive = false;

const clipsByIndex = new Map();   // index -> {index, start, end, text, clip}
let sortedClips = [];             // sorted by start, rebuilt as clips arrive
let clipAudio = null;             // single reusable <audio> for the active clip
let scheduler = null;             // setInterval id
let sseSource = null;

// Sequential player state: speak clips one at a time, never overlapping, never
// cutting. Wait during pauses; play back-to-back to catch up when behind.
let lastStart = -1;               // start-time of the last clip we began speaking
let speaking = false;             // a clip is currently playing
const SPEAK_LOOKAHEAD = 0.25;     // begin a clip once the video reaches its start
const MAX_LAG = 4.0;              // if the dub falls this far behind, skip ahead

let DUB_VOLUME = 1.0;
let ORIGINAL_VOLUME = 0.12;       // duck the original audio under the dub

let waitingFirstClip = false;     // pause video until the first dubbed clip is ready
let firstStartAt = 0;
let firstClipTimer = null;
// 0.05s of silence — played on the user's click to unlock browser autoplay.
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";

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
  clipAudio.addEventListener("ended", () => { speaking = false; trySpeakNext(); });
  clipAudio.addEventListener("error", () => { speaking = false; });
  // Unlock autoplay within the user gesture by playing a tiny silent clip.
  try { clipAudio.src = SILENT_WAV; clipAudio.play().catch(() => {}); } catch {}

  // Pause until the first dubbed clip is ready, then resume aligned to it
  // (so the very first sentences are never skipped while processing catches up).
  waitingFirstClip = true;
  firstStartAt = startAt;
  if (video && !video.paused) video.pause();
  setStatus("Đang chuẩn bị câu đầu tiên...", 2);
  if (firstClipTimer) clearTimeout(firstClipTimer);
  firstClipTimer = setTimeout(() => {
    if (waitingFirstClip) {
      waitingFirstClip = false;
      const v = getVideo();
      if (v) v.play().catch(() => {});
    }
  }, 25000);

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

  // First clip ready → align the video to it and resume playback.
  if (waitingFirstClip) {
    waitingFirstClip = false;
    if (firstClipTimer) { clearTimeout(firstClipTimer); firstClipTimer = null; }
    const v = getVideo();
    if (v) {
      const target = sortedClips[0];
      try { if (Math.abs(v.currentTime - target.start) > 1.0) v.currentTime = target.start; } catch {}
      v.play().catch(() => {});
    }
  }
}

// ---------- Sequential player ----------
function startScheduler() {
  if (scheduler) return;
  scheduler = setInterval(trySpeakNext, 120);
}

function nextSegmentToSpeak() {
  for (const s of sortedClips) {
    if (s.start > lastStart + 0.001) return s;  // sortedClips is ascending by start
  }
  return null;
}

function latestSegmentAtOrBefore(t) {
  let found = null;
  for (const s of sortedClips) {
    if (s.start <= t + 0.05) found = s; else break;
  }
  return found;
}

function trySpeakNext() {
  if (!isDubActive || !clipAudio || speaking) return;
  const video = getVideo();
  if (!video || video.paused || video.seeking) return;

  const t = video.currentTime;
  let next = nextSegmentToSpeak();
  if (!next) return;

  // The next sentence hasn't started yet in the video (a pause) → wait so the
  // dub re-aligns naturally instead of running ahead.
  if (next.start > t + SPEAK_LOOKAHEAD) return;

  // Falling too far behind (continuous fast speech) → skip ahead to "now".
  if (next.start < t - MAX_LAG) {
    const jump = latestSegmentAtOrBefore(t);
    if (jump && jump.start > lastStart) next = jump;
  }

  lastStart = next.start;
  speaking = true;
  showSub(next.text);
  clipAudio.src = `${cfg.backendUrl}${next.clip}`;
  clipAudio.volume = DUB_VOLUME;
  clipAudio.playbackRate = video.playbackRate || 1;
  clipAudio.play().catch(() => { speaking = false; });
}

function onVideoPause() {
  if (clipAudio && !clipAudio.paused) { try { clipAudio.pause(); } catch {} }
}

function onVideoPlay() {
  // Resume the in-progress clip if we paused mid-sentence; else start the next.
  if (speaking && clipAudio && clipAudio.paused && clipAudio.src) {
    clipAudio.play().catch(() => { speaking = false; });
  } else {
    trySpeakNext();
  }
}

function onSeeking() {
  // Stop the current clip and re-pick from the new position next tick.
  speaking = false;
  lastStart = -1;
  if (clipAudio) { try { clipAudio.pause(); } catch {} }
  showSub("");
}

// ---------- Teardown ----------
function resetDub() {
  if (scheduler) { clearInterval(scheduler); scheduler = null; }
  if (firstClipTimer) { clearTimeout(firstClipTimer); firstClipTimer = null; }
  waitingFirstClip = false;
  if (sseSource) { try { sseSource.close(); } catch {} sseSource = null; }
  if (clipAudio) { try { clipAudio.pause(); } catch {} clipAudio.src = ""; clipAudio = null; }
  clipsByIndex.clear();
  sortedClips = [];
  lastStart = -1;
  speaking = false;
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
  video.addEventListener("pause", onVideoPause);
  video.addEventListener("play", onVideoPlay);
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
