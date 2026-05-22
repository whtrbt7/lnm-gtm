from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Update fetch_location to get gtm_lnm_acct
if 'gtm_lnm_acct' not in content:
    content = content.replace("select = 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,", 
                              "select = 'id,name,url,gtm_id,gtm_lnm_acct,gtm_account_id,gtm_container_id,")

# 2. Add token auto-selection logic
old_logic = """    with open(args.token_file or TOKEN_FILE) as f: data = json.load(f)"""

new_logic = """    # Auto-select token based on account if not provided
    token_file = args.token_file
    if not token_file:
        acct_email = str(loc.get('gtm_lnm_acct') or '').lower().strip()
        if 'analytics2' in acct_email:
            token_file = os.path.join(SCRIPT_DIR, 'token_analytics2.json')
        elif 'reports' in acct_email:
            token_file = os.path.join(SCRIPT_DIR, 'token_reports.json')
        elif 'analytics' in acct_email:
            token_file = os.path.join(SCRIPT_DIR, 'token_analytics.json')
        else:
            token_file = TOKEN_FILE # fallback to token.json

    print(f'  Using token: {os.path.basename(token_file)}')
    with open(token_file) as f: data = json.load(f)"""

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    path.write_text(content)
    print('Successfully enabled token auto-selection in setup_tags.py')
else:
    print('Could not find existing token loading block')
