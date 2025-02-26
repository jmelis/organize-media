#!/usr/bin/env python3

"""
remember that sometimes this fails because of chflags nouchg
"""

import argparse
from datetime import datetime
import filecmp
import os
import re
import shutil
from glob import glob
from pathlib import Path
import subprocess

import exiftool

PHOTO_EXTENSIONS = [".jpg", ".arw", ".sr2", ".raf"]
VID_EXTENSIONS = [".mp4", ".mov"]


def dir_path(path):
    if os.path.isdir(path):
        return path
    else:
        raise argparse.ArgumentTypeError(f"TARGET {path} is not a valid path.")


def get_date_exif(file):
    tag = "EXIF:DateTimeOriginal"
    with exiftool.ExifToolHelper() as et:
        try:
            t = et.get_tags([file], tags=tag)[0][tag]
        except KeyError:
            raise Exception("No EXIF data for DateTimeOriginal")

        if not re.match(r"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}", t):
            raise Exception(f"WOAH: {t}")

        return datetime.strptime(t, "%Y:%m:%d %H:%M:%S")


def get_date_ffmpeg(file):
    cmd = subprocess.run(["ffmpeg", "-i", file, "-dump"], capture_output=True)
    stderr = cmd.stderr.decode("utf-8")
    for line in stderr.split("\n"):
        if "creation_time" in line:
            return datetime.fromisoformat(line.split()[-1])
    raise Exception(f"could not find date for {file}")


parser = argparse.ArgumentParser(prog="organize-media")
parser.add_argument("source", metavar="SOURCE")
parser.add_argument("target", metavar="TARGET", type=dir_path)
parser.add_argument("-n", action="store_true")
parser.add_argument("--ext", action="store_true", help="group by extension")


args = parser.parse_args()

if not os.path.isdir(args.source):
    raise Exception("source_dir not a dir")

errors = []

for file in glob(os.path.join(args.source, "**"), recursive=True):
    _, ext = os.path.splitext(file)
    ext = ext.lower()

    if ext in PHOTO_EXTENSIONS:
        try:
            date = get_date_exif(file)
        except Exception as e:
            errors.append((file, str(e)))
            continue
    elif ext in VID_EXTENSIONS:
        date = get_date_ffmpeg(file)
    else:
        continue

    target_dir = Path(args.target) / date.strftime("%Y") / date.strftime("%Y-%m-%d")

    if args.ext:
        target_dir = target_dir / ext[1:]

    target_file = target_dir / os.path.basename(file)

    if target_dir.is_file():
        print(f"Skipping {file}: target dir {target_dir} is a file")
        continue

    print(f"{file} -> {target_file}")

    if target_file.exists():
        if filecmp.cmp(file, target_file):
            print(
                f"Can delete {file}: {target_file} already present in target directory"
            )
        else:
            raise Exception(
                f"ERROR: File discrepancy: {target_file} exists with different contents than {file}"
            )

    if not args.n:
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(file, target_file)
        except PermissionError as e:
            errors.append((file, e))
            continue

if errors:
    print(f"There were {len(errors)} errors:")
    for file, error in errors:
        print(f"- {file}: {error}")
    exit(1)

