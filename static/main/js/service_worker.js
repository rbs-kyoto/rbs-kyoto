if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
        .catch((error) => {
            console.error("Offline support could not be enabled.", error);
        });
}
