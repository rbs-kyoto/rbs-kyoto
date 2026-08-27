document.addEventListener("DOMContentLoaded", () => {
    const rawEl = document.getElementById("manual-raw-content");
    const targetEl = document.getElementById("manual-rendered-content");

    if (!rawEl || !targetEl || typeof marked === "undefined") {
        return;
    }

    targetEl.innerHTML = marked.parse(rawEl.value);
});
