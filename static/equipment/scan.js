(() => {
    const video = document.querySelector("#equipment-camera");
    const message = document.querySelector("#camera-message");
    const retryButton = document.querySelector("#camera-retry");

    if (!video || !message || !retryButton) {
        return;
    }

    let activeStream;
    let scanning = false;

    function stopCamera() {
        scanning = false;
        if (activeStream) {
            activeStream.getTracks().forEach((track) => track.stop());
            activeStream = undefined;
        }
        video.srcObject = null;
    }

    function showCameraError(error) {
        stopCamera();
        if (error.name === "NotAllowedError" || error.name === "SecurityError") {
            message.textContent = "カメラの使用が許可されていません。ブラウザの権限を確認し、備品番号で検索してください。";
        } else if (error.name === "NotFoundError") {
            message.textContent = "利用できるカメラが見つかりません。備品番号で検索してください。";
        } else {
            message.textContent = "このブラウザではQR読み取りを利用できません。備品番号で検索してください。";
        }
    }

    async function scanFrame(detector) {
        if (!scanning) {
            return;
        }
        try {
            const results = await detector.detect(video);
            if (results.length) {
                const rawValue = results[0].rawValue.trim();
                if (/^[A-Z]-\d{1,8}$/.test(rawValue)) {
                    stopCamera();
                    const searchUrl = new URL(
                        document.querySelector(".equipment__manual-search").action,
                        window.location.origin,
                    );
                    searchUrl.searchParams.set("q", rawValue);
                    window.location.assign(searchUrl);
                    return;
                }

                let target;
                try {
                    target = new URL(rawValue, window.location.origin);
                } catch {
                    message.textContent = "備品番号または備品管理システムのQRコードではありません。";
                    window.requestAnimationFrame(() => scanFrame(detector));
                    return;
                }
                if (
                    target.origin === window.location.origin
                    && (
                        target.pathname.startsWith("/equipment/item/")
                        || target.pathname.startsWith("/equipment/q/")
                    )
                ) {
                    stopCamera();
                    window.location.assign(target.href);
                    return;
                }
                message.textContent = "備品番号または備品管理システムのQRコードではありません。";
            }
        } catch (error) {
            showCameraError(error);
            return;
        }
        window.requestAnimationFrame(() => scanFrame(detector));
    }

    async function startCamera() {
        stopCamera();
        if (!navigator.mediaDevices?.getUserMedia || !("BarcodeDetector" in window)) {
            message.textContent = "このブラウザはカメラQR読み取りに対応していません。備品番号で検索してください。";
            return;
        }
        try {
            const detector = new BarcodeDetector({ formats: ["qr_code"] });
            activeStream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: { facingMode: { ideal: "environment" } },
            });
            video.srcObject = activeStream;
            await video.play();
            message.textContent = "QRコードをカメラに映してください。";
            scanning = true;
            scanFrame(detector);
        } catch (error) {
            showCameraError(error);
        }
    }

    retryButton.addEventListener("click", startCamera);
    window.addEventListener("pagehide", stopCamera);
    startCamera();
})();
