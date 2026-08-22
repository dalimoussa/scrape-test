var cachedApiUrl = "http://127.0.0.1:8485/data";

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get("apiUrl", (result) => {
    if (!result.apiUrl) {
      chrome.storage.local.set({ apiUrl: cachedApiUrl }, () => {
        console.log("Default apiUrl set.");
      });
    } else {
      cachedApiUrl = result.apiUrl;
    }
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "SEND_HTTP") {
    fetch(cachedApiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        data: message.data,
        lang: message.lang,
        msgType: message.msgType || 'live'   // NEW: forward type to backend
      })
    })
    .then(response => response.text())
    .then(responseData => {
      console.log("Response from API:", responseData);
    })
    .catch(error => {
      console.error("Error during API request:", error);
    });
    return true;
  }
  else if (message.type === "SET_API_URL") {
    cachedApiUrl = message.apiUrl;
    chrome.storage.local.set({ apiUrl: message.apiUrl }, () => {
      console.log("apiUrl updated to:", message.apiUrl);
      sendResponse({ success: true });
    });
    return true;
  }
});