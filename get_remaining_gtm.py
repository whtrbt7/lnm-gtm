import json
from pathlib import Path

def main():
    # Load all
    with open('gtm_locations.json') as f:
        all_locs = json.load(f)
        
    # I don't have the audit results in a file, but I can re-run the logic or just use the whole list
    # and let the activation script handle idempotency.
    # To be safe and thorough, let's just use the whole list but add a retry for 429s.
    
    with open('remaining_gtm.json', 'w') as f:
        json.dump(all_locs, f, indent=2)

if __name__ == '__main__':
    main()
