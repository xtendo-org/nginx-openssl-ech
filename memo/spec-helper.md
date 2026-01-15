This document describes the specification for the Python script that lets us programmatically query how the CI run in GitHub Actions actually went.

## Idea

- GitHub provides API.
- The logs of each CI run in GitHub Actions is crucial for finding out what worked and what went wrong.
- With proper configuration, we should be able to run a script locally to fetch anything necessary.

## Assumptions

- Assume the token is available as an environment variable named `GITHUB_TOKEN`.
- For now, hard-code the `<owner>/<repo>` part. The owner name is `xtendo-org` and the repo name is `nginx-openssl-ech`. Therefore it would be `xtendo-org/nginx-openssl-ech`.
- Assume at least Python 3.13 is available.
    - Use the new type annotation style like `list[str]`. Don't use the old `List[Str]`.
- Assume you can `import requests`.

## Steps to be performed in the helper script

- Use the GitHub API to list workflow runs for the repo.
- Pick the latest run.
- If the run is in progress, `time.sleep()` for a minute then retry. Otherwise, proceed.
- Fetch the run logs and save them to local files.
    - Create a directory under `novcs/ci-log`, like `novcs/ci-log/<run-id>`
    - Save the log files under this new directory.
- Print a summary:
    - Run ID, conclusion, start/end time, etc.
    - URL
    - If the run ended in a failure: an analysis. Why it failed, how it could be fixed, etc.
