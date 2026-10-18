// 非常に複雑です．あんまりいじらないことをお勧めします．
// 仕組みは，「ページ及びブラウザの戻る進むボタンからの動作があればそれでアニメーション向きを判定，ボタン以外からの操作なら全て進むアニメーションで扱う」ということです．
// 間違いあったらごめんね．ではよろしく． by梶原

document.addEventListener("DOMContentLoaded", () => {
    const main = document.querySelector("main");
    const themeOptions = document.querySelectorAll("[data-theme-mode]");
    const themeImages = document.querySelectorAll("[data-theme-light-src][data-theme-dark-src]");
    let savedTheme = null;
    try {
        savedTheme = localStorage.getItem("rbs-theme");
    } catch (error) {
        console.warn("Theme preference could not be read from local storage.", error);
    }
    let hasManualTheme = Boolean(savedTheme);

    const updateThemeControls = () => {
        const isDark = document.body.classList.contains("dark-mode");
        themeImages.forEach((image) => {
            image.src = isDark ? image.dataset.themeDarkSrc : image.dataset.themeLightSrc;
        });
        themeOptions.forEach((option) => {
            option.setAttribute(
                "aria-pressed",
                String(option.dataset.themeMode === (isDark ? "dark" : "light"))
            );
        });
    };

    updateThemeControls();

    themeOptions.forEach((option) => {
        option.addEventListener("click", () => {
            const isDark = option.dataset.themeMode === "dark";
            document.body.classList.toggle("dark-mode", isDark);
            hasManualTheme = true;
            try {
                localStorage.setItem("rbs-theme", isDark ? "dark" : "light");
            } catch (error) {
                console.warn("Theme preference could not be saved to local storage.", error);
            }
            updateThemeControls();
        });
    });

    if (!hasManualTheme) {
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
            if (!hasManualTheme) {
                document.body.classList.toggle("dark-mode", event.matches);
                updateThemeControls();
            }
        });
    }

    if (!main) {
        return;
    }

    const pageDirection = sessionStorage.getItem("pageDirection");

    if (pageDirection === "back") {
        main.classList.add("page-back");
    } else if (pageDirection === "forward") {
        main.classList.add("page-forward");
    }

    sessionStorage.removeItem("pageDirection");

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

            const isBack = link.classList.contains(
                "page-control-style-back"
            );

            const isForward = link.classList.contains(
                "page-control-style-forward"
            );

            if (isBack) {
                sessionStorage.setItem("pageDirection", "back");
            } else {
                sessionStorage.setItem("pageDirection", "forward");
            }

            if (isBack) {
                main.classList.add("page-leaving-back");
            } else if (isForward) {
                main.classList.add("page-leaving-forward");
            } else {
                main.classList.add("page-leaving");
            }

            main.addEventListener("animationend", () => {
                window.location.href = href;
            }, { once: true });
        });
    });

    window.addEventListener("pageshow", () => {

        main.classList.remove(
            "page-leaving",
            "page-leaving-back",
            "page-leaving-forward"
        );

        main.style.animation = "none";

        requestAnimationFrame(() => {
            main.style.animation = "";
        });
    });
});