document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-live-preview]");
    const form = root && document.getElementById(root.dataset.formId);
    if (!root || !(form instanceof HTMLFormElement)) {
        return;
    }

    const frame = root.querySelector("iframe");
    const viewport = root.querySelector("[data-live-preview-viewport]");
    const statusLabel = root.querySelector("[data-live-preview-status]");
    const locationLabel = root.querySelector("[data-live-preview-location]");
    const modeButtons = root.querySelectorAll("[data-live-preview-mode]");
    const designWidths = { pc: 1280, mobile: 390 };
    const inlineFilePrefix = "live-preview-file:";
    // 選択中の画像はアップロードせず、ここに読み込んだものをプレビューに埋め込む
    const selectedFiles = new Map();
    let mode = "pc";
    let scrollY = 0;
    let debounceTimer;
    let controller;

    const setStatus = (text, state = "") => {
        statusLabel.textContent = text;
        statusLabel.dataset.state = state;
    };

    const layoutFrame = () => {
        const designWidth = designWidths[mode];
        const scale = Math.min(1, viewport.clientWidth / designWidth);
        frame.style.width = `${designWidth}px`;
        frame.style.height = `${viewport.clientHeight / scale}px`;
        frame.style.left = `${Math.max(0, (viewport.clientWidth - designWidth * scale) / 2)}px`;
        frame.style.transform = `scale(${scale})`;
    };

    // リンクはプレビュー内では開かず、別タブのプレビューで開く
    const frameHead = '<base target="_blank">';

    const buildFormData = () => {
        const data = new FormData(form);
        for (const input of form.querySelectorAll('input[type="file"]')) {
            data.delete(input.name);
            if (selectedFiles.has(input.name)) {
                data.append("_live_preview_files", input.name);
            }
        }
        data.set("_live_preview_object_id", root.dataset.objectId);
        return data;
    };

    const refresh = async () => {
        controller?.abort();
        controller = new AbortController();
        setStatus("更新中…");
        try {
            const response = await fetch(root.dataset.url, {
                method: "POST",
                body: buildFormData(),
                credentials: "same-origin",
                signal: controller.signal,
            });
            const result = await response.json();
            if (!response.ok) {
                setStatus(result.error || "プレビューを表示できません。", "error");
                return;
            }

            let html = result.html;
            for (const [name, dataUrl] of selectedFiles) {
                html = html.replaceAll(`${inlineFilePrefix}${name}`, dataUrl);
            }
            // 差し替えるとスクロール位置が戻るので、読み込み後に元の位置へ戻す
            scrollY = frame.contentWindow?.scrollY ?? scrollY;
            frame.addEventListener("load", () => frame.contentWindow.scrollTo(0, scrollY), { once: true });
            frame.srcdoc = html.replace("</head>", `${frameHead}</head>`);
            locationLabel.textContent = result.location;
            setStatus("最新");
        } catch (error) {
            if (error.name !== "AbortError") {
                console.error("Live preview could not be updated.", error);
                setStatus("プレビューを更新できませんでした。", "error");
            }
        }
    };

    const scheduleRefresh = () => {
        window.clearTimeout(debounceTimer);
        debounceTimer = window.setTimeout(refresh, 500);
    };

    form.addEventListener("input", scheduleRefresh);
    form.addEventListener("change", scheduleRefresh);
    // CKEditor のツールバー操作は input イベントを出さないので、クリックでも更新する
    form.addEventListener("click", scheduleRefresh);

    for (const input of form.querySelectorAll('input[type="file"]')) {
        input.addEventListener("change", () => {
            const file = input.files[0];
            if (!file || !file.type.startsWith("image/")) {
                selectedFiles.delete(input.name);
                scheduleRefresh();
                return;
            }
            const reader = new FileReader();
            reader.addEventListener("load", () => {
                selectedFiles.set(input.name, reader.result);
                scheduleRefresh();
            });
            reader.readAsDataURL(file);
        });
    }

    for (const button of modeButtons) {
        button.addEventListener("click", () => {
            mode = button.dataset.livePreviewMode;
            for (const other of modeButtons) {
                other.setAttribute("aria-pressed", String(other === button));
            }
            layoutFrame();
        });
    }

    new ResizeObserver(layoutFrame).observe(viewport);
    layoutFrame();
    refresh();
});
