document.addEventListener("DOMContentLoaded", () => {
    const pickup = document.querySelector(".top-pickup");
    if (!pickup) return;
    const slides = pickup.querySelectorAll(".top-pickup__image");
    const bannerText = pickup.querySelector(".top-pickup__bnr .low");
    const captionText = pickup.querySelector(".top-pickup__caption span");
    if (slides.length === 0 || !bannerText) return;
    let currentIndex = 0;
    function showSlide(index) {
        slides.forEach((slide, i) => {
            slide.classList.toggle("is-active", i === index);
        });
        bannerText.textContent = slides[index].dataset.text || "";
        if (captionText) {
            captionText.textContent = slides[index].dataset.caption || "";
        }
    }
    function nextSlide() {
        currentIndex++;
        if (currentIndex >= slides.length) {
            currentIndex = 0;
        }
        showSlide(currentIndex);
    }
    showSlide(0);
    if (slides.length > 1) {
        setInterval(nextSlide, 5000);
    }
});