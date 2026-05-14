"""
Fetch CallRail recordings, transcribe with faster-whisper, auto-qualify, store in DB.

Usage:
  python transcribe_calls.py --account-id ACC123 [--days-back 30] [--model tiny.en]
  python transcribe_calls.py --account-id ACC123 --days-back 1   # daily run

Env:
  CALLRAIL_API_KEY  SUPABASE_URL  SUPABASE_KEY

Speaker separation (stereo recordings):
  Requires ffmpeg: brew install ffmpeg
  When stereo, left channel = shop employee, right channel = customer.
  Only customer channel keywords are scored. Falls back to mono if ffmpeg absent.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta

import requests

CALLRAIL_KEY  = os.environ.get('CALLRAIL_API_KEY', '36497188d7030dbe692425202acf5a63')
CALLRAIL_BASE = 'https://api.callrail.com/v3'
CR_HEADERS    = {'Authorization': f'Token token={CALLRAIL_KEY}'}

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
SB_HEADERS   = {
    'apikey':        SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type':  'application/json',
    'Prefer':        'return=representation',
}

def _find_bin(name):
    found = shutil.which(name)
    if found:
        return found
    for p in ('/opt/homebrew/bin', '/usr/local/bin'):
        candidate = os.path.join(p, name)
        if os.path.isfile(candidate):
            return candidate
    return None

FFMPEG  = _find_bin('ffmpeg')
FFPROBE = _find_bin('ffprobe')

# ── Shop employee sentence filters ───────────────────────────────────────────
# Sentences starting with or containing these phrases are likely shop-side speech

SHOP_PREFIXES = [
    # Greetings / openers
    'thank you for calling', 'thanks for calling', 'thank you for holding',
    'thanks for holding', 'thank you for your patience',
    'this is ', 'my name is ', "you've reached", 'you have reached',
    'how can i help', 'how can i assist', 'what can i do for you',
    'how may i help', 'how may i assist',
    'good morning', 'good afternoon', 'good evening',
    # Diagnostic / intake questions
    'what seems to be', "what's going on with", 'what is going on with',
    'what year is', 'what year make', 'what make and model',
    'how many miles', 'what is the mileage', "what's the mileage",
    'when did you', 'how long has it', 'has it been',
    'can you describe', 'can you tell me more',
    'is it making', 'does it make', 'is the check engine',
    # Filler acknowledgments (short standalone sentences)
    # handled separately by length check below
    # Scheduling confirmations
    'i have you down', 'i have you scheduled', "i'll put you down",
    "we'll see you", 'your appointment is', 'we have you',
    'let me get you', 'let me set you', 'let me schedule',
    'i can get you in', 'we can get you in',
    # Closings
    'see you then', 'see you at', 'see you on',
    'we look forward', 'have a great', 'have a good',
    'thanks again', 'thank you again', 'take care',
    'is there anything else', 'anything else i can',
    'drive safe', 'sounds good',
    # Shop info
    'we are located', "we're located", 'our address',
    'our hours', 'we open', 'we close', 'we are open',
    "we're open", 'our phone number',
    # Workflow
    'let me check', 'let me look', 'let me pull up',
    'one moment', 'one second', 'bear with me', 'bear with us',
    'we can do that', 'we can get that', "we'll get that",
    'absolutely', 'of course', 'sure thing', 'no problem',
    'not a problem', 'certainly',
]

# Very short responses that are almost always shop acknowledgments
SHOP_FILLERS = {
    'sure', 'okay', 'ok', 'right', 'yep', 'yup', 'yeah', 'yes',
    'alright', 'alrighty', 'perfect', 'great', 'awesome', 'got it',
    'gotcha', 'understood', 'mm-hmm', 'uh-huh', 'i see', 'i understand',
}

def filter_shop_lines(text):
    """Remove sentences that are likely shop employee speech."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    customer_sentences = []
    for s in sentences:
        low = s.lower().strip().rstrip('.,!?')
        # Drop pure filler words
        if low in SHOP_FILLERS:
            continue
        # Drop sentences starting with or containing shop patterns
        if any(low.startswith(p) or (len(p) > 14 and p in low) for p in SHOP_PREFIXES):
            continue
        customer_sentences.append(s)
    return ' '.join(customer_sentences)


# ── Keyword lists ─────────────────────────────────────────────────────────────

