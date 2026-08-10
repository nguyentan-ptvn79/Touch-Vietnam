(() => {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
    if (!csrfToken) {
        return;
    }

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        const method = (form.getAttribute("method") || "get").toLowerCase();
        if (!["post", "put", "patch", "delete"].includes(method)) {
            return;
        }
        let field = form.querySelector('input[name="csrf_token"]');
        if (!field) {
            field = document.createElement("input");
            field.type = "hidden";
            field.name = "csrf_token";
            form.appendChild(field);
        }
        field.value = csrfToken;
    }, true);

    const nativeFetch = window.fetch.bind(window);
    window.fetch = (resource, options = {}) => {
        const sourceRequest = resource instanceof Request ? resource : null;
        const requestUrl = typeof resource === "string" ? resource : sourceRequest?.url;
        const targetUrl = new URL(requestUrl || window.location.href, window.location.href);
        const method = String(options.method || sourceRequest?.method || "GET").toUpperCase();
        const unsafeMethod = !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method);
        if (unsafeMethod && targetUrl.origin === window.location.origin) {
            const headers = new Headers(options.headers || sourceRequest?.headers || {});
            headers.set("X-CSRF-Token", csrfToken);
            options = { ...options, headers };
        }
        return nativeFetch(resource, options);
    };
})();
