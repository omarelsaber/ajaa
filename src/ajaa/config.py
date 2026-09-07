"""
src/ajaa/config.py

Layered configuration loader.

Load order (last wins):
  1. Built-in defaults (hardcoded in schema)
  2. Bundled example templates (configs/*.example.yaml) — read only, never mutated
  3. User config directory (~/.config/ajaa/ or %APPDATA%/ajaa/ on Windows)
  4. Environment variables prefixed AJAA_ (for CI / Docker overrides)

IMPORTANT: The user config directory is NEVER inside the repo working tree.
If it resolves inside the repo, startup is refused with a clear error message.

Usage:
    from ajaa.config import get_settings
    settings = get_settings()           # cached singleton
    settings.reload()                   # for tests only
"""
from __future__ import annotations

import os
import platform
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Platform-specific config directory ───────────────────────────────────────

def _default_config_dir() -> Path:
    """
    Return the platform-appropriate user config directory.
    This is always OUTSIDE the repo working tree — by construction.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / "ajaa"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ajaa"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
        return Path(xdg) / "ajaa"


def _default_data_dir() -> Path:
    """
    Return the platform-appropriate user data directory.
    This is always OUTSIDE the repo working tree — by construction.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "ajaa"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ajaa" / "data"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        return Path(xdg) / "ajaa"


# ── Sub-models ────────────────────────────────────────────────────────────────

class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    reload: bool = False


class LoggingConfig(BaseModel):
    level: str = "INFO"
    jsonl: bool = True
    redact_pii: bool = True

    @field_validator("level")
    @classmethod
    def valid_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"level must be one of {allowed}")
        return v.upper()

    @model_validator(mode="after")
    def pii_redaction_cannot_be_disabled_in_production(self) -> "LoggingConfig":
        # redact_pii=false is allowed only in tests (AJAA_TESTING=1)
        if not self.redact_pii and not os.environ.get("AJAA_TESTING"):
            raise ValueError(
                "logging.redact_pii cannot be false outside of test mode. "
                "Set AJAA_TESTING=1 only in test environments."
            )
        return self


class BackupConfig(BaseModel):
    enabled: bool = True
    retention_days: int = Field(default=14, ge=1, le=365)
    schedule: str = "0 2 * * *"


class FreshnessConfig(BaseModel):
    ttl_hours: int = Field(default=24, ge=1)
    request_timeout_s: int = Field(default=10, ge=3, le=60)


class BrowserConfig(BaseModel):
    channel: str = "chromium"
    headless: bool = False
    slow_mo_ms: int = Field(default=0, ge=0)
    process_recycle_every: int = Field(default=25, ge=5)


class EmailConfig(BaseModel):
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    dry_run_output_dir: str | None = None


# ── Safety config (hard ceiling — users may lower but not raise above limits) ─

class SafetyConfig(BaseModel):
    max_applications_per_day: int = Field(default=10, ge=1, le=15)
    max_browser_concurrency: int = Field(default=2, ge=1, le=4)
    never_auto_submit_if: list[str] = Field(default_factory=lambda: [
        "unanswered_required_questions_exist",
        "any_answer_confidence_below_type_floor",
        "cover_letter_failed_grounding",
        "consent_checkbox_present_without_prior_grant",
        "demographic_question_without_decline_option",
        "sensitive_field_required_but_not_enabled",
        "job_quarantined_for_suspected_injection",
        "calibration_not_completed",
        "connector_trust_period_not_elapsed",
    ])

    @field_validator("max_applications_per_day")
    @classmethod
    def ceiling_cannot_exceed_15(cls, v: int) -> int:
        if v > 15:
            raise ValueError(
                "safety.max_applications_per_day cannot exceed 15. "
                "This is a hard architectural ceiling, not a configurable limit. "
                "Lower it if needed; do not raise it."
            )
        return v


class OperationalConfig(BaseModel):
    max_applications_per_day: int | None = None
    min_match_score: float | None = None
    browser_concurrency: int = Field(default=1, ge=1, le=4)


class ReviewConfig(BaseModel):
    default_mode: str = "always"

    @field_validator("default_mode")
    @classmethod
    def valid_mode(cls, v: str) -> str:
        allowed = {"always", "first_n_per_connector", "above_score_threshold", "never"}
        if v not in allowed:
            raise ValueError(f"review.default_mode must be one of {allowed}")
        return v