LEAD_KEYWORDS = [
    'appointment', 'schedule', 'book', 'estimate', 'quote', 'bring in',
    'drop off', 'drop it off', 'how much', 'price', 'cost', 'available',
    'service', 'repair', 'diagnose', 'check out', 'look at', 'oil change',
    'when can', 'earliest', 'opening', 'slot', 'take it in',
]

DISQUALIFY_KEYWORDS = [
    'wrong number', 'not interested', 'soliciting', 'job application',
    'hiring', 'employment', 'sell my', 'marketing company', 'spam',
    'recruiting', 'extended warranty', 'lower your rate', 'lower your interest',
    'press 1', 'press one', 'robocall', 'debt collection', 'collections',
    'insurance claim', 'total loss', 'no fault', 'body shop', 'collision center',
    'credit card', 'loan', 'solar', 'yelp advertising', 'google advertising',
    'sales representative', 'sales rep', 'i am calling to offer', "i'm calling to offer",
    'on behalf of', 'i represent', 'reaching out to offer', 'business solution',
    'marketing services', 'seo services', 'web design', 'we provide',
]

TOW_KEYWORDS = [
    'tow', 'towing', 'towed', 'flatbed', 'roadside', 'breakdown',
    'broke down', 'stranded', "won't start", 'dead battery', 'flat tire',
    'accident', 'just towed', 'being towed', "on its way", 'leaving it tonight',
]

# Phrases that identify shop employee speech — used to detect which stereo channel is shop
SHOP_GREETING_PATTERNS = [
    'thank you for calling', 'thanks for calling', 'this is', 'how can i help',
    'how can i assist', 'good morning', 'good afternoon', 'good evening',
    'auto repair', 'service center', 'auto service', 'garage',
]

AUTO_QUALIFY_THRESHOLD = 2      # net score for repeat callers
NEW_CALLER_THRESHOLD   = 1      # net score for first-time callers (lower bar)

# ── Repair category detection ─────────────────────────────────────────────────
# Ordered by specificity — longer phrases first within each category.
# extract_repair_category() returns all matching category keys.

REPAIR_CATEGORIES: dict[str, list[str]] = {
    'check_engine':       ['check engine', 'engine light', 'engine check', 'warning light', 'cel'],
    'oil_change':         ['oil change', 'oil filter', 'lube job'],
    'brakes':             ['rack and pinion', 'brake pad', 'brake rotor', 'brake check', 'abs light', 'brake', 'rotor', 'brakes'],
    'suspension':         ['rack and pinion', 'control arm', 'ball joint', 'tie rod', 'suspension', 'shocks', 'struts', 'alignment', 'steering', 'vibration', 'wobble', 'pulling'],
    'transmission':       ['torque converter', 'transmission', 'gearbox', 'shifting', 'clutch'],
    'battery_electrical': ["won't start", 'dead battery', 'alternator', 'starter', 'battery', 'electrical'],
    'cooling':            ['head gasket', 'water pump', 'antifreeze', 'overheating', 'coolant', 'radiator', 'thermostat'],
    'ac_heat':            ['air conditioning', 'air conditioner', 'hvac', 'blower', 'climate', 'heater', 'heat', 'ac'],
    'exhaust':            ['catalytic converter', 'cat converter', 'exhaust', 'muffler', 'resonator'],
    'engine':             ['head gasket', 'timing belt', 'timing chain', 'misfire', 'knocking', 'engine'],
    'tires':              ['flat tire', 'blowout', 'rotation', 'balance', 'tires', 'tire'],
    'diagnostic':         ['diagnostic', 'inspection'],
}

def extract_repair_category(text: str) -> list[str]:
    """Return list of matched repair category keys from transcript text."""
    low = text.lower()
    matched: list[str] = []
    seen: set[str] = set()
    for category, keywords in REPAIR_CATEGORIES.items():
        if category in seen:
            continue
        if any(_kw_match(kw, low) for kw in keywords):
            matched.append(category)
            seen.add(category)
    return matched


# ── Keyword scoring ───────────────────────────────────────────────────────────

def _kw_match(kw, text):
    """Whole-word match so 'tow' doesn't hit 'downtown'."""
    return bool(re.search(r'(?<![\w])' + re.escape(kw) + r'(?![\w])', text))

