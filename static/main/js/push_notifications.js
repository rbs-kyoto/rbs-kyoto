(() => {
    const form = document.querySelector("[data-push-form]");
    if (!form) {
        return;
    }

    const publicKey = form.querySelector("[data-push-public-key]").textContent.trim();
    const subscribeUrl = form.querySelector("[data-push-subscribe-url]").textContent.trim();
    const preferencesUrl = form.querySelector("[data-push-preferences-url]").textContent.trim();
    const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;
    const buttons = [...form.querySelectorAll("[data-notification-type]")];
    const enabled = { equipment: false, news: false, schedule: false };
    const labels = { equipment: "返却予定", news: "新着投稿", schedule: "出欠リマインド" };
    let subscription = null;

    function setStatus(type, message) {
        form.querySelector(`[data-notification-status="${type}"]`).textContent = message;
    }

    function updateButton(type) {
        const button = form.querySelector(`[data-notification-type="${type}"]`);
        button.textContent = enabled[type]
            ? `${labels[type]}通知を無効にする`
            : `${labels[type]}通知を有効にする`;
        button.setAttribute("aria-pressed", String(enabled[type]));
    }

    function decodeApplicationServerKey(value) {
        const padded = value + "=".repeat((4 - value.length % 4) % 4);
        const decoded = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
        return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
    }

    async function readResponse(response) {
        let result = {};
        try {
            result = await response.json();
        } catch {
            // Use the status-specific fallback if the server response is not JSON.
        }
        if (!response.ok) {
            const error = new Error(result.error || "通知設定を更新できませんでした。");
            error.status = response.status;
            throw error;
        }
        return result;
    }

    async function post(url, payload) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken,
            },
            body: JSON.stringify(payload),
        });
        return readResponse(response);
    }

    async function loadPreferences() {
        if (!subscription) {
            enabled.equipment = false;
            enabled.news = false;
            enabled.schedule = false;
            buttons.forEach((button) => updateButton(button.dataset.notificationType));
            return;
        }
        const url = new URL(preferencesUrl, window.location.origin);
        url.searchParams.set("endpoint", subscription.endpoint);
        const result = await readResponse(await fetch(url, { credentials: "same-origin" }));
        enabled.equipment = Boolean(result.subscribed && result.equipment_reminders_enabled);
        enabled.news = Boolean(result.subscribed && result.news_notifications_enabled);
        enabled.schedule = Boolean(result.subscribed && result.schedule_reminders_enabled);
        buttons.forEach((button) => updateButton(button.dataset.notificationType));
    }

    async function ensureSubscription() {
        if (subscription) {
            return;
        }
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
            throw new Error("通知が許可されていません。ブラウザーの設定をご確認ください。");
        }
        const registration = await navigator.serviceWorker.ready;
        subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: decodeApplicationServerKey(publicKey),
        });
        await post(subscribeUrl, subscription.toJSON());
    }

    async function toggleNotification(type, button) {
        button.disabled = true;
        try {
            const nextEnabled = !enabled[type];
            if (nextEnabled) {
                await ensureSubscription();
            }
            await post(preferencesUrl, {
                endpoint: subscription.endpoint,
                type,
                enabled: nextEnabled,
            });
            enabled[type] = nextEnabled;
            updateButton(type);
            setStatus(
                type,
                nextEnabled
                    ? "確認通知を送信しました。"
                    : "通知を停止しました。",
            );
        } catch (error) {
            if (error.status === 410 && subscription) {
                await subscription.unsubscribe();
                subscription = null;
                enabled.equipment = false;
                enabled.news = false;
                enabled.schedule = false;
                buttons.forEach((item) => updateButton(item.dataset.notificationType));
            }
            setStatus(type, error.message || "通知設定に失敗しました。");
        } finally {
            button.disabled = false;
        }
    }

    async function initialize() {
        if (!("serviceWorker" in navigator)
            || !("PushManager" in window)
            || !("Notification" in window)) {
            buttons.forEach((button) => {
                button.disabled = true;
                setStatus(button.dataset.notificationType, "このブラウザーはPush通知に対応していません。");
            });
            return;
        }
        const registration = await navigator.serviceWorker.ready;
        subscription = await registration.pushManager.getSubscription();
        await loadPreferences();
    }

    buttons.forEach((button) => {
        const type = button.dataset.notificationType;
        button.addEventListener("click", () => toggleNotification(type, button));
        updateButton(type);
    });

    initialize().catch((error) => {
        buttons.forEach((button) => {
            setStatus(button.dataset.notificationType, error.message || "通知設定を確認できませんでした。");
        });
    });
})();