class SensitiveFieldsConfig(BaseModel):
    allow_date_of_birth: bool = False
    allow_nationality: bool = False
    allow_national_id: bool = False
    allow_photograph: bool = False
    allow_disability_status: bool = False
    allow_ethnicity: bool = False
    allow_veteran_status: bool = False


class PolicyConfig(BaseModel):
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    operational: OperationalConfig = Field(default_factory=OperationalConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    sensitive_fields: SensitiveFieldsConfig = Field(default_factory=SensitiveFieldsConfig)


# ── Main settings ─────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AJAA_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # Paths (resolved at startup, validated to be outside repo)
    config_dir: Path = Field(default_factory=_default_config_dir)
    data_dir: Path = Field(default_factory=_default_data_dir)

    # Display
    display_name: str = "User"
    locale: str = "en-US"

    # Sub-configs
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    # Internal flags
    dry_run: bool = False
    testing: bool = False  # set by AJAA_TESTING=1

    @model_validator(mode="after")
    def validate_data_dir_outside_repo(self) -> "Settings":
        """
        HARD RULE: data_dir must not resolve inside the repo working tree.
        If it does, we refuse to start. This prevents candidate data from
        being accidentally committed to a public repository.
        """
        if self.testing:
            return self  # allow in tests

        repo_root = _find_repo_root()
        if repo_root is None:
            return self  # not in a git repo — no constraint

        try:
            self.data_dir.resolve().relative_to(repo_root.resolve())
            # If we get here, data_dir IS inside the repo — refuse to start.
            raise ValueError(
                f"\n\n"
                f"STARTUP REFUSED: data_dir resolves inside the git repository.\n"
                f"  data_dir:  {self.data_dir.resolve()}\n"
                f"  repo_root: {repo_root.resolve()}\n\n"
                f"Candidate data must NEVER be stored inside the repository working tree.\n"
                f"This prevents accidentally committing personal data to a public fork.\n\n"
                f"Fix: set AJAA_DATA_DIR to a path outside the repo, or run 'ajaa init'.\n"
            )
        except ValueError as e:
            # relative_to raises ValueError if path is NOT relative — that's good.
            # Re-raise only our custom message.
            if "STARTUP REFUSED" in str(e):
                raise
            return self  # data_dir is outside repo — OK

    @model_validator(mode="after")
    def validate_config_dir_outside_repo(self) -> "Settings":
        if self.testing:
            return self

        repo_root = _find_repo_root()
        if repo_root is None:
            return self

        try:
            self.config_dir.resolve().relative_to(repo_root.resolve())
            raise ValueError(
                f"\n\n"
                f"STARTUP REFUSED: config_dir resolves inside the git repository.\n"
                f"  config_dir: {self.config_dir.resolve()}\n"
                f"  repo_root:  {repo_root.resolve()}\n\n"
                f"User config (which may contain display_name and locale) must not be\n"
                f"inside the working tree. Run 'ajaa init' to set up correctly.\n"
            )
        except ValueError as e:
            if "STARTUP REFUSED" in str(e):
                raise
            return self


def _find_repo_root() -> Path | None:
    """Walk up from cwd to find the nearest .git directory."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning empty dict if missing."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge: override wins on conflicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(config_dir: Path | None = None) -> Settings:
    """
    Load settings from the user config directory + environment variables.
    Does NOT use lru_cache — use get_settings() for the singleton.
    """
    if config_dir is None:
        config_dir = _default_config_dir()

    # Start with empty dict (Pydantic defaults are the true baseline)
    merged: dict[str, Any] = {}

    # Load user settings.yaml if it exists
    settings_file = config_dir / "settings.yaml"
    if settings_file.exists():
        merged = _merge_dicts(merged, _load_yaml_file(settings_file))

    # Load user policy.yaml if it exists
    policy_file = config_dir / "policy.yaml"
    if policy_file.exists():
        policy_data = _load_yaml_file(policy_file)
        if policy_data:
            merged["policy"] = _merge_dicts(merged.get("policy", {}), policy_data)

    # Inject config_dir itself into merged so the validator has it
    merged["config_dir"] = str(config_dir)

    return Settings(**merged)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings singleton. Call reload_settings() to refresh."""
    return load_settings()


def reload_settings() -> Settings:
    """Invalidate cache and reload. Use in tests and after ajaa init."""
    get_settings.cache_clear()
    return get_settings()


def get_user_data_dir() -> Path:
    """Return the active user data directory outside the repo."""
    try:
        return get_settings().data_dir
    except Exception:
        return _default_data_dir()