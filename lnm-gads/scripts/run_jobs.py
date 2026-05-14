"""
Automation job runner — polls locations.automation_queued and executes scripts.
Uses a lockfile (~/llmprojects/lnm-gads/.job_runner.pid) to prevent duplicate processes.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.services.database import DatabaseService

PID_FILE_BASE = ROOT / '.job_runner'
POLL_INTERVAL = 5  # seconds between polls when idle
FLUSH_LINES   = 8  # buffer N lines before writing to DB

GTM_SCRIPTS = Path(os.environ.get('GTM_SCRIPTS', ROOT.parent / 'lnm-gtm'))
GTM_PYTHON  = GTM_SCRIPTS / 'venv' / 'bin' / 'python'

GTM_TOKEN_MAP = {
    'analytics@leadsnearme.com':  GTM_SCRIPTS / 'token_analytics.json',
    'analytics2@leadsnearme.com': GTM_SCRIPTS / 'token_analytics2.json',
    'reports@leadsnearme.com':    GTM_SCRIPTS / 'token_reports.json',
}
GTM_TOKEN_DEFAULT = Path(os.environ.get('GTM_TOKEN_FILE', GTM_SCRIPTS / 'token_analytics.json'))
LNM_CRM = Path(os.environ.get('LNM_CRM', ROOT.parent / 'lnm-crm'))


def run_job(db: DatabaseService, job: dict, track: str = "automation") -> None:
    loc_id      = str(job['id'])
    job_type    = job['automation_queued']
    gads_cid    = job.get('gads_cid')
    cr_acct     = job.get('callrail_account_id')
    gtm_lnm_acct = job.get('gtm_lnm_acct') or ''
    gtm_token   = GTM_TOKEN_MAP.get(gtm_lnm_acct.lower(), GTM_TOKEN_DEFAULT)
    name     = job.get('name', loc_id)

    print(f"\n[run_jobs] {name} → {job_type}")
    db.claim_automation(loc_id, track=track)

    if job_type in ('gads_optimization', 'gads_optimization_dry', 'gads_touch', 'gads_touch_dry'):
        if not gads_cid:
            db.append_automation_output(loc_id, '[error] no gads_cid on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        cmd = [sys.executable, 'main.py', 'optimize', '--cid', str(gads_cid), '--location-id', loc_id]
        if job_type in ('gads_optimization_dry', 'gads_touch_dry'):
            cmd.append('--dry-run')

    elif job_type == 'gads_conv_setup':
        if not gads_cid:
            db.append_automation_output(loc_id, '[error] no gads_cid on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        cmd = [sys.executable, 'main.py', 'conv-setup', '--cid', str(gads_cid), '--name', name, '--location-id', loc_id]

    elif job_type == 'callrail_30d':
        cmd = [sys.executable, 'scripts/run_callrail.py', '--minutes-back', '43200']
        if cr_acct:
            cmd += ['--account-id', str(cr_acct)]

    elif job_type == 'callrail_2d':
        cmd = [sys.executable, 'scripts/run_callrail.py', '--minutes-back', '2880']
        if cr_acct:
            cmd += ['--account-id', str(cr_acct)]

    elif job_type == 'gtm_setup':
        if not gads_cid:
            db.append_automation_output(loc_id, '[error] no gads_cid on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        py = str(GTM_PYTHON) if GTM_PYTHON.exists() else sys.executable
        cmd = [py, str(GTM_SCRIPTS / 'setup_tags.py'), '--gads-cid', str(gads_cid),
               '--location-id', loc_id, '--token-file', str(gtm_token)]

    elif job_type == 'gtm_fix':
        if not gads_cid:
            db.append_automation_output(loc_id, '[error] no gads_cid on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        py = str(GTM_PYTHON) if GTM_PYTHON.exists() else sys.executable
        cmd = [py, str(GTM_SCRIPTS / 'setup_tags.py'), '--gads-cid', str(gads_cid),
               '--location-id', loc_id, '--token-file', str(gtm_token), '--force-recreate']

    elif job_type == 'gtm_build_cache':
        py = str(GTM_PYTHON) if GTM_PYTHON.exists() else sys.executable
        cmd = [py, str(GTM_SCRIPTS / 'build_gtm_cache.py'), '--token-file', str(gtm_token)]

    elif job_type == 'gtm_inject':
        if not gads_cid:
            db.append_automation_output(loc_id, '[error] no gads_cid on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        py = str(GTM_PYTHON) if GTM_PYTHON.exists() else sys.executable
        cmd = [py, str(GTM_SCRIPTS / 'inject_wordpress.py'), '--gads-cid', str(gads_cid), '--location-id', loc_id]

    elif job_type == 'competitor_sync':
        if not os.environ.get('GOOGLE_MAPS_API_KEY'):
            db.append_automation_output(loc_id, '[error] GOOGLE_MAPS_API_KEY not set\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        cmd = [sys.executable, str(LNM_CRM / 'sync_competitors.py'), '--location-id', loc_id, '--force']

    elif job_type == 'transcribe_calls':
        if not cr_acct:
            db.append_automation_output(loc_id, '[error] no callrail_account_id on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        cr_company = job.get('callrail_company_id')
        if not cr_company:
            db.append_automation_output(loc_id, '[error] no callrail_company_id on this location — cannot filter calls to correct location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        cmd = [sys.executable, str(LNM_CRM / 'transcribe_calls.py'),
               '--account-id', str(cr_acct), '--company-id', str(cr_company),
               '--location-id', loc_id, '--days-back', '30']
    elif job_type == 'ga4_hybrid_pull':
        cmd = [sys.executable, 'scripts/hybrid_ga4_finder.py', '--location-id', loc_id]

    elif job_type == 'gads_pull':
        if not gads_cid:
            db.append_automation_output(loc_id, '[error] no gads_cid on this location\n', track=track)
            db.complete_automation(loc_id, 'failed', track=track)
            return
        cmd = [sys.executable, 'main.py', 'pull', '--cid', str(gads_cid), '--location-id', loc_id]

    else:
        db.append_automation_output(loc_id, f'[error] unknown job type: {job_type}\n', track=track)
        db.complete_automation(loc_id, 'failed', track=track)
        return

    db.append_automation_output(loc_id, f'$ {" ".join(cmd)}\n', track=track)

    # Determine best CWD based on command
    run_cwd = str(ROOT)
    if any(str(GTM_SCRIPTS) in c for c in cmd):
        run_cwd = str(GTM_SCRIPTS)
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=run_cwd,
        env={**os.environ, 'PYTHONUNBUFFERED': '1'},
    )

    assert proc.stdout is not None
    buf: list[str] = []

    for line in proc.stdout:
        print(line, end='')
        buf.append(line)
        if len(buf) >= FLUSH_LINES:
            db.append_automation_output(loc_id, ''.join(buf), track=track)
            buf.clear()

    if buf:
        db.append_automation_output(loc_id, ''.join(buf), track=track)

    proc.wait()
    exit_line = f'[exit {proc.returncode}]\n'
    print(exit_line, end='')
    db.append_automation_output(loc_id, exit_line, track=track)

    if job_type in ('gads_optimization_dry', 'gads_touch_dry'):
        status = 'dry_done' if proc.returncode == 0 else 'failed'
    else:
        status = 'done' if proc.returncode == 0 else 'failed'
    db.complete_automation(loc_id, status, gads_cid=gads_cid if job_type in ('gads_optimization', 'gads_optimization_dry', 'gads_touch', 'gads_touch_dry') else None, track=track)
    print(f"[run_jobs] {name} → {status}")


def check_lock(pid_file: Path):
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)
            print(f"[run_jobs] Error: Another instance is already running (PID {old_pid}).")
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink()

    pid_file.write_text(str(os.getpid()))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--lnm-acct', default=None,
                        help='Only process jobs for this gtm_lnm_acct value (enables parallel runners)')
    parser.add_argument('--track', default='automation',
                        help='Job track: automation (default) or recurring')
    args = parser.parse_args()

    slug = (args.lnm_acct.split('@')[0] if args.lnm_acct else 'default') + '.' + args.track
    pid_file = Path(str(PID_FILE_BASE) + f'.{slug}.pid')

    check_lock(pid_file)
    db = DatabaseService()
    if not db.enabled:
        print("[run_jobs] DB_ENABLED is not true — set it in .env and retry.")
        sys.exit(1)

    db.init_tables()
    track = args.track
    label = f" [{args.lnm_acct}]" if args.lnm_acct else ""
    if track != 'automation':
        label += f" [track:{track}]"
    print(f"[run_jobs]{label} Watching for automation jobs… (Ctrl+C to stop)")

    try:
        while True:
            job = db.get_queued_automation(lnm_acct=args.lnm_acct, track=track)
            if job:
                run_job(db, job, track=track)
            else:
                time.sleep(POLL_INTERVAL)
    finally:
        if pid_file.exists():
            pid_file.unlink()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n[run_jobs] Stopped.')
