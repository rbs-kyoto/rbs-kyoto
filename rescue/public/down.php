<?php
// Django に繋がらないときの案内。Apache の ErrorDocument から呼ばれる。
//
// Apache が 502/504 を返すと、Cloudflare は中身を捨てて自社のエラー画面に差し替えてしまう。
// 503 ならそのまま通るので、どの失敗でも 503 に統一して、この案内を届ける。
declare(strict_types=1);

http_response_code(503);
header('Content-Type: text/html; charset=utf-8');
header('Retry-After: 30');
header('Cache-Control: no-store');
readfile(__DIR__ . '/down.html');
