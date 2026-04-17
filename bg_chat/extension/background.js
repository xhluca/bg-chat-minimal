// Toggle the chat panel when the user clicks the extension icon.
chrome.action.onClicked.addListener((tab) => {
    if (!tab || !tab.id) return;
    chrome.tabs.sendMessage(tab.id, { type: "bg-chat-toggle" }).catch(() => {
        // Content script may not be loaded on chrome:// pages, etc.
    });
});
