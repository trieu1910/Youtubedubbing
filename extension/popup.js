const $ = (id) => document.getElementById(id);

chrome.storage.sync.get(["targetLang", "geminiApiKey", "backendUrl"], (d) => {
  if (d.targetLang) $("targetLang").value = d.targetLang;
  if (d.geminiApiKey) $("apiKey").value = d.geminiApiKey;
  $("backendUrl").value = d.backendUrl || "http://localhost:8788";
});

$("save").addEventListener("click", () => {
  chrome.storage.sync.set({
    targetLang: $("targetLang").value,
    geminiApiKey: $("apiKey").value.trim(),
    backendUrl: ($("backendUrl").value.trim() || "http://localhost:8788").replace(/\/$/, ""),
  }, () => setStatus("Đã lưu.", "ok"));
});

$("check").addEventListener("click", async () => {
  const url = ($("backendUrl").value.trim() || "http://localhost:8788").replace(/\/$/, "");
  setStatus("Đang kiểm tra...", "");
  try {
    const r = await fetch(`${url}/health`);
    const j = await r.json();
    setStatus(`OK • GPU: ${j.cuda ? j.device : "CPU"} • ffmpeg: ${j.ffmpeg ? "có" : "thiếu"}`, j.cuda && j.ffmpeg ? "ok" : "err");
  } catch {
    setStatus("Không kết nối được backend. Hãy chạy run.ps1.", "err");
  }
});

function setStatus(msg, cls) {
  const el = $("status");
  el.textContent = msg;
  el.className = cls;
}
