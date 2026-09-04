#!/usr/bin/env python3
"""
Mercury KM15-103H CI helper - lets any assistant watch GitHub Actions and
trigger builds the same way, using only the Python standard library.

Auth:  export GH_TOKEN=<fine-grained PAT>   (repo scope: Contents R/W + Actions R/W)
Repo:  override with  export GH_REPO=owner/name   (defaults below)

Usage:
  python3 ci.py status            # latest run: sha, status, conclusion, failed step
  python3 ci.py log [run_id]      # download the failed job's log, print error lines
  python3 ci.py build [--23ghz]   # trigger a build via workflow_dispatch on master
  python3 ci.py watch [secs]      # poll (default 90s) until the latest run finishes
"""
import json, os, sys, time, urllib.request, urllib.error

REPO = os.environ.get("GH_REPO", "mohamadyfarag1/Mercury-KM15-103H-OpenWrt")
WORKFLOW = os.environ.get("GH_WORKFLOW", "build_mercury_km15_103h.yml")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
API = f"https://api.github.com/repos/{REPO}"

def _req(method, url, body=None, raw=False):
    if not TOKEN:
        sys.exit("ERROR: set GH_TOKEN (a fine-grained PAT with Contents+Actions on this repo).")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data: req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=60)
        b = r.read()
        return b if raw else (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {method} {url}\n{e.read().decode(errors='replace')[:800]}")

def latest_run():
    return _req("GET", f"{API}/actions/runs?per_page=1")["workflow_runs"][0]

def cmd_status():
    run = latest_run()
    print(f"title      : {run['display_title']}")
    print(f"sha        : {run['head_sha'][:12]}")
    print(f"status     : {run['status']}")
    print(f"conclusion : {run['conclusion']}")
    print(f"run_id     : {run['id']}")
    print(f"url        : {run['html_url']}")
    if run["conclusion"] == "failure":
        jobs = _req("GET", f"{API}/actions/runs/{run['id']}/jobs")["jobs"]
        for j in jobs:
            for s in j.get("steps", []):
                if s.get("conclusion") == "failure":
                    print(f"FAILED step : #{s['number']} {s['name']}  (job {j['id']})")

def cmd_log(run_id=None):
    run = _req("GET", f"{API}/actions/runs/{run_id}")  if run_id else latest_run()
    rid = run["id"]
    jobs = _req("GET", f"{API}/actions/runs/{rid}/jobs")["jobs"]
    job = next((j for j in jobs if j.get("conclusion") == "failure"), jobs[0])
    raw = _req("GET", f"{API}/actions/jobs/{job['id']}/logs", raw=True).decode(errors="replace")
    markers = ("!!!!","ERROR:","Error 1","Error 2","failed to build","Collected errors",
               "make[","No rule to make","BUILD FAILED","CHAN5G","cannot","not found")
    hits = [ln for ln in raw.splitlines() if any(m in ln for m in markers)]
    print("\n".join(hits[-70:]) if hits else raw[-4000:])

def cmd_build(dgz=False):
    body = {"ref": "master", "inputs": {"enable_23ghz": "true" if dgz else "false"}}
    _req("POST", f"{API}/actions/workflows/{WORKFLOW}/dispatches", body=body)
    print(f"Dispatched build on master (enable_23ghz={dgz}). Poll with: python3 ci.py watch")

def cmd_watch(interval=90):
    while True:
        run = latest_run()
        st, cc = run["status"], run["conclusion"]
        print(f"[{time.strftime('%H:%M:%S')}] {run['head_sha'][:12]} status={st} conclusion={cc}")
        if st == "completed":
            print("DONE:", cc)
            if cc == "failure":
                cmd_log(run["id"])
            return 0 if cc == "success" else 1
        time.sleep(interval)

def main():
    a = sys.argv[1:] or ["status"]
    c = a[0]
    if c == "status": cmd_status()
    elif c == "log": cmd_log(a[1] if len(a) > 1 else None)
    elif c == "build": cmd_build("--23ghz" in a)
    elif c == "watch": cmd_watch(int(a[1]) if len(a) > 1 else 90)
    else: sys.exit(__doc__)

if __name__ == "__main__":
    main()
