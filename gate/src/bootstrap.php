<?php
declare(strict_types=1);

const GATE_SESSION_NAME = 'rbs_gate';

function gate_config(): array
{
    static $config = null;
    if ($config === null) {
        $file = __DIR__ . '/../config.php';
        if (!is_file($file)) {
            http_response_code(500);
            header('Content-Type: text/plain; charset=utf-8');
            exit("gate/config.php がありません。config.example.php をコピーして設定してください。\n");
        }
        $config = require $file;
    }
    return $config;
}

function gate_session_start(array $config): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    ini_set('session.use_strict_mode', '1');
    ini_set('session.gc_maxlifetime', (string) $config['session_lifetime']);
    session_name(GATE_SESSION_NAME);
    session_set_cookie_params([
        'lifetime' => $config['session_lifetime'],
        'path' => '/',
        'secure' => str_starts_with($config['base_url'], 'https://'),
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
}

function gate_current_user(array $config): ?array
{
    // 未ログインの訪問者にはセッションを作らない
    if (!isset($_COOKIE[GATE_SESSION_NAME])) {
        return null;
    }
    gate_session_start($config);
    $user = $_SESSION['user'] ?? null;
    if (!is_array($user)) {
        return null;
    }
    // gc_maxlifetime は確率的にしか効かないので、期限はここでも確認する
    if (($user['login_at'] ?? 0) + $config['session_lifetime'] < time()) {
        unset($_SESSION['user']);
        return null;
    }
    return $user;
}

function gate_logout(array $config): void
{
    if (!isset($_COOKIE[GATE_SESSION_NAME])) {
        return;
    }
    gate_session_start($config);
    $_SESSION = [];
    session_destroy();
    $params = session_get_cookie_params();
    setcookie(GATE_SESSION_NAME, '', [
        'expires' => time() - 3600,
        'path' => $params['path'],
        'secure' => $params['secure'],
        'httponly' => $params['httponly'],
        'samesite' => $params['samesite'],
    ]);
}

function gate_redirect(string $location, int $status = 302): never
{
    header('Location: ' . $location, true, $status);
    header('Cache-Control: no-store');
    exit;
}

// ログイン後の戻り先。サイト内のパスだけを許可する（オープンリダイレクト対策）
function gate_safe_next(mixed $next): string
{
    if (
        !is_string($next)
        || strlen($next) > 2000
        || !str_starts_with($next, '/')
        || str_starts_with($next, '//')
        || str_contains($next, '\\')
        || preg_match('/[\x00-\x1f\x7f]/', $next)
    ) {
        return '/';
    }
    return $next;
}
