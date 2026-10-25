<?php
// 救出画面。Django とは別の Apache + PHP で動くので、Django の更新に失敗して死んでも使える。
// できるのは、バックアップの復元・更新前に戻す・再起動・ログ表示・バックアップ取得だけ。
// サーバーは直接は操作せず、operator（opsd）に「依頼」を書いて頼む（opsd/protocol.py と同じ取り決め）。
declare(strict_types=1);

date_default_timezone_set(getenv('TZ') ?: 'Asia/Tokyo');

const RESCUE_SESSION = 'rbs_rescue';
const RESCUE_MAX_FAILURES = 5;
const RESCUE_LOCK_SECONDS = 600;
const RESCUE_ACTIONS = ['backup', 'restart', 'logs', 'restore', 'rollback'];
const RESCUE_ID_RE = '/^\d{14}-[0-9a-f]{8}$/';
const RESCUE_BACKUP_RE = '/^\d{8}-\d{6}-[a-z]+(?:-[a-z]+)*$/';

function h(mixed $text): string
{
    return htmlspecialchars((string) $text, ENT_QUOTES, 'UTF-8');
}

function rescue_config(): array
{
    return [
        'password_file' => getenv('RESCUE_PASSWORD_FILE') ?: '/run/rescue/password_hash',
        'spool' => rtrim(getenv('RESCUE_SPOOL') ?: '/spool', '/'),
        'backups' => rtrim(getenv('RESCUE_BACKUPS') ?: '/backups', '/'),
        'admin_health_url' => getenv('RESCUE_ADMIN_HEALTH_URL') ?: 'http://admin:8000/healthz/',
        'session_lifetime' => 3600,
    ];
}

function rescue_is_https(): bool
{
    return ($_SERVER['HTTPS'] ?? '') === 'on' || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https';
}

function rescue_session(array $config): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    ini_set('session.use_strict_mode', '1');
    session_name(RESCUE_SESSION);
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/rescue/',
        'secure' => rescue_is_https(),
        'httponly' => true,
        'samesite' => 'Strict',
    ]);
    session_start();
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
    if (isset($_SESSION['login_at']) && $_SESSION['login_at'] + $config['session_lifetime'] < time()) {
        $_SESSION = ['csrf' => $_SESSION['csrf']];
    }
}

function rescue_logged_in(): bool
{
    return isset($_SESSION['login_at']);
}

function rescue_csrf_ok(): bool
{
    $sent = $_POST['csrf'] ?? '';
    return is_string($sent) && hash_equals($_SESSION['csrf'] ?? '', $sent);
}

// --- ログイン（固定パスワード）---------------------------------------------

function rescue_throttle_file(): string
{
    return sys_get_temp_dir() . '/rbs-rescue-failures.json';
}

function rescue_recent_failures(): array
{
    $data = json_decode((string) @file_get_contents(rescue_throttle_file()), true);
    $failures = is_array($data) ? array_filter($data, 'is_int') : [];
    return array_values(array_filter($failures, fn (int $at) => $at > time() - RESCUE_LOCK_SECONDS));
}

function rescue_locked(): bool
{
    return count(rescue_recent_failures()) >= RESCUE_MAX_FAILURES;
}

function rescue_record_failure(): void
{
    $failures = rescue_recent_failures();
    $failures[] = time();
    file_put_contents(rescue_throttle_file(), json_encode($failures), LOCK_EX);
}

// 戻り値: null なら成功、文字列ならエラーメッセージ
function rescue_login(array $config, string $password): ?string
{
    if (rescue_locked()) {
        return '失敗が続いたため、しばらくログインできません。10分ほどお待ちください。';
    }
    $hash = trim((string) @file_get_contents($config['password_file']));
    if ($hash === '') {
        return '救出画面のパスワードが設定されていません。';
    }
    if ($password === '' || !password_verify($password, $hash)) {
        rescue_record_failure();
        return 'パスワードが違います。';
    }
    @unlink(rescue_throttle_file());
    session_regenerate_id(true);
    $_SESSION['login_at'] = time();
    return null;
}

