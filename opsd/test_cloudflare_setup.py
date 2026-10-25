import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from . import cloudflare, protocol
from .daemon import Config, Job, Ops
from .fake_cloudflare import FakeCloudflare

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "setup-token-abc123"
HOST = "poc-rbs.clusters-prj.com"

spec = importlib.util.spec_from_file_location("rbs_cloudflare_setup", ROOT / "deploy" / "cloudflare" / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class FakeDocker:
    """wrangler を動かす docker run の代わり。渡された内容を、その場で記録する。"""

    def __init__(self, returncode=0, output="Deployed rbs-maintenance"):
        self.calls = []
        self.staged = {}
        self.returncode = returncode
        self.output = output

    def __call__(self, command, env=None, capture_output=True, text=True):
        self.calls.append({"command": list(command), "env": dict(env or {})})
        if command[:2] == ["docker", "run"]:
            page = Path(command[command.index("-v") + 1].split(":")[0])
            self.staged = {
                "config": json.loads((page / "public" / "config.json").read_text()),
                "wrangler": (page / "wrangler.jsonc").read_text(),
                "has_index": (page / "public" / "index.html").exists(),
            }
        return subprocess.CompletedProcess(command, self.returncode, stdout=self.output, stderr="")


class PageOpener:
    """Cloudflare の API には本物の接続、メンテナンス画面の確認には 200 を返す。"""

    def __init__(self, api_base, page_status=200):
        self.api_base = api_base
        self.page_status = page_status
        self.pages = []

    def __call__(self, request, timeout=None):
        import urllib.request

        url = request.full_url if hasattr(request, "full_url") else request
        if url.startswith(self.api_base):
            return urllib.request.urlopen(request, timeout=timeout)
        self.pages.append(url)
        if self.page_status != 200:
            raise OSError("not reachable yet")
        return _Ok()


class _Ok:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SetupTestCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.home / ".env").write_text(f"PUBLIC_HOST={HOST}\nADMIN_HOST=admin-{HOST}\n")
        self.docker = FakeDocker()
        self.make_fake()

    def make_fake(self, **kwargs):
        self.fake = FakeCloudflare(token=TOKEN, **kwargs).start()
        self.addCleanup(self.fake.stop)
        self.opener = PageOpener(self.fake.base)

    def run_setup(self, argv=(), answers=("rbs-kyoto",), page_status=200, env=None):
        self.opener.page_status = page_status
        answers = iter(answers)
        out, err = io.StringIO(), io.StringIO()
        environment = {"CF_API_TOKEN": TOKEN, "CF_API_BASE": self.fake.base, **(env or {})}
        with mock.patch.dict(os.environ, environment), redirect_stdout(out), redirect_stderr(err):
            code = setup.main(
                ["--home", str(self.home), "--no-restart", *argv],
                runner=self.docker, ask=lambda prompt: next(answers), ask_secret=lambda prompt: TOKEN,
                opener=self.opener, sleep=lambda seconds: None,
            )
        return code, out.getvalue(), err.getvalue()

    def settings(self):
        return setup.read_env_file(self.home / "cloudflare.env")


