"""Portable self-test entrypoint; synthetic fixtures, no external course paths."""
import sys
import unittest
from test_regressions import RegressionTests

CASES = [
    "test_consistency_missing_files_blocked_not_traceback",
    "test_consistency_checks_all_nested_courses",
    "test_consistency_rejects_each_time_contract",
    "test_ambiguous_versions_blocked",
    "test_ascii_quotes_ignore_quoted_durations",
    "test_manifest_accepts_complete_and_rejects_hidden_or_omitted_files"
]


def main():
    suite = unittest.TestSuite(RegressionTests(name) for name in CASES)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
