"""operator（opsd）。依頼を受けて、決まった作業だけを実行する常駐プログラム。

Django とは別プロセス（ホスト上の systemd）で動くので、Django の更新に失敗して
落ちても、救出画面からの依頼はここが受けて実行する。標準ライブラリだけで動く。

置き場所（RBS_HOME、既定 /srv/rbs）:
    repo/        GitHub のチェックアウト（ビルドの元。git pull はここだけ）
    state/data/  db.sqlite3 と media/
    state/site/  静的書き出し（releases/ と current）
    backups/     <ID>/db.sqlite3, media/, meta.json
    spool/       requests/ results/ logs/
state/ は1つのまま Django のコンテナに mount する（書き出しの画像をハードリンクにするため）。
"""

import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import autoupdate, cloudflare, maintenance, protocol

OUTPUT_LIMIT = 20000
BUILD_TIMEOUT = 1800
COMMAND_TIMEOUT = 180

# 世代の残し方（ラベルごとに新しい順で）
RETENTION = {"daily": 14, "manual": 14, "pre-update": 10, "before-restore": 10}
DEFAULT_RETENTION = 10

logger = logging.getLogger("opsd")


class OpsError(Exception):
    """利用者に見せてよいメッセージを持つ失敗。"""


@dataclass
class Config:
    home: Path
    project: str = "rbs"
    uid: "int | None" = None
    gid: "int | None" = None
    daily_backup_hour: int = 3
    health_timeout: int = 120
    # compose.yaml に重ねる追加ファイル（ポートの変更など、その環境だけの設定用）
    compose_overrides: tuple = ()

    @property
    def repo(self):
        return self.home / "repo"

    @property
    def data_dir(self):
        return self.home / "state" / "data"

    @property
    def db(self):
        return self.data_dir / "db.sqlite3"

    @property
    def media(self):
        return self.data_dir / "media"

    @property
    def backups(self):
        return self.home / "backups"

    @property
    def spool(self):
        return self.home / "spool"

    @property
    def compose_file(self):
        return self.repo / "deploy" / "docker" / "compose.yaml"

    @property
    def env_file(self):
        return self.home / ".env"

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ

        def optional_int(name):
            value = environ.get(name, "").strip()
            return int(value) if value else None

        overrides = tuple(Path(path) for path in environ.get("RBS_COMPOSE_OVERRIDES", "").split(":") if path)
        return cls(
            home=Path(environ.get("RBS_HOME", "/srv/rbs")),
            uid=optional_int("RBS_UID"),
            gid=optional_int("RBS_GID"),
            compose_overrides=overrides,
        )


def subprocess_runner(cmd, timeout, cwd=None):
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        return 124, f"{output}\n（{timeout}秒で時間切れになりました）"
    except OSError as error:
        return 127, str(error)
    return completed.returncode, completed.stdout


class Job:
    """1件の依頼の実行記録。出力を溜めながら、結果ファイルを書き換えていく。"""

    def __init__(self, ops, request):
        self.ops = ops
        self.request = request
        self.lines = []
        self.started_at = ops.now().isoformat(timespec="seconds")
        self.result_path = ops.config.spool / "results" / f"{request['id']}.json"

    def emit(self, text):
        for line in str(text).splitlines():
            self.lines.append(line)
        self.write(protocol.RUNNING)

    def write(self, status, finished=False):
        output = "\n".join(self.lines)
        if len(output) > OUTPUT_LIMIT:
            output = "…（前の部分は省略）\n" + output[-OUTPUT_LIMIT:]
        protocol.write_json_atomic(
            self.result_path,
            {
                "id": self.request["id"],
                "action": self.request["action"],
                "params": self.request["params"],
                "source": self.request.get("source", ""),
                "requested_at": self.request.get("requested_at", ""),
                "status": status,
                "started_at": self.started_at,
                "finished_at": self.ops.now().isoformat(timespec="seconds") if finished else None,
                "output": output,
            },
        )


