"""
ophix_bundle.cli
~~~~~~~~~~~~~~~~
Command-line interface for ophix-bundle.

Entry point: ophix-bundle (registered in pyproject.toml).
"""

import argparse
import configparser
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, List, Mapping, Optional

from ophix_bundle._version import __version__


CONFIG_DIR = Path.home() / ".config" / "ophix-bundle"
CONFIG_FILE = CONFIG_DIR / "config.ini"
SECTION = "ophix-bundle"
DEFAULT_BUNDLES_DIR = Path.home() / "ophix-bundles"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config():
    # type: () -> configparser.ConfigParser
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)
    return cfg


def save_config(cfg):
    # type: (configparser.ConfigParser) -> None
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)


def cfg_get(cfg, key):
    # type: (configparser.ConfigParser, str) -> str
    return cfg.get(SECTION, key, fallback="")


def cfg_set(cfg, key, value):
    # type: (configparser.ConfigParser, str, str) -> None
    if not cfg.has_section(SECTION):
        cfg.add_section(SECTION)
    cfg.set(SECTION, key, value)


def resolve_server(cfg, override):
    # type: (configparser.ConfigParser, Optional[str]) -> str
    return override or cfg_get(cfg, "server")


def resolve_bundles_dir(cfg):
    # type: (configparser.ConfigParser) -> Path
    stored = cfg_get(cfg, "bundles_dir")
    return Path(stored) if stored else DEFAULT_BUNDLES_DIR


# ---------------------------------------------------------------------------
# Bundle file helpers
# ---------------------------------------------------------------------------

def bundle_path(name, bundles_dir):
    # type: (str, Path) -> Path
    return bundles_dir / "{}.txt".format(name)