def score_transcript(text, is_new_caller=False):
    low = text.lower()
    lead_hits       = [kw for kw in LEAD_KEYWORDS       if _kw_match(kw, low)]
    disqualify_hits = [kw for kw in DISQUALIFY_KEYWORDS if _kw_match(kw, low)]
    tow_hit         = any(_kw_match(kw, low) for kw in TOW_KEYWORDS)
    tow_hits        = [kw for kw in TOW_KEYWORDS        if _kw_match(kw, low)]

    net_score = len(lead_hits) - 2 * len(disqualify_hits)
    if tow_hit:
        net_score += 2  # tow calls weighted heavier

    threshold = NEW_CALLER_THRESHOLD if is_new_caller else AUTO_QUALIFY_THRESHOLD

    qualified = None
    if disqualify_hits and not lead_hits and not tow_hit:
        qualified = False
    elif net_score >= threshold or tow_hit:
        qualified = True
    # else leave None (short/ambiguous call)

    return {
        'lead_keywords':       lead_hits + tow_hits,
        'disqualify_keywords': disqualify_hits,
        'tow_call':            tow_hit,
        'lead_score':          net_score,
        'qualified':           qualified,
    }


def extract_key_sentence(text, keywords):
    """Return sentence(s) with highest keyword density for the note excerpt."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not keywords:
        return text[:200].strip()
    def density(s):
        sl = s.lower()
        return sum(1 for kw in keywords if kw in sl)
    ranked = sorted(sentences, key=density, reverse=True)
    best = ranked[0] if ranked else ''
    return best[:300].strip()


REPAIR_LABELS = {
    'check_engine': 'Check Engine', 'oil_change': 'Oil Change', 'brakes': 'Brakes',
    'suspension': 'Suspension', 'transmission': 'Transmission',
    'battery_electrical': 'Battery/Electrical', 'cooling': 'Cooling',
    'ac_heat': 'AC/Heat', 'exhaust': 'Exhaust', 'engine': 'Engine',
    'tires': 'Tires', 'diagnostic': 'Diagnostic',
}

def build_note(transcript, score_result, duration_sec, caller_number, direction,
               is_new_caller=False, speaker_separated=False, repair_cats=None):
    qual = score_result['qualified']
    status = 'QUALIFIED' if qual is True else ('NOT QUALIFIED' if qual is False else 'UNSCORED')
    score  = score_result['lead_score']
    repair_str = ', '.join(REPAIR_LABELS.get(c, c) for c in (repair_cats or [])) or 'Unknown'
    duration   = f"{duration_sec // 60}m{duration_sec % 60}s" if duration_sec else '?'

    flags = []
    if score_result['tow_call']:
        flags.append('Tow')
    if is_new_caller:
        flags.append('New')
    if speaker_separated:
        flags.append('Cust-only')
    flag_str = ' · '.join(flags)

    footer_parts = [f'LNM · {status} · {score}pts · {repair_str}']
    if flag_str:
        footer_parts.append(flag_str)
    footer_parts.append(duration)
    footer = '[' + ' · '.join(footer_parts) + ']'

    excerpt = extract_key_sentence(transcript, score_result['lead_keywords'] + score_result['disqualify_keywords'])
    # Trim excerpt so total note stays under 500 chars
    max_excerpt = 500 - len(footer) - 3  # 3 for newline + quotes
    if len(excerpt) > max_excerpt:
        excerpt = excerpt[:max_excerpt - 1].rstrip() + '…'

    return f'"{excerpt}"\n{footer}'


# ── CallRail API ──────────────────────────────────────────────────────────────

QUALIFIED_TAG     = 'LNM Qualified'
NOT_QUALIFIED_TAG = 'LNM Not Qualified'
_tag_cache: dict = {}  # account_id → {tag_name: tag_id}


def _ensure_tag(account_id, tag_name):
    if account_id not in _tag_cache:
        _tag_cache[account_id] = {}
    if tag_name in _tag_cache[account_id]:
        return _tag_cache[account_id][tag_name]
    r = requests.get(f'{CALLRAIL_BASE}/a/{account_id}/tags.json', headers=CR_HEADERS, timeout=10)
    for t in r.json().get('tags', []):
        if t['name'].lower() == tag_name.lower():
            _tag_cache[account_id][tag_name] = t['id']
            return t['id']
    color = 'green' if 'Not' not in tag_name else 'red'
    r = requests.post(f'{CALLRAIL_BASE}/a/{account_id}/tags.json',
                      headers=CR_HEADERS, json={'name': tag_name, 'color': color}, timeout=10)
    tag_id = r.json().get('id')
    _tag_cache[account_id][tag_name] = tag_id
    return tag_id


def push_note_to_callrail(account_id, call_id, note, qualified):
    try:
        # 1. Update note + lead_status in one PUT call
        payload = {'note': note}
        qual_ok = True
        if qualified is not None:
            payload['lead_status'] = 'good_lead' if qualified else 'not_a_lead'
        r = requests.put(
            f'{CALLRAIL_BASE}/a/{account_id}/calls/{call_id}.json',
            headers=CR_HEADERS, json=payload, timeout=15,
        )
        note_ok = r.status_code in (200, 201)
        if not note_ok:
            print(f'  [warn] CR update failed ({r.status_code}): {r.text[:120]}')
            return

        # 2. Tag for visual filtering
        tag_ok = True
        if qualified is not None:
            tag_name = QUALIFIED_TAG if qualified else NOT_QUALIFIED_TAG
            tag_id = _ensure_tag(account_id, tag_name)
            if tag_id:
                r2 = requests.post(
                    f'{CALLRAIL_BASE}/a/{account_id}/calls/{call_id}/tags.json',
                    headers=CR_HEADERS, json={'tag_id': tag_id}, timeout=10,
                )
                tag_ok = r2.status_code in (200, 201)

        requests.patch(
            f'{SUPABASE_URL}/rest/v1/call_transcripts',
            headers={**SB_HEADERS, 'Prefer': 'return=minimal'},
            params={'call_id': f'eq.{call_id}'},
            json={'cr_synced_at': datetime.now(timezone.utc).isoformat()},
            timeout=10,
        )
        print(f'  ↑ CR synced (note=True lead_status={qual_ok} tag={tag_ok})')
    except Exception as e:
        print(f'  [warn] CR sync failed: {e}')


def fetch_calls(account_id, start_date, page=1, company_id=None):
    params = {
        'start_date': start_date,
        'fields':     'recording,recording_player,duration,company_id,company_name,customer_phone_number,customer_name,direction,start_time,tracking_phone_number',
        'per_page':   100,
        'page':       page,
        'sort':       'start_time',
    }
    if company_id:
        params['company_id'] = company_id
    r = requests.get(
        f'{CALLRAIL_BASE}/a/{account_id}/calls.json',
        headers=CR_HEADERS,
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def download_recording(url, dest_path):
    # CallRail recording endpoint returns JSON {url: "..."} with a pre-signed redirect URL
    r = requests.get(url, headers=CR_HEADERS, timeout=30)
    r.raise_for_status()
    ct = r.headers.get('content-type', '')
    if 'json' in ct:
        actual_url = r.json().get('url', url)
    else:
        actual_url = url
    # Download the actual audio (pre-signed URL, no auth header needed)
    r2 = requests.get(actual_url, timeout=120, stream=True)
    r2.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r2.iter_content(chunk_size=65536):
            f.write(chunk)


# ── Supabase helpers ──────────────────────────────────────────────────────────

def already_transcribed(call_id):
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/call_transcripts',
        headers=SB_HEADERS,
        params={'call_id': f'eq.{call_id}', 'select': 'id'},
        timeout=10,
    )
    return bool(r.json())


def is_new_caller(caller_number, location_id):
    """Return True if this phone number has no prior transcripts for this location."""
    if not caller_number:
        return False
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/call_transcripts',
        headers=SB_HEADERS,
        params={
            'caller_number': f'eq.{caller_number}',
            'location_id':   f'eq.{location_id}',
            'select':        'id',
            'limit':         1,
        },
        timeout=10,
    )
    return not bool(r.json())


def find_location_id(callrail_account_id):
    # Try exact match first, then ILIKE for numeric vs ACC format variants
    for val in [callrail_account_id, f'%{callrail_account_id}%']:
        op = 'eq' if val == callrail_account_id else 'ilike'
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            headers=SB_HEADERS,
            params={'callrail_account_id': f'{op}.{val}', 'select': 'id,callrail_account_id', 'limit': 1},
            timeout=10,
        )
        rows = r.json()
        if rows:
            return rows[0]['id'], rows[0]['callrail_account_id']
    return None, callrail_account_id


def upsert_transcript(row):
    r = requests.post(
        f'{SUPABASE_URL}/rest/v1/call_transcripts?on_conflict=call_id',
        headers={**SB_HEADERS, 'Prefer': 'resolution=merge-duplicates,return=minimal'},
        json=row,
        timeout=45,
    )
    if r.status_code == 409:
        return True  # already exists
    if r.status_code not in (200, 201, 204):
        print(f'  [db error] {r.status_code}: {r.text[:200]}')
        return False
    return True


# ── Audio helpers ─────────────────────────────────────────────────────────────

def get_channel_count(audio_path):
    """Return number of audio channels (1=mono, 2=stereo). Returns 1 if ffprobe unavailable."""
    if not FFPROBE:
        return 1
    try:
        result = subprocess.run(
            [FFPROBE, '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=channels', '-of', 'csv=p=0', audio_path],
            capture_output=True, text=True, timeout=10,
        )
        return int(result.stdout.strip() or '1')
    except Exception:
        return 1


def split_stereo(audio_path, tmpdir):
    """Split stereo MP3 into left (shop) and right (customer) mono WAV files."""
    left  = os.path.join(tmpdir, 'left.wav')
    right = os.path.join(tmpdir, 'right.wav')
    subprocess.run(
        [FFMPEG, '-y', '-i', audio_path,
         '-filter_complex', '[0:a]channelsplit=channel_layout=stereo[left][right]',
         '-map', '[left]',  left,
         '-map', '[right]', right],
        capture_output=True, timeout=60, check=True,
    )
    return left, right

SHOP_CHANNEL_PATTERNS = SHOP_GREETING_PATTERNS + [
    'let me check', 'hold on', 'hold please', 'one moment', 'give me a second',
    'what can i do for you', 'what seems to be the problem', 'how may i',
    'we can get you in', "we'll get you in", 'our next available',
    'let me look', 'does that work for you', 'go ahead and', 'bring it in',
]

def identify_shop_channel(left_text, right_text, left_segs=None, right_segs=None):
    """Return 'left' or 'right' for whichever channel is the shop employee.
    Shop phrase scoring; on tie, first-speaker wins (shop answers the call).
    """
    def shop_score(t):
        low = t.lower()
        return sum(1 for p in SHOP_CHANNEL_PATTERNS if p in low)
    ls, rs = shop_score(left_text), shop_score(right_text)
    if ls != rs:
        return 'left' if ls > rs else 'right'
    # Tiebreak: shop speaks first (answers the call)
    if left_segs and right_segs:
        l_start = left_segs[0]['start']  if left_segs  else float('inf')
        r_start = right_segs[0]['start'] if right_segs else float('inf')
        return 'left' if l_start <= r_start else 'right'
    # Final fallback: more text = more likely shop
    return 'left' if len(left_text) >= len(right_text) else 'right'


# ── Transcription ─────────────────────────────────────────────────────────────

def transcribe_file(audio_path, model):
    segments_iter, _ = model.transcribe(audio_path, language='en', beam_size=1)
    segments = []
    full_text = []
    for seg in segments_iter:
        segments.append({'start': round(seg.start, 2), 'end': round(seg.end, 2), 'text': seg.text.strip()})
        full_text.append(seg.text.strip())
    return ' '.join(full_text), segments


def transcribe(audio_path, model_name):
    """
    Transcribe audio. If stereo and ffmpeg available, returns:
      (full_transcript, customer_transcript, segments, speaker_separated)
    Otherwise full_transcript == customer_transcript and speaker_separated=False.
    """
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device='cpu', compute_type='int8')

    channels = get_channel_count(audio_path)
    if channels >= 2 and FFMPEG:
        tmpdir = tempfile.mkdtemp()
        try:
            left_path, right_path = split_stereo(audio_path, tmpdir)
            left_text,  left_segs  = transcribe_file(left_path,  model)
            right_text, right_segs = transcribe_file(right_path, model)

            shop_side = identify_shop_channel(left_text, right_text, left_segs, right_segs)
            if shop_side == 'left':
                shop_text, customer_text = left_text,  right_text
                customer_segs = right_segs
            else:
                shop_text, customer_text = right_text, left_text
                customer_segs = left_segs

            # Full transcript interleaves both channels (for display)
            full_text = f'[Shop] {shop_text}\n[Customer] {customer_text}'
            return full_text, customer_text, customer_segs, True
        except Exception as e:
            print(f'  [warn] stereo split failed ({e}), falling back to mono')
        finally:
            import shutil as _sh
            _sh.rmtree(tmpdir, ignore_errors=True)

    # Mono fallback
    full_text, segs = transcribe_file(audio_path, model)
    return full_text, full_text, segs, False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id',  required=True)
    parser.add_argument('--company-id',  default=None, help='CallRail company ID to filter calls')
    parser.add_argument('--location-id', default=None, help='Supabase location UUID (skips DB lookup)')
    parser.add_argument('--days-back',   type=int, default=30)
    parser.add_argument('--model',       default='small.en', help='tiny.en | base.en | medium.en')
    args = parser.parse_args()

    if FFMPEG:
        print(f'ffmpeg: {FFMPEG} — stereo speaker separation enabled')
    else:
        print('[warn] ffmpeg not found — speaker separation disabled. Install: brew install ffmpeg')

    start_date = (datetime.now(timezone.utc) - timedelta(days=args.days_back)).strftime('%Y-%m-%d')
    print(f'Fetching calls for account {args.account_id} since {start_date}...')

    if args.location_id:
        location_id, acc_id = args.location_id, args.account_id
    else:
        location_id, acc_id = find_location_id(args.account_id)
    print(f'Location ID: {location_id or "not found"} | Account key: {acc_id}')

    # Auto-derive company_id from location when not explicitly provided
    company_id = args.company_id
    if location_id and not company_id:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            headers=SB_HEADERS,
            params={'id': f'eq.{location_id}', 'select': 'callrail_company_id'},
            timeout=10,
        )
        rows = r.json()
        if rows and rows[0].get('callrail_company_id'):
            company_id = rows[0]['callrail_company_id']
            print(f'Company ID: {company_id} (auto-derived from location)')

    all_calls = []
    page = 1
    while True:
        data = fetch_calls(args.account_id, start_date, page, company_id=company_id)
        calls = data.get('calls', [])
        all_calls.extend(calls)
        if not data.get('has_next_page'):
            break
        page += 1
        time.sleep(0.3)

    print(f'Total calls: {len(all_calls)}')

    ok = fail = skip = 0
    for call in all_calls:
        call_id = str(call['id'])
        if already_transcribed(call_id):
            skip += 1
            continue

        rec_url         = call.get('recording') or call.get('recording_player')
        duration        = int(call.get('duration') or 0)
        caller          = call.get('customer_phone_number', '')
        name            = call.get('customer_name', '')
        direct          = call.get('direction', 'inbound')
        call_at         = call.get('start_time')
        tracking_phone  = call.get('tracking_phone_number', '')

        # Only process first-time callers
        new_caller = is_new_caller(caller, location_id) if (caller and location_id) else False
        if not new_caller:
            skip += 1
            continue

        print(f'\n  {call_id} | {call_at} | {duration}s | {caller} ★ new')

        if not rec_url:
            skip += 1
            continue

        try:
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                tmp_path = tmp.name

            download_recording(rec_url, tmp_path)
            full_transcript, customer_transcript, segments, separated = transcribe(tmp_path, args.model)
            os.unlink(tmp_path)
        except Exception as e:
            print(f'  [error] transcription failed: {e}')
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            fail += 1
            continue

        if not full_transcript.strip():
            print('  [skip] empty transcript')
            skip += 1
            continue

        # Filter shop lines then score
        customer_transcript = filter_shop_lines(customer_transcript)
        scored = score_transcript(customer_transcript, is_new_caller=new_caller)
        repair_cats = extract_repair_category(customer_transcript)
        note   = build_note(
            customer_transcript, scored, duration, caller, direct,
            is_new_caller=new_caller, speaker_separated=separated,
            repair_cats=repair_cats,
        )

        sep_tag = '(customer-only)' if separated else '(mono)'
        print(f'  {sep_tag}')

        row = {
            'call_id':             call_id,
            'location_id':         location_id,
            'callrail_account_id': acc_id,
            'call_at':             call_at,
            'duration_sec':        duration,
            'caller_number':       caller,
            'caller_name':         name,
            'direction':           direct,
            'recording_url':       rec_url,
            'transcript':          full_transcript,
            'segments':            segments,
            'lead_keywords':       scored['lead_keywords'],
            'disqualify_keywords': scored['disqualify_keywords'],
            'tow_call':            scored['tow_call'],
            'lead_score':          scored['lead_score'],
            'qualified':           scored['qualified'],
            'repair_category':         repair_cats,
            'notes':                   note,
            'tracking_phone_number':   tracking_phone,
            'whisper_model':           args.model,
        }

        if upsert_transcript(row):
            status = 'qualified' if scored['qualified'] is True \
                     else ('not qualified' if scored['qualified'] is False else 'unscored')
            print(f'  ✓ score={scored["lead_score"]} → {status}')
            ok += 1
            push_note_to_callrail(acc_id, call_id, note, scored['qualified'])
        else:
            fail += 1

    print(f'\nDone. Transcribed: {ok}  Failed: {fail}  Skipped: {skip}')


if __name__ == '__main__':
    main()
