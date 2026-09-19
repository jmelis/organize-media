#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
Copy ~/Pictures to the SAN, and check whether a path is already safely there.

Usage:
    ./vault.py sync [-n]
    ./vault.py check PATH [--checksum] [--limit N] [--extra] [--quiet]

sync copies ~/Pictures/{Albums,YYYY} to the SAN. It is purely additive and never
deletes anything on either side.

check answers "is this already on the SAN?" so that deleting the local copy stays a
manual decision. It exits 0 when everything matches and 1 otherwise, so it composes:

    ./vault.py check 2025/2025-10-05 && rm -rf ~/Pictures/2025/2025-10-05
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Tuple

SOURCE_ROOT = Path.home() / "Pictures"
TARGET_ROOT = Path("/Volumes/data/Fotos")

# The entire selection rule for sync: Albums, plus every four-digit year directory.
COPY_DIRS = re.compile(r"^(Albums|\d{4})$")

# The SAN's SMB server. Asserted at preflight so a different volume mounted at the
# same path is rejected rather than silently used.
SMB_SERVER = "192.168.1.130"

EXCLUDE_NAMES = {".DS_Store", ".claude"}
EXCLUDE_PREFIXES = ("._",)
RSYNC_EXCLUDES = [".DS_Store", "._*", ".claude"]

CHUNK = 1 << 20


def die(message: str) -> None:
    """Print an error and exit non-zero."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #


def smb_mountpoint(path: Path) -> Path:
    """Walk up from path to the filesystem mount point containing it."""
    p = path.resolve()
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    return p


def require_smb_target() -> None:
    """
    Assert TARGET_ROOT really is the expected SMB share.

    If the share is unmounted, /Volumes/data/Fotos can resolve to an empty local
    directory. sync would then quietly fill the boot disk, and check would report
    everything as missing -- the answer most likely to be acted on destructively.

    Note both smbutil subcommands exit 0 even on failure: smbstat writes its error to
    stderr and leaves stdout empty, and statshares prints an empty table. The return
    code is worthless here, so parse stdout.
    """
    probe = subprocess.run(
        ["smbutil", "smbstat", str(TARGET_ROOT)],
        capture_output=True,
        text=True,
    )
    if "Object Type:" not in probe.stdout:
        die(
            f"{TARGET_ROOT} is not served over SMB -- the share looks unmounted.\n"
            f"       Mount it and try again; refusing to touch a local directory "
            f"standing in for the SAN."
        )

    mountpoint = smb_mountpoint(TARGET_ROOT)
    shares = subprocess.run(
        ["smbutil", "statshares", "-m", str(mountpoint)],
        capture_output=True,
        text=True,
    )
    server = None
    for line in shares.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "SERVER_NAME":
            server = fields[1]
            break

    if server != SMB_SERVER:
        die(
            f"{mountpoint} is served by {server or 'an unknown server'}, "
            f"expected {SMB_SERVER}."
        )


# --------------------------------------------------------------------------- #
# Walking and comparing
# --------------------------------------------------------------------------- #


def is_excluded(name: str) -> bool:
    """Whether a file or directory name should be ignored entirely."""
    return name in EXCLUDE_NAMES or name.startswith(EXCLUDE_PREFIXES)


def iter_files(root: Path) -> Iterator[Path]:
    """Yield every non-excluded file under root, as a path relative to root."""
    def raise_walk_error(error: OSError) -> None:
        raise error

    for dirpath, dirnames, filenames in os.walk(root, onerror=raise_walk_error):
        dirnames[:] = sorted(d for d in dirnames if not is_excluded(d))
        base = Path(dirpath)
        for name in sorted(filenames):
            if is_excluded(name):
                continue
            yield (base / name).relative_to(root)


def same_content(a: Path, b: Path) -> bool:
    """Byte-compare two files. Only used under --checksum."""
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ba, bb = fa.read(CHUNK), fb.read(CHUNK)
            if ba != bb:
                return False
            if not ba:
                return True


def stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def compare(local: Path, remote: Path, checksum: bool) -> Optional[str]:
    """
    Compare one local file against its SAN counterpart.

    Returns None when they match, otherwise a human-readable reason. mtimes are
    compared as whole seconds: measured on this share, local and SAN mtimes agree
    exactly and sub-second precision is always zero, so there is no rounding to
    absorb -- but truncating keeps a stray sub-second local timestamp from reading
    as a spurious difference.
    """
    if not remote.exists():
        return "missing"

    lstat, rstat = local.stat(), remote.stat()
    problems = []
    if lstat.st_size != rstat.st_size:
        problems.append(f"size  {lstat.st_size} -> {rstat.st_size}")
    if int(lstat.st_mtime) != int(rstat.st_mtime):
        problems.append(f"mtime {stamp(lstat.st_mtime)} -> {stamp(rstat.st_mtime)}")

    if checksum and not problems and not same_content(local, remote):
        problems.append("content differs")

    return "; ".join(problems) if problems else None


def to_remote(local: Path) -> Path:
    """Map a path under SOURCE_ROOT to its SAN counterpart."""
    return TARGET_ROOT / local.relative_to(SOURCE_ROOT)


def resolve_under_source(raw: str) -> Path:
    """Resolve a user-supplied path and require it to live under ~/Pictures."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()

    source = SOURCE_ROOT.resolve()
    if path != source and source not in path.parents:
        die(f"{path} is not under {SOURCE_ROOT}")
    if not path.exists():
        die(f"{path} does not exist")
    return path


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #


