import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from src.core.client import get_client, MANAGER_CID
from google.api_core import protobuf_helpers

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

def get_customer_autotagging_status(client, customer_id):
    """Check if auto-tagging is enabled for a given customer ID."""
    ga_svc = client.get_service('GoogleAdsService')
    query = f"SELECT customer.id, customer.auto_tagging_enabled FROM customer WHERE customer.id = '{customer_id}'"
    try:
        response = ga_svc.search(customer_id=customer_id, query=query)
        for row in response:
            return row.customer.auto_tagging_enabled
    except Exception as e:
        print(f"  [{customer_id}] Error checking status: {e}")
    return None

def enable_autotagging(client, customer_id):
    """Enable auto-tagging for a given customer ID."""
    customer_service = client.get_service("CustomerService")
    customer_operation = client.get_type("CustomerOperation")
    customer = customer_operation.update
    customer.resource_name = customer_service.customer_path(customer_id)
    customer.auto_tagging_enabled = True
    
    client.copy_from(
        customer_operation.update_mask,
        protobuf_helpers.field_mask(None, customer._pb)
    )
    
    try:
        response = customer_service.mutate_customer(
            customer_id=customer_id, 
            operation=customer_operation
        )
        print(f"  [{customer_id}] SUCCESS: Enabled auto-tagging.")
        return True
    except Exception as e:
        print(f"  [{customer_id}] ERROR: Failed to enable auto-tagging: {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description='Audit and enable auto-tagging on GAds accounts')
    parser.add_argument('--apply', action='store_true', help='Actually enable auto-tagging (dry-run by default)')
    args = parser.parse_args()

    print(f"Starting auto-tagging audit under MCC {MANAGER_CID}...")
    if not args.apply:
        print("DRY-RUN MODE: No changes will be made.")

    client = get_client()
    accounts = fetch_enabled_client_accounts(client)
    print(f"Found {len(accounts)} enabled client accounts.\n")
    
    for acc in accounts:
        cid = acc['id']
        name = acc['name']
        status = get_customer_autotagging_status(client, cid)
        
        if status is None:
            continue
            
        status_str = "ENABLED" if status else "DISABLED"
        print(f"[{cid}] {name} - Auto-tagging: {status_str}")
        
        if not status:
            if args.apply:
                enable_autotagging(client, cid)
            else:
                print(f"  [DRY-RUN] Would enable auto-tagging for {cid}")

if __name__ == "__main__":
    main()
