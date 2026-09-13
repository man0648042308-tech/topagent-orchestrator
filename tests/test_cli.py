from __future__ import annotations

import unittest

from topagent.__main__ import parser


class CliTests(unittest.TestCase):
    def test_dispatch_timeout_defaults_to_five_minutes(self):
        args = parser().parse_args(["dispatch", "agent", "task"])
        self.assertEqual(300, args.timeout_seconds)
        self.assertTrue(args.allow_paid_calls)

    def test_dispatch_timeout_can_be_raised_without_disabling_quality(self):
        args = parser().parse_args([
            "dispatch", "agent", "task", "--timeout-seconds", "900",
        ])
        self.assertEqual(900, args.timeout_seconds)
        self.assertTrue(args.allow_paid_calls)

    def test_run_step_accepts_timeout(self):
        args = parser().parse_args([
            "run-step", "run-1", "step_1", "--timeout-seconds", "600",
        ])
        self.assertEqual(600, args.timeout_seconds)


if __name__ == "__main__":
    unittest.main()
