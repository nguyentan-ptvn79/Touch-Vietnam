document.addEventListener("DOMContentLoaded", () => {
    const roots = document.querySelectorAll("[data-ar-viewer]");
    if (!roots.length) {
        return;
    }

    roots.forEach((root) => {
        const video = root.querySelector("[data-ar-video]");
        const statusNode = root.querySelector("[data-ar-status]");
        const startButton = root.querySelector("[data-ar-start]");
        const stopButton = root.querySelector("[data-ar-stop]");
        const idleText = root.dataset.idleText || "";
        const activeText = root.dataset.activeText || "";
        const errorText = root.dataset.errorText || "";
        let stream = null;

        const setStatus = (message) => {
            if (statusNode) {
                statusNode.textContent = message || "";
            }
        };

        const stopCamera = () => {
            if (stream) {
                stream.getTracks().forEach((track) => track.stop());
                stream = null;
            }
            if (video) {
                video.pause();
                video.srcObject = null;
            }
            setStatus(idleText);
        };

        const startCamera = async () => {
            if (!video || !navigator.mediaDevices?.getUserMedia) {
                setStatus(errorText);
                return;
            }
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        facingMode: { ideal: "environment" },
                    },
                    audio: false,
                });
                video.srcObject = stream;
                await video.play();
                setStatus(activeText);
            } catch (_error) {
                setStatus(errorText);
            }
        };

        startButton?.addEventListener("click", startCamera);
        stopButton?.addEventListener("click", stopCamera);
        window.addEventListener("beforeunload", stopCamera);
        setStatus(idleText);
    });
});
