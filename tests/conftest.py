"""Keep the platform test suite usable without optional research packages."""

from importlib.util import find_spec

RESEARCH_TESTS = [
    "test_exp_a.py", "test_exp_b.py", "test_features.py", "test_features_v2.py",
    "test_metrics.py", "test_replay.py", "test_splits.py",
]

collect_ignore = RESEARCH_TESTS if find_spec("numpy") is None or find_spec("pandas") is None else []
if find_spec("lightgbm") is None:
    collect_ignore.extend(["test_exp_a.py", "test_exp_b.py"])
