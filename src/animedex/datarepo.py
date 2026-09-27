"""Private data backups (owner ruling 2026-09-27).

The code repo is public, so data that must stay private (canonical profiles, blind-review files, gold
annotations, later the Studio) lives in the private repo `Kingsley-Cyber/animedex-data` instead:

- `make data-push [TAG=m3-complete]` mirrors the listed paths into a local clone, commits, pushes, and
  gives the data repo the same milestone tag as the code, so code and data versions always pair.
- `make data-pull` restores those paths from the data repo (it never deletes local files).
- Cache and raw run logs are skipped: they are large and can be rebuilt.
- After every batch run the batch runner pushes too, once the local clone exists (a first manual
  `make data-push` creates it), so tests and fresh checkouts never touch the network.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animedex.paths import Paths

DEFAULT_PATHS = ("data/canonical", "data/blind", "data/diagnose", "data/backtest", "data/commentary", "eval/audit",
                 "eval/blind", "eval/gold", "steering", "seeds", "studio")
GH_AUTH = ("-c", "credential.helper=!gh auth git-credential")  # https pushes use the gh login
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


class DataRepoError(RuntimeError):
    pass


@dataclass(frozen=True)
class DataRepoConfig:
    remote: str
    clone: Path
    paths: tuple[str, ...]
    push_after_batch: bool = True


@dataclass
class PushResult:
    changed: int
    committed: bool
    head: str
    tag: str | None


def load_config(paths: Paths, settings: Any) -> DataRepoConfig | None:
    cfg = (getattr(settings, "model_extra", None) or {}).get("data_repo")
    if not cfg or not cfg.get("remote"):
        return None
    clone = Path(cfg.get("clone") or "../animedex-data")
    return DataRepoConfig(remote=str(cfg["remote"]), clone=(paths.root / clone).resolve(),
                          paths=tuple(cfg.get("paths") or DEFAULT_PATHS),
                          push_after_batch=bool(cfg.get("push_after_batch", True)))


def _git(clone: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *GH_AUTH, "-C", str(clone), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise DataRepoError(f"git {args[0]}: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def ensure_clone(cfg: DataRepoConfig) -> None:
    """Clone the data repo once; an empty remote gets a `main` branch on the first push."""
    if (cfg.clone / ".git").is_dir():
        return
    cfg.clone.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["git", *GH_AUTH, "clone", "-q", cfg.remote, str(cfg.clone)], capture_output=True, text=True)
    if done.returncode != 0:
        raise DataRepoError(f"git clone {cfg.remote}: {done.stderr.strip()[:300]}")
    if not _git(cfg.clone, "rev-parse", "--verify", "-q", "HEAD", check=False):
        _git(cfg.clone, "symbolic-ref", "HEAD", "refs/heads/main")


def mirror(src_root: Path, dst_root: Path, rel_paths: tuple[str, ...], *, delete: bool = True) -> int:
    """Copy the listed paths from src to dst. With `delete`, files gone from src are removed from dst,
    but only inside those paths. A path missing from src (e.g. `studio/` before it exists) is left
    alone. Returns the number of files written or removed."""
    changed = 0
    for rel in rel_paths:
        src, dst = src_root / rel, dst_root / rel
        if not src.exists():
            continue
        wanted = {p.relative_to(src) for p in src.rglob("*") if p.is_file()}
        for name in sorted(wanted):
            s, d = src / name, dst / name
            if not d.is_file() or d.read_bytes() != s.read_bytes():
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
                changed += 1
        if delete and dst.exists():
            for p in sorted(dst.rglob("*")):
                if p.is_file() and p.relative_to(dst) not in wanted:
                    p.unlink()
                    changed += 1
    return changed


def _code_head(root: Path) -> str:
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return done.stdout.strip() or "unknown"


def push(paths: Paths, cfg: DataRepoConfig, *, tag: str | None = None) -> PushResult:
    ensure_clone(cfg)
    has_remote_main = bool(_git(cfg.clone, "ls-remote", "--heads", "origin", "main", check=False))
    if has_remote_main:
        _git(cfg.clone, "pull", "-q", "--ff-only", "origin", "main")
    changed = mirror(paths.root, cfg.clone, cfg.paths)
    _git(cfg.clone, "add", "-A")
    committed = bool(_git(cfg.clone, "status", "--porcelain"))
    code = _code_head(paths.root)
    if committed:
        when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        _git(cfg.clone, "commit", "-q", "-m", f"data: {when}; code {code}" + (f"; {tag}" if tag else ""),
             "-m", TRAILER)
    head = _git(cfg.clone, "rev-parse", "--short", "HEAD", check=False)
    if not head:
        raise DataRepoError("nothing to back up yet: none of the listed paths has files")
    _git(cfg.clone, "push", "-q", "-u", "origin", "HEAD:main")
    if tag:
        existing = _git(cfg.clone, "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
        if existing and not existing.startswith(_git(cfg.clone, "rev-parse", "HEAD")):
            raise DataRepoError(f"tag {tag} already marks another data commit; pick a new tag")
        if not existing:
            _git(cfg.clone, "tag", "-a", tag, "-m", f"data for code tag {tag} (code {code})")
        _git(cfg.clone, "push", "-q", "origin", f"refs/tags/{tag}")
    return PushResult(changed=changed, committed=committed, head=head, tag=tag)


def pull(paths: Paths, cfg: DataRepoConfig) -> int:
    """Restore the listed paths from the data repo; local files are updated, never deleted."""
    ensure_clone(cfg)
    if _git(cfg.clone, "ls-remote", "--heads", "origin", "main", check=False):
        _git(cfg.clone, "pull", "-q", "--ff-only", "origin", "main")
    return mirror(cfg.clone, paths.root, cfg.paths, delete=False)


def push_after_batch(paths: Paths, settings: Any) -> str | None:
    """Best-effort backup at the end of a batch run; only once the local clone exists."""
    cfg = load_config(paths, settings)
    if cfg is None or not cfg.push_after_batch or not (cfg.clone / ".git").is_dir():
        return None
    try:
        res = push(paths, cfg)
    except DataRepoError as exc:
        return f"data backup failed: {exc}"
    return f"data backup: {res.changed} file(s) changed, data repo at {res.head}"
