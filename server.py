"""
server.py — FastAPI backend for the GTM Setup UI.

Streams script output via Server-Sent Events.
Runs on http://localhost:8765.

Usage:
  source venv/bin/activate
  pip install fastapi uvicorn
  uvicorn server:app --port 8765 --reload
"""

import asyncio
import json
import os
import sys
import requests

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5174', 'http://localhost:5173'],
    allow_methods=['GET', 'POST'],
    allow_headers=['*'],
)

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PYTHON      = os.path.join(SCRIPT_DIR, 'venv', 'bin', 'python')
CHROME_CDP  = 'http://localhost:9222/json/version'

ACTIONS = {
    'create-container': 'create_container.py',
    'setup-tags':       'setup_tags.py',
    'inject-wordpress': 'inject_wordpress.py',
}


# ── Chrome status ─────────────────────────────────────────────────────────────

@app.get('/api/chrome-status')
def chrome_status():
    try:
        r = requests.get(CHROME_CDP, timeout=2)
        return {'up': r.status_code == 200}
    except Exception:
        return {'up': False}


# ── Job runner ────────────────────────────────────────────────────────────────


async def stream_script_with_cancel(script_name: str, gads_cid: str):
    script_path = os.path.join(SCRIPT_DIR, script_name)
    cmd = [PYTHON, script_path, '--gads-cid', gads_cid]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=SCRIPT_DIR,
    )
    try:
        async for raw in proc.stdout:
            text = raw.decode('utf-8', errors='replace').rstrip('\n')
            if not text:
                continue
            line_type = 'err' if any(w in text.lower() for w in ('error', 'fail', 'traceback', 'exception')) \
                        else 'warn' if any(w in text.lower() for w in ('warn', 'warning', 'already')) \
                        else 'ok' if any(w in text.lower() for w in ('done', 'success', 'injected', 'updated', 'created', 'active')) \
                        else 'plain'
            yield f"event: line\ndata: {json.dumps({'text': text, 'type': line_type})}\n\n"

        await proc.wait()
        yield f"event: done\ndata: {json.dumps({'exit_code': proc.returncode})}\n\n"
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise


@app.get('/api/run/{action}')
async def run_action(action: str, gads_cid: str = Query(...)):
    if action not in ACTIONS:
        raise HTTPException(status_code=400, detail=f'Unknown action: {action}')

    return StreamingResponse(
        stream_script_with_cancel(ACTIONS[action], gads_cid),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )
