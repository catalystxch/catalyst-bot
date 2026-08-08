from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_code_quality_runs_on_main_and_test_branches():
    workflow = _read(".github/workflows/code-quality.yml")

    assert "branches: [main, test]" in workflow
    assert "branches: [test, master]" not in workflow


def test_code_quality_runs_python_dependency_audit():
    workflow = _read(".github/workflows/code-quality.yml")
    requirements = _read("requirements-dev.txt")

    assert "pip-audit" in requirements
    assert "python -m pip_audit" in workflow


def test_deep_security_workflow_runs_supply_chain_and_sast_scans():
    workflow_path = ROOT / ".github" / "workflows" / "security-deep-scan.yml"
    assert workflow_path.exists()

    workflow = workflow_path.read_text(encoding="utf-8")
    assert "branches: [main, test]" in workflow
    assert "cron:" in workflow
    assert "semgrep" in workflow.lower()
    assert "gitleaks" in workflow.lower()
    assert "zricethezav/gitleaks:v8.30.1" in workflow


def test_release_workflow_uses_env_for_github_ref_in_shell_steps():
    workflow = _read(".github/workflows/build-release.yml")

    shell_blocks = re.findall(
        r"\n        run: \|\n(.*?)(?=\n\n      - name:|\n\n  [A-Za-z0-9_-]+:|\Z)",
        workflow,
        flags=re.S,
    )
    unsafe = [
        block.strip().splitlines()[0].strip()
        for block in shell_blocks
        if "${{ github.ref_name }}" in block
    ]
    assert unsafe == []


def test_security_policy_names_main_as_supported_branch():
    policy = _read("SECURITY.md")

    assert "branch, `main`" in policy
    assert "branch, `master`" not in policy


def test_local_agent_artifacts_are_ignored():
    gitignore = _read(".gitignore")

    for pattern in (".playwright-cli/", "outputs/", "capture_screenshots.py"):
        assert pattern in gitignore
