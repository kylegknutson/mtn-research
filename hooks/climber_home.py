"""MkDocs hook: map a per-climber home page (index.<climber>.md) to the site root.

A friend's site shares the same docs_dir as Kyle's, so it can't also have an
`index.md` (that's Kyle's). Their home is `index.<climber>.md`; mkdocs would build
that to `/index.<climber>/` and leave the site root without an index.html (404).

This hook finds the build's `index.*.md` file and retargets it to the root
`index.html`, so `/<subpath>/` serves the friend's home.
"""
import os
import re


def on_files(files, config):
    for f in list(files):
        if re.fullmatch(r"index\.[a-z0-9_]+\.md", f.src_path):
            f.dest_path = "index.html"
            f.abs_dest_path = os.path.join(config["site_dir"], "index.html")
            f.url = "."
    return files
