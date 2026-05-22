from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Update the AI Referrer JS to be even more robust
old_js = """ai_ref_js = \"\"\"function() { var r = document.referrer || ''; var s = ['perplexity.ai','chatgpt.com','chat.openai.com','gemini.google.com','copilot.microsoft.com','claude.ai','you.com','phind.com']; for (var i = 0; i < s.length; i++) { if (r.indexOf(s[i]) !== -1) return s[i]; } return ''; }\"\"\"""
new_js = """ai_ref_js = \"\"\"function() { var r = document.referrer || ''; var s = ['perplexity.ai','chatgpt.com','chat.openai.com','gemini.google.com','copilot.microsoft.com','claude.ai','you.com','phind.com','openai.com']; for (var i = 0; i < s.length; i++) { if (r.indexOf(s[i]) !== -1) return s[i]; } return ''; }\"\"\"""
content = content.replace(old_js, new_js)

# 2. Add a Custom JS variable for History New URL Fragment as a fallback
new_vars_section = """    # Custom Fallback Variables
    new_fragment_js = \"\"\"function() { return window.location.hash || ''; }\"\"\"
    ensure_variable(service, acct_id, ctr_id, ws_id, {'name': 'JS - New Fragment', 'type': 'jsm', 'parameter': [{'type': 'TEMPLATE', 'key': 'javascript', 'value': new_fragment_js}]}, existing_vars, fr)
"""
content = content.replace("    ai_ref_js = ", new_vars_section + "    ai_ref_js = ")

# 3. Update the Text Fragment trigger to use the new JS variable (more reliable than built-in in some GTM versions)
content = content.replace("{{History New URL Fragment}}", "{{JS - New Fragment}}")

path.write_text(content)
print('Successfully added JS fallback variables to setup_tags.py')
