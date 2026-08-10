document.addEventListener("DOMContentLoaded", () => {
    const roots = document.querySelectorAll("[data-qr-scanner]");
    if (!roots.length) {
        return;
    }

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
            throw new Error(payload.error || payload.message || "QR request failed.");
        }
        return payload;
    };

    const escapeHtml = (value) =>
        String(value ?? "").replace(
            /[&<>"']/g,
            (character) => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#039;",
            })[character],
        );

    const safeUrl = (value, fallback = "#") => {
        try {
            const url = new URL(String(value || ""), window.location.origin);
            if (!["http:", "https:"].includes(url.protocol)) {
                return fallback;
            }
            return url.toString();
        } catch (_error) {
            return fallback;
        }
    };

    roots.forEach((root) => {
        const video = root.querySelector("[data-qr-video]");
        const statusNode = root.querySelector("[data-qr-status]");
        const resultNode = root.querySelector("[data-qr-result]");
        const startButton = root.querySelector("[data-qr-start]");
        const stopButton = root.querySelector("[data-qr-stop]");
        const manualForm = root.querySelector("[data-qr-manual-form]");
        const manualInput = root.querySelector("[data-qr-manual-input]");
        const resolveEndpoint = root.dataset.qrResolveEndpoint;
        const idleText = root.dataset.idleText || "";
        const activeText = root.dataset.activeText || "";
        const errorText = root.dataset.errorText || "";
        const successText = root.dataset.successText || "";
        const resultLabel = root.dataset.resultLabel || "QR";
        const openDetailLabel = root.dataset.openDetailLabel || "Open details";
        const openMapLabel = root.dataset.openMapLabel || "Open map";

        let detector = null;
        let stream = null;
        let loopToken = null;
        let scanLocked = false;

        const setStatus = (message) => {
            if (statusNode) {
                statusNode.textContent = message || "";
            }
        };

        const stopCamera = () => {
            if (loopToken) {
                window.clearTimeout(loopToken);
                loopToken = null;
            }
            if (stream) {
                stream.getTracks().forEach((track) => track.stop());
                stream = null;
            }
            if (video) {
                video.pause();
                video.srcObject = null;
            }
            scanLocked = false;
            setStatus(idleText);
        };

        const renderResult = (payload) => {
            if (!resultNode) {
                return;
            }
            const place = payload.place || {};
            const weather = payload.weather || null;
            const nearby = payload.nearby_services || [];
            const nearbyHtml = nearby.length
                ? `<div class="stack-list">${nearby
                    .map(
                        (item) => `
                            <div class="stack-row">
                                <strong>${escapeHtml(item.name)}</strong>
                                <span>${escapeHtml(item.distance_km)} km</span>
                                <p>${escapeHtml(item.note)}</p>
                            </div>
                        `
                    )
                    .join("")}</div>`
                : "";
            const weatherHtml = weather
                ? `
                    <div class="place-weather qr-result-weather">
                        <div class="place-weather-top">
                            <strong>${escapeHtml(weather.temperature_c)}&deg;C</strong>
                            <span>${escapeHtml(weather.condition)}</span>
                        </div>
                        <p>${escapeHtml(weather.advice)}</p>
                    </div>
                `
                : "";

            resultNode.innerHTML = `
                <span class="card-label">${escapeHtml(resultLabel)}</span>
                <h3>${escapeHtml(place.name)}</h3>
                <p>${escapeHtml(place.description)}</p>
                <ul class="mini-list">
                    ${(place.highlights || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                </ul>
                ${weatherHtml}
                ${nearbyHtml}
                <div class="inline-actions">
                    <a class="button secondary" href="${escapeHtml(safeUrl(payload.detail_url))}">${escapeHtml(openDetailLabel)}</a>
                    <a class="text-link" href="${escapeHtml(safeUrl(payload.map_view_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(openMapLabel)}</a>
                </div>
            `;
        };

        const resolveCode = async (code) => {
            const payload = await requestJson(resolveEndpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ code }),
            });
            renderResult(payload);
            stopCamera();
            setStatus(successText);
        };

        const scanLoop = async () => {
            if (!detector || !video || scanLocked) {
                return;
            }
            try {
                const results = await detector.detect(video);
                const hit = results.find((item) => item.rawValue);
                if (hit && hit.rawValue) {
                    scanLocked = true;
                    await resolveCode(hit.rawValue);
                    return;
                }
            } catch (_error) {
                setStatus(errorText);
            }
            loopToken = window.setTimeout(scanLoop, 500);
        };

        const startCamera = async () => {
            if (!("BarcodeDetector" in window) || !video) {
                setStatus(errorText);
                return;
            }
            try {
                detector = new window.BarcodeDetector({ formats: ["qr_code"] });
                stream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        facingMode: { ideal: "environment" },
                    },
                    audio: false,
                });
                video.srcObject = stream;
                await video.play();
                scanLocked = false;
                setStatus(activeText);
                scanLoop();
            } catch (_error) {
                setStatus(errorText);
            }
        };

        startButton?.addEventListener("click", () => {
            startCamera();
        });
        stopButton?.addEventListener("click", () => {
            stopCamera();
        });
        manualForm?.addEventListener("submit", async (event) => {
            event.preventDefault();
            const value = manualInput?.value?.trim() || "";
            if (!value) {
                return;
            }
            try {
                await resolveCode(value);
            } catch (_error) {
                setStatus(errorText);
            }
        });
        window.addEventListener("beforeunload", stopCamera);
        setStatus(idleText);
    });
});
