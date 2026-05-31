(function () {
    const root = document.documentElement;
    const button = document.getElementById("theme-toggle");

    function systemTheme() {
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function applyTheme(theme) {
        const resolved = theme === "system" ? systemTheme() : theme;
        root.setAttribute("data-theme", resolved);
        if (button) {
            button.textContent = resolved === "dark" ? "Light" : "Dark";
        }
    }

    const stored = localStorage.getItem("theme-preference");
    const initial = stored || root.getAttribute("data-theme") || "system";
    applyTheme(initial);

    if (!button) {
        return;
    }

    button.addEventListener("click", function () {
        const current = root.getAttribute("data-theme") === "dark" ? "dark" : "light";
        const next = current === "dark" ? "light" : "dark";
        localStorage.setItem("theme-preference", next);
        applyTheme(next);

        if (button.dataset.authenticated === "true") {
            fetch("/settings/theme", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({theme: next})
            }).catch(function () {});
        }
    });
})();
