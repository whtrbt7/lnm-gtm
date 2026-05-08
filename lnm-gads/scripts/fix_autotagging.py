import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.client import get_client, MANAGER_CID

def main():
    parser = argparse.ArgumentParser(description='Audit and enable auto-tagging on GAds accounts')
    parser.add_argument('--apply', action='store_true', help='Actually enable auto-tagging (dry-run by default)')
    args = parser.parse_args()

    print(f"Starting auto-tagging audit under MCC {MANAGER_CID}...")
    if not args.apply:
        print("DRY-RUN MODE: No changes will be made.")

if __name__ == "__main__":
    main()
