# CI access for assistants (`ci.py`)

A zero-dependency Python 3 helper (standard library only) that lets any
assistant watch this repo's GitHub Actions build and trigger new builds -
exactly what a human would do on the Actions tab, over the REST API.

Repo: `mohamadyfarag1/Mercury-KM15-103H-OpenWrt` (private)

## 1. Get a token (one-time, by the repo owner)

Create a **fine-grained Personal Access Token** scoped to *only* this repo:

GitHub → Settings → Developer settings → Fine-grained tokens → Generate:
- **Resource owner:** mohamadyfarag1
- **Repository access:** Only select repositories → `Mercury-KM15-103H-OpenWrt`
- **Permissions:**
  - Contents: **Read and write**  (needed to push commits / trigger push builds)
  - Actions:  **Read and write**  (needed to read runs+logs and dispatch builds)
- Expiration: pick a short one; revoke any time from the same page.

Hand that token to the assistant. It is revocable and scoped to this one
repo only - it is NOT the owner's main git credential.

## 2. Point the helper at the token

```bash
export GH_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxx
# optional overrides:
# export GH_REPO=mohamadyfarag1/Mercury-KM15-103H-OpenWrt
# export GH_WORKFLOW=build_mercury_km15_103h.yml
```

## 3. Commands

```bash
python3 tools/ci.py status         # latest run: sha, status, conclusion, failed step
python3 tools/ci.py log            # failed job log, filtered to the error lines
python3 tools/ci.py log 33852440301  # ...for a specific run id
python3 tools/ci.py build          # start a build (workflow_dispatch on master)
python3 tools/ci.py build --23ghz  # ...including the experimental 2.3 GHz channels
python3 tools/ci.py watch          # poll until the latest run finishes, then dump errors
python3 tools/ci.py watch 60       # ...polling every 60s
```

## 4. How builds are triggered

Two ways, both covered by the token above:

1. **Push** - the workflow runs automatically on any push that touches
   `mercury_km15_103h_build/**`, `scripts/mercury-*.sh`,
   or the workflow file itself.
   `concurrency: cancel-in-progress` means a newer push cancels the older run.
2. **Manual** - `python3 tools/ci.py build` calls the `workflow_dispatch`
   trigger directly, no commit needed. Use this to rebuild the same commit.

## 5. Artifacts a green build produces

- `Mercury_KM15-103H_Firmware` - the `*-sysupgrade.bin` to flash
- `Mercury_KM15-103H_UART_Recovery` - `u-boot.bin` + `*-initramfs-kernel.bin`
  + `HOW_TO_USE.txt` for UART Ymodem recovery

Download artifacts from the run's `html_url` (printed by `status`), or via
`GET /repos/{repo}/actions/runs/{run_id}/artifacts`.
