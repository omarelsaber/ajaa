"""
src/ajaa/bootstrap.py

First-run setup: creates all required directories OUTSIDE the repo,
validates the environment, and writes the data directory marker.

Called by:  ajaa init
Also used by: ajaa doctor (read-only probe mode)
"""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ajaa.config import _default_config_dir, _default_data_dir, _find_repo_root


@dataclass
class BootstrapCheck:
    name: str
    passed: bool
    message: str
    fix: str = ""
    critical: bool = False


@dataclass
class BootstrapResult:
    checks: list[BootstrapCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks if c.critical)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, check: BootstrapCheck) -> None:
        self.checks.append(check)


DATA_SUBDIRS = [
    "db",
    "cvs",
    "extractions",
    "artifacts",
    "browser_profiles",
    "emails",
    "backups",
    "logs",
]

CONFIG_SUBDIRS: list[str] = []


def run_checks(data_dir: Path | None = None, config_dir: Path | None = None) -> BootstrapResult:
    """
    Run all bootstrap checks. Does NOT create directories.
    Used by ajaa doctor.
    """
    result = BootstrapResult()
    data_dir = data_dir or _default_data_dir()
    config_dir = config_dir or _default_config_dir()
    repo_root = _find_repo_root()

    # ── Check 1: data_dir is outside repo ────────────────────────────────────
    if repo_root is not None:
        try:
            data_dir.resolve().relative_to(repo_root.resolve())
            # If no exception: data_dir IS inside repo — fail
            result.add(BootstrapCheck(
                name="data_dir_outside_repo",
                passed=False,
                message=f"data_dir ({data_dir}) is INSIDE the git repository ({repo_root})",
                fix="Set AJAA_DATA_DIR to a path outside the repo, then run 'ajaa init'.",
                critical=True,
            ))
        except ValueError:
            result.add(BootstrapCheck(
                name="data_dir_outside_repo",
                passed=True,
                message=f"data_dir is outside repo: {data_dir}",
            ))
    else:
        result.add(BootstrapCheck(
            name="data_dir_outside_repo",
            passed=True,
            message="Not inside a git repo — data_dir constraint not applicable.",
        ))

    # ── Check 2: data_dir exists ──────────────────────────────────────────────
    result.add(BootstrapCheck(
        name="data_dir_exists",
        passed=data_dir.exists(),
        message=f"data_dir exists: {data_dir}" if data_dir.exists() else f"data_dir missing: {data_dir}",
        fix="Run 'ajaa init' to create it.",
        critical=True,
    ))

    # ── Check 3: data subdirectories ─────────────────────────────────────────
    for subdir in DATA_SUBDIRS:
        p = data_dir / subdir
        result.add(BootstrapCheck(
            name=f"data_subdir_{subdir}",
            passed=p.exists(),
            message=f"  {subdir}/: {'OK' if p.exists() else 'MISSING'}",
            fix=f"Run 'ajaa init' to create {subdir}/.",
        ))

    # ── Check 4: Python version ───────────────────────────────────────────────
    py = sys.version_info
    py_ok = py >= (3, 12)
    result.add(BootstrapCheck(
        name="python_version",
        passed=py_ok,
        message=f"Python {py.major}.{py.minor}.{py.micro} ({'OK' if py_ok else 'requires >= 3.12'})",
        fix="Install Python 3.12+ or use 'uv python install 3.12'.",
        critical=True,
    ))

    # ── Check 5: OS keychain — API key ────────────────────────────────────────
    try:
        from ajaa.secrets.keychain import exists
        key_present = exists("agent_router_api_key")
        result.add(BootstrapCheck(
            name="api_key_in_keychain",
            passed=key_present,
            message="API key: found in Windows Credential Manager" if key_present else "API key: NOT FOUND",
            fix="Run: ajaa init --set-api-key",
            critical=True,
        ))
    except Exception as e:
        result.add(BootstrapCheck(
            name="api_key_in_keychain",
            passed=False,
            message=f"Keychain error: {e}",
            fix="Check that keyring is installed: uv sync",
            critical=True,
        ))

    # ── Check 6: Platform ─────────────────────────────────────────────────────
    os_name = platform.system()
    supported = os_name in ("Windows", "Darwin", "Linux")
    result.add(BootstrapCheck(
        name="platform",
        passed=supported,
        message=f"Platform: {os_name} {platform.release()} ({'supported' if supported else 'unsupported'})",
        fix="AJAA supports Windows, macOS, Linux.",
    ))

    return result


def init_directories(data_dir: Path | None = None, config_dir: Path | None = None) -> BootstrapResult:
    """
    Create all required directories. Called by 'ajaa init'.
    Returns a BootstrapResult reflecting the final state.
    """
    data_dir = data_dir or _default_data_dir()
    config_dir = config_dir or _default_config_dir()

    # Create directories
    for subdir in DATA_SUBDIRS:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)

    config_dir.mkdir(parents=True, exist_ok=True)

    # Write a marker file so ajaa doctor can verify the install
    marker = data_dir / ".ajaa_data_dir"
    if not marker.exists():
        marker.write_text(
            "This directory contains AJAA local data.\n"
            "Do NOT commit this directory to any git repository.\n",
            encoding="utf-8",
        )

    return run_checks(data_dir=data_dir, config_dir=config_dir)