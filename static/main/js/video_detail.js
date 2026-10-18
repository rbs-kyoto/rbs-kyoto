document.addEventListener("DOMContentLoaded", () => {
    const iframe = document.querySelector(".video-detail__player iframe");
    const embedUrl = iframe?.dataset.embedUrl;
    const poster = document.querySelector(".video-detail__poster");
    const dialog = document.querySelector(".video-playback-dialog");

    if (
        !iframe ||
        !embedUrl ||
        !(poster instanceof HTMLButtonElement) ||
        !(dialog instanceof HTMLDialogElement)
    ) {
        return;
    }

    const startPlayback = (muted) => {
        const playerUrl = new URL(embedUrl);
        playerUrl.searchParams.set("autoplay", "1");
        playerUrl.searchParams.set("mute", muted ? "1" : "0");
        playerUrl.searchParams.set("controls", "0");
        iframe.src = playerUrl.toString();
        iframe.hidden = false;
        poster.hidden = true;
        dialog.close();
    };

    poster.addEventListener("click", () => dialog.showModal());
    dialog.querySelectorAll("[data-playback-muted]").forEach((button) => {
        button.addEventListener("click", () => {
            startPlayback(button.dataset.playbackMuted === "true");
        });
    });
    dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        startPlayback(true);
    });
});
