"""
scripts/verify_audit_chain.py

Stand-alone tool to verify the cryptographic audit hash chain (PRD §23.7).

Usage:
  python scripts/verify_audit_chain.py
  python scripts/verify_audit_chain.py --log-file path/to/audit.jsonl
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ajaa.obs.events import get_audit_log_path, verify_audit_chain


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AJAA Cryptographic Audit Hash Chain")
    parser.add_argument("--log-file", type=Path, default=None, help="Path to audit_events.jsonl")
    args = parser.parse_args()

    log_path = args.log_file or get_audit_log_path()
    print(f"\nVerifying AJAA Audit Chain (PRD §23.7)...")
    print(f"Log path: {log_path}")

    if not log_path.exists():
        print("  [WARN] Audit log file does not exist yet (no events recorded).")
        return 0

    valid, count, error = verify_audit_chain(log_path)
    if valid:
        print(f"  [OK] Hash chain verified successfully. {count} events validated with 0 errors.")
        return 0
    else:
        print(f"  [FAIL] Cryptographic verification failed after {count} events!")
        print(f"  Reason: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
