from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import panbagi  # pyright: ignore[reportImplicitRelativeImport]  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = REPO_ROOT / "template"

ENV_TEMPLATE = TEMPLATE_DIR / "env.yml"
WORKFLOW_TEMPLATE = TEMPLATE_DIR / "build-nginx-ech.yml"
README_TEMPLATE = TEMPLATE_DIR / "README.md"

WORKFLOW_OUT = REPO_ROOT / ".github/workflows/build-nginx-ech.yml"
README_OUT = REPO_ROOT / "README.md"


def gen_env_vars_map(path: Path) -> Iterator[tuple[str, str]]:
    lines = path.read_text().splitlines()

    for raw_line in lines[1:]:
        line = raw_line.lstrip()
        if not line:
            continue

        k, sep, v = line.partition(": ")
        assert sep
        yield (k, v[1:-1])


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


def diff_file(tool: str, expected: Path, actual: Path) -> int:
    result = subprocess.run([tool, str(expected), str(actual)])
    return result.returncode


def run_check(workflow_text: str, readme_text: str) -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        workflow_tmp = tmp_path / WORKFLOW_OUT.name
        readme_tmp = tmp_path / README_OUT.name
        _ = workflow_tmp.write_text(workflow_text)
        _ = readme_tmp.write_text(readme_text)

        compare_mappings = [
            (workflow_tmp, WORKFLOW_OUT),
            (readme_tmp, README_OUT),
        ]

        tool = os.getenv("DIFF_TOOL", "diff")

        for expected, actual in compare_mappings:
            code = diff_file(tool, expected, actual)
            if code != 0:
                return code

        return 0


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
    vars_map = dict(gen_env_vars_map(ENV_TEMPLATE))
    readme_text = render_readme(vars_map)
    workflow_text = render_workflow()

    if args.mode == "write":
        write_outputs(workflow_text, readme_text)
        return 0

    return run_check(workflow_text, readme_text)


if __name__ == "__main__":
    raise SystemExit(main())