def read_bundle(name, bundles_dir):
    # type: (str, Path) -> List[str]
    p = bundle_path(name, bundles_dir)
    if not p.exists():
        return []
    return [
        line.strip()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def write_bundle(name, bundles_dir, lines):
    # type: (str, Path, List[str]) -> None
    bundles_dir.mkdir(parents=True, exist_ok=True)
    bundle_path(name, bundles_dir).write_text(
        "\n".join(lines) + "\n" if lines else "",
        encoding="utf-8",
    )


def pkg_base_name(req_line):
    # type: (str) -> str
    """Extract bare package name from a requirements-style line."""
    return re.split(r"[><=![\s;@#]", req_line.strip())[0].strip()


def normalize_name(name):
    # type: (str) -> str
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------------------------------------------------------------------
# PyPI helpers
# ---------------------------------------------------------------------------

def get_latest_version(package, server_url):
    # type: (str, str) -> Optional[str]
    """Return the latest version of a package from the configured PyPI server."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", package,
             "--index-url", server_url, "--no-input"],
            capture_output=True, text=True, timeout=30,
        )
        # pip index versions first output line: "package-name (latest_version)"
        match = re.search(r"\(([^)]+)\)", result.stdout)
        if match:
            return match.group(1).strip()
    except Exception as exc:
        print("  Warning: version query failed for {}: {}".format(package, exc), file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Shared add/update logic
# ---------------------------------------------------------------------------

def apply_adds(incoming, existing, pin_version, server):
    # type: (List[str], List[str], bool, str) -> List[str]
    """Merge incoming packages into existing list, updating in-place where names match."""
    by_name = {normalize_name(pkg_base_name(p)): i for i, p in enumerate(existing)}
    to_append = []  # type: List[str]

    for raw in incoming:
        entry = raw
        if pin_version:
            print("  Querying {} ...".format(raw), end=" ", flush=True)
            ver = get_latest_version(raw, server)
            if ver:
                entry = "{}>={}".format(raw, ver)
                print(">={}".format(ver))
            else:
                print("(version unknown, adding unpinned)")

        key = normalize_name(pkg_base_name(raw))
        if key in by_name:
            idx = by_name[key]
            old = existing[idx]
            existing[idx] = entry
            if old != entry:
                print("  Updated: {}  ->  {}".format(old, entry))
            else:
                print("  Unchanged: {}".format(entry))
        else:
            print("  Added: {}".format(entry))
            to_append.append(entry)

    return existing + to_append


# ---------------------------------------------------------------------------
# CLI command implementations
# ---------------------------------------------------------------------------

def run_config(args):
    # type: (Any) -> None
    cfg = load_config()
    changed = False

    if args.server is not None:
        cfg_set(cfg, "server", args.server)
        print("Server set to:      {}".format(args.server))
        changed = True

    if args.bundles_dir is not None:
        cfg_set(cfg, "bundles_dir", args.bundles_dir)
        print("Bundles dir set to: {}".format(args.bundles_dir))
        changed = True

    if changed:
        save_config(cfg)
    else:
        print("Config file:   {}".format(CONFIG_FILE))
        print("Server:        {}".format(cfg_get(cfg, "server") or "(not set)"))
        print("Bundles dir:   {}".format(resolve_bundles_dir(cfg)))


def run_add(args):
    # type: (Any) -> None
    cfg = load_config()
    server = resolve_server(cfg, args.server)
    bundles_dir = resolve_bundles_dir(cfg)

    if args.pin_version and not server:
        print("Error: --pin-version requires a server URL.", file=sys.stderr)
        print("       Set one with: ophix-bundle config --server <url>", file=sys.stderr)
        sys.exit(1)

    incoming = [p.strip() for p in args.packages.split(",") if p.strip()]
    existing = read_bundle(args.name, bundles_dir)
    result = apply_adds(incoming, existing, args.pin_version, server)
    write_bundle(args.name, bundles_dir, result)
    print("\nBundle saved: {}".format(bundle_path(args.name, bundles_dir)))


def run_update(args):
    # type: (Any) -> None
    cfg = load_config()
    server = resolve_server(cfg, args.server)
    bundles_dir = resolve_bundles_dir(cfg)
    bp = bundle_path(args.name, bundles_dir)

    if not bp.exists():
        print("Error: bundle not found: {}".format(bp), file=sys.stderr)
        sys.exit(1)

    if args.pin_version and not server and args.add:
        print("Error: --pin-version requires a server URL.", file=sys.stderr)
        print("       Set one with: ophix-bundle config --server <url>", file=sys.stderr)
        sys.exit(1)

    existing = read_bundle(args.name, bundles_dir)

    if args.remove:
        to_remove = {normalize_name(p.strip()) for p in args.remove.split(",") if p.strip()}
        kept, removed = [], []
        for line in existing:
            (removed if normalize_name(pkg_base_name(line)) in to_remove else kept).append(line)
        existing = kept
        for r in removed:
            print("  Removed: {}".format(r))
        if not removed:
            print("  Warning: no matching packages found for: {}".format(args.remove))

    if args.add:
        incoming = [p.strip() for p in args.add.split(",") if p.strip()]
        existing = apply_adds(incoming, existing, args.pin_version, server)

    write_bundle(args.name, bundles_dir, existing)
    print("\nBundle saved: {}".format(bp))


def run_list(args):
    # type: (Any) -> None
    cfg = load_config()
    bundles_dir = resolve_bundles_dir(cfg)

    if args.name:
        bp = bundle_path(args.name, bundles_dir)
        if not bp.exists():
            print("Error: bundle not found: {}".format(bp), file=sys.stderr)
            sys.exit(1)
        lines = read_bundle(args.name, bundles_dir)
        print("Bundle: {}  ({})".format(args.name, bp))
        print("{} package(s):\n".format(len(lines)))
        for line in lines:
            print("  {}".format(line))
    else:
        txt_files = sorted(bundles_dir.glob("*.txt")) if bundles_dir.exists() else []
        if not txt_files:
            print("No bundles found in: {}".format(bundles_dir))
            return
        print("Bundles in {}:\n".format(bundles_dir))
        for bf in txt_files:
            count = len(read_bundle(bf.stem, bundles_dir))
            print("  {:<40}  {} package(s)".format(bf.stem, count))


def run_package(args):
    # type: (Any) -> None
    cfg = load_config()
    server = resolve_server(cfg, args.server)
    bundles_dir = resolve_bundles_dir(cfg)

    if not server:
        print("Error: PyPI server URL is required.", file=sys.stderr)
        print("       Set one with: ophix-bundle config --server <url>", file=sys.stderr)
        sys.exit(1)

    bp = bundle_path(args.name, bundles_dir)
    if not bp.exists():
        print("Error: bundle not found: {}".format(bp), file=sys.stderr)
        sys.exit(1)

    lines = read_bundle(args.name, bundles_dir)
    if not lines:
        print("Error: bundle is empty: {}".format(bp), file=sys.stderr)
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    archive_name = "{}_{}.tgz".format(args.name, ts)
    out_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
    archive_path = out_dir / archive_name

    extra_indexes = args.extra_index_url or []

    print("Bundle:     {} ({} package spec(s))".format(args.name, len(lines)))
    print("Server:     {}".format(server))
    for url in extra_indexes:
        print("Extra idx:  {}".format(url))
    print("Output:     {}".format(archive_path))
    print("Deps:       {}".format("excluded" if args.no_deps else "included"))
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        dl_dir = Path(tmpdir) / "packages"
        dl_dir.mkdir()

        pip_cmd = [
            sys.executable, "-m", "pip", "download",
            "--index-url", server,
            "--dest", str(dl_dir),
            "--no-input",
            "-r", str(bp),
        ]
        for url in extra_indexes:
            pip_cmd.extend(["--extra-index-url", url])
        if args.no_deps:
            pip_cmd.append("--no-deps")

        print("Running pip download...")
        result = subprocess.run(pip_cmd)
        if result.returncode != 0:
            print("\nError: pip download failed.", file=sys.stderr)
            sys.exit(1)

        downloaded = sorted(dl_dir.iterdir())
        print("\nDownloaded {} file(s). Creating archive...".format(len(downloaded)))

        out_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for f in downloaded:
                # Store files under packages/ inside the archive for clean extraction
                tar.add(f, arcname="packages/{}".format(f.name))

        size = archive_path.stat().st_size
        size_str = "{} KB".format(size // 1024) if size < 1_048_576 else "{:.1f} MB".format(size / 1_048_576)
        print("\nCreated: {} ({})".format(archive_path, size_str))
        print("Contains {} file(s) in packages/".format(len(downloaded)))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser(prog, version, commands, description=None):
    # type: (str, str, Mapping[str, dict], Optional[str]) -> Any

    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("-v", "--version", action="version", version=version)

    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, spec in commands.items():
        help_text = None if spec.get("hidden") else spec.get("help")
        sub = subparsers.add_parser(
            name,
            help=help_text if help_text is not None else argparse.SUPPRESS,
        )

        for arg in spec.get("arguments", []):
            arg = arg.copy()
            arg_name = arg.pop("name")
            sub.add_argument(arg_name, **arg)

        for group_spec in spec.get("mutually_exclusive_groups", []):
            group = sub.add_mutually_exclusive_group(required=group_spec.get("required", False))
            for arg in group_spec["arguments"]:
                arg = arg.copy()
                arg_name = arg.pop("name")
                group.add_argument(arg_name, **arg)

        sub.set_defaults(func=spec["handler"])

    return parser


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMANDS = {
    "config": {
        "help": "Show or update tool configuration (server URL, bundles directory)",
        "arguments": [
            {"name": "--server",      "metavar": "URL",  "default": None,
             "help": "Store this PyPI server URL as the default"},
            {"name": "--bundles-dir", "metavar": "DIR",  "default": None, "dest": "bundles_dir",
             "help": "Store this path as the default bundles directory"},
        ],
        "handler": run_config,
    },

    "add": {
        "help": "Add packages to a bundle (creates the bundle file if it does not exist)",
        "arguments": [
            {"name": "--name",        "required": True,  "metavar": "NAME",
             "help": "Bundle name"},
            {"name": "--packages",    "required": True,  "metavar": "PKGS",
             "help": "Comma-separated package names to add"},
            {"name": "--pin-version", "action": "store_true", "dest": "pin_version",
             "help": "Query server for latest version and record as minimum (>=)"},
            {"name": "--server",      "metavar": "URL",  "default": None,
             "help": "Override configured PyPI server URL (required with --pin-version)"},
        ],
        "handler": run_add,
    },

    "update": {
        "help": "Add or remove packages in an existing bundle",
        "arguments": [
            {"name": "--name",        "required": True,  "metavar": "NAME",
             "help": "Bundle name"},
            {"name": "--add",         "metavar": "PKGS", "default": None,
             "help": "Comma-separated packages to add"},
            {"name": "--remove",      "metavar": "PKGS", "default": None,
             "help": "Comma-separated packages to remove (version specifiers ignored)"},
            {"name": "--pin-version", "action": "store_true", "dest": "pin_version",
             "help": "Pin added packages to current latest version (>=)"},
            {"name": "--server",      "metavar": "URL",  "default": None,
             "help": "Override configured PyPI server URL"},
        ],
        "handler": run_update,
    },

    "list": {
        "help": "List all bundles, or show the contents of a named bundle",
        "arguments": [
            {"name": "--name", "metavar": "NAME", "default": None,
             "help": "Show contents of this specific bundle"},
        ],
        "handler": run_list,
    },

    "package": {
        "help": "Download a bundle from the PyPI server and create a distributable archive",
        "arguments": [
            {"name": "--name",            "required": True,  "metavar": "NAME",
             "help": "Bundle name"},
            {"name": "--server",          "metavar": "URL",  "default": None,
             "help": "Override configured PyPI server URL"},
            {"name": "--extra-index-url", "metavar": "URL",  "default": None,
             "dest": "extra_index_url",   "action": "append",
             "help": "Additional index to search for dependencies (repeatable); "
                     "use https://pypi.org/simple/ to pull public deps"},
            {"name": "--output-dir",      "metavar": "DIR",  "default": None, "dest": "output_dir",
             "help": "Directory for the output archive (default: current directory)"},
            {"name": "--no-deps",         "action": "store_true", "dest": "no_deps",
             "help": "Download only the listed packages, skip transitive dependencies"},
        ],
        "handler": run_package,
    },
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser(
        prog="ophix-bundle",
        version=__version__,
        description="Bundle packages from a local PyPI server for air-gap deployment.",
        commands=COMMANDS,
    )
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
