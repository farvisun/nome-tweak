#!/usr/bin/python3
"""Install Ryoku's Bibata cursor collection without selecting a cursor theme."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desktop_studio.platform.cursors import install_archive, install_collection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use the original, checksum-verified upstream Bibata.tar.xz")
    args = parser.parse_args()
    result = install_archive(args.archive) if args.archive else install_collection()
    print(json.dumps(result, indent=2))
    print("Your selected cursor theme and size were not changed.")


if __name__ == "__main__":
    main()