def check_file(local: Path, remote: Path, checksum: bool, quiet: bool) -> int:
    """Check a single file. Presence is the verdict; any mismatch is also a failure."""
    rel = local.relative_to(SOURCE_ROOT)
    reason = compare(local, remote, checksum)

    if reason == "missing":
        if not quiet:
            print(f"✗ {rel} — not on the SAN")
        return 1
    if reason:
        if not quiet:
            print(f"✗ {rel} — on the SAN but differs")
            print(f"    {reason}")
        return 1
    if not quiet:
        basis = "contents match" if checksum else "size and mtime match"
        print(f"✓ {rel} — present on the SAN, {basis}")
    return 0


def report_group(title: str, rows: list[str], limit: int) -> None:
    print(f"  {title} ({len(rows)}):")
    shown = rows if limit == 0 else rows[:limit]
    for row in shown:
        print(f"    {row}")
    if len(rows) > len(shown):
        remaining = len(rows) - len(shown)
        print(f"    ... and {remaining} more (--limit 0 to list all)")


def check_dir(
    local: Path, remote: Path, checksum: bool, limit: int, extra: bool, quiet: bool
) -> int:
    """Check every file under a directory against the SAN."""
    rel = local.relative_to(SOURCE_ROOT)
    missing: list[str] = []
    differing: list[str] = []
    total = 0

    for relfile in iter_files(local):
        total += 1
        reason = compare(local / relfile, remote / relfile, checksum)
        if reason == "missing":
            missing.append(str(relfile))
        elif reason:
            differing.append(f"{relfile}   {reason}")

    surplus: list[str] = []
    if extra and remote.is_dir():
        local_set = set(iter_files(local))
        surplus = [str(f) for f in iter_files(remote) if f not in local_set]

    if quiet:
        return 1 if (missing or differing) else 0

    if total == 0:
        print(f"✓ {rel} — no files to check (empty)")
    elif not missing and not differing:
        basis = "contents match" if checksum else "sizes and mtimes match"
        print(f"✓ {rel} — all {total} files present on the SAN, {basis}")
    else:
        parts = []
        if missing:
            parts.append(f"{len(missing)} missing")
        if differing:
            parts.append(f"{len(differing)} differing")
        print(f"✗ {rel} — {total} files checked, {', '.join(parts)}")
        if missing:
            report_group("MISSING", missing, limit)
        if differing:
            report_group("DIFFERS", differing, limit)

    if surplus:
        report_group("ON SAN ONLY", surplus, limit)

    return 1 if (missing or differing) else 0


