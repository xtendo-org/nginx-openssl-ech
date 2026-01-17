from __future__ import annotations

import argparse
import json
import os
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from typing import TypedDict, cast
from urllib.response import addinfourl


class Asset(TypedDict):
    id: int
    name: str


class Release(TypedDict, total=False):
    assets: list[Asset]


@dataclass(frozen=True)
class Args:
    tag: str | None
    latest: bool
    nginx_asset: str | None
    openssl_asset: str
    repo: str


def api_get(url: str, accept: str) -> bytes:
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(url, headers=headers)
    with closing(cast(addinfourl, urllib.request.urlopen(req))) as resp:
        return resp.read()


def download_assets(
    repo: str, asset_names: list[str], asset_ids: dict[str, int]
) -> None:
    for name in asset_names:
        asset_id = asset_ids[name]
        asset_url = (
            f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
        )
        data = api_get(asset_url, "application/octet-stream")
        with open(name, "wb") as handle:
            _ = handle.write(data)


def parse_args() -> Args:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    _ = mode.add_argument("--tag", help="Release tag to download assets from")
    _ = mode.add_argument(
        "--latest", action="store_true", help="Use latest release"
    )
    _ = parser.add_argument("--nginx-asset", help="Exact nginx asset name")
    _ = parser.add_argument(
        "--openssl-asset", required=True, help="OpenSSL asset name"
    )
    _ = parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/repo; defaults to GITHUB_REPOSITORY",
    )
    ns = parser.parse_args()
    tag = cast(str | None, ns.tag)
    latest = cast(bool, ns.latest)
    nginx_asset = cast(str | None, ns.nginx_asset)
    openssl_asset = cast(str, ns.openssl_asset)
    repo = cast(str, ns.repo)
    return Args(
        tag=tag,
        latest=latest,
        nginx_asset=nginx_asset,
        openssl_asset=openssl_asset,
        repo=repo,
    )


def main() -> int:
    args = parse_args()
    repo = args.repo
    if not repo:
        print("GITHUB_REPOSITORY is not set and --repo was not provided.")
        return 1

    if args.tag:
        release_url = (
            f"https://api.github.com/repos/{repo}/releases/tags/{args.tag}"
        )
    else:
        release_url = f"https://api.github.com/repos/{repo}/releases/latest"

    release = cast(
        Release, json.loads(api_get(release_url, "application/vnd.github+json"))
    )
    assets = {asset["name"]: asset["id"] for asset in release.get("assets", [])}

    openssl_asset = args.openssl_asset
    if args.tag:
        if not args.nginx_asset:
            print("--nginx-asset is required when using --tag.")
            return 1
        required = [args.nginx_asset, openssl_asset]
    else:
        nginx_assets = [
            name
            for name in assets
            if name.startswith("nginx-")
            and name.endswith("-ech-linux-arm64.tar.gz")
        ]
        if len(nginx_assets) != 1:
            names = ", ".join(nginx_assets)
            print(f"Expected exactly one nginx asset, found: {names}")
            return 1
        required = [nginx_assets[0], openssl_asset]

    missing = [name for name in required if name not in assets]
    if missing:
        print(f"Missing release assets: {', '.join(missing)}")
        return 1

    download_assets(repo, required, assets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