class Ops:
    def __init__(self, config, runner=subprocess_runner, now=datetime.now, sleep=time.sleep, cloudflare_opener=None):
        self.config = config
        self.runner = runner
        self.now = now
        self.sleep = sleep
        self.cloudflare_opener = cloudflare_opener or urllib.request.urlopen
        self.restart_requested = False

    # --- 下回り -----------------------------------------------------------

    def compose(self, *args):
        c = self.config
        files = [c.compose_file, *c.compose_overrides]
        command = ["docker", "compose", "-p", c.project]
        for file in files:
            command += ["-f", str(file)]
        return [*command, "--env-file", str(c.env_file), *args]

    def sh(self, job, cmd, timeout=COMMAND_TIMEOUT, cwd=None, check=True):
        job.emit("$ " + " ".join(cmd))
        returncode, output = self.runner(cmd, timeout, cwd)
        if output.strip():
            job.emit(output.strip())
        if check and returncode != 0:
            raise OpsError(f"コマンドが失敗しました（終了コード {returncode}）: {' '.join(cmd[:3])}")
        return returncode, output

    def capture(self, cmd, cwd=None):
        returncode, output = self.runner(cmd, COMMAND_TIMEOUT, cwd)
        return output.strip() if returncode == 0 else None

    def image_id(self, image):
        return self.capture(["docker", "image", "inspect", "--format", "{{.Id}}", image])

    def git_head(self):
        return self.capture(["git", "-C", str(self.config.repo), "rev-parse", "HEAD"])

    def own(self, path):
        c = self.config
        if c.uid is None:
            return
        for directory, subdirectories, files in os.walk(path):
            for name in [".", *subdirectories, *files]:
                os.chown(Path(directory) / name, c.uid, c.gid if c.gid is not None else -1, follow_symlinks=False)

    def ensure_state_dirs(self):
        """コンテナが使うフォルダを、先に作って持ち主を合わせる。

        compose.yaml は media を web に読み取りで渡すので、無いと Docker が root 持ちで作ってしまい、
        管理画面（rbs ユーザー）が画像を保存できなくなる。
        """
        c = self.config
        for directory in (c.data_dir, c.media, c.home / "state" / "site"):
            directory.mkdir(parents=True, exist_ok=True)
            if c.uid is not None and directory.stat().st_uid != c.uid:
                os.chown(directory, c.uid, c.gid if c.gid is not None else -1)

    def wait_healthy(self, job, service):
        deadline = time.monotonic() + self.config.health_timeout
        template = "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}"
        state = ""
        while True:
            returncode, output = self.runner(["docker", "inspect", "--format", template, f"rbs-{service}"], 30, None)
            state = output.strip() if returncode == 0 else "なし"
            if state.startswith("running") and state.endswith("healthy") and "unhealthy" not in state:
                job.emit(f"{service} は正常に動いています。")
                return
            if state.startswith(("exited", "dead", "restarting", "なし")) or "unhealthy" in state:
                break
            if time.monotonic() > deadline:
                break
            self.sleep(2)
        raise OpsError(f"{service} が正常に起動しませんでした（状態: {state}）。")

    # --- バックアップ -----------------------------------------------------

    def backup(self, job, label):
        c = self.config
        if not protocol.LABEL_RE.fullmatch(label):
            raise OpsError("バックアップの名前が正しくありません。")
        moment = self.now()
        while True:
            backup_id = f"{moment:%Y%m%d-%H%M%S}-{label}"
            directory = c.backups / backup_id
            if not directory.exists():
                break
            moment += timedelta(seconds=1)

        work = c.backups / f".{backup_id}.tmp"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        try:
            if c.db.exists():
                source = sqlite3.connect(f"file:{c.db}?mode=ro", uri=True)
                target = sqlite3.connect(work / "db.sqlite3")
                try:
                    source.backup(target)
                finally:
                    target.close()
                    source.close()
            else:
                job.emit("DBがまだありません。画像だけ保存します。")
            if c.media.is_dir():
                self._link_tree(c.media, work / "media")
            protocol.write_json_atomic(
                work / "meta.json",
                {
                    "id": backup_id,
                    "label": label,
                    "created_at": moment.isoformat(timespec="seconds"),
                    "has_db": (work / "db.sqlite3").exists(),
                    "admin_image": self.image_id("rbs-admin:current"),
                    "web_image": self.image_id("rbs-web:current"),
                    "git_commit": self.git_head(),
                },
            )
            work.rename(directory)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        job.emit(f"バックアップ {backup_id} を保存しました。")
        self.prune_backups(job)
        return backup_id

    @staticmethod
    def _link_tree(source, destination):
        # 画像は後から書き換えない（新しい名前で増えるだけ）ので、ハードリンクで容量を節約する
        for directory, subdirectories, files in os.walk(source):
            target = destination / Path(directory).relative_to(source)
            target.mkdir(parents=True, exist_ok=True)
            for name in files:
                try:
                    os.link(Path(directory) / name, target / name)
                except OSError:
                    shutil.copy2(Path(directory) / name, target / name)

    def prune_backups(self, job=None):
        by_label = {}
        for meta in protocol.list_backups(self.config.backups):
            by_label.setdefault(meta["label"], []).append(meta["id"])
        for label, ids in by_label.items():
            for backup_id in ids[RETENTION.get(label, DEFAULT_RETENTION):]:
                shutil.rmtree(self.config.backups / backup_id, ignore_errors=True)
                if job is not None:
                    job.emit(f"古いバックアップ {backup_id} を削除しました。")

    # --- 復元 ---------------------------------------------------------------

    def restore_data(self, job, backup_id):
        c = self.config
        directory = c.backups / backup_id
        if not (directory / "meta.json").exists():
            raise OpsError(f"バックアップ {backup_id} が見つかりません。")
        if not (directory / "db.sqlite3").exists():
            raise OpsError("このバックアップにはDBが含まれていないので、復元できません。")

        for suffix in ("-wal", "-shm"):
            Path(f"{c.db}{suffix}").unlink(missing_ok=True)
        c.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = c.db.with_name(".db.sqlite3.restore")
        shutil.copy2(directory / "db.sqlite3", temporary)
        os.replace(temporary, c.db)

        shutil.rmtree(c.media, ignore_errors=True)
        if (directory / "media").is_dir():
            shutil.copytree(directory / "media", c.media)
        else:
            c.media.mkdir()
        self.own(c.data_dir)
        job.emit("データを戻しました。")

    def restore(self, job, backup_id):
        directory = self.config.backups / backup_id
        meta = protocol._read_json(directory / "meta.json")
        if meta is None:
            raise OpsError(f"バックアップ {backup_id} が見つかりません。")

        self.backup(job, "before-restore")
        self.sh(job, self.compose("stop", "admin"), check=False)
        self.restore_data(job, backup_id)

        image = meta.get("admin_image")
        if image and self.image_id(image):
            self.sh(job, ["docker", "tag", image, "rbs-admin:current"])
        elif image:
            job.emit("そのときの管理画面の版が残っていないので、データだけ戻して今の版のまま起動します。")
        self.sh(job, self.compose("up", "-d", "admin"), timeout=BUILD_TIMEOUT)
        self.wait_healthy(job, "admin")
        job.emit(f"{backup_id} の状態に戻しました。")

    def rollback(self, job):
        pre_updates = [meta for meta in protocol.list_backups(self.config.backups) if meta["label"] == "pre-update"]
        if not pre_updates:
            raise OpsError("「更新前」のバックアップがありません。")
        self.restore(job, pre_updates[0]["id"])

    # --- 更新 ---------------------------------------------------------------

    def update(self, job, service):
        c = self.config
        image = f"rbs-{service}"
        repo = str(c.repo)

        self.ensure_state_dirs()
        pre_update = self.backup(job, "pre-update") if service == "admin" else None
        old_commit = self.git_head()
        self.sh(job, ["git", "-C", repo, "pull", "--ff-only"], timeout=300)
        new_commit = self.git_head()
        if old_commit and new_commit and old_commit != new_commit:
            changed = self.capture(["git", "-C", repo, "diff", "--name-only", old_commit, new_commit, "--", "opsd"])
            if changed:
                self.restart_requested = True
                job.emit("operator のコードが変わったので、この作業のあとで operator を再起動します。")

        self.sh(job, ["docker", "tag", f"{image}:current", f"{image}:previous"], check=False)
        try:
            returncode, _ = self.sh(job, self.compose("build", "--pull", service), timeout=BUILD_TIMEOUT, check=False)
            if returncode != 0:
                # Docker Hub の一時的な不調などで最新のベースイメージを取れないときは、取得済みのもので作る
                job.emit("最新のベースイメージを取得できなかったので、取得済みのもので作り直します。")
                self.sh(job, self.compose("build", service), timeout=BUILD_TIMEOUT)
            if service == "admin":
                self.sh(job, self.compose("stop", "admin"), check=False)
                self.sh(
                    job,
                    self.compose("run", "--rm", "--no-deps", "admin", "python", "manage.py", "migrate", "--noinput"),
                    timeout=600,
                )
            self.sh(job, self.compose("up", "-d", service), timeout=BUILD_TIMEOUT)
            self.wait_healthy(job, service)
        except OpsError as error:
            job.emit(f"失敗しました: {error}")
            self.undo_update(job, service, pre_update, old_commit)
            raise OpsError("更新に失敗したので、元の版に戻しました。公開サイトは更新前のままです。") from error
        job.emit(f"{service} を更新しました。")

    def undo_update(self, job, service, pre_update, old_commit):
        image = f"rbs-{service}"
        job.emit("--- 元の版に戻します ---")
        try:
            if old_commit:
                self.sh(job, ["git", "-C", str(self.config.repo), "reset", "--hard", old_commit], check=False)
            if service == "admin":
                self.sh(job, self.compose("stop", "admin"), check=False)
                self.restore_data(job, pre_update)
            self.sh(job, ["docker", "tag", f"{image}:previous", f"{image}:current"])
            self.sh(job, self.compose("up", "-d", service), timeout=BUILD_TIMEOUT)
            self.wait_healthy(job, service)
        except (OpsError, OSError) as error:
            raise OpsError(
                f"更新に失敗し、元に戻すことにも失敗しました（{error}）。救出画面（/rescue/）から復元してください。"
            ) from error
        job.emit("元の版に戻しました。")

    # --- その他の操作 -------------------------------------------------------

    def restart(self, job, service):
        self.sh(job, self.compose("restart", service))
        self.wait_healthy(job, service)

    def logs(self, job, service, lines):
        if service == "opsd":
            log_file = self.config.spool / "logs" / "opsd.log"
            try:
                tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            except OSError:
                raise OpsError("operator のログがまだありません。")
            job.emit("\n".join(tail) or "（ログは空です）")
            return
        self.sh(job, self.compose("logs", "--no-color", "--tail", str(lines), service))

    # --- メンテナンス（Cloudflare） ----------------------------------------

    def maintenance_settings(self):
        return cloudflare.Settings.load(self.config.home / "cloudflare.env")

    def maintenance_sync(self, force=False):
        """予定から「いまどうあるべきか」を決めて、Cloudflare の状態と違っていれば反映する。

        戻り値: "unchanged" / "unconfigured" / "applied-on" / "applied-off"。反映に失敗したら CloudflareError。
        """
        spool = self.config.spool
        state = maintenance.State.load(spool)
        enabled, message, until = state.schedule.wanted(self.now())
        wanted = {"enabled": enabled, "message": message, "until": until}
        if not force and state.applied is not None and {key: state.applied.get(key) for key in wanted} == wanted:
            return "unchanged"

        settings = self.maintenance_settings()
        if settings is None:
            if state.configured:
                state.configured = False
                state.save(spool)
            return "unconfigured"

        state.configured = True
        try:
            settings.apply(enabled, message, until, opener=self.cloudflare_opener)
        except cloudflare.CloudflareError as error:
            state.last_error = str(error)
            retry_at = self.now() + timedelta(seconds=maintenance.RETRY_SECONDS)
            state.next_retry = retry_at.isoformat(timespec="seconds")
            state.save(spool)
            raise
        state.applied = {**wanted, "at": self.now().isoformat(timespec="seconds")}
        state.last_error = ""
        state.next_retry = ""
        state.save(spool)
        return "applied-on" if enabled else "applied-off"

    def maintenance_tick(self):
        """1秒ごとに呼ばれる。予定の時刻が来たら切り替え、失敗したら30秒おいて再試行する。"""
        state = maintenance.State.load(self.config.spool)
        if state.next_retry and self.now() < datetime.fromisoformat(state.next_retry):
            return
        try:
            self.maintenance_sync()
        except cloudflare.CloudflareError as error:
            logger.warning("maintenance sync failed: %s", error)

    def maintenance_change(self, job, schedule, source, force):
        spool = self.config.spool
        state = maintenance.State.load(spool)
        state.schedule = schedule
        state.updated_at = self.now().isoformat(timespec="seconds")
        state.updated_by = source
        state.save(spool)

        try:
            result = self.maintenance_sync(force=force)
        except cloudflare.CloudflareError as error:
            raise OpsError(f"予定は保存しましたが、Cloudflare に反映できませんでした（30秒ごとに再試行します）: {error}") from error

        if not force:
            # 予定の保存（Django の設定画面から）。いま始まった・終わったのではなく、予定を受け取っただけ
            if result == "unconfigured":
                job.emit("予定を保存しました（Cloudflare が未設定なので、画面の切り替えは行いません）。")
            else:
                active = schedule.status_at(self.now()) != maintenance.INACTIVE
                job.emit("予定を保存しました。" + ("いまメンテナンス中です。" if active else "いまは通常どおりです。"))
            return

        settings = self.maintenance_settings()
        hosts = ", ".join(settings.hosts) if settings else ""
        if result == "applied-on":
            job.emit(f"メンテナンスを始めました。{hosts} は、メンテナンス画面に切り替わります（反映に数秒かかります）。")
        elif result == "applied-off":
            job.emit(f"メンテナンスを終えました。{hosts} は、元に戻ります（反映に数秒かかります）。")
        elif result == "unconfigured":
            raise OpsError("Cloudflare が設定されていません。deploy/cloudflare の手順（setup.sh）を済ませてください。予定は保存しました。")

    # --- 依頼の処理 ---------------------------------------------------------

    def execute(self, job, action, params):
        if action == "backup":
            self.backup(job, "manual")
        elif action == "update_web":
            self.update(job, "web")
        elif action == "update_admin":
            self.update(job, "admin")
        elif action == "restart":
            self.restart(job, params["service"])
        elif action == "logs":
            self.logs(job, params["service"], params["lines"])
        elif action == "maintenance_on":
            schedule = maintenance.Schedule(mode="emergency", announcement=params["message"])
            self.maintenance_change(job, schedule, job.request.get("source", ""), force=True)
        elif action == "maintenance_off":
            self.maintenance_change(job, maintenance.Schedule(mode="off"), job.request.get("source", ""), force=True)
        elif action == "maintenance_set":
            self.maintenance_change(job, maintenance.Schedule(**params), job.request.get("source", ""), force=False)
        elif action == "autoupdate_set":
            self.autoupdate_set(job, params["enabled"], job.request.get("source", ""))
        elif action == "restore":
            self.restore(job, params["backup"])
        elif action == "rollback":
            self.rollback(job)

    def process(self, path):
        spool = self.config.spool
        request_id = path.stem
        if not protocol.REQUEST_ID_RE.fullmatch(request_id):
            path.unlink(missing_ok=True)
            return

        running = spool / "running" / path.name
        running.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(path, running)
        except OSError:
            return
        request = protocol._read_json(running) or {}
        request = {"id": request_id, "action": str(request.get("action", "")), "params": request.get("params"),
                   "source": request.get("source", ""), "requested_at": request.get("requested_at", "")}

        job = Job(self, request)
        try:
            request["params"] = protocol.validate(request["action"], request["params"])
        except ValueError as error:
            job.emit(str(error))
            job.write(protocol.FAILED, finished=True)
            running.unlink(missing_ok=True)
            return

        logger.info("start %s %s %s", request_id, request["action"], request["params"])
        job.emit(f"「{protocol.ACTIONS[request['action']]['label']}」を実行します。")
        try:
            self.execute(job, request["action"], request["params"])
        except OpsError as error:
            job.emit(str(error))
            job.write(protocol.FAILED, finished=True)
            logger.warning("failed %s: %s", request_id, error)
        except Exception as error:  # 想定外でも operator 自体は止めない
            logger.exception("unexpected error in %s", request_id)
            job.emit(f"想定外のエラーが起きました: {error}")
            job.write(protocol.FAILED, finished=True)
        else:
            job.write(protocol.SUCCEEDED, finished=True)
            logger.info("done %s", request_id)
        running.unlink(missing_ok=True)

    def process_pending(self):
        requests = self.config.spool / "requests"
        for path in sorted(requests.glob("*.json")):
            self.process(path)
            if self.restart_requested:
                return

    def recover(self):
        """前回、途中で止まった依頼を失敗にする。"""
        spool = self.config.spool
        for name in ("requests", "results", "running", "logs"):
            (spool / name).mkdir(parents=True, exist_ok=True)
        (spool / "requests").chmod(0o1777)
        for path in (spool / "running").glob("*.json"):
            path.unlink(missing_ok=True)
        for path in (spool / "results").glob("*.json"):
            result = protocol._read_json(path)
            if result and result.get("status") == protocol.RUNNING:
                result["status"] = protocol.FAILED
                result["finished_at"] = self.now().isoformat(timespec="seconds")
                result["output"] = (result.get("output") or "") + "\noperator が再起動したため、この作業は途中で止まりました。"
                protocol.write_json_atomic(path, result)

    def autoupdate_tick(self):
        """毎週日曜の4時を過ぎたら、公開サイト用サーバーの更新を1回だけ依頼する（手で押したときと同じ処理）。"""
        spool = self.config.spool
        moment = self.now()
        if not (spool / autoupdate.STATE_FILE).exists():
            # 入れた直後に、過ぎた時刻の分を実行しない
            autoupdate.State(last_slot=autoupdate.latest_slot(moment).isoformat(timespec="minutes")).save(spool)
            return
        state = autoupdate.State.load(spool)
        if not autoupdate.is_due(state, moment):
            return
        state.last_slot = autoupdate.latest_slot(moment).isoformat(timespec="minutes")
        state.last_request = protocol.submit(spool, "update_web", {}, source="auto", now=moment)
        state.save(spool)
        logger.info("auto update requested: %s", state.last_request)

    def autoupdate_set(self, job, enabled, source):
        spool = self.config.spool
        state = autoupdate.State.load(spool)
        if not (spool / autoupdate.STATE_FILE).exists():
            state.last_slot = autoupdate.latest_slot(self.now()).isoformat(timespec="minutes")
        state.enabled = enabled
        state.updated_by = source
        state.save(spool)
        job.emit("自動更新を" + ("オンにしました。毎週日曜の午前4時に、公開サイト用サーバー（Apache・PHP）を最新版にします。" if enabled else "オフにしました。"))

    def maintenance(self):
        """1日1回のバックアップと、古いイメージの掃除。"""
        moment = self.now()
        if moment.hour < self.config.daily_backup_hour or not self.config.db.exists():
            return
        today = f"{moment:%Y%m%d}"
        if any(meta["label"] == "daily" and meta["id"].startswith(today) for meta in protocol.list_backups(self.config.backups)):
            return
        job = Job(self, {"id": protocol.new_request_id(moment), "action": "backup", "params": {}, "source": "opsd",
                         "requested_at": moment.isoformat(timespec="seconds")})
        try:
            job.emit("毎日のバックアップを始めます。")
            self.backup(job, "daily")
            self.sh(job, ["docker", "image", "prune", "-f", "--filter", "until=2160h"], check=False)
        except Exception as error:
            logger.exception("daily backup failed")
            job.emit(f"失敗しました: {error}")
            job.write(protocol.FAILED, finished=True)
        else:
            job.write(protocol.SUCCEEDED, finished=True)


