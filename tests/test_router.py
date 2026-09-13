from __future__ import annotations

import unittest
from unittest.mock import patch

from router import router
from router.providers import ProviderError


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def chat(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.result


class RouterTests(unittest.TestCase):
    def tearDown(self):
        router._providers.clear()

    def test_dry_run_never_resolves_key_or_provider(self):
        with patch.object(router, "_get_provider", side_effect=AssertionError("must not call")):
            result = router.route_and_execute("general", prompt="x", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])

    def test_provider_failure_falls_back(self):
        decision = router.route_task("general")
        primary = decision["full_chain"][0]["platform"]
        fallback = decision["full_chain"][1]["platform"]

        def provider(platform):
            if platform == primary:
                return FakeProvider(error=ProviderError("primary down"))
            if platform == fallback:
                return FakeProvider(result="fallback success")
            raise AssertionError(platform)

        with patch.object(router, "_get_provider", side_effect=provider):
            result = router.route_and_execute("general", prompt="x")
        self.assertTrue(result["ok"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual("fallback success", result["response"])

    def test_unknown_task_uses_general_contract(self):
        self.assertEqual(
            router.route_task("general")["primary"],
            router.route_task("does-not-exist")["primary"],
        )


if __name__ == "__main__":
    unittest.main()
