document.addEventListener("DOMContentLoaded", () => {
    const createBubble = (role, content, createdAt) => {
        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${role === "user" ? "user" : "bot"}`;
        const textNode = document.createElement("div");
        textNode.textContent = content || "";
        bubble.appendChild(textNode);
        if (createdAt) {
            const timeNode = document.createElement("time");
            timeNode.className = "chat-bubble-time";
            timeNode.setAttribute("datetime", createdAt);
            timeNode.dataset.relativeTime = "true";
            bubble.appendChild(timeNode);
        }
        return bubble;
    };

    const emitChatUpdated = (payload) => {
        window.dispatchEvent(new CustomEvent("touchvn:chat-updated", { detail: payload }));
    };

    const renderMessageList = (container, messages, emptyText) => {
        if (!container) {
            return;
        }

        container.innerHTML = "";

        if (!messages || messages.length === 0) {
            const emptyState = document.createElement("div");
            emptyState.className = "chat-empty";
            emptyState.textContent = emptyText || "";
            container.appendChild(emptyState);
            return;
        }

        const thread = document.createElement("div");
        thread.className = "chat-thread";
        messages.forEach((message) => {
            thread.appendChild(createBubble(message.role, message.content, message.created_at));
        });
        container.appendChild(thread);
        container.scrollTop = container.scrollHeight;
        window.dispatchEvent(new CustomEvent("touchvn:relative-time-refresh"));
    };

    const requestJson = async (url, options = {}) => {
        const response = await fetch(url, {
            headers: {
                "Accept": "application/json",
                ...(options.headers || {}),
            },
            ...options,
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || payload.message || "Request failed.");
        }
        return payload;
    };

    const postQuestion = (endpoint, question) =>
        requestJson(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ question }),
        });

    const initFloatingWidget = () => {
        const root = document.querySelector("[data-floating-chat]");
        if (!root) {
            return;
        }

        const endpoint = root.dataset.chatEndpoint;
        const historyEndpoint = root.dataset.chatHistoryEndpoint;
        const resetEndpoint = root.dataset.chatResetEndpoint;
        const loadingText = root.dataset.loadingText || "Loading...";
        const errorText = root.dataset.errorText || "Something went wrong.";
        const emptyText = root.dataset.emptyText || "";
        const fab = root.querySelector("[data-chat-fab]");
        const panel = root.querySelector("[data-chat-panel]");
        const form = root.querySelector("[data-chat-form]");
        const input = root.querySelector("[data-chat-input]");
        const status = root.querySelector("[data-chat-status]");
        const history = root.querySelector("[data-chat-history]");
        const resetButton = root.querySelector("[data-chat-reset]");
        const closeButton = root.querySelector("[data-chat-close]");
        const backdrop = root.querySelector("[data-chat-backdrop]");
        const prompts = root.querySelectorAll("[data-chat-question]");
        if (!fab || !panel || !form || !input || !status || !history || !endpoint || !historyEndpoint) {
            return;
        }

        let hasLoadedHistory = false;

        const syncOpenState = (isOpen) => {
            panel.classList.toggle("is-hidden", !isOpen);
            backdrop?.classList.toggle("is-hidden", !isOpen);
            panel.hidden = !isOpen;
            if (backdrop) {
                backdrop.hidden = !isOpen;
            }
            panel.setAttribute("aria-hidden", String(!isOpen));
            panel.setAttribute("aria-modal", String(isOpen));
            fab.setAttribute("aria-expanded", String(isOpen));
            root.classList.toggle("is-open", isOpen);
        };

        const openPanel = async () => {
            syncOpenState(true);
            if (!hasLoadedHistory) {
                await loadHistory();
            }
            input.focus();
        };

        const closePanel = () => {
            syncOpenState(false);
            fab.focus();
        };

        const renderPayloadHistory = (payload) => {
            renderMessageList(history, payload.messages || [], payload.empty_text || emptyText);
            hasLoadedHistory = true;
        };

        const loadHistory = async () => {
            status.textContent = loadingText;
            try {
                const payload = await requestJson(historyEndpoint);
                renderPayloadHistory(payload);
                status.textContent = "";
            } catch (_error) {
                status.textContent = errorText;
            }
        };

        const sendQuestion = async (question) => {
            status.textContent = loadingText;
            try {
                const payload = await postQuestion(endpoint, question);
                renderPayloadHistory(payload);
                status.textContent = "";
                input.value = "";
                emitChatUpdated(payload);
            } catch (_error) {
                status.textContent = errorText;
            }
        };

        const resetConversation = async () => {
            if (!resetEndpoint) {
                return;
            }
            status.textContent = loadingText;
            try {
                const payload = await requestJson(resetEndpoint, { method: "POST" });
                renderPayloadHistory(payload);
                status.textContent = payload.message || "";
                input.value = "";
                emitChatUpdated(payload);
            } catch (_error) {
                status.textContent = errorText;
            }
        };

        fab.addEventListener("click", async () => {
            if (panel.classList.contains("is-hidden")) {
                await openPanel();
                return;
            }
            closePanel();
        });

        closeButton?.addEventListener("click", () => {
            closePanel();
        });

        backdrop?.addEventListener("click", () => {
            closePanel();
        });

        form.addEventListener("submit", async (event) => {
            const question = input.value.trim();
            if (!question) {
                return;
            }
            event.preventDefault();
            await sendQuestion(question);
        });

        prompts.forEach((prompt) => {
            prompt.addEventListener("click", async (event) => {
                const question = prompt.dataset.chatQuestion || "";
                if (!question) {
                    return;
                }
                event.preventDefault();
                if (panel.classList.contains("is-hidden")) {
                    await openPanel();
                }
                input.value = question;
                await sendQuestion(question);
            });
        });

        resetButton?.addEventListener("click", async () => {
            await resetConversation();
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !panel.classList.contains("is-hidden")) {
                closePanel();
            }
        });

        document.addEventListener("click", (event) => {
            if (panel.classList.contains("is-hidden")) {
                return;
            }
            const target = event.target;
            if (!(target instanceof Node)) {
                return;
            }
            if (root.contains(target)) {
                return;
            }
            closePanel();
        });

        window.addEventListener("touchvn:chat-updated", (event) => {
            const payload = event.detail || {};
            if (!payload.messages) {
                return;
            }
            renderPayloadHistory(payload);
        });

        syncOpenState(false);
    };

    initFloatingWidget();
});
