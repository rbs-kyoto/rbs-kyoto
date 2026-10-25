document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-ops]");
    if (!root) return;

    const statusLabel = root.querySelector("[data-ops-status]");
    const output = root.querySelector("[data-ops-output]");
    const statusUrl = (id) => root.dataset.statusUrl.replace("REQUEST_ID", id);
    const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]")?.value
        || document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1];
    const labels = { queued: "待機中…", running: "実行中…", succeeded: "成功しました", failed: "失敗しました" };
    let polling = false;

    const show = (result) => {
        statusLabel.textContent = labels[result.status] || result.status;
        output.hidden = !result.output;
        output.textContent = result.output || "";
        output.scrollTop = output.scrollHeight;
    };

    const watch = async (id) => {
        if (polling) return;
        polling = true;
        let failures = 0;
        for (;;) {
            try {
                const response = await fetch(statusUrl(id), { credentials: "same-origin", cache: "no-store" });
                if (!response.ok) throw new Error(String(response.status));
                const result = await response.json();
                failures = 0;
                show(result);
                if (result.status === "succeeded" || result.status === "failed") break;
            } catch (error) {
                // 管理画面の更新・再起動中は、この画面自体が一時的に繋がらなくなる
                failures += 1;
                statusLabel.textContent = "管理画面が入れ替わり中です。そのままお待ちください…";
                if (failures > 90) {
                    statusLabel.textContent = "管理画面に繋がりません。/rescue/ を開いてください。";
                    break;
                }
            }
            await new Promise((resolve) => window.setTimeout(resolve, 2000));
        }
        polling = false;
    };

    const run = async (action, params) => {
        statusLabel.textContent = "依頼しています…";
        output.hidden = true;
        try {
            const response = await fetch(root.dataset.runUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
                body: JSON.stringify({ action, params }),
            });
            const result = await response.json();
            if (!response.ok) {
                statusLabel.textContent = result.error || "依頼できませんでした。";
                return;
            }
            watch(result.id);
        } catch (error) {
            statusLabel.textContent = "依頼できませんでした。時間をおいてもう一度お試しください。";
        }
    };

    for (const button of root.querySelectorAll("[data-ops-action]")) {
        button.addEventListener("click", () => {
            if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
            run(button.dataset.opsAction, button.dataset.params ? JSON.parse(button.dataset.params) : {});
        });
    }

    root.querySelector("[data-ops-logs]")?.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        run("logs", { service: form.get("service"), lines: Number(form.get("lines")) });
    });
});
