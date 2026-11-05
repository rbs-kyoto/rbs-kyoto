(() => {
    const form = document.querySelector("[data-push-form]");
    if (!form) {
        return;
    }

    const button = form.querySelector("[data-push-toggle]");
    const status = form.querySelector("[data-push-status]");
    const publicKey = form.querySelector("[data-push-public-key]").textContent.trim();
    const subscribeUrl = form.querySelector("[data-push-subscribe-url]").textContent.trim();
    const deleteUrl = form.querySelector("[data-push-delete-url]").textContent.trim();
    const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

    function setStatus(message) {
        status.textContent = message;
    }

    function decodeApplicationServerKey(value) {
        const padded = value + "=".repeat((4 - value.length % 4) % 4);
        const decoded = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
        return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
    }

    async function sendSubscription(url, subscription) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken,
            },
            body: JSON.stringify(subscription),
        });
        if (!response.ok) {
            let message = "通知設定を保存できませんでした。";
            try {
                const result = await response.json();
                message = result.error || message;
            } catch {
                // Keep the user-facing fallback for non-JSON server errors.
            }
            throw new Error(message);
        }
    }

    async function initialize() {
        if (!("serviceWorker" in navigator)
            || !("PushManager" in window)
            || !("Notification" in window)) {
            button.disabled = true;
            setStatus("このブラウザーはPush通知に対応していません。");
            return;
        }
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        button.textContent = subscription ? "通知を停止する" : "通知を有効にする";
    }

    button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const registration = await navigator.serviceWorker.ready;
            const existing = await registration.pushManager.getSubscription();
            if (existing) {
                await sendSubscription(deleteUrl, { endpoint: existing.endpoint });
                await existing.unsubscribe();
                button.textContent = "通知を有効にする";
                setStatus("返却予定の通知を停止しました。");
                return;
            }

            const permission = await Notification.requestPermission();
            if (permission !== "granted") {
                setStatus("通知が許可されていません。ブラウザーの設定をご確認ください。");
                return;
            }
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: decodeApplicationServerKey(publicKey),
            });
            await sendSubscription(subscribeUrl, subscription.toJSON());
            button.textContent = "通知を停止する";
            setStatus("返却予定の通知を有効にしました。");
        } catch (error) {
            setStatus(error.message || "通知設定に失敗しました。");
        } finally {
            button.disabled = false;
        }
    });

    initialize().catch((error) => {
        button.disabled = true;
        setStatus(error.message || "通知設定を確認できませんでした。");
    });
})();
