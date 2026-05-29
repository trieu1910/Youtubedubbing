// Minimal service worker: defaults + health relay (avoids page CORS edge cases).
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.sync.set({ targetLang: "vi", backendUrl: "http://localhost:8788" });
  }
});
