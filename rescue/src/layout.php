<?php
declare(strict_types=1);

function rescue_layout(string $title, string $body): void
{
    $csrf = h($_SESSION['csrf'] ?? '');
    $logout = rescue_logged_in()
        ? "<form method=\"post\" action=\"/rescue/logout\"><input type=\"hidden\" name=\"csrf\" value=\"$csrf\"><button class=\"link\">ログアウト</button></form>"
        : '';
    echo <<<HTML
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{$title}｜rbs京都 救出画面</title>
<style>
:root { color-scheme: light dark; --accent: #620610; --line: #8884; --warn: #b45309; --ok: #15803d; --bad: #b91c1c; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.6 system-ui, "Noto Sans JP", sans-serif; }
header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .75rem 1rem; background: var(--accent); color: #fff; }
header h1 { margin: 0; font-size: 1.1rem; }
header .link { color: #fff; }
main { max-width: 56rem; margin: 0 auto; padding: 1rem; display: grid; gap: 1rem; }
section { padding: 1rem; border: 1px solid var(--line); border-radius: .5rem; }
h2 { margin: 0 0 .5rem; font-size: 1.05rem; }
p { margin: .25rem 0; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { padding: .4rem .5rem; border-top: 1px solid var(--line); text-align: left; vertical-align: top; }
input[type=text], input[type=password], select { padding: .5rem; font: inherit; border: 1px solid var(--line); border-radius: .375rem; background: transparent; color: inherit; max-width: 100%; }
button { padding: .5rem 1rem; font: inherit; border: 1px solid var(--line); border-radius: .375rem; background: transparent; color: inherit; cursor: pointer; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.danger { background: var(--bad); border-color: var(--bad); color: #fff; }
button.link { border: 0; padding: 0; text-decoration: underline; }
.row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.badge { padding: .1rem .6rem; border-radius: 999px; font-size: .8rem; font-weight: 600; color: #fff; }
.ok { background: var(--ok); } .bad { background: var(--bad); } .warn { background: var(--warn); } .neutral { background: #6b7280; }
.error { padding: .6rem .8rem; border-radius: .375rem; background: var(--bad); color: #fff; }
pre { max-height: 26rem; margin: .5rem 0 0; padding: .75rem; overflow: auto; border-radius: .375rem; background: #111827; color: #e5e7eb; font-size: .8rem; white-space: pre-wrap; word-break: break-all; }
.muted { opacity: .7; font-size: .9rem; }
</style>
</head>
<body>
<header><h1>rbs京都 救出画面</h1>{$logout}</header>
<main>
{$body}
</main>
</body>
</html>
HTML;
}

function rescue_page_login(?string $error): void
{
    $csrf = h($_SESSION['csrf'] ?? '');
    $message = $error === null ? '' : '<p class="error">' . h($error) . '</p>';
    rescue_layout('ログイン', <<<HTML
<section>
<h2>ログイン</h2>
<p class="muted">管理画面が開けなくなったときに、バックアップの復元とログの確認ができる画面です。</p>
{$message}
<form method="post" action="/rescue/" class="row">
<input type="hidden" name="csrf" value="{$csrf}">
<input type="password" name="password" autocomplete="current-password" aria-label="パスワード" required autofocus>
<button class="primary">ログイン</button>
</form>
</section>
HTML);
}

// 2026-10-25T05:35:37 → 2026-10-25 05:35
function rescue_when(mixed $iso): string
{
    return h(substr(str_replace('T', ' ', (string) $iso), 0, 16));
}

function rescue_status_badge(string $status): string
{
    $map = ['succeeded' => ['ok', '成功'], 'failed' => ['bad', '失敗'], 'running' => ['warn', '実行中'], 'queued' => ['neutral', '待機中']];
    [$class, $label] = $map[$status] ?? ['neutral', $status];
    return "<span class=\"badge $class\">" . h($label) . '</span>';
}

function rescue_page_dashboard(array $config, ?array $watch, ?string $error): void
{
    $csrf = h($_SESSION['csrf'] ?? '');
    $html = '';
    if ($error !== null) {
        $html .= '<p class="error">' . h($error) . '</p>';
    }

    if ($watch !== null) {
        $unfinished = in_array($watch['status'] ?? '', ['queued', 'running'], true);
        if ($unfinished) {
            header('Refresh: 3');
        }
        $html .= '<section><h2>実行結果 ' . rescue_status_badge((string) ($watch['status'] ?? '')) . '</h2>';
        $html .= '<p class="muted">' . h($watch['action'] ?? '') . ($unfinished ? '（3秒ごとに自動で更新します）' : '') . '</p>';
        $output = trim((string) ($watch['output'] ?? ''));
        $html .= $output === '' ? '' : '<pre>' . h($output) . '</pre>';
        $html .= '<p><a href="/rescue/">戻る</a></p></section>';
    }

    $alive = rescue_admin_alive($config);
    $html .= '<section><h2>今の状態</h2><p>管理画面（Django）：'
        . ($alive ? '<span class="badge ok">動いています</span>' : '<span class="badge bad">応答しません</span>')
        . '</p>';
    $html .= $alive ? '<p><a href="/">管理画面へ</a></p>' : '<p class="muted">下の「更新前の状態に戻す」を試してください。</p>';
    $html .= '</section>';

    $backups = rescue_backups($config);
    $preUpdate = null;
    foreach ($backups as $backup) {
        if (($backup['label'] ?? '') === 'pre-update') {
            $preUpdate = $backup;
            break;
        }
    }

    $html .= '<section><h2>更新前の状態に戻す</h2>';
    if ($preUpdate === null) {
        $html .= '<p class="muted">「更新前」のバックアップがまだありません。</p>';
    } else {
        $html .= '<p>戻す先：' . rescue_when($preUpdate['created_at'] ?? '') . ' の更新前の状態</p>'
            . '<p class="muted">管理画面の更新に失敗して動かなくなったときは、ここです。データと管理画面の版が、そのときに戻ります。それ以降に編集した内容は消えます。</p>'
            . rescue_form($csrf, 'rollback', '', '更新前に戻す', true);
    }
    $html .= '</section>';

    $html .= '<section><h2>バックアップから復元</h2>';
    if ($backups === []) {
        $html .= '<p class="muted">バックアップがありません。</p>';
    } else {
        $options = '';
        foreach ($backups as $backup) {
            $options .= '<option value="' . h($backup['id']) . '">' . rescue_when($backup['created_at'] ?? '') . '（' . h($backup['label'] ?? '') . '）</option>';
        }
        $html .= '<p class="muted">復元する前に、今の状態も自動でバックアップします。</p>'
            . rescue_form($csrf, 'restore', '<select name="backup" aria-label="バックアップ">' . $options . '</select>', '復元する', true);
    }
    $html .= '</section>';

    $html .= '<section><h2>ログを見る</h2>'
        . rescue_form(
            $csrf,
            'logs',
            '<select name="service" aria-label="どのログか"><option value="admin">admin（管理画面）</option><option value="web">web（公開サイト）</option><option value="opsd">opsd（operator）</option></select>'
            . '<select name="lines" aria-label="行数"><option value="100">直近100行</option><option value="200" selected>直近200行</option><option value="500">直近500行</option></select>',
            '表示',
            false
        )
        . '</section>';

    $html .= '<section><h2>再起動・バックアップ</h2><div class="row">'
        . rescue_form($csrf, 'restart', '<input type="hidden" name="service" value="admin">', 'admin を再起動', false)
        . rescue_form($csrf, 'restart', '<input type="hidden" name="service" value="web">', 'web を再起動', false)
        . rescue_form($csrf, 'backup', '', 'バックアップを取る', false)
        . '</div></section>';

    $recent = rescue_recent($config);
    $html .= '<section><h2>最近の操作</h2><table><tbody>';
    foreach ($recent as $item) {
        $html .= '<tr><td>' . rescue_when($item['requested_at'] ?? '') . '</td><td>' . h($item['action'] ?? '') . '</td><td>'
            . rescue_status_badge((string) ($item['status'] ?? '')) . '</td><td><a href="/rescue/?watch=' . h($item['id'] ?? '') . '">見る</a></td></tr>';
    }
    $html .= $recent === [] ? '<tr><td>まだありません。</td></tr>' : '';
    $html .= '</tbody></table></section>';

    rescue_layout('救出画面', $html);
}

function rescue_form(string $csrf, string $action, string $fields, string $label, bool $confirm): string
{
    $confirmField = $confirm
        ? '<input type="text" name="confirm" placeholder="確認のため「復元」と入力" aria-label="確認のため「復元」と入力" autocomplete="off" required>'
        : '';
    $class = $confirm ? 'danger' : '';
    return '<form method="post" action="/rescue/run" class="row">'
        . "<input type=\"hidden\" name=\"csrf\" value=\"$csrf\">"
        . '<input type="hidden" name="action" value="' . h($action) . '">'
        . $fields . $confirmField
        . "<button class=\"$class\">" . h($label) . '</button></form>';
}
