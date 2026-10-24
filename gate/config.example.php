<?php
// config.php にコピーして値を埋める（config.php はコミットしない）
return [
    // Django の SITE_BUILD_ROOT と同じ場所（current/ と releases/ がある）
    'site_root' => '/srv/rbs-site',

    // 公開サイトのURL（末尾スラッシュなし）。Googleのリダイレクト先にも使う。
    // Google Cloud 側には <base_url>/accounts/google/login/callback/ を登録する。
    'base_url' => 'https://rbs-poc.clusters-prj.com',

    'google_client_id' => '',
    'google_client_secret' => '',

    // ログインを許可するメールのドメイン。自分のGmailで試すときは 'gmail.com'
    'allowed_domain' => 'rakunan-h.ed.jp',

    // ログインの有効期間（秒）。Djangoの既定と同じ2週間
    'session_lifetime' => 60 * 60 * 24 * 14,
];
