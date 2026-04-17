var USER_MESSAGE_RECEIVED = false;
var AGENT_PAUSED = false;
var AGENT_END = false;

const feed = document.getElementById('feed');
const inputBox = document.getElementById('inputBox');
const pauseBtn = document.getElementById('pauseBtn');
const endBtn = document.getElementById('endBtn');
const chatForm = document.getElementById('chatForm');

function scrollFeedToBottom() {
    feed.scrollTop = feed.scrollHeight;
}

function togglePause() {
    AGENT_PAUSED = !AGENT_PAUSED;
    if (AGENT_PAUSED) {
        pauseBtn.textContent = 'Resume';
        pauseBtn.classList.add('paused');
        addChatMessage('info', '', 'Agent paused.');
    } else {
        pauseBtn.textContent = 'Pause';
        pauseBtn.classList.remove('paused');
        addChatMessage('info', '', 'Agent resumed.');
    }
}

function doEnd() {
    AGENT_END = true;
    AGENT_PAUSED = false;
    addChatMessage('info', '', 'Ending session...');
}

function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function nl2br(s) { return s.replace(/\n/g, "<br>"); }

function addChatMessage(role, timeString, msg) {
    if (role === "think") {
        const entry = document.createElement('details');
        entry.className = 'entry think';
        entry.innerHTML =
            '<summary>Thought</summary>' +
            '<div class="stream-content">' + nl2br(escapeHtml(msg)) + '</div>';
        feed.appendChild(entry);
        scrollFeedToBottom();
        return;
    }

    if (role === "info") {
        const entry = document.createElement('div');
        const lower = msg.toLowerCase();
        if (lower.startsWith("action:")) {
            entry.className = 'entry action';
        } else if (lower.includes("error")) {
            entry.className = 'entry error';
        } else {
            entry.className = 'entry step';
        }
        entry.innerHTML = nl2br(escapeHtml(msg));
        feed.appendChild(entry);
        scrollFeedToBottom();
        return;
    }

    const container = document.createElement('div');
    container.className = 'message';
    const label = document.createElement('div');
    label.className = 'message-label';
    const text = document.createElement('div');
    text.className = 'message-text';

    switch (role) {
        case "user":
            container.classList.add('user-message');
            label.textContent = timeString + ' \u00b7 You';
            text.innerHTML = nl2br(escapeHtml(msg));
            break;
        case "user_image":
            container.classList.add('user-message');
            label.textContent = timeString + ' \u00b7 You';
            text.innerHTML = '<img src="' + msg + '" style="max-width:100%">';
            break;
        case "assistant":
            container.classList.add('assistant-message');
            label.textContent = timeString + ' \u00b7 Agent';
            text.innerHTML = nl2br(escapeHtml(msg));
            break;
        case "infeasible":
            container.classList.add('infeasible-message');
            label.textContent = timeString + ' \u00b7 Agent (cannot complete)';
            text.innerHTML = nl2br(escapeHtml(msg));
            break;
        default:
            return;
    }

    container.appendChild(label);
    container.appendChild(text);
    feed.appendChild(container);
    scrollFeedToBottom();

    if (role === "user") {
        USER_MESSAGE_RECEIVED = true;
    }
}

var _streamEntry = null;
var _streamTokenCount = 0;

function startStreamingThink() {
    _streamTokenCount = 0;
    const wrapper = document.createElement('div');
    wrapper.className = 'entry think';
    const details = document.createElement('details');
    details.open = false;
    const summary = document.createElement('summary');
    summary.innerHTML = '<span class="spinner">&#9679;</span> Thinking... <span class="token-count">0 tokens</span>';
    const content = document.createElement('div');
    content.className = 'stream-content';
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

// Expose to window so Playwright's page.evaluate can call them.
window.addChatMessage = addChatMessage;
window.startStreamingThink = startStreamingThink;
window.appendStreamingToken = appendStreamingToken;
window.finalizeStreamingThink = finalizeStreamingThink;

// send_user_message is exposed by Playwright via expose_function.
// Provide a fallback so the page is usable before the binding lands.
if (typeof window.send_user_message !== 'function') {
    window.send_user_message = function (msg) {};
}

async function send_msg(msg) {
    if (msg.trim()) {
        const strings = await window.send_user_message(msg);
        addChatMessage(strings[0], strings[1], strings[2]);
        inputBox.value = '';
        inputBox.style.height = 'auto';
    }
}

inputBox.addEventListener('input', () => {
    inputBox.style.height = 'auto';
    inputBox.style.height = Math.min(inputBox.scrollHeight, 120) + 'px';
});

inputBox.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send_msg(inputBox.value);
    }
});

chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    send_msg(inputBox.value);
    return false;
});

pauseBtn.addEventListener('click', togglePause);
endBtn.addEventListener('click', doEnd);
