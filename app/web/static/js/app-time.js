document.addEventListener("DOMContentLoaded", () => {
    const localeMap = {
        vi: "vi-VN",
        en: "en-US",
        ko: "ko-KR",
    };

    const pageLang = document.documentElement.lang || "vi";
    const locale = localeMap[pageLang] || "vi-VN";
    const clockFormatter = new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    });
    const fallbackFormatter = new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    });
    const relativeFormatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });

    const normalizeDate = (value) => {
        if (!value) {
            return null;
        }
        const raw = String(value).trim();
        if (!raw) {
            return null;
        }
        const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
        const date = new Date(normalized);
        return Number.isNaN(date.getTime()) ? null : date;
    };

    const formatRelative = (date) => {
        const now = new Date();
        const diffSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
        const absSeconds = Math.abs(diffSeconds);

        if (absSeconds < 60) {
            return relativeFormatter.format(diffSeconds, "second");
        }
        const diffMinutes = Math.round(diffSeconds / 60);
        if (Math.abs(diffMinutes) < 60) {
            return relativeFormatter.format(diffMinutes, "minute");
        }
        const diffHours = Math.round(diffMinutes / 60);
        if (Math.abs(diffHours) < 24) {
            return relativeFormatter.format(diffHours, "hour");
        }
        const diffDays = Math.round(diffHours / 24);
        if (Math.abs(diffDays) < 7) {
            return relativeFormatter.format(diffDays, "day");
        }
        return fallbackFormatter.format(date);
    };

    const updateLiveClocks = () => {
        document.querySelectorAll("[data-live-clock]").forEach((element) => {
            const date = normalizeDate(element.getAttribute("datetime") || element.dataset.datetime) || new Date();
            const nextValue = new Date(date.getTime() + Date.now() - window.__touchvnClockStart);
            element.textContent = clockFormatter.format(nextValue);
        });
    };

    const updateRelativeTimes = () => {
        document.querySelectorAll("[data-relative-time]").forEach((element) => {
            const date = normalizeDate(element.getAttribute("datetime") || element.dataset.datetime);
            if (!date) {
                return;
            }
            element.textContent = formatRelative(date);
            element.setAttribute("title", fallbackFormatter.format(date));
        });
    };

    window.__touchvnClockStart = Date.now();
    updateLiveClocks();
    updateRelativeTimes();
    window.addEventListener("touchvn:relative-time-refresh", updateRelativeTimes);
    window.setInterval(updateLiveClocks, 1000);
    window.setInterval(updateRelativeTimes, 60000);
});
