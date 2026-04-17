(function () {
    if (window.__bgChatPanelInstalled) return;
    window.__bgChatPanelInstalled = true;

    const PANEL_WIDTH = 400;

    function install() {
        // about:blank and other early pages may be missing head/body at
        // document_start.
        if (!document.head) {
            document.documentElement.appendChild(document.createElement("head"));
        }
        if (!document.body) {
            document.documentElement.appendChild(document.createElement("body"));
        }

        // Reserve space on the right for the chat panel so the page content
        // genuinely shrinks rather than being covered by the overlay. We set
        // it on both <html> and <body> with !important to defeat per-page
        // styles that reset margins/widths.
        const html = document.documentElement;
        const body = document.body;
        html.style.setProperty("padding-right", PANEL_WIDTH + "px", "important");
        html.style.setProperty("box-sizing", "border-box", "important");
        body.style.setProperty("max-width", `calc(100vw - ${PANEL_WIDTH}px)`, "important");
        body.style.setProperty("box-sizing", "border-box", "important");

        // Use Shadow DOM so the host page's CSS cannot bleed into the chat
        // panel (this fixes colour-scheme issues on pages like example.com
        // that ship aggressive base styles).
        const host = document.createElement("div");
        host.id = "bg-chat-host";
        // Hide from accessibility tree so the agent's AX-tree observation
        // doesn't see the chat panel as part of the page being interacted with.
        host.setAttribute("aria-hidden", "true");
        host.setAttribute("role", "none");
        host.style.cssText =
            "all: initial !important; position: fixed !important; top: 0 !important; " +
            "right: 0 !important; width: " + PANEL_WIDTH + "px !important; " +
            "height: 100vh !important; z-index: 2147483647 !important;";
        document.body.appendChild(host);
        const shadow = host.attachShadow({ mode: "open" });
        shadow.innerHTML = `
            <style>
                :host { display: block; width: ${PANEL_WIDTH}px; height: 100vh; }
                * { box-sizing: border-box; margin: 0; padding: 0; }
                #panel {
                    width: 100%; height: 100%;
                    background: #0a0f1a;
                    color: #e0e0e0;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex; flex-direction: column; overflow: hidden;
                    border-left: 1px solid #1a2540;
                    box-shadow: -2px 0 8px rgba(0,0,0,0.4);
                }
                #feed {
                    flex: 1; overflow-y: auto; padding: 12px 14px;
                    display: flex; flex-direction: column; gap: 8px;
                }
                #feed::-webkit-scrollbar { width: 4px; }
                #feed::-webkit-scrollbar-thumb { background: #2a3a5a; border-radius: 2px; }
                .message { max-width: 94%; display: flex; flex-direction: column; }
                .message-label {
                    font-size: 10px; text-transform: uppercase;
                    letter-spacing: 1px; margin-bottom: 4px;
                }
                .message-text {
                    font-size: 14px; line-height: 1.5;
                    word-break: break-word; overflow-wrap: anywhere;
                }
                .user-message { align-self: flex-end; align-items: flex-end; text-align: right; }
                .user-message .message-label { color: #3a9fbf; }
                .user-message .message-text { color: #ffffff; }
                .assistant-message { align-self: flex-start; align-items: flex-start; }
                .assistant-message .message-label { color: #2ecc71; }
                .assistant-message .message-text { color: #7dcea0; }
                .infeasible-message { align-self: flex-start; align-items: flex-start; }
                .infeasible-message .message-label { color: #e67e22; }
                .infeasible-message .message-text { color: #f0b27a; }
                .entry {
                    font-size: 12px; line-height: 1.4; padding: 6px 10px;
                    border-radius: 6px; max-width: 92%; align-self: flex-start;
                    word-break: break-word;
                    overflow-wrap: anywhere;
                    white-space: pre-wrap;
                    box-sizing: border-box;
                }
                .entry.action {
                    background: #11201a; border-left: 3px solid #2ecc71;
                    color: #7dcea0; font-family: 'SF Mono', 'Fira Code', monospace;
                }
                .entry.error {
                    background: #201111; border-left: 3px solid #e74c3c; color: #f1948a;
                }
                .entry.step {
                    background: transparent; border: none; color: #4a5a7a;
                    font-size: 11px; padding: 2px 6px; text-transform: uppercase; letter-spacing: 1px;
                }
                .entry.think {
                    background: #111d30; border-left: 3px solid #3a7bd5; color: #8ab4f0;
                }
                .entry.think summary {
                    cursor: pointer; font-size: 12px; color: #4a6a8a;
                    user-select: none; outline: none; padding: 2px 0; list-style: none;
                }
                .entry.think summary::-webkit-details-marker { display: none; }
                .entry.think summary::before {
                    content: '\\25B6'; display: inline-block; font-size: 9px;
                    margin-right: 6px; transition: transform 0.15s;
                }
                .entry.think details[open] > summary::before { transform: rotate(90deg); }
                .entry.think summary .token-count { color: #3a7bd5; font-weight: 600; }
                .entry.think summary .spinner {
                    display: inline-block; animation: bgChatPulse 1s infinite;
                    margin-right: 4px; color: #3a7bd5;
                }
                @keyframes bgChatPulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
                .entry.think .stream-content {
                    margin-top: 6px; padding-top: 6px; border-top: 1px solid #1a2540;
                    white-space: pre-wrap; font-size: 12px; line-height: 1.5;
                    max-height: 300px; overflow-y: auto; color: #8ab4f0;
                }
                .entry.think .stream-content::-webkit-scrollbar { width: 4px; }
                .entry.think .stream-content::-webkit-scrollbar-thumb {
                    background: #2a3a5a; border-radius: 2px;
                }
                .chat-input-area {
                    padding: 12px 16px; background: #0d1525;
                    border-top: 1px solid #1a2540; flex-shrink: 0;
                }
                .chat-input-area form {
                    display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap;
                }
                .input-box {
                    flex: 1; min-width: 150px; padding: 10px 14px;
                    background: #141e33; color: #e0e0e0; border: 1px solid #1a2540;
                    border-radius: 8px; outline: none; resize: none;
                    font-size: 14px; font-family: inherit;
                    min-height: 42px; max-height: 120px; overflow-y: auto;
                }
                .input-box::placeholder { color: #4a5a7a; }
                .input-box:focus { border-color: #3a7bd5; }
                .submit-button {
                    padding: 10px 20px; background: #1a3a5c; color: #8ab4f0;
                    border: 1px solid #2a4a7a; border-radius: 8px; cursor: pointer;
                    font-size: 13px; font-weight: 600; transition: background 0.15s;
                }
                .submit-button:hover { background: #2a4a7a; }
                .control-buttons { display: flex; gap: 6px; }
                .control-btn {
                    padding: 10px 14px; border: 1px solid #2a4a7a; border-radius: 8px;
                    cursor: pointer; font-size: 13px; font-weight: 600; transition: background 0.15s;
                }
                .pause-btn { background: #3a2a1a; color: #f0b27a; border-color: #5a3a1a; }
                .pause-btn:hover { background: #4a3a2a; }
                .pause-btn.paused { background: #1a3a2a; color: #7dcea0; border-color: #2a5a3a; }
                .pause-btn.paused:hover { background: #2a4a3a; }
                .end-btn { background: #2a1a1a; color: #f1948a; border-color: #4a2a2a; }
                .end-btn:hover { background: #3a2a2a; }
                .hide-btn { background: #1a2540; color: #8ab4f0; border-color: #2a4a7a; }
                .hide-btn:hover { background: #2a3a5a; }
            </style>
            <div id="panel">
                <div id="feed"></div>
                <div class="chat-input-area">
                    <form id="bgChatForm">
                        <textarea class="input-box" id="bgInputBox" placeholder="Type a message..." rows="1"></textarea>
                        <button type="submit" class="submit-button">Send</button>
                        <div class="control-buttons">
                            <button type="button" class="control-btn pause-btn" id="bgPauseBtn">Pause</button>
                            <button type="button" class="control-btn hide-btn" id="bgHideBtn">Hide</button>
                            <button type="button" class="control-btn end-btn" id="bgEndBtn">End</button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        const panel = shadow;

        window.USER_MESSAGE_RECEIVED = false;
        window.AGENT_PAUSED = false;
        window.AGENT_END = false;

        const feed = panel.querySelector("#feed");
        const inputBox = panel.querySelector("#bgInputBox");
        const pauseBtn = panel.querySelector("#bgPauseBtn");
        const endBtn = panel.querySelector("#bgEndBtn");
        const chatForm = panel.querySelector("#bgChatForm");

        function scrollFeedToBottom() { feed.scrollTop = feed.scrollHeight; }

        function escapeHtml(s) {
            return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }
        function nl2br(s) { return s.replace(/\n/g, "<br>"); }

        function addChatMessage(role, timeString, msg) {
            if (role === "think") {
                const entry = document.createElement("details");
                entry.className = "entry think";
                entry.innerHTML =
                    '<summary>Thought</summary>' +
                    '<div class="stream-content">' + nl2br(escapeHtml(msg)) + '</div>';
                feed.appendChild(entry);
                scrollFeedToBottom();
                return;
            }
            if (role === "info") {
                const entry = document.createElement("div");
                const lower = msg.toLowerCase();
                if (lower.startsWith("action:")) entry.className = "entry action";
                else if (lower.includes("error")) entry.className = "entry error";
                else entry.className = "entry step";
                entry.innerHTML = nl2br(escapeHtml(msg));
                feed.appendChild(entry);
                scrollFeedToBottom();
                return;
            }
            const container = document.createElement("div");
            container.className = "message";
            const label = document.createElement("div");
            label.className = "message-label";
            const text = document.createElement("div");
            text.className = "message-text";
            switch (role) {
                case "user":
                    container.classList.add("user-message");
                    label.textContent = timeString + " \u00b7 You";
                    text.innerHTML = nl2br(escapeHtml(msg));
                    break;
                case "assistant":
                    container.classList.add("assistant-message");
                    label.textContent = timeString + " \u00b7 Agent";
                    text.innerHTML = nl2br(escapeHtml(msg));
                    break;
                case "infeasible":
                    container.classList.add("infeasible-message");
                    label.textContent = timeString + " \u00b7 Agent (cannot complete)";
                    text.innerHTML = nl2br(escapeHtml(msg));
                    break;
                default:
                    return;
            }
            container.appendChild(label);
            container.appendChild(text);
            feed.appendChild(container);
            scrollFeedToBottom();
            if (role === "user") window.USER_MESSAGE_RECEIVED = true;
        }

        let _streamEntry = null;
        let _streamTokenCount = 0;

        function startStreamingThink() {
            _streamTokenCount = 0;
            const wrapper = document.createElement("div");
            wrapper.className = "entry think";
            const details = document.createElement("details");
            details.open = false;
            const summary = document.createElement("summary");
            summary.innerHTML = '<span class="spinner">&#9679;</span> Thinking... <span class="token-count">0 tokens</span>';
            const content = document.createElement("div");
            content.className = "stream-content";
            details.appendChild(summary);
            details.appendChild(content);
            wrapper.appendChild(details);
            feed.appendChild(wrapper);
            scrollFeedToBottom();
            _streamEntry = { wrapper, summary, content, details };
        }
        function appendStreamingToken(token) {
            if (!_streamEntry) return;
            _streamTokenCount++;
            _streamEntry.content.textContent += token;
            _streamEntry.summary.innerHTML =
                '<span class="spinner">&#9679;</span> Thinking... <span class="token-count">' + _streamTokenCount + ' tokens</span>';
            if (_streamEntry.details.open) {
                _streamEntry.content.scrollTop = _streamEntry.content.scrollHeight;
            }
            scrollFeedToBottom();
        }
        function finalizeStreamingThink() {
            if (!_streamEntry) return;
            _streamEntry.summary.innerHTML =
                'Thought <span class="token-count">(' + _streamTokenCount + ' tokens)</span>';
            _streamEntry = null;
        }

        // Expose for Playwright's page.evaluate to call.
        window.addChatMessage = addChatMessage;
        window.startStreamingThink = startStreamingThink;
        window.appendStreamingToken = appendStreamingToken;
        window.finalizeStreamingThink = finalizeStreamingThink;

        if (typeof window.send_user_message !== "function") {
            window.send_user_message = function () {};
        }

        async function send_msg(msg) {
            if (msg.trim()) {
                const strings = await window.send_user_message(msg);
                addChatMessage(strings[0], strings[1], strings[2]);
                inputBox.value = "";
                inputBox.style.height = "auto";
            }
        }

        inputBox.addEventListener("input", () => {
            inputBox.style.height = "auto";
            inputBox.style.height = Math.min(inputBox.scrollHeight, 120) + "px";
        });
        inputBox.addEventListener("keypress", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send_msg(inputBox.value);
            }
        });
        chatForm.addEventListener("submit", (e) => {
            e.preventDefault();
            send_msg(inputBox.value);
            return false;
        });
        pauseBtn.addEventListener("click", () => {
            window.AGENT_PAUSED = !window.AGENT_PAUSED;
            if (window.AGENT_PAUSED) {
                pauseBtn.textContent = "Resume";
                pauseBtn.classList.add("paused");
                addChatMessage("info", "", "Agent paused.");
            } else {
                pauseBtn.textContent = "Pause";
                pauseBtn.classList.remove("paused");
                addChatMessage("info", "", "Agent resumed.");
            }
        });
        endBtn.addEventListener("click", () => {
            window.AGENT_END = true;
            window.AGENT_PAUSED = false;
            addChatMessage("info", "", "Ending session...");
        });

        const hideBtn = panel.querySelector("#bgHideBtn");
        function setVisible(visible) {
            window.__bgChatHidden = !visible;
            if (visible) {
                host.style.setProperty("display", "block", "important");
                html.style.setProperty("padding-right", PANEL_WIDTH + "px", "important");
                body.style.setProperty("max-width", `calc(100vw - ${PANEL_WIDTH}px)`, "important");
            } else {
                host.style.setProperty("display", "none", "important");
                html.style.removeProperty("padding-right");
                body.style.removeProperty("max-width");
            }
        }
        function toggleVisible() {
            setVisible(!!window.__bgChatHidden);
        }
        window.bgChatToggle = toggleVisible;
        window.bgChatSetVisible = setVisible;

        hideBtn.addEventListener("click", () => setVisible(false));

        // Toolbar-icon clicks arrive via the extension's content script and
        // are forwarded to us as window messages.
        window.addEventListener("message", (e) => {
            if (e.data && e.data.source === "bg-chat-ext" && e.data.action === "toggle") {
                toggleVisible();
            }
        });

        // Notify the agent that the overlay is ready (used after navigations).
        window.__bgChatReady = true;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", install, { once: true });
    } else {
        install();
    }
})();
