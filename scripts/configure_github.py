#!/usr/bin/python3
"""Bind this source checkout's update checker to its GitHub release repository."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desktop_studio.platform.updates import normalize_repository
from desktop_studio.core.settings import SettingsError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="GitHub owner/repository or repository URL")
    args = parser.parse_args()
    try:
        repository = normalize_repository(args.repository)
        if not repository:
            raise SettingsError("The GitHub repository cannot be empty")
        target = ROOT / "data/update-source.json"
        target.write_text(json.dumps({"version": 1, "repository": repository}, indent=2) + "\n")
        print(f"Release source configured: https://github.com/{repository}/releases")
    except SettingsError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
