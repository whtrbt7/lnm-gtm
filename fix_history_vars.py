from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# Ensure all relevant History variables are enabled
old_vars = """    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'newHistoryFragment')
    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'clickUrl')"""

new_vars = """    # Enable ALL History built-in variables for robust tracking
    for h_var in ['historySource', 'newHistoryFragment', 'oldHistoryFragment', 'newHistoryState', 'oldHistoryState']:
        enable_builtin_variable(service, acct_id, ctr_id, ws_id, h_var)
    
    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'clickUrl')
    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'clickText')"""

if old_vars in content:
    content = content.replace(old_vars, new_vars)
    path.write_text(content)
    print('Successfully enabled all History variables in setup_tags.py')
else:
    print('Could not find existing variable enablement block')
