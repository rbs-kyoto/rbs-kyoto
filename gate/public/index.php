<?php
// 公開サイトの入口。Apache の DocumentRoot はこのディレクトリだけにする。
// /static/ と /media/ は Apache が直接返し、それ以外はすべてここに来る。
declare(strict_types=1);

require __DIR__ . '/../src/bootstrap.php';
require __DIR__ . '/../src/site.php';
require __DIR__ . '/../src/google.php';

// コンテナの健康チェック用。設定やログイン状態には触れない
if (parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) === '/healthz') {
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    exit('ok');
}

$config = gate_config();
$path = gate_request_path();

switch ($path) {
    case '/accounts/login/':
        gate_show_login_page($config);
        break;
    case '/accounts/logout/':
        gate_logout($config);
        gate_redirect('/');
        break;
    case '/accounts/google/login/':
        google_login_start($config);
        break;
    case '/accounts/google/login/callback/':
        google_login_callback($config);
        break;
    default:
        gate_serve_path($config, $path);
}
