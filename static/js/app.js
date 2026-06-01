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

    const menuToggle = document.getElementById("menu-toggle");
    const drawer = document.getElementById("site-drawer");
    const drawerOverlay = document.getElementById("drawer-overlay");
    const drawerClose = document.getElementById("drawer-close");

    function setMenuOpen(open) {
        if (!menuToggle || !drawer || !drawerOverlay) {
            return;
        }
        menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
        menuToggle.setAttribute("aria-label", open ? "Close navigation menu" : "Open navigation menu");
        drawer.setAttribute("aria-hidden", open ? "false" : "true");
        drawer.inert = !open;
        drawer.classList.toggle("open", open);
        drawerOverlay.hidden = !open;
        document.body.classList.toggle("drawer-open", open);
        if (open) {
            const activeLink = drawer.querySelector(".drawer-nav a.active") || drawer.querySelector(".drawer-nav a");
            if (activeLink) {
                window.setTimeout(function () { activeLink.focus(); }, 80);
            }
        } else {
            menuToggle.focus();
        }
    }

    if (menuToggle && drawer && drawerOverlay) {
        menuToggle.addEventListener("click", function () {
            setMenuOpen(menuToggle.getAttribute("aria-expanded") !== "true");
        });

        if (drawerClose) {
            drawerClose.addEventListener("click", function () { setMenuOpen(false); });
        }

        drawerOverlay.addEventListener("click", function () { setMenuOpen(false); });

        drawer.addEventListener("click", function (event) {
            if (event.target.closest(".drawer-nav a")) {
                setMenuOpen(false);
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
                setMenuOpen(false);
            }
        });
    }

    const summary = document.getElementById("deployment-summary");
    if (summary && ["queued", "running"].includes(summary.dataset.status || "")) {
        const deploymentId = summary.dataset.deploymentId;
        window.setInterval(function () {
            fetch(`/deployments/${deploymentId}/status`)
                .then(function (response) { return response.ok ? response.json() : null; })
                .then(function (payload) {
                    if (!payload) { return; }
                    summary.dataset.status = payload.status || "";
                    const statusNode = summary.querySelector(".status");
                    if (statusNode && payload.status) {
                        statusNode.textContent = payload.status;
                    }
                    if (!["queued", "running"].includes(payload.status || "")) {
                        window.location.reload();
                    }
                })
                .catch(function () {});
        }, 5000);
    }
})();
