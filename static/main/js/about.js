document.addEventListener("DOMContentLoaded", () => {
    const page = document.querySelector(".about-page");
    const screens = [...document.querySelectorAll("[data-about-screen]")];
    const paginationButtons = [...document.querySelectorAll("[data-screen-target]")];

    if (!(page instanceof HTMLElement) || screens.length === 0 || screens.length !== paginationButtons.length) {
        console.error("The about page screen navigation could not be initialized.");
        return;
    }

    let activeIndex = 0;
    let isSwitching = false;
    let touchStartY = null;

    const setActiveScreen = (nextIndex) => {
        const boundedIndex = Math.max(0, Math.min(screens.length - 1, nextIndex));
        if (boundedIndex === activeIndex) {
            return;
        }

        activeIndex = boundedIndex;
        screens.forEach((screen, index) => {
            screen.classList.toggle("is-active", index === activeIndex);
            screen.classList.toggle("is-before", index < activeIndex);
            screen.setAttribute("aria-hidden", String(index !== activeIndex));
            screen.inert = index !== activeIndex;
        });
        paginationButtons.forEach((button, index) => {
            if (index === activeIndex) {
                button.setAttribute("aria-current", "step");
            } else {
                button.removeAttribute("aria-current");
            }
        });
    };

    const moveScreen = (direction) => {
        if (isSwitching) {
            return;
        }

        const nextIndex = Math.max(0, Math.min(screens.length - 1, activeIndex + direction));
        if (nextIndex === activeIndex) {
            return;
        }

        isSwitching = true;
        setActiveScreen(nextIndex);
        window.setTimeout(() => {
            isSwitching = false;
        }, 650);
    };

    page.classList.add("has-screen-switching");
    screens.forEach((screen, index) => {
        screen.classList.toggle("is-active", index === activeIndex);
        screen.setAttribute("aria-hidden", String(index !== activeIndex));
        screen.inert = index !== activeIndex;
    });

    page.addEventListener("wheel", (event) => {
        if (event.ctrlKey || Math.abs(event.deltaY) < 8) {
            return;
        }

        event.preventDefault();
        moveScreen(event.deltaY > 0 ? 1 : -1);
    }, { passive: false });

    page.addEventListener("touchstart", (event) => {
        touchStartY = event.touches[0]?.clientY ?? null;
    }, { passive: true });

    page.addEventListener("touchend", (event) => {
        const touchEndY = event.changedTouches[0]?.clientY;
        if (touchStartY !== null && touchEndY !== undefined) {
            const distance = touchStartY - touchEndY;
            if (Math.abs(distance) > 45) {
                moveScreen(distance > 0 ? 1 : -1);
            }
        }
        touchStartY = null;
    }, { passive: true });

    document.addEventListener("keydown", (event) => {
        const target = event.target;
        if (
            !(target instanceof HTMLElement)
            || target.isContentEditable
            || target.closest("a, button, input, select, textarea")
        ) {
            return;
        }

        if (["ArrowDown", "PageDown", " "].includes(event.key)) {
            event.preventDefault();
            moveScreen(1);
        } else if (["ArrowUp", "PageUp"].includes(event.key)) {
            event.preventDefault();
            moveScreen(-1);
        }
    });

    paginationButtons.forEach((button, index) => {
        button.addEventListener("click", () => {
            isSwitching = false;
            setActiveScreen(index);
        });
    });

    const logoStage = document.querySelector("[data-logo-stage]");
    if (!(logoStage instanceof HTMLElement)) {
        console.error("The about page logo interaction could not be initialized.");
        return;
    }

    logoStage.addEventListener("pointermove", (event) => {
        if (event.pointerType !== "mouse") {
            return;
        }

        const bounds = logoStage.getBoundingClientRect();
        const horizontal = (event.clientX - bounds.left) / bounds.width - .5;
        const vertical = (event.clientY - bounds.top) / bounds.height - .5;
        const rotateX = Math.max(-8, Math.min(8, -vertical * 16));
        const rotateY = Math.max(-8, Math.min(8, horizontal * 16));
        logoStage.style.setProperty("--tilt-x", `${rotateX}deg`);
        logoStage.style.setProperty("--tilt-y", `${rotateY}deg`);
    });

    logoStage.addEventListener("pointerleave", () => {
        logoStage.style.setProperty("--tilt-x", "0deg");
        logoStage.style.setProperty("--tilt-y", "0deg");
    });
});
