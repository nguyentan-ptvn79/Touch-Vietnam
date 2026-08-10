(() => {
    const toggle = document.querySelector("[data-nav-toggle]");
    const navigation = document.querySelector("[data-site-nav]");
    if (!(toggle instanceof HTMLButtonElement) || !(navigation instanceof HTMLElement)) {
        return;
    }

    const setOpen = (isOpen) => {
        navigation.classList.toggle("is-open", isOpen);
        toggle.classList.toggle("is-open", isOpen);
        toggle.setAttribute("aria-expanded", String(isOpen));
    };

    toggle.addEventListener("click", () => {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });

    navigation.addEventListener("click", (event) => {
        if (event.target instanceof HTMLAnchorElement) {
            setOpen(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setOpen(false);
            toggle.focus();
        }
    });

    window.matchMedia("(min-width: 641px)").addEventListener("change", (event) => {
        if (event.matches) {
            setOpen(false);
        }
    });
})();