class FreshSetupTests(SetupTestCase):
    def test_a_fresh_zone_gets_the_page_a_disabled_rule_and_a_private_settings_file(self):
        code, out, err = self.run_setup()

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.fake.subdomain, "rbs-kyoto")
        self.assertEqual(self.docker.staged["config"], {"allowedHosts": [HOST]})
        self.assertTrue(self.docker.staged["has_index"])
        self.assertIn('"name": "rbs-maintenance"', self.docker.staged["wrangler"])

        [created] = self.fake.calls("POST", "/rulesets")
        rule = created[2]["rules"][0]
        self.assertEqual((rule["ref"], rule["enabled"], rule["action"]), (cloudflare.RULE_REF, False, "redirect"))
        self.assertEqual(rule["expression"], f'(http.host in {{"{HOST}"}})')

        values = self.settings()
        self.assertEqual(values["MAINTENANCE_URL"], "https://rbs-maintenance.rbs-kyoto.workers.dev/")
        self.assertEqual((values["CF_ZONE_ID"], values["CF_RULESET_ID"], values["CF_PUBLIC_HOSTS"]), ("zone1", "ruleset1", HOST))
        self.assertEqual(values["CF_RULE_ID"], self.fake.ruleset["rules"][0]["id"])
        self.assertEqual(stat.S_IMODE((self.home / "cloudflare.env").stat().st_mode), 0o600)
        self.assertFalse(self.fake.put_called)

    def test_the_token_goes_to_wrangler_only_through_the_environment(self):
        self.run_setup()
        call = self.docker.calls[0]
        self.assertNotIn(TOKEN, " ".join(call["command"]))
        self.assertEqual(call["env"]["CLOUDFLARE_API_TOKEN"], TOKEN)
        self.assertEqual(call["env"]["CLOUDFLARE_ACCOUNT_ID"], "acct1")
        self.assertIn("node:22-slim", call["command"])

    def test_the_token_is_never_printed(self):
        _, out, err = self.run_setup()
        self.assertNotIn(TOKEN, out + err)

    def test_an_existing_workers_subdomain_is_reused_without_asking(self):
        self.fake.subdomain = "already-mine"
        self.run_setup(answers=())
        self.assertEqual(self.settings()["MAINTENANCE_URL"], "https://rbs-maintenance.already-mine.workers.dev/")
        self.assertEqual(self.fake.calls("PUT", "workers/subdomain"), [])

    def test_the_page_is_checked_and_a_slow_rollout_is_only_a_warning(self):
        code, out, _ = self.run_setup(page_status=503)
        self.assertEqual(code, 0)
        self.assertIn("まだ開けませんでした", out)
        self.assertEqual(len(self.opener.pages), 5)

    def test_a_subdomain_host_finds_its_zone_and_the_page_may_serve_several_hosts(self):
        self.run_setup(["--hosts", f"{HOST},www2.clusters-prj.com"])
        self.assertEqual(self.docker.staged["config"]["allowedHosts"], [HOST, "www2.clusters-prj.com"])
        self.assertIn('"www2.clusters-prj.com"', self.fake.ruleset["rules"][0]["expression"])


class ExistingRulesTests(SetupTestCase):
    OTHER = {"id": "other", "ref": "keep-me", "action": "redirect", "enabled": True, "expression": '(http.host eq "x.clusters-prj.com")',
             "action_parameters": {"from_value": {"target_url": {"value": "https://example.com"}, "status_code": 301}}}

    def test_it_adds_one_rule_without_touching_or_replacing_the_others(self):
        self.make_fake(subdomain="s", rules=[dict(self.OTHER)])
        self.run_setup(answers=())

        rules = self.fake.ruleset["rules"]
        self.assertEqual([rule["ref"] for rule in rules], ["keep-me", cloudflare.RULE_REF])
        self.assertEqual(rules[0], self.OTHER)
        self.assertFalse(self.fake.put_called)
        self.assertEqual(self.fake.calls("POST", "/rulesets/ruleset1/rules")[0][2]["enabled"], False)

    def test_running_it_again_does_not_duplicate_the_rule_and_keeps_it_switched_on(self):
        self.make_fake(subdomain="s")
        self.run_setup(answers=())
        rule_id = self.settings()["CF_RULE_ID"]
        self.fake.ruleset["rules"][0]["enabled"] = True  # メンテナンス中に、再度セットアップしても

        self.run_setup(answers=())

        self.assertEqual(len(self.fake.ruleset["rules"]), 1)
        self.assertEqual(self.settings()["CF_RULE_ID"], rule_id)
        self.assertTrue(self.fake.ruleset["rules"][0]["enabled"])
        self.assertEqual(len(self.fake.calls("POST")), 1)

    def test_the_settings_it_writes_drive_the_operator_end_to_end(self):
        self.make_fake(subdomain="s", rules=[dict(self.OTHER)])
        self.run_setup(answers=())
        ops = Ops(Config(home=self.home), runner=lambda *a, **k: (0, ""), now=lambda: datetime(2026, 10, 26, 12, 0, 0))
        ops.recover()
        job = Job(ops, {"id": protocol.new_request_id(), "action": "maintenance_on", "params": {}, "source": "test"})

        ops.execute(job, "maintenance_on", {"message": "データを整理しています"})
        ours = next(rule for rule in self.fake.ruleset["rules"] if rule["ref"] == cloudflare.RULE_REF)
        self.assertTrue(ours["enabled"])
        self.assertIn("workers.dev", ours["action_parameters"]["from_value"]["target_url"]["expression"])

        ops.execute(job, "maintenance_off", {})
        ours = next(rule for rule in self.fake.ruleset["rules"] if rule["ref"] == cloudflare.RULE_REF)
        self.assertFalse(ours["enabled"])
        self.assertEqual(next(rule for rule in self.fake.ruleset["rules"] if rule["id"] == "other"), self.OTHER)


