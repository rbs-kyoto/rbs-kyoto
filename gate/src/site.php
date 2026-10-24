<?php
// 書き出し済みのページを返す。ファイルの置き場所の規則は publisher/pages.py と揃える。
declare(strict_types=1);

const GATE_QUERY_KEYS = ['sort', 'page', 'year'];
const GATE_EMAIL_PLACEHOLDER = '<!--RBS_GATE_EMAIL-->';
const GATE_MESSAGE_PLACEHOLDER = '<!--RBS_GATE_MESSAGE-->';

// URLのパス部分。書き出しで使う文字以外を含むもの（.. など）は null
function gate_request_path(): ?string
{
    $raw = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    if (!is_string($raw)) {
        return null;
    }
    $path = rawurldecode($raw);
    if (!preg_match('#^(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*/?$#', $path)) {
        return null;
    }
    return $path;
}

// 公開中のバージョンのディレクトリ。リクエストの途中で切り替わっても混ざらないよう最初に解決する
function gate_release_root(array $config): ?string
{
    $root = realpath($config['site_root'] . '/current');
    return ($root !== false && is_dir($root)) ? $root : null;
}

function gate_query_suffix(array $query): string
{
    $parts = [];
    foreach (GATE_QUERY_KEYS as $key) {
        $value = $query[$key] ?? null;
        if (is_string($value) && preg_match('/^[a-z0-9]{1,16}$/', $value)) {
            $parts[] = "$key-$value";
        }
    }
    return implode('/', $parts);
}

function gate_page_file(string $path, array $query): string
{
    $directory = trim($path, '/');
    $suffix = gate_query_suffix($query);
    if ($suffix !== '') {
        $directory = $directory === '' ? "_q/$suffix" : "$directory/_q/$suffix";
    }
    return $directory === '' ? 'index.html' : "$directory/index.html";
}

function gate_find(string $root, string $variant, string $path, array $query): ?string
{
    if (str_ends_with($path, '/')) {
        // ?page=99 のように書き出していないクエリはクエリなしのページにする
        $candidates = array_unique([gate_page_file($path, $query), gate_page_file($path, [])]);
    } else {
        $candidates = [ltrim($path, '/')];
    }
    foreach ($candidates as $candidate) {
        $file = "$root/$variant/$candidate";
        if (is_file($file)) {
            return $file;
        }
    }
    return null;
}

function gate_serve_path(array $config, ?string $path): never
{
    $root = gate_release_root($config);
    if ($root === null) {
        gate_unavailable();
    }
    if ($path === null) {
        gate_error_page($root, 404);
    }

    $user = gate_current_user($config);
    if (session_status() === PHP_SESSION_ACTIVE) {
        session_write_close();
    }

    if (!str_ends_with($path, '/') && !str_contains(basename($path), '.')) {
        // Django の APPEND_SLASH と同じく、末尾スラッシュ付きのページがあればそちらへ
        $slashed = $path . '/';
        if (gate_find($root, 'public', $slashed, []) !== null || gate_find($root, 'members', $slashed, []) !== null) {
            $queryString = $_SERVER['QUERY_STRING'] ?? '';
            gate_redirect($slashed . ($queryString !== '' ? "?$queryString" : ''), 301);
        }
        gate_error_page($root, 404);
    }

    if ($user !== null) {
        $file = gate_find($root, 'members', $path, $_GET) ?? gate_find($root, 'public', $path, $_GET);
    } else {
        $file = gate_find($root, 'public', $path, $_GET);
        if ($file === null && gate_find($root, 'members', $path, $_GET) !== null) {
            gate_redirect('/accounts/login/?next=' . rawurlencode($_SERVER['REQUEST_URI'] ?? $path));
        }
    }
    if ($file === null) {
        gate_error_page($root, 404);
    }

    $replacements = [];
    if ($user !== null && $path === '/accounts/mypage/') {
        $replacements[GATE_EMAIL_PLACEHOLDER] = htmlspecialchars($user['email'], ENT_QUOTES, 'UTF-8');
    }
    gate_send_file($file, $user !== null, $replacements);
}

function gate_show_login_page(array $config): never
{
    $root = gate_release_root($config);
    if ($root === null) {
        gate_unavailable();
    }

    if (gate_current_user($config) !== null) {
        gate_redirect(gate_safe_next($_GET['next'] ?? '/'));
    }

    gate_session_start($config);
    if (isset($_GET['next'])) {
        $_SESSION['login_next'] = gate_safe_next($_GET['next']);
    }
    $message = $_SESSION['login_message'] ?? '';
    unset($_SESSION['login_message']);
    session_write_close();

    $html = $message === ''
        ? ''
        : '<div class="login-error">' . htmlspecialchars($message, ENT_QUOTES, 'UTF-8') . '</div>';
    gate_send_file("$root/public/accounts/login/index.html", true, [GATE_MESSAGE_PLACEHOLDER => $html]);
}

function gate_send_file(string $file, bool $private, array $replacements = []): never
{
    $types = [
        'html' => 'text/html; charset=utf-8',
        'js' => 'application/javascript; charset=utf-8',
    ];
    $extension = strtolower(pathinfo($file, PATHINFO_EXTENSION));

    header('Content-Type: ' . ($types[$extension] ?? 'application/octet-stream'));
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Referrer-Policy: strict-origin-when-cross-origin');
    // 部員向けのページを Cloudflare などの共有キャッシュに載せない
    header('Cache-Control: ' . ($private ? 'private, no-store' : 'no-cache'));
    header('Vary: Cookie');
    if (basename($file) === 'service-worker.js') {
        header('Service-Worker-Allowed: /');
    }

    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'HEAD') {
        exit;
    }
    if ($replacements === []) {
        readfile($file);
    } else {
        echo strtr((string) file_get_contents($file), $replacements);
    }
    exit;
}

function gate_error_page(string $root, int $status): never
{
    http_response_code($status);
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-cache');
    $file = "$root/errors/$status.html";
    if (is_file($file)) {
        readfile($file);
    } else {
        echo "<h1>$status</h1>";
    }
    exit;
}

function gate_unavailable(): never
{
    http_response_code(503);
    header('Content-Type: text/plain; charset=utf-8');
    header('Retry-After: 300');
    exit("サイトはまだ公開されていません。管理画面からデプロイしてください。\n");
}
