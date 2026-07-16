"""gpx_root.py — resolve gpx/<slug> artifacts across a linked git worktree.

Why this exists (Kyle, 2026-07-15): the recorded GPX tracks and the composed
`*_recommended.gpx` routes are **gitignored** — they live only in the working tree,
never in a commit. `git worktree add` does NOT copy gitignored files, so a fresh
linked worktree has each report's tracked `peaks.yml` / `sources.json` but none of
its tracks or routes. Run from there, the source/route/map gates all "fail" on a
report that is actually complete in the main tree — a false negative that blocks an
unrelated prose fix (a Brown Mountain coordinate typo tripped exactly this).

The fix: when a gate is running inside a **linked** worktree, also look in the
**main** worktree's `gpx/`. A normal (non-worktree) checkout has `.git` as a
directory and gets no fallback — so behavior is byte-for-byte identical outside a
worktree, and CI (where gpx is absent everywhere) is unaffected.

Resolution is a per-file **union**, worktree-wins: a file the worktree DOES have
(e.g. an edited `peaks.yml`, or a route you just rebuilt here) shadows the main
tree's copy, and the main tree only fills the gaps (the gitignored tracks/routes).
That keeps the gates honest — edit a recipe here without rebuilding the route and
the recipe gate still compares your new recipe against the stale route, as before.

    from gpx_root import glob_gpx, gpx_file
    for f in glob_gpx(ROOT, slug, "*.gpx"): ...      # union glob, worktree wins
    sources = gpx_file(ROOT, slug, "sources.json")   # single file, worktree wins
"""
from __future__ import annotations
from pathlib import Path


def _main_tree(root: Path) -> Path | None:
    """The main worktree's root, iff `root` is a linked worktree whose main tree
    still has a `gpx/` dir; else None (normal checkout → no fallback)."""
    gitp = root / ".git"
    if not gitp.is_file():          # normal checkout has .git as a DIR → no fallback
        return None
    try:
        txt = gitp.read_text().strip()
    except OSError:
        return None
    if not txt.startswith("gitdir:"):
        return None
    gitdir = Path(txt.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    # gitdir = <main>/.git/worktrees/<name>  →  <main>/.git  →  <main>
    main = gitdir.parent.parent.parent
    return main if (main / "gpx").is_dir() else None


def main_tree(root: Path) -> Path | None:
    """The main worktree's root if `root` is a linked worktree (else None). Use when a
    check needs the REAL build state — e.g. file mtimes, which a `git checkout` into a
    linked worktree resets to checkout time and so can't be compared meaningfully."""
    return _main_tree(root)


def gpx_roots(root: Path) -> list[Path]:
    """gpx search roots, most-specific first: this tree's gpx, then (if `root` is a
    linked worktree) the main worktree's gpx."""
    roots = [root / "gpx"]
    mt = _main_tree(root)
    if mt is not None:
        roots.append(mt / "gpx")
    return roots


def glob_gpx(root: Path, slug: str, pattern: str) -> list[Path]:
    """Union of `gpx/<slug>/<pattern>` across gpx_roots(root); a filename found in an
    earlier (more-specific) root shadows the same name in a later one."""
    out: dict[str, Path] = {}
    for r in gpx_roots(root):
        d = r / slug
        if d.is_dir():
            for f in d.glob(pattern):
                out.setdefault(f.name, f)
    return list(out.values())


def gpx_file(root: Path, slug: str, relname: str) -> Path:
    """Path to `gpx/<slug>/<relname>`: the worktree's copy if it exists, else the main
    tree's, else the worktree path (so a caller's 'missing' message still points home)."""
    cands = [r / slug / relname for r in gpx_roots(root)]
    for c in cands:
        if c.exists():
            return c
    return cands[0]


def slug_dir(root: Path, slug: str) -> Path:
    """Best single `gpx/<slug>` directory: the first root whose slug dir exists and holds
    a gitignored track/route (`*.gpx`), else the worktree's slug dir. Prefer glob_gpx /
    gpx_file when you can — this is for callers that must pass one directory around."""
    for r in gpx_roots(root):
        d = r / slug
        if d.is_dir() and any(d.glob("*.gpx")):
            return d
    return root / "gpx" / slug
