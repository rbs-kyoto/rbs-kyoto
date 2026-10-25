<?php
declare(strict_types=1);

require __DIR__ . '/../src/lib.php';
require __DIR__ . '/../src/layout.php';

$config = rescue_config();
rescue_session($config);

header('X-Frame-Options: DENY');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('Cache-Control: no-store');

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/rescue/', PHP_URL_PATH) ?: '/rescue/';
$route = trim(substr($path, strlen('/rescue')), '/');
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

function rescue_redirect(string $location): never
{
    header('Location: ' . $location, true, 303);
    exit;
}

if ($route === 'logout' && $method === 'POST' && rescue_csrf_ok()) {
    $_SESSION = [];
    session_destroy();
    rescue_redirect('/rescue/');
}

if (!rescue_logged_in()) {
    $error = null;
    if ($method === 'POST' && $route === '') {
        $error = rescue_csrf_ok()
            ? rescue_login($config, (string) ($_POST['password'] ?? ''))
            : 'もう一度お試しください。';
        if ($error === null) {
            rescue_redirect('/rescue/');
        }
    }
    rescue_page_login($error);
    exit;
}

if ($route === 'run' && $method === 'POST') {
    if (!rescue_csrf_ok()) {
        rescue_redirect('/rescue/');
    }
    $action = (string) ($_POST['action'] ?? '');
    // 復元は取り返しがつかないので、「復元」と入力してもらう
    if (in_array($action, ['restore', 'rollback'], true) && trim((string) ($_POST['confirm'] ?? '')) !== '復元') {
        rescue_page_dashboard($config, null, '確認のため、入力欄に「復元」と入力してください。');
        exit;
    }
    [$id, $error] = rescue_submit($config, $action, $_POST);
    if ($error !== null) {
        rescue_page_dashboard($config, null, $error);
        exit;
    }
    rescue_redirect('/rescue/?watch=' . $id);
}

$watch = isset($_GET['watch']) && is_string($_GET['watch']) ? rescue_status($config, $_GET['watch']) : null;
rescue_page_dashboard($config, $watch, null);
