from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import panbagi  # pyright: ignore[reportImplicitRelativeImport]

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = REPO_ROOT / "template"

ENV_TEMPLATE = TEMPLATE_DIR / "env.yml"
WORKFLOW_TEMPLATE = TEMPLATE_DIR / "build-nginx-ech.yml"
README_TEMPLATE = TEMPLATE_DIR / "README.md"

WORKFLOW_OUT = REPO_ROOT / ".github" / "workflows" / "build-nginx-ech.yml"
README_OUT = REPO_ROOT / "README.md"

_ENV_LINE_RE = re.compile(
    r'^\s{2}([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"([^"]*)"\s*(?:#.*)?$'
)


def parse_env_template(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    env_seen = False
    vars_map: dict[str, str] = {}

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not env_seen:
            if stripped != "env:":
                msg = f"Expected 'env:' at {path}:{idx}, found: {line!r}"
                raise ValueError(msg)
            env_seen = True
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            msg = f"Invalid env line at {path}:{idx}: {line!r}"
            raise ValueError(msg)
        key, value = match.groups()
        vars_map[key] = value

    if not env_seen:
        raise ValueError(f"Missing 'env:' header in {path}")

    return vars_map


def render_readme(vars_map: dict[str, str]) -> str:
    template = panbagi.Template.load(str(README_TEMPLATE))
    return template.render(vars_map)


def render_workflow() -> str:
    env_text = ENV_TEMPLATE.read_text()
    workflow_text = WORKFLOW_TEMPLATE.read_text()
    return env_text + workflow_text


def write_outputs(workflow_text: str, readme_text: str) -> None:
    WORKFLOW_OUT.parent.mkdir(parents=True, exist_ok=True)
    _ = WORKFLOW_OUT.write_text(workflow_text)
    _ = README_OUT.write_text(readme_text)


def diff_file(expected: Path, actual: Path) -> int:
    result = subprocess.run(["diff", "-u", str(expected), str(actual)])
    return result.returncode


def run_check(workflow_text: str, readme_text: str) -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        workflow_tmp = tmp_path / WORKFLOW_OUT.name
        readme_tmp = tmp_path / README_OUT.name
        _ = workflow_tmp.write_text(workflow_text)
        _ = readme_tmp.write_text(readme_text)

        code = diff_file(workflow_tmp, WORKFLOW_OUT)
        if code != 0:
            return code
        return diff_file(readme_tmp, README_OUT)


@dataclass(frozen=True)
class CliArgs:
    mode: str


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "mode",
        choices=("check", "write"),
        nargs="?",
        default="check",
        help="check compares generated files; write overwrites outputs",
    )
    ns = parser.parse_args()
    return CliArgs(mode=cast(str, ns.mode))


def main() -> int:
    args = parse_args()
    vars_map = parse_env_template(ENV_TEMPLATE)
    readme_text = render_readme(vars_map)
    workflow_text = render_workflow()

    if args.mode == "write":
        write_outputs(workflow_text, readme_text)
        return 0

    return run_check(workflow_text, readme_text)


if __name__ == "__main__":
    raise SystemExit(main())
