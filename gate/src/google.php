<?php
// Googleログイン（OpenID Connect の認可コードフロー）
declare(strict_types=1);

const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';
const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token';
const GOOGLE_ISSUERS = ['https://accounts.google.com', 'accounts.google.com'];
const GOOGLE_LOGIN_TIMEOUT = 600;

function google_redirect_uri(array $config): string
{
    return rtrim($config['base_url'], '/') . '/accounts/google/login/callback/';
}

function google_login_start(array $config): never
{
    gate_session_start($config);
    $state = bin2hex(random_bytes(16));
    $nonce = bin2hex(random_bytes(16));
    $_SESSION['oauth'] = ['state' => $state, 'nonce' => $nonce, 'created_at' => time()];

    $params = [
        'client_id' => $config['google_client_id'],
        'redirect_uri' => google_redirect_uri($config),
        'response_type' => 'code',
        'scope' => 'openid email',
        'state' => $state,
        'nonce' => $nonce,
        'prompt' => 'select_account',
    ];
    if ($config['allowed_domain'] !== '' && $config['allowed_domain'] !== 'gmail.com') {
        // アカウント選択画面で学校のアカウントを優先させるだけ。検証は callback で行う
        $params['hd'] = $config['allowed_domain'];
    }
    gate_redirect(GOOGLE_AUTH_URL . '?' . http_build_query($params));
}

function google_login_callback(array $config): never
{
    gate_session_start($config);
    $oauth = $_SESSION['oauth'] ?? null;
    unset($_SESSION['oauth']);

    $state = $_GET['state'] ?? null;
    if (
        !is_array($oauth)
        || !is_string($state)
        || !hash_equals($oauth['state'], $state)
        || $oauth['created_at'] + GOOGLE_LOGIN_TIMEOUT < time()
    ) {
        google_fail('ログインの有効期限が切れました。もう一度お試しください。');
    }
    if (isset($_GET['error'])) {
        google_fail('ログインがキャンセルされました。');
    }
    $code = $_GET['code'] ?? null;
    if (!is_string($code) || $code === '') {
        google_fail('ログインに失敗しました。もう一度お試しください。');
    }

    $claims = google_exchange_code($config, $code);
    if ($claims === null) {
        google_fail('Googleとの通信に失敗しました。時間をおいてもう一度お試しください。');
    }
    $error = google_validate_claims($config, $claims, $oauth['nonce']);
    if ($error !== null) {
        google_fail($error);
    }

    $next = gate_safe_next($_SESSION['login_next'] ?? '/');
    session_regenerate_id(true);
    $_SESSION = [
        'user' => [
            'email' => strtolower($claims['email']),
            'sub' => (string) $claims['sub'],
            'login_at' => time(),
        ],
    ];
    gate_redirect($next);
}

function google_fail(string $message): never
{
    $_SESSION['login_message'] = $message;
    gate_redirect('/accounts/login/');
}

function google_exchange_code(array $config, string $code): ?array
{
    $curl = curl_init(GOOGLE_TOKEN_URL);
    curl_setopt_array($curl, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => http_build_query([
            'code' => $code,
            'client_id' => $config['google_client_id'],
            'client_secret' => $config['google_client_secret'],
            'redirect_uri' => google_redirect_uri($config),
            'grant_type' => 'authorization_code',
        ]),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 10,
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
    ]);
    $body = curl_exec($curl);
    $status = curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
    curl_close($curl);
    if (!is_string($body) || $status !== 200) {
        return null;
    }

    $token = json_decode($body, true);
    $idToken = is_array($token) ? ($token['id_token'] ?? null) : null;
    if (!is_string($idToken)) {
        return null;
    }

    // IDトークンはGoogleのトークンエンドポイントからTLSで直接受け取っているので、
    // 署名検証は省略できる（OpenID Connect Core 1.0 3.1.3.7 の 6）
    $parts = explode('.', $idToken);
    if (count($parts) !== 3) {
        return null;
    }
    $payload = base64_decode(strtr($parts[1], '-_', '+/'), true);
    $claims = is_string($payload) ? json_decode($payload, true) : null;
    return is_array($claims) ? $claims : null;
}

function google_validate_claims(array $config, array $claims, string $nonce): ?string
{
    if (
        !in_array($claims['iss'] ?? null, GOOGLE_ISSUERS, true)
        || ($claims['aud'] ?? null) !== $config['google_client_id']
        || !is_int($claims['exp'] ?? null)
        || $claims['exp'] < time()
        || !is_string($claims['nonce'] ?? null)
        || !hash_equals($nonce, $claims['nonce'])
        || !is_string($claims['sub'] ?? null)
    ) {
        return 'ログインに失敗しました。もう一度お試しください。';
    }

    $email = $claims['email'] ?? null;
    if (!is_string($email) || ($claims['email_verified'] ?? false) !== true) {
        return 'メールアドレスを確認できませんでした。';
    }

    $domain = strtolower($config['allowed_domain']);
    if ($domain !== '') {
        $emailMatches = str_ends_with(strtolower($email), '@' . $domain);
        // Google Workspace のアカウントは hd でも組織を確認する（gmail.com には hd がない）
        $hostedMatches = $domain === 'gmail.com' || ($claims['hd'] ?? null) === $domain;
        if (!$emailMatches || !$hostedMatches) {
            return "権限がありません。組織管理（末尾が @{$domain}）のアカウントでログインしてください。";
        }
    }
    return null;
}
