import os
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

OWNER = "xtendo-org"
REPO = "nginx-openssl-ech"
API_BASE = "https://api.github.com"

POLL_SECONDS = 30
POLL_ATTEMPTS = 20


def require_token() -> str:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set.")
    return token


def make_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nginx-openssl-ech-helper",
        }
    )
    return session


def get_latest_run(session: requests.Session) -> dict[str, Any]:
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/actions/runs"
    resp = session.get(url, params={"per_page": 1})
    resp.raise_for_status()
    runs = resp.json().get("workflow_runs", [])
    if not runs:
        raise SystemExit("No workflow runs found.")
    return runs[0]


def wait_for_run(session: requests.Session) -> dict[str, Any]:
    for attempt in range(POLL_ATTEMPTS):
        run = get_latest_run(session)
        status = run.get("status")
        if status in {"queued", "in_progress"}:
            if attempt == POLL_ATTEMPTS - 1:
                raise SystemExit(
                    f"Run {run.get('id')} still in progress after {POLL_ATTEMPTS} attempts."
                )
            time.sleep(POLL_SECONDS)
            continue
        return run
    raise SystemExit("Polling attempts exhausted.")


def download_logs(session: requests.Session, run_id: int) -> tuple[Path, Path]:
    zip_path = Path(f"/tmp/ci-log-{run_id}.zip")
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/logs"
    with session.get(url, stream=True) as resp:
        resp.raise_for_status()
        with zip_path.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    out_dir = Path("novcs/ci-log") / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(out_dir)
    return zip_path, out_dir


def list_failed_jobs(session: requests.Session, run_id: int) -> list[str]:
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs"
    resp = session.get(url, params={"per_page": 100})
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    return [
        job.get("name", "<unnamed>")
        for job in jobs
        if job.get("conclusion") == "failure"
    ]


def print_summary(
    run: dict[str, Any], zip_path: Path, out_dir: Path, failed_jobs: list[str]
) -> None:
    print(f"Run ID: {run.get('id')}")
    print(f"Status: {run.get('status')}")
    print(f"Conclusion: {run.get('conclusion')}")
    print(f"Created at: {run.get('created_at')}")
    print(f"Updated at: {run.get('updated_at')}")
    print(f"URL: {run.get('html_url')}")
    print(f"Logs ZIP: {zip_path}")
    print(f"Logs dir: {out_dir}")
    if run.get("conclusion") == "failure":
        if failed_jobs:
            print("Failed jobs:")
            for name in failed_jobs:
                print(f"- {name}")
        else:
            print("Failed jobs: (none found)")


def main() -> None:
    token = require_token()
    session = make_session(token)
    run = wait_for_run(session)
    run_id = int(run["id"])
    zip_path, out_dir = download_logs(session, run_id)
    failed_jobs = []
    if run.get("conclusion") == "failure":
        failed_jobs = list_failed_jobs(session, run_id)
    print_summary(run, zip_path, out_dir, failed_jobs)


if __name__ == "__main__":
    main()
