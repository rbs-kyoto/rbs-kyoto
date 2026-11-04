(() => {
    const video = document.querySelector("#equipment-camera");
    const message = document.querySelector("#camera-message");
    const retryButton = document.querySelector("#camera-retry");

    if (!video || !message || !retryButton) {
        return;
    }

    let activeStream;
    let scanning = false;
    let barcodeDetector;
    const canvas = document.createElement("canvas");
    const canvasContext = canvas.getContext("2d", { willReadFrequently: true });

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

    function scheduleNextFrame() {
        window.setTimeout(() => scanFrame(), 150);
    }

    function findQrWithJsQr() {
        if (!video.videoWidth || !video.videoHeight || !canvasContext) {
            return null;
        }

        const scale = Math.min(1, 640 / video.videoWidth);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        canvasContext.drawImage(video, 0, 0, canvas.width, canvas.height);
        const image = canvasContext.getImageData(0, 0, canvas.width, canvas.height);
        return window.jsQR(image.data, image.width, image.height, {
            inversionAttempts: "dontInvert",
        });
    }

    function openSearchForInventoryNumber(rawValue) {
        if (!/^[A-Z]-[A-Z0-9]{1,18}$/i.test(rawValue)) {
            message.textContent = "備品番号または備品管理システムのQRコードではありません。";
            return false;
        }

        stopCamera();
        const searchUrl = new URL(
            document.querySelector(".equipment__manual-search").action,
            window.location.origin,
        );
        searchUrl.searchParams.set("q", rawValue);
        window.location.assign(searchUrl);
        return true;
    }

    function handleQrValue(rawValue) {
        const value = rawValue.trim();
        if (!value) {
            return false;
        }

        try {
            const target = new URL(value, window.location.origin);
            if (
                target.origin === window.location.origin
                && (
                    target.pathname.startsWith("/equipment/item/")
                    || target.pathname.startsWith("/equipment/q/")
                )
            ) {
                stopCamera();
                window.location.assign(target.href);
                return true;
            }
        } catch {
            // Non-URL payloads are checked as inventory numbers below.
        }
        return openSearchForInventoryNumber(value);
    }

    async function scanFrame() {
        if (!scanning) {
            return;
        }
        try {
            let rawValue;
            if (barcodeDetector) {
                try {
                    const results = await barcodeDetector.detect(video);
                    rawValue = results[0]?.rawValue;
                } catch {
                    barcodeDetector = null;
                }
            }
            if (!barcodeDetector) {
                rawValue = findQrWithJsQr()?.data;
            }
            if (rawValue && handleQrValue(rawValue)) {
                return;
            }
        } catch (error) {
            showCameraError(error);
            return;
        }
        scheduleNextFrame();
    }

    async function startCamera() {
        stopCamera();
        if (!navigator.mediaDevices?.getUserMedia || typeof window.jsQR !== "function") {
            message.textContent = "このブラウザではカメラQR読み取りを利用できません。備品番号で検索してください。";
            return;
        }
        try {
            barcodeDetector = null;
            if ("BarcodeDetector" in window) {
                try {
                    barcodeDetector = new BarcodeDetector({ formats: ["qr_code"] });
                } catch {
                    barcodeDetector = null;
                }
            }
            activeStream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: { facingMode: { ideal: "environment" } },
            });
            video.srcObject = activeStream;
            await video.play();
            message.textContent = "QRコードをカメラに映してください。";
            scanning = true;
            scanFrame();
        } catch (error) {
            showCameraError(error);
        }
    }

    retryButton.addEventListener("click", startCamera);
    window.addEventListener("pagehide", stopCamera);
    startCamera();
})();
