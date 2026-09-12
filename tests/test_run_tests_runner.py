from __future__ import annotations

from types import SimpleNamespace

import pytest
import run_tests


def test_batch_runner_uses_tests_directory_and_never_reports_pytest_failure_as_pass(
    monkeypatch,
):
    calls = []

    def failed_pytest(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(
            returncode=4,
            stdout="",
            stderr="ERROR: file or directory not found: missing_test.py\n",
        )

    monkeypatch.setattr(
        run_tests,
        "BATCHES",
        [{"name": "broken batch", "files": ["missing_test.py"]}],
    )
    monkeypatch.setattr(run_tests.subprocess, "run", failed_pytest)
    monkeypatch.setattr(run_tests.sys, "argv", ["run_tests.py"])

    with pytest.raises(SystemExit) as stopped:
        run_tests.main()

    assert stopped.value.code == 1
    assert calls[0][1]["cwd"] == run_tests.TESTS_DIR
