from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. More aggressive backoff and longer base wait
old_call = """def _call(fn, retries=6):
    from googleapiclient.errors import HttpError
    import random
    for i in range(retries):
        try: return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                wait = (2 ** i) + random.random()
                time.sleep(wait); continue
            raise"""

new_call = """def _call(fn, retries=10):
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
content = content.replace(old_call, new_call)

path.write_text(content)
print('Successfully robustified setup_tags.py with aggressive backoff and inter-call delays')
