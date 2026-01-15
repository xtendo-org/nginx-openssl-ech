import os
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict, cast

import requests

OWNER = "xtendo-org"
REPO = "nginx-openssl-ech"
API_BASE = "https://api.github.com"

POLL_SECONDS = 30
POLL_ATTEMPTS = 20


class WorkflowRun(TypedDict):
    id: int
    status: str
    conclusion: str | None
    created_at: str
    updated_at: str
    html_url: str


class WorkflowRunsResponse(TypedDict):
    workflow_runs: list[WorkflowRun]


class Job(TypedDict):
    name: str
    conclusion: str | None


class JobsResponse(TypedDict):
    jobs: list[Job]


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


def get_latest_run(session: requests.Session) -> WorkflowRun:
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/actions/runs"
    resp = session.get(url, params={"per_page": 1})
    resp.raise_for_status()
    data = cast(WorkflowRunsResponse, resp.json())
    runs = data["workflow_runs"]
    if not runs:
        raise SystemExit("No workflow runs found.")
    return runs[0]


def wait_for_run(session: requests.Session) -> WorkflowRun:
    if POLL_ATTEMPTS <= 0:
        raise SystemExit("POLL_ATTEMPTS must be positive.")
    remaining = POLL_ATTEMPTS
    while True:
        run = get_latest_run(session)
        status = run.get("status")
        if status not in {"queued", "in_progress"}:
            return run
        remaining -= 1
        if remaining <= 0:
            run_id = run.get("id")
            message = (
                f"Run {run_id} still in progress after "
                f"{POLL_ATTEMPTS} attempts."
            )
            raise SystemExit(message)
        message = (
            f"Run {run.get('id')} still in progress; sleeping {POLL_SECONDS}s "
            f"({remaining} attempts remaining)"
        )
        print(message)
        time.sleep(POLL_SECONDS)


def download_logs(session: requests.Session, run_id: int) -> tuple[Path, Path]:
    zip_path = Path(f"/tmp/ci-log-{run_id}.zip")
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/logs"
    resp = session.get(url, stream=True)
    try:
        resp.raise_for_status()
        with zip_path.open("wb") as handle:
            chunks = cast(
                Iterable[bytes], resp.iter_content(chunk_size=1024 * 1024)
            )
            for chunk in chunks:
                if chunk:
                    _ = handle.write(chunk)
    finally:
        resp.close()

    out_dir = Path("novcs/ci-log") / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(out_dir)
    return zip_path, out_dir


def list_failed_jobs(session: requests.Session, run_id: int) -> list[str]:
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs"
    resp = session.get(url, params={"per_page": 100})
    resp.raise_for_status()
    data = cast(JobsResponse, resp.json())
    jobs = data["jobs"]
    return [job["name"] for job in jobs if job.get("conclusion") == "failure"]


def print_summary(
    run: WorkflowRun, zip_path: Path, out_dir: Path, failed_jobs: list[str]
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
    run_id = run["id"]
    zip_path, out_dir = download_logs(session, run_id)
    failed_jobs = []
    if run.get("conclusion") == "failure":
        failed_jobs = list_failed_jobs(session, run_id)
    print_summary(run, zip_path, out_dir, failed_jobs)


if __name__ == "__main__":
    main()
