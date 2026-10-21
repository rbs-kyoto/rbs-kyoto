document.addEventListener("DOMContentLoaded", () => {
    const dialog = document.querySelector(".error-preview-dialog");
    const openButton = document.querySelector("[data-error-preview-open]");
    const closeButton = document.querySelector("[data-error-preview-close]");

    if (
        !(dialog instanceof HTMLDialogElement)
        || !(openButton instanceof HTMLButtonElement)
        || !(closeButton instanceof HTMLButtonElement)
    ) {
        return;
    }

    openButton.addEventListener("click", () => dialog.showModal());
    closeButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            dialog.close();
        }
    });
});
