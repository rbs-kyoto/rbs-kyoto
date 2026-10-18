document.addEventListener("DOMContentLoaded", () => {
    const iframe = document.querySelector(".video-detail__player iframe");
    const embedUrl = iframe?.dataset.embedUrl;
    const dialog = document.querySelector(".video-playback-dialog");

    if (!iframe || !embedUrl || !(dialog instanceof HTMLDialogElement)) {
        return;
    }

    const startPlayback = (muted) => {
        const playerUrl = new URL(embedUrl);
        playerUrl.searchParams.set("autoplay", "1");
        playerUrl.searchParams.set("mute", muted ? "1" : "0");
        iframe.src = playerUrl.toString();
        dialog.close();
    };

    dialog.querySelectorAll("[data-playback-muted]").forEach((button) => {
        button.addEventListener("click", () => {
            startPlayback(button.dataset.playbackMuted === "true");
        });
    });
    dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        startPlayback(true);
    });

    dialog.showModal();
});
