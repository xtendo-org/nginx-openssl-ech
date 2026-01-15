import argparse
import os
import sys
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import requests

OWNER = "xtendo-org"
REPO = "nginx-openssl-ech"
API_BASE = "https://api.github.com"
WORKFLOW_FILE = "build-nginx-ech.yml"
DEFAULT_REF = "main"

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


@dataclass(frozen=True)
class ParsedArgs:
    command: str
    run_id: int | None
    ref: str
    tag: str | None
    title: str | None
    notes: str
    draft: bool
    prerelease: bool


class RefResponse(TypedDict):
    object: dict[str, str]


class ReleaseResponse(TypedDict):
    html_url: str


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
        try:
            run = get_latest_run(session)
        except requests.ConnectionError:
            print("Connection error.")
            sys.exit(-1)
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


def dispatch_run(session: requests.Session, run_id: int, ref: str) -> None:
    url = (
        f"{API_BASE}/repos/{OWNER}/{REPO}/actions/workflows/"
        f"{WORKFLOW_FILE}/dispatches"
    )
    payload = {
        "ref": ref,
        "inputs": {
            "skip_builds": "true",
            "artifact_run_id": str(run_id),
        },
    }
    resp = session.post(url, json=payload)
    resp.raise_for_status()
    print(
        "Workflow dispatched.",
        f"ref={ref}",
        f"artifact_run_id={run_id}",
    )


def get_ref_sha(session: requests.Session, ref: str) -> str:
    ref_name = ref
    if ref_name.startswith("refs/heads/"):
        ref_name = ref_name[len("refs/heads/") :]
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/git/ref/heads/{ref_name}"
    resp = session.get(url)
    resp.raise_for_status()
    data = cast(RefResponse, resp.json())
    sha = data.get("object", {}).get("sha")
    if not sha:
        raise SystemExit(f"Unable to resolve ref SHA for {ref}.")
    return sha


def create_tag_ref(session: requests.Session, tag: str, sha: str) -> None:
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/git/refs"
    payload = {"ref": f"refs/tags/{tag}", "sha": sha}
    resp = session.post(url, json=payload)
    if resp.status_code == 422:
        raise SystemExit(f"Tag already exists: {tag}")
    resp.raise_for_status()
    print(f"Created tag refs/tags/{tag} at {sha}.")


def create_release(
    session: requests.Session,
    tag: str,
    ref: str,
    title: str | None,
    notes: str,
    draft: bool,
    prerelease: bool,
) -> None:
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/releases"
    payload = {
        "tag_name": tag,
        "target_commitish": ref,
        "name": title or tag,
        "body": notes,
        "draft": draft,
        "prerelease": prerelease,
    }
    resp = session.post(url, json=payload)
    resp.raise_for_status()
    data = cast(ReleaseResponse, resp.json())
    print(f"Created release: {data.get('html_url')}")


def parse_args() -> ParsedArgs:
    parser = argparse.ArgumentParser(
        description=(
            "Download logs for the latest run or dispatch a manual run."
        )
    )
    subparsers = parser.add_subparsers(dest="command")
    logs_parser = subparsers.add_parser(
        "logs",
        help="Download logs for the latest workflow run (default).",
    )
    logs_parser.set_defaults(command="logs")

    dispatch_parser = subparsers.add_parser(
        "dispatch",
        help="Dispatch a workflow run using artifacts from a run ID.",
    )
    _ = dispatch_parser.add_argument(
        "run_id", type=int, help="Run ID that produced artifacts."
    )
    _ = dispatch_parser.add_argument(
        "--ref", default=DEFAULT_REF, help="Git ref to dispatch."
    )

    release_parser = subparsers.add_parser(
        "release",
        help="Create a tag and release at a ref.",
    )
    _ = release_parser.add_argument("tag", help="Release tag name.")
    _ = release_parser.add_argument(
        "--ref", default=DEFAULT_REF, help="Git ref to tag."
    )
    _ = release_parser.add_argument(
        "--title", default=None, help="Release title (defaults to tag)."
    )
    _ = release_parser.add_argument(
        "--notes", default="", help="Release notes body."
    )
    _ = release_parser.add_argument(
        "--draft", action="store_true", help="Create as a draft release."
    )
    _ = release_parser.add_argument(
        "--prerelease",
        action="store_true",
        help="Create as a prerelease.",
    )

    args = parser.parse_args()
    command = cast(str | None, getattr(args, "command", None))
    if command is None:
        command = "logs"
    if command == "dispatch":
        return ParsedArgs(
            command=command,
            run_id=cast(int, args.run_id),
            ref=cast(str, args.ref),
            tag=None,
            title=None,
            notes="",
            draft=False,
            prerelease=False,
        )
    if command == "release":
        return ParsedArgs(
            command=command,
            run_id=None,
            ref=cast(str, args.ref),
            tag=cast(str, args.tag),
            title=cast(str | None, args.title),
            notes=cast(str, args.notes),
            draft=cast(bool, args.draft),
            prerelease=cast(bool, args.prerelease),
        )
    return ParsedArgs(
        command=command,
        run_id=None,
        ref=DEFAULT_REF,
        tag=None,
        title=None,
        notes="",
        draft=False,
        prerelease=False,
    )


def print_summary(
    run: WorkflowRun,
    zip_path: Path,
    out_dir: Path,
    failed_jobs: list[str],
    downloaded: bool = True,
) -> None:
    print(f"Run ID: {run.get('id')}")
    print(f"Status: {run.get('status')}")
    print(f"Conclusion: {run.get('conclusion')}")
    print(f"Created at: {run.get('created_at')}")
    print(f"Updated at: {run.get('updated_at')}")
    print(f"URL: {run.get('html_url')}")
    if downloaded:
        print(f"Logs ZIP: {zip_path}")
    else:
        print("Logs ZIP: (skipped)")
    print(f"Logs dir: {out_dir}")
    if not downloaded:
        print("Logs already exist; skipping download.")
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
    args = parse_args()
    if args.command == "dispatch":
        if args.run_id is None or args.run_id <= 0:
            raise SystemExit("run_id must be a positive integer.")
        dispatch_run(session, args.run_id, args.ref)
        return
    if args.command == "release":
        if not args.tag:
            raise SystemExit("tag is required for release.")
        sha = get_ref_sha(session, args.ref)
        create_tag_ref(session, args.tag, sha)
        create_release(
            session,
            args.tag,
            args.ref,
            args.title,
            args.notes,
            args.draft,
            args.prerelease,
        )
        return
    run = wait_for_run(session)
    run_id = run["id"]
    out_dir = Path("novcs/ci-log") / str(run_id)
    if out_dir.exists():
        failed_jobs = []
        if run.get("conclusion") == "failure":
            failed_jobs = list_failed_jobs(session, run_id)
        zip_path = Path(f"/tmp/ci-log-{run_id}.zip")
        print_summary(run, zip_path, out_dir, failed_jobs, downloaded=False)
        return
    zip_path, out_dir = download_logs(session, run_id)
    failed_jobs = []
    if run.get("conclusion") == "failure":
        failed_jobs = list_failed_jobs(session, run_id)
    print_summary(run, zip_path, out_dir, failed_jobs)


if __name__ == "__main__":
    main()