class FailureTests(SetupTestCase):
    def test_a_token_without_edit_permission_is_explained_and_nothing_is_saved(self):
        self.fake.deny_patch = True
        code, _, err = self.run_setup()

        self.assertEqual(code, 1)
        self.assertIn("権限", err)
        self.assertIn("Single Redirect", err)
        self.assertFalse((self.home / "cloudflare.env").exists())

    def test_a_wrong_token_is_explained(self):
        code, _, err = self.run_setup(env={"CF_API_TOKEN": "nope"})
        self.assertEqual(code, 1)
        self.assertIn("トークンが無効", err)
        self.assertEqual(self.docker.calls, [])

    def test_a_host_outside_the_tokens_zones_is_explained(self):
        code, _, err = self.run_setup(["--hosts", "poc.other-site.org"])
        self.assertEqual(code, 1)
        self.assertIn("ゾーンが、このトークンから見つかりません", err)

    def test_hosts_from_different_zones_are_refused(self):
        self.make_fake(zones={"clusters-prj.com": {"id": "z1", "account": {"id": "a"}}, "other.org": {"id": "z2", "account": {"id": "a"}}})
        code, _, err = self.run_setup(["--hosts", f"{HOST},www.other.org"])
        self.assertEqual(code, 1)
        self.assertIn("別々のゾーン", err)

    def test_a_failed_deploy_stops_before_any_rule_is_created(self):
        self.docker = FakeDocker(returncode=1, output="npm ERR! network")
        code, _, err = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("デプロイに失敗", err)
        self.assertIn("npm ERR! network", err)
        self.assertEqual(self.fake.calls("POST"), [])
        self.assertFalse((self.home / "cloudflare.env").exists())

    def test_bad_input_is_refused(self):
        self.assertEqual(self.run_setup(answers=("Bad_Name!",))[0], 1)
        self.assertEqual(self.run_setup(["--worker-name", "A b"])[0], 1)
        (self.home / ".env").write_text("")
        code, _, err = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("PUBLIC_HOST", err)

    def test_the_saved_token_is_reused_only_when_asked(self):
        self.make_fake(subdomain="s")
        self.run_setup(answers=())
        prompts = []
        out, err = io.StringIO(), io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != "CF_API_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = setup.main(["--home", str(self.home), "--no-restart", "--reuse-token"], runner=self.docker,
                              ask=lambda p: "", ask_secret=lambda p: prompts.append(p) or "", opener=self.opener, sleep=lambda s: None)
        self.assertEqual((code, prompts), (0, []))


class ScriptTests(unittest.TestCase):
    def test_the_shell_wrapper_is_valid_and_executable(self):
        wrapper = ROOT / "deploy" / "cloudflare" / "setup.sh"
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", str(wrapper)]).returncode, 0)

    def test_help_runs(self):
        completed = subprocess.run(["python3", str(ROOT / "deploy" / "cloudflare" / "setup.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--hosts", completed.stdout)


if __name__ == "__main__":
    unittest.main()
