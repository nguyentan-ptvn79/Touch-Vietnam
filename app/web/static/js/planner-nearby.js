(() => {
    const button = document.querySelector("[data-nearby-location]");
    const status = document.querySelector("[data-nearby-location-status]");
    if (!button) {
        return;
    }
    button.addEventListener("click", () => {
        if (!navigator.geolocation) {
            if (status) {
                status.textContent = button.dataset.errorText || "";
            }
            return;
        }
        if (status) {
            status.textContent = button.dataset.loadingText || "";
        }
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const targetUrl = new URL(button.dataset.targetUrl || window.location.pathname, window.location.origin);
                targetUrl.searchParams.set("lat", position.coords.latitude.toFixed(6));
                targetUrl.searchParams.set("lng", position.coords.longitude.toFixed(6));
                window.location.href = targetUrl.toString();
            },
            () => {
                if (status) {
                    status.textContent = button.dataset.errorText || "";
                }
            },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 300000 }
        );
    });
})();