def forget_env_file_variables(env_file, environ=None):
    """.env に書かれた変数を、この operator の環境から消す。

    systemd の EnvironmentFile で起動時に読んだ古い値が残っていると、docker compose は
    --env-file より環境変数を優先するので、.env を書き換えても反映されなくなる。
    """
    environ = os.environ if environ is None else environ
    try:
        lines = Path(env_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    names = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name = line.split("=", 1)[0].strip()
            if environ.pop(name, None) is not None:
                names.append(name)
    return names


def main():
    # 依頼ID・バックアップ名・「毎日3時」の基準を、Django や救出画面と同じ日本時間にそろえる
    os.environ["TZ"] = os.environ.get("RBS_TZ", "Asia/Tokyo")
    time.tzset()
    config = Config.from_env()
    forget_env_file_variables(config.env_file)
    ops = Ops(config)
    ops.recover()
    handler = RotatingFileHandler(config.spool / "logs" / "opsd.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[handler, logging.StreamHandler(sys.stdout)],
    )
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    logger.info("opsd started (home=%s)", config.home)

    while not stopping:
        ops.process_pending()
        if ops.restart_requested:
            logger.info("restarting to load new code")
            return
        ops.maintenance_tick()
        ops.autoupdate_tick()
        ops.maintenance()
        time.sleep(1)
    logger.info("opsd stopped")


if __name__ == "__main__":
    main()
