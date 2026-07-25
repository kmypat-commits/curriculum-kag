from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.models.user import User
from app.services.auth import get_current_user


router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[3]
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")
MAX_DIFF_CHARS = 120_000


class GitFileStatus(BaseModel):
    path: str
    status: str


class GitCommit(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str


class GitOverview(BaseModel):
    branch: str
    clean: bool
    status_text: str
    changed_files: List[GitFileStatus]
    commits: List[GitCommit]


class CreateBranchRequest(BaseModel):
    branch_name: str = Field(min_length=1, max_length=80)


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git command timed out")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Git command failed").strip()
        raise HTTPException(status_code=500, detail=detail)
    return result.stdout.strip()


def _parse_status(text: str) -> List[GitFileStatus]:
    files: List[GitFileStatus] = []
    for line in text.splitlines():
        if not line:
            continue
        status = line[:2].strip() or "?"
        path = line[3:].strip()
        files.append(GitFileStatus(path=path, status=status))
    return files


def _parse_commits(text: str) -> List[GitCommit]:
    commits: List[GitCommit] = []
    for line in text.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        full_hash, short_hash, date, author, message = parts
        commits.append(
            GitCommit(
                hash=full_hash,
                short_hash=short_hash,
                message=message,
                author=author,
                date=date,
            )
        )
    return commits


def _bounded_diff(text: str) -> dict:
    if len(text) <= MAX_DIFF_CHARS:
        return {"diff": text, "truncated": False, "max_chars": MAX_DIFF_CHARS}
    return {
        "diff": text[:MAX_DIFF_CHARS]
        + "\n\n... Diff обрезан для безопасности интерфейса. Используйте Git CLI для полного вывода.",
        "truncated": True,
        "max_chars": MAX_DIFF_CHARS,
    }


@router.get("/overview", response_model=GitOverview)
async def git_overview(current_user: User = Depends(get_current_user)):
    branch = _git("branch", "--show-current") or "detached HEAD"
    status_raw = _git("status", "--porcelain")
    commits_raw = _git(
        "log",
        "-20",
        "--date=iso-strict",
        "--pretty=format:%H%x1f%h%x1f%ad%x1f%an%x1f%s",
    )
    changed_files = _parse_status(status_raw)
    return GitOverview(
        branch=branch,
        clean=len(changed_files) == 0,
        status_text="Чисто" if not changed_files else "Есть незакоммиченные изменения",
        changed_files=changed_files,
        commits=_parse_commits(commits_raw),
    )


@router.get("/commits/{commit_hash}/diff")
async def commit_diff(commit_hash: str, current_user: User = Depends(get_current_user)):
    _git("rev-parse", "--verify", f"{commit_hash}^{{commit}}")
    payload = _bounded_diff(_git("show", "--stat", "--patch", "--find-renames", commit_hash))
    return {"commit": commit_hash, **payload}


@router.get("/commits/{commit_hash}/compare-current")
async def compare_with_current(commit_hash: str, current_user: User = Depends(get_current_user)):
    _git("rev-parse", "--verify", f"{commit_hash}^{{commit}}")
    payload = _bounded_diff(_git("diff", "--stat", "--patch", "--find-renames", f"{commit_hash}..HEAD"))
    return {"commit": commit_hash, **payload}


@router.post("/commits/{commit_hash}/branches")
async def create_branch_from_commit(
    commit_hash: str,
    payload: CreateBranchRequest,
    current_user: User = Depends(get_current_user),
):
    _git("rev-parse", "--verify", f"{commit_hash}^{{commit}}")
    branch_name = payload.branch_name.strip()
    if (
        not BRANCH_RE.fullmatch(branch_name)
        or branch_name.startswith(("/", "-"))
        or branch_name.endswith("/")
        or ".." in branch_name
        or "@{" in branch_name
        or "//" in branch_name
    ):
        raise HTTPException(status_code=400, detail="Некорректное имя ветки")
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=REPO_ROOT,
        check=False,
    )
    if existing.returncode == 0:
        raise HTTPException(status_code=409, detail="Такая ветка уже существует")
    _git("branch", branch_name, commit_hash)
    return {"branch": branch_name, "commit": commit_hash, "created": True}