// --- operator への依頼 -------------------------------------------------------

// 戻り値: [依頼ID, null] または [null, エラーメッセージ]
function rescue_submit(array $config, string $action, array $params): array
{
    if (!in_array($action, RESCUE_ACTIONS, true)) {
        return [null, '未対応の操作です。'];
    }
    $clean = [];
    if ($action === 'restart') {
        if (!in_array($params['service'] ?? null, ['admin', 'web'], true)) {
            return [null, '再起動できるのは admin と web だけです。'];
        }
        $clean = ['service' => $params['service']];
    } elseif ($action === 'logs') {
        $lines = filter_var($params['lines'] ?? 200, FILTER_VALIDATE_INT);
        if (!in_array($params['service'] ?? null, ['admin', 'web', 'opsd'], true) || $lines === false || $lines < 1 || $lines > 1000) {
            return [null, 'ログの指定が正しくありません。'];
        }
        $clean = ['service' => $params['service'], 'lines' => $lines];
    } elseif ($action === 'restore') {
        $backup = $params['backup'] ?? '';
        if (!is_string($backup) || !preg_match(RESCUE_BACKUP_RE, $backup)) {
            return [null, 'バックアップの指定が正しくありません。'];
        }
        $clean = ['backup' => $backup];
    }

    $id = date('YmdHis') . '-' . bin2hex(random_bytes(4));
    $directory = $config['spool'] . '/requests';
    $payload = json_encode([
        'id' => $id,
        'action' => $action,
        'params' => (object) $clean,
        'source' => 'rescue',
        'requested_at' => date('Y-m-d\TH:i:s'),
    ], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    $temporary = "$directory/.$id.tmp";
    if (@file_put_contents($temporary, $payload) === false) {
        return [null, '依頼を書き込めませんでした。operator との共有フォルダを確認してください。'];
    }
    chmod($temporary, 0666);
    rename($temporary, "$directory/$id.json");
    return [$id, null];
}

function rescue_read_json(string $path): ?array
{
    $data = json_decode((string) @file_get_contents($path), true);
    return is_array($data) ? $data : null;
}

function rescue_status(array $config, string $id): ?array
{
    if (!preg_match(RESCUE_ID_RE, $id)) {
        return null;
    }
    $result = rescue_read_json($config['spool'] . "/results/$id.json");
    if ($result !== null) {
        return $result;
    }
    $request = rescue_read_json($config['spool'] . "/requests/$id.json");
    return $request === null ? null : $request + ['status' => 'queued', 'output' => ''];
}

function rescue_recent(array $config, int $limit = 5): array
{
    $ids = [];
    foreach (['results', 'requests'] as $directory) {
        foreach (glob($config['spool'] . "/$directory/*.json") ?: [] as $path) {
            $ids[basename($path, '.json')] = true;
        }
    }
    $ids = array_keys($ids);
    rsort($ids);
    $recent = [];
    foreach (array_slice($ids, 0, $limit) as $id) {
        $status = rescue_status($config, (string) $id);
        if ($status !== null) {
            $recent[] = $status;
        }
    }
    return $recent;
}

function rescue_backups(array $config): array
{
    $backups = [];
    foreach (glob($config['backups'] . '/*/meta.json') ?: [] as $path) {
        $meta = rescue_read_json($path);
        $id = basename(dirname($path));
        if ($meta !== null && ($meta['id'] ?? '') === $id && preg_match(RESCUE_BACKUP_RE, $id)) {
            $backups[] = $meta;
        }
    }
    usort($backups, fn (array $a, array $b) => strcmp($b['id'], $a['id']));
    return $backups;
}

// 管理画面（Django）が応答するか
function rescue_admin_alive(array $config): bool
{
    $context = stream_context_create(['http' => ['timeout' => 2, 'ignore_errors' => true, 'header' => "Host: localhost\r\n"]]);
    $body = @file_get_contents($config['admin_health_url'], false, $context);
    $status = $http_response_header[0] ?? '';
    return $body !== false && str_contains($status, ' 200');
}
