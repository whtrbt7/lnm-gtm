from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Update _call for even more defensive pacing
old_call = """def _call(fn, retries=12):
    from googleapiclient.errors import HttpError
    import random
    for i in range(retries):
        try: 
            # Force a 2-second sleep before EVERY single API call
            time.sleep(2.0 + random.random())
            return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                # Start wait at 10s and double each time
                wait = (10 * (2 ** i)) + (random.random() * 10)
                print(f'  [warn] Quota exceeded. Pacing... {wait:.1f}s (retry {i+1}/{retries})...')
                time.sleep(wait); continue
            raise"""

new_call = """def _call(fn, retries=15):
    from googleapiclient.errors import HttpError
    import random
    for i in range(retries):
        try: 
            # Force a 3-second sleep before EVERY single API call
            time.sleep(3.0 + random.random() * 2)
            return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                # Wait longer initially, doubling up to a cap
                wait = min(300, (20 * (2 ** i)) + (random.random() * 20))
                print(f'  [warn] Quota exceeded. Pacing... {wait:.1f}s (retry {i+1}/{retries})...')
                time.sleep(wait); continue
            raise"""
content = content.replace(old_call, new_call)

# 2. Update mandatory pause between accounts
content = content.replace("time.sleep(10) # Heavy mandatory pause between accounts", "time.sleep(30) # Heavy mandatory pause between accounts")

path.write_text(content)
print('Successfully applied FINAL pacing robustification')
