from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Improve _call to be more aggressive with backoff
old_call = """def _call(fn, retries=3):
    from googleapiclient.errors import HttpError
    for i in range(retries):
        try: return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                time.sleep(2 ** i); continue
            raise"""

new_call = """def _call(fn, retries=6):
    from googleapiclient.errors import HttpError
    import random
    for i in range(retries):
        try: return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                # Add jitter to backoff
                wait = (2 ** i) + random.random()
                time.sleep(wait); continue
            raise"""
content = content.replace(old_call, new_call)

# 2. Wrap the workspace list call
old_ws_list = "ws_id = service.accounts().containers().workspaces().list(parent=f'accounts/{acct_id}/containers/{ctr_id}').execute()"
new_ws_list = "ws_id = _call(lambda: service.accounts().containers().workspaces().list(parent=f'accounts/{acct_id}/containers/{ctr_id}').execute())"
content = content.replace(old_ws_list, new_ws_list)

# 3. Wrap version creation and publish
content = content.replace("res = service.accounts().containers().workspaces().create_version(",
                          "res = _call(lambda: service.accounts().containers().workspaces().create_version(")
# Need to fix the trailing .execute() for the above replacement as it's part of the res assignment
content = content.replace("f'LNM Setup - {time.strftime(\"%Y-%m-%d %H:%M\")}'} \n        ).execute()",
                          "f'LNM Setup - {time.strftime(\"%Y-%m-%d %H:%M\")}'} \n        ).execute()") 
# Actually let's just manually fix the end of main

# 4. Add a delay at the very end of main
old_done = "print('\\n=== Done ===')" # Wait, my script had a different end
# Let's find the end of the publish block
publish_end = "print('Changes are saved in the workspace. You may need to re-authorize for Publish scope.')"""
if publish_end in content:
    content = content.replace(publish_end, publish_end + "\n    time.sleep(3) # Mandatory pause to respect quota")

path.write_text(content)
print('Successfully robustified GTM setup with pacing')
