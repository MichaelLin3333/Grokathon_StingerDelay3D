"""Read-only upstream watcher. Runs only while the local server is running."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import subprocess
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / 'StingerDelay-3D'
REPOSITORY = 'https://github.com/danmano411/StingerDelay-3D.git'
INTERVAL = 300
_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD = None
_STATE = {'status': 'pending', 'checked_at': None, 'remote_sha': None, 'local_sha': None,
          'changed': False, 'commits': [], 'interval_seconds': INTERVAL,
          'repository': 'https://github.com/danmano411/StingerDelay-3D', 'running': False}


def status():
    with _LOCK:
        return dict(_STATE)


def _git(*args, cwd=None):
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True,
                            timeout=12, check=True)
    return result.stdout.strip()


def _fetch_commits():
    request = urllib.request.Request(
        'https://api.github.com/repos/danmano411/StingerDelay-3D/commits?per_page=5',
        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'StingerD-GPT'})
    with urllib.request.urlopen(request, timeout=12) as response:
        results = json.load(response)
    commits = [{'sha': c['sha'], 'message': c['commit']['message'].splitlines()[0],
                'url': c['html_url'], 'date': c['commit']['committer']['date']} for c in results]
    if not commits:
        raise ValueError('GitHub returned no commits')
    return commits


def check():
    checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
    previous = status()
    local = previous.get('local_sha')
    local_error = False
    try:
        if (SOURCE / '.git').exists():
            local = _git('rev-parse', 'HEAD', cwd=SOURCE)
    except (OSError, subprocess.SubprocessError):
        local_error = True
    try:
        try:
            commits = _fetch_commits()
            remote = commits[0]['sha']
            transport, details_stale = 'github_api', False
        except (OSError, ValueError, KeyError, TypeError):
            remote = _git('ls-remote', REPOSITORY, 'HEAD').split()[0]
            transport = 'git'
            details_stale = remote != previous.get('remote_sha')
            commits = previous.get('commits', []) if not details_stale else []
        try:
            review = json.loads((ROOT / 'data/upstream-review.json').read_text())
            reviewed = review.get('reviewed_sha')
            alignment = review.get('alignment_status', 'unknown')
        except (OSError, ValueError):
            reviewed, alignment = None, 'unknown'
        with _LOCK:
            _STATE.update(status='ok', checked_at=checked_at, last_success_at=checked_at,
                          local_sha=local, remote_sha=remote, changed=bool(local and local != remote),
                          new_since_previous=bool(previous.get('remote_sha') and previous['remote_sha'] != remote),
                          commits=commits, reviewed_sha=reviewed, needs_review=bool(reviewed and remote != reviewed),
                          transport=transport, commit_details_stale=details_stale,
                          local_check_failed=local_error, alignment_status=alignment)
            _STATE.pop('error', None)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        with _LOCK:
            _STATE.update(status='error', checked_at=checked_at,
                          error='Could not reach GitHub. Last successful revision is retained; source files were not modified.')
    # Observability only. Never fetch/pull/merge/push or modify the source checkout.
    try:
        target = ROOT / 'docs/upstream-state.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(status(), indent=2) + '\n')
        temp.replace(target)
    except OSError:
        pass
    return status()


def _loop():
    while not _STOP.is_set():
        check()
        _STOP.wait(INTERVAL)
    with _LOCK:
        _STATE['running'] = False


def start():
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return _THREAD
    _STOP.clear()
    with _LOCK:
        _STATE['running'] = True
    _THREAD = threading.Thread(target=_loop, name='upstream-watch', daemon=True)
    _THREAD.start()
    return _THREAD


def stop():
    _STOP.set()
