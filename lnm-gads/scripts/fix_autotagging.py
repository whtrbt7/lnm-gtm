import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.client import get_client, MANAGER_CID

def fetch_enabled_client_accounts(client):
    """Return all enabled, non-manager client accounts under the MCC."""
    ga_svc = client.get_service('GoogleAdsService')
    query = """
        SELECT
            customer_client.id,
            customer_client.descriptive_name,
            customer_client.manager,
            customer_client.status
        FROM customer_client
        WHERE customer_client.level > 0
          AND customer_client.status = 'ENABLED'
    """
    accounts = []
    seen = set()
    try:
        response = ga_svc.search(customer_id=MANAGER_CID, query=query)
        for row in response:
            cc = row.customer_client
            if cc.manager or cc.id in seen:
                continue
            seen.add(cc.id)
            accounts.append({'id': str(cc.id), 'name': cc.descriptive_name})
    except Exception as e:
        print(f"Error fetching accounts: {e}")
        sys.exit(1)
    return accounts

def main():
    parser = argparse.ArgumentParser(description='Audit and enable auto-tagging on GAds accounts')
    parser.add_argument('--apply', action='store_true', help='Actually enable auto-tagging (dry-run by default)')
    args = parser.parse_args()

    print(f"Starting auto-tagging audit under MCC {MANAGER_CID}...")
    if not args.apply:
        print("DRY-RUN MODE: No changes will be made.")

    client = get_client()
    accounts = fetch_enabled_client_accounts(client)
    print(f"Found {len(accounts)} enabled client accounts.")
    for acc in accounts:
        print(f"  CID: {acc['id']} - {acc['name']}")

if __name__ == "__main__":
    main()
