from django.contrib.auth import get_user_model
from django.test import TestCase

from .checker import run_deterministic_check
from .models import GucchiJob, Script
from .worker import claim_next_job, process_job, run_next_job


class DeterministicCheckerTests(TestCase):
    def test_character_count_and_reading_time(self):
        result = run_deterministic_check("放送部です。")

        self.assertEqual(result["character_count"], 6)
        self.assertEqual(
            result["reading_seconds"],
            {"min": 1, "median": 1, "max": 1},
        )

    def test_target_seconds_reports_too_long(self):
        result = run_deterministic_check("放送部の原稿です。" * 20, target_seconds=30)

        finding = next(
            item for item in result["findings"] if item["code"] == "target_length"
        )
        self.assertIn("長い", finding["message"])

    def test_long_sentence_is_detected(self):
        result = run_deterministic_check("あ" * 61 + "。")

        self.assertTrue(
            any(item["code"] == "long_sentence" for item in result["findings"])
        )

    def test_invalid_date_is_detected(self):
        result = run_deterministic_check("2026年2月29日")

        self.assertTrue(
            any(item["code"] == "invalid_date" for item in result["findings"])
        )

    def test_weekday_mismatch_is_detected(self):
        result = run_deterministic_check("2026年11月19日水曜日")

        self.assertTrue(
            any(item["code"] == "weekday_mismatch" for item in result["findings"])
        )

    def test_number_reading_is_marked(self):
        result = run_deterministic_check("午後3時から5人で開始します。")

        self.assertTrue(
            any(item["code"] == "number_reading" for item in result["findings"])
        )


class GucchiJobTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="member")
        self.script = Script.objects.create(
            owner=self.user,
            source_text="放送部です。",
        )

    def test_worker_processes_deterministic_job(self):
        job = GucchiJob.objects.create(
            owner=self.user,
            script=self.script,
            kind=GucchiJob.Kind.DETERMINISTIC_CHECK,
            payload={"text": "放送部です。", "target_seconds": 10},
        )

        processed = run_next_job()

        self.assertEqual(processed.pk, job.pk)
        self.assertEqual(processed.status, GucchiJob.Status.SUCCEEDED)
        self.assertEqual(processed.result["character_count"], 6)

    def test_only_one_job_can_run(self):
        first = GucchiJob.objects.create(
            owner=self.user,
            script=self.script,
            kind=GucchiJob.Kind.DETERMINISTIC_CHECK,
        )
        GucchiJob.objects.create(
            owner=self.user,
            script=self.script,
            kind=GucchiJob.Kind.DETERMINISTIC_CHECK,
        )
        self.assertEqual(claim_next_job(), first)
        self.assertIsNone(claim_next_job())

    def test_failed_job_records_error(self):
        job = GucchiJob(
            owner=self.user,
            kind="unsupported",
        )
        job.save(force_insert=True)

        self.assertFalse(process_job(job))
        job.refresh_from_db()
        self.assertEqual(job.status, GucchiJob.Status.FAILED)
        self.assertIn("未対応", job.error)
