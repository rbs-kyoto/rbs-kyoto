document.addEventListener("DOMContentLoaded", () => {
    const main = document.querySelector("main");
    if (!main) {
        return;
    }
    document.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", (event) => {
            if (
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }
            const href = link.getAttribute("href");
            if (!href) {
                return;
            }
            if (href.startsWith("#")) {
                return;
            }
            if (link.origin !== window.location.origin) {
                return;
            }

            if (link.target && link.target !== "_self") {
                return;
            }
            event.preventDefault();
            main.classList.add("page-leaving");
            setTimeout(() => {
                window.location.href = href;
            }, 250);
        });
    });
    window.addEventListener("pageshow", () => {
        main.classList.remove("page-leaving");

        // アニメーションを確実に再実行
        main.style.animation = "none";

        requestAnimationFrame(() => {
            main.style.animation = "";
        });
    });
});