// お知らせ・再開予定・戻り先は、リダイレクトのURLに付いてくる（?msg=…&until=…&host=…）。
// 値は textContent だけで表示する。戻り先は config.json に書いたホストだけを許す
// （このページを経由した、ほかのサイトへの転送に使われないようにするため）。
(async () => {
    const params = new URLSearchParams(location.search);
    const show = (id, text) => {
        const element = document.getElementById(id);
        element.textContent = text;
        element.hidden = false;
        return element;
    };

    const message = (params.get("msg") || "").slice(0, 200).trim();
    const until = (params.get("until") || "").slice(0, 40).trim();
    if (message) show("notice", message);
    if (until) show("until", `再開予定：${until}`);

    let allowedHosts = [];
    try {
        const response = await fetch("config.json", { cache: "no-store" });
        allowedHosts = (await response.json()).allowedHosts || [];
    } catch (error) {
        return;
    }

    const host = (params.get("host") || "").toLowerCase();
    if (!allowedHosts.includes(host)) return;

    const target = `https://${host}/`;
    const back = show("back", "サイトを開く");
    back.href = target;
    show("auto", "このページは、1分ごとに自動で確認します。");
    // メンテナンスが終わっていれば、そのまま表示される。まだなら、また、ここに戻ってくる
    window.setTimeout(() => location.replace(target), 60000);
})();
