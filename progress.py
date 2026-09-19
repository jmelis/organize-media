#!/usr/bin/env python3
"""Quick and dirty progress for a running `vault.py sync`.

Usage: ./progress.py [LOGFILE]   (defaults to the current sync's log)

Sums the sizes of the files rsync has named in the log so far against the total the
run has to move (measured once, hardcoded below -- recompute with vault.py if the
source tree changes materially).
"""

import os
import re
import sys
import time

TOTAL = int(84.39 * 2**30)  # bytes this sync has to move
SRC = os.path.expanduser("~/Pictures")

LOG = os.path.expanduser("~/vault-sync.log")

log = sys.argv[1] if len(sys.argv) > 1 else LOG
cur, done, files = None, 0, 0

for line in open(log, errors="replace"):
    line = line.rstrip("\n")
    m = re.match(r"^=== (\S+) ===$", line)
    if m:
        cur = m.group(1)
        continue
    if not cur or not line or line.startswith((" ", "\t")):
        continue
    if line.endswith("/") or "%" in line:
        continue
    p = os.path.join(SRC, cur, line)
    if os.path.isfile(p):
        done += os.path.getsize(p)
        files += 1

# Measure the rate over the *current* run: a resumed sync appends to an existing
# log, and the log's birthtime says nothing useful once it has been copied or
# reused. Stash a baseline on first sight and rate from there.
mark = os.path.expanduser("~/.vault-sync-mark")
now = time.time()
if os.path.exists(mark):
    t0, b0 = (float(x) for x in open(mark).read().split())
    if b0 > done:  # log restarted from scratch
        t0, b0 = now, done
        open(mark, "w").write(f"{t0} {b0}")
else:
    t0, b0 = now, done
    open(mark, "w").write(f"{t0} {b0}")

elapsed = max(now - t0, 1.0)
rate = (done - b0) / elapsed
left = max(TOTAL - done, 0)
pct = 100 * done / TOTAL
eta = left / rate if rate > 0 else 0

print(f"\n  [{'#' * int(pct / 2.5):<40}] {pct:.1f}%")
print(f"  {done / 2**30:.2f} / {TOTAL / 2**30:.2f} GiB   {files} files   in {cur}")
if rate > 0:
    print(f"  {rate / 1e6:.2f} MB/s   {left / 2**30:.1f} GiB left   "
          f"~{int(eta // 3600)}h {int(eta % 3600 // 60):02d}m remaining\n")
else:
    print(f"  {left / 2**30:.1f} GiB left   (no progress yet this run)\n")
