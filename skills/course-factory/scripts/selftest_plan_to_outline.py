"""Portable self-test entrypoint; synthetic fixtures, no external course paths."""
import sys
import unittest
from test_regressions import RegressionTests

CASES = [
    "test_real_outline_generator_with_unused_component",
    "test_module_assignment_order_and_duration",
    "test_bridge_rejects_missing_module_id_section_and_disposition",
    "test_full_single_course_and_repeat_status"
]


def main():
    suite = unittest.TestSuite(RegressionTests(name) for name in CASES)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
