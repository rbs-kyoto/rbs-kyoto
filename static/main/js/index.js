document.addEventListener("DOMContentLoaded", () => {
    const pickup = document.querySelector(".top-pickup");
    if (!pickup) return;
    const slider = pickup.querySelector(".top-pickup__slide");
    const slides = pickup.querySelectorAll(".top-pickup__image");
    const bannerText = pickup.querySelector(".top-pickup__bnr .low");
    const captionText = pickup.querySelector(".top-pickup__caption span");
    if (slides.length === 0 || !bannerText) return;
    const intervalMs = 5000;
    let currentIndex = 0;
    let timer;
    let dots = [];

    function showSlide(index) {
        currentIndex = (index + slides.length) % slides.length;
        slides.forEach((slide, i) => {
            slide.classList.toggle("is-active", i === currentIndex);
        });
        dots.forEach((dot, i) => {
            dot.setAttribute("aria-current", String(i === currentIndex));
        });
        bannerText.textContent = slides[currentIndex].dataset.text || "";
        if (captionText) {
            captionText.textContent = slides[currentIndex].dataset.caption || "";
        }
    }

    function startTimer() {
        window.clearInterval(timer);
        timer = window.setInterval(() => showSlide(currentIndex + 1), intervalMs);
    }

    function stopTimer() {
        window.clearInterval(timer);
    }

    function createButton(className, label, content) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = className;
        button.setAttribute("aria-label", label);
        button.textContent = content;
        return button;
    }

    // 手動で切り替えたあとは、5秒数え直す
    function move(index) {
        showSlide(index);
        startTimer();
    }

    if (slides.length > 1 && slider) {
        const previousButton = createButton("top-pickup__arrow top-pickup__arrow--previous", "前のスライド", "chevron_left");
        const nextButton = createButton("top-pickup__arrow top-pickup__arrow--next", "次のスライド", "chevron_right");
        previousButton.addEventListener("click", () => move(currentIndex - 1));
        nextButton.addEventListener("click", () => move(currentIndex + 1));

        const dotList = document.createElement("div");
        dotList.className = "top-pickup__dots";
        dotList.setAttribute("role", "group");
        dotList.setAttribute("aria-label", "スライドの選択");
        dots = Array.from(slides, (slide, i) => {
            const dot = createButton("top-pickup__dot", `${i + 1}枚目のスライド`, "");
            dot.addEventListener("click", () => move(i));
            dotList.append(dot);
            return dot;
        });

        slider.append(previousButton, nextButton, dotList);

        // 操作中は止める
        slider.addEventListener("pointerenter", stopTimer);
        slider.addEventListener("pointerleave", startTimer);
        slider.addEventListener("focusin", stopTimer);
        slider.addEventListener("focusout", startTimer);

        // スマホでは左右のスワイプで切り替える
        let touchStartX = null;
        slider.addEventListener("touchstart", (event) => {
            touchStartX = event.touches[0].clientX;
        }, { passive: true });
        slider.addEventListener("touchend", (event) => {
            if (touchStartX === null) return;
            const distance = event.changedTouches[0].clientX - touchStartX;
            touchStartX = null;
            if (Math.abs(distance) > 40) {
                move(currentIndex + (distance < 0 ? 1 : -1));
            }
        });

        startTimer();
    }

    showSlide(0);
});
