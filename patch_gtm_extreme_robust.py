from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Even more aggressive pacing and specific 429 reporting
old_call = """def _call(fn, retries=10):
    from googleapiclient.errors import HttpError
    import random
    for i in range(retries):
        try: 
            # Force a tiny sleep before EVERY call to stay under rate limits
            time.sleep(1.0 + random.random())
            return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                # Add jitter and longer base wait for 429s
                wait = (5 * (2 ** i)) + (random.random() * 5)
                print(f'  [warn] Rate limited. Waiting {wait:.1f}s (retry {i+1}/{retries})...')
                time.sleep(wait); continue
            raise"""

new_call = """def _call(fn, retries=12):
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
content = content.replace(old_call, new_call)

# 2. Add a longer pause at the end of each account
content = content.replace("time.sleep(2) # Final mandatory pause to pace rollout", "time.sleep(10) # Heavy mandatory pause between accounts")

path.write_text(content)
print('Successfully robustified setup_tags.py with EXTREME pacing')
