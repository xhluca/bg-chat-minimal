// Content script: runs in the isolated world. Inject overlay-main.js into the
// page's main world so window-level functions (addChatMessage, etc.) are
// callable via Playwright's page.evaluate(). Also bridge toolbar-icon clicks
// from the extension's service worker into the page.
(function () {
    if (window.__bgChatLoaderRan) return;
    window.__bgChatLoaderRan = true;

    const script = document.createElement("script");
    script.src = chrome.runtime.getURL("overlay-main.js");
    script.onload = function () { this.remove(); };
    (document.documentElement || document.head).appendChild(script);

    chrome.runtime.onMessage.addListener((msg) => {
        if (msg && msg.type === "bg-chat-toggle") {
            window.postMessage({ source: "bg-chat-ext", action: "toggle" }, "*");
        }
    });
})();
