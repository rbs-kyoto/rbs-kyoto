#!/usr/bin/env bash
# Cloudflare のメンテナンス画面を、自動でセットアップする（Docker 版の install.sh のあとに実行する）。
#
#   sudo ./setup.sh
#
# 何度実行しても壊れない。詳しい手順と、最初に1回だけ手でやること（API トークンの発行）は README.md。
set -euo pipefail
exec python3 "$(dirname "$(readlink -f "$0")")/setup.py" "$@"
