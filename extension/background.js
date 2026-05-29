// Minimal service worker: sets default settings on first install.
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.sync.set({ targetLang: "vi", backendUrl: "http://localhost:8788" });
  }
});
