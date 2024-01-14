#!/usr/bin/env python3

import os
from glob import glob

def ff(s):
    return os.path.splitext(os.path.basename(s))[0]

raws = glob('**/*.ARW', recursive=True)
jpgs = glob('**/*.JPG', recursive=True)
raws_base = [ff(s) for s in raws]

for f in jpgs:
    if ff(f) in raws_base:
        print(['remove', f])
        # os.remove(f)