def cmd_check(args: argparse.Namespace) -> int:
    require_smb_target()
    local = resolve_under_source(args.path)
    remote = to_remote(local)

    if local.is_dir():
        return check_dir(
            local, remote, args.checksum, args.limit, args.extra, args.quiet
        )
    return check_file(local, remote, args.checksum, args.quiet)


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #


def copy_dirs() -> list[Path]:
    """The directories sync copies: Albums plus every YYYY directory."""
    return sorted(
        d for d in SOURCE_ROOT.iterdir() if d.is_dir() and COPY_DIRS.match(d.name)
    )


def build_rsync(source: Path, target: Path, dry_run: bool) -> list[str]:
    """
    Assemble the rsync command.

    -rlt rather than -a: SMB cannot preserve owner/group/perms, and -a would emit an
    error per file. -t is essential -- check compares mtimes. macOS ships openrsync
    (protocol 29), so the GNU-only --info=progress2, --no-perms and --mkpath are
    unavailable; --no-perms is moot anyway, since -rlt never requests permissions.

    Built from a fixed list with no passthrough: --delete must never appear. The SAN
    legitimately holds far more than the local disk (12,528 files under 2025/ against
    2,488 locally), so a single --delete would destroy ~10,000 archived files.
    """
    cmd = ["rsync", "-rlt"]
    # A dry run is summarised per directory, so ask for stats and stay quiet;
    # a real run streams so there is something to watch over a multi-hour copy.
    cmd += ["--dry-run", "--stats"] if dry_run else ["-v", "--progress"]
    for pattern in RSYNC_EXCLUDES:
        cmd.append(f"--exclude={pattern}")
    cmd.append(f"{source}/")
    cmd.append(f"{target}/")

    assert not any(a.startswith("--del") for a in cmd), "refusing to run a deleting rsync"
    return cmd


def cmd_sync(args: argparse.Namespace) -> int:
    require_smb_target()

    dirs = copy_dirs()
    if not dirs:
        die(f"no directories matching {COPY_DIRS.pattern} under {SOURCE_ROOT}")

    verb = "Would copy" if args.dry_run else "Copying"
    print(f"{verb} {len(dirs)} directories from {SOURCE_ROOT} to {TARGET_ROOT}\n")

    failures = []
    pending = 0

    for source in dirs:
        target = TARGET_ROOT / source.name
        cmd = build_rsync(source, target, args.dry_run)

        if args.dry_run:
            result = subprocess.run(cmd, capture_output=True, text=True)
            count = 0
            for line in result.stdout.splitlines():
                if line.startswith("Number of files transferred:"):
                    count = int(line.split(":")[1].strip())
                    break
            pending += count
            print(f"  {source.name:<10} {count:>6} files to copy")
        else:
            print(f"=== {source.name} ===", flush=True)
            target.mkdir(parents=True, exist_ok=True)
            # rsync writes straight to our stdout, so flush first or the headers
            # arrive after the output they label.
            sys.stdout.flush()
            result = subprocess.run(cmd)
            print(flush=True)

        if result.returncode != 0:
            failures.append((source.name, result.returncode))

    if failures:
        print("\nrsync reported errors:", file=sys.stderr)
        for name, code in failures:
            print(f"  {name}: exit {code}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"\ndry run complete — {pending} files would be copied.")
    else:
        print("done.")
    return 0


# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="vault",
        description="Copy ~/Pictures to the SAN, and check what is already there",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser(
        "sync", help="copy ~/Pictures/{Albums,YYYY} to the SAN (never deletes)"
    )
    p_sync.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be copied without copying it",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_check = sub.add_parser("check", help="report whether a path is already on the SAN")
    p_check.add_argument("path", help="File or directory under ~/Pictures")
    p_check.add_argument(
        "--checksum",
        action="store_true",
        help="Compare file contents as well as size and mtime (slow over SMB)",
    )
    p_check.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum entries to list per section, 0 for all (default: 50)",
    )
    p_check.add_argument(
        "--extra",
        action="store_true",
        help="Also list files present on the SAN but not locally",
    )
    p_check.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Print nothing; report the verdict via exit code only",
    )
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
