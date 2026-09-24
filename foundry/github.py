"""Bounded, read-only GitHub evidence using the user's existing gh login.

Credentials remain with gh. No clone, checkout, install, build, shell, provider
call or execution of imported code occurs here.
"""

import base64
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import subprocess
from urllib.parse import quote

from .skillmap import empty_map
from .validation import Invalid, digest, require, words
from .workflow import now, uid

MAX_FILES = 8
MAX_FILE_BYTES = 20_000
MAX_TOTAL_BYTES = 80_000
SUFFIXES = {".rs", ".py", ".cpp", ".c", ".h", ".hpp", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".vhd", ".vhdl", ".sv", ".m", ".md"}
MANIFESTS = {"Cargo.toml", "pyproject.toml", "requirements.txt", "package.json", "CMakeLists.txt"}
SKIP_PARTS = {"node_modules", "vendor", "target", "dist", "build", ".git", ".github", ".claude", ".codex", ".agents", ".venv", "venv", "__pycache__"}


def repo_name(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value), "choose owner/repository")
    require(all(p not in (".", "..") for p in value.split("/")), "invalid repository name")
    return value


def code_path(path):
    if not isinstance(path, str) or not path or len(path) > 600 or any(ord(c) < 32 for c in path):
        return False
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or set(p.parts) & SKIP_PARTS:
        return False
    lower = path.casefold()
    if any(term in lower for term in ("secret", "credential", "token", "private_key", "id_rsa", ".env")):
        return False
    return p.suffix in SUFFIXES or p.name in MANIFESTS


class GitHub:
    def get(self, endpoint):
        require(endpoint.startswith(("user", "repos/")) and not endpoint.startswith("/"), "invalid GitHub endpoint")
        env = os.environ.copy()
        env.pop("GH_DEBUG", None)
        env.update(GH_PROMPT_DISABLED="1", GH_PAGER="cat")
        try:
            response = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint,
                                       "-H", "Accept: application/vnd.github+json"],
                                      capture_output=True, timeout=30, env=env, check=False)
        except FileNotFoundError as exc:
            raise Invalid("GitHub CLI (gh) is not installed. Install it separately, then sign in with gh auth login.") from exc
        except subprocess.TimeoutExpired as exc:
            raise Invalid("GitHub did not respond within 30 seconds. Nothing was imported; retry when connected.") from exc
        require(response.returncode == 0, "GitHub access failed. Check your connection and gh auth status; sign in with gh auth login if needed. No credential output is stored.")
        require(len(response.stdout) <= 8_000_000, "GitHub response exceeded the 8 MB budget")
        try:
            return json.loads(response.stdout)
        except (ValueError, UnicodeError) as exc:
            raise Invalid("GitHub returned an unreadable response") from exc

    def repositories(self, page=1):
        require(type(page) is int and 1 <= page <= 20, "invalid repository page")
        user = self.get("user")
        login = user["login"]
        repos = self.get(f"user/repos?affiliation=owner&per_page=100&page={page}&sort=updated")
        require(isinstance(repos, list), "invalid repository listing")
        # Personal owner repositories only; no organization or collaborator scan.
        return {"login": login, "page": page, "more": len(repos) == 100,
                "repositories": [{"name": r["full_name"], "private": r["private"], "archived": r["archived"]}
                                 for r in repos if r["owner"]["login"].casefold() == login.casefold()]}

    def inventory(self, repository):
        repository = repo_name(repository)
        meta = self.get("repos/" + repository)
        branch = meta["default_branch"]
        head = self.get(f"repos/{repository}/commits/{quote(branch, safe='')}")
        sha = head["sha"]
        require(re.fullmatch(r"[0-9a-f]{40}", sha), "invalid commit identity")
        tree = self.get(f"repos/{repository}/git/trees/{head['commit']['tree']['sha']}?recursive=1")
        history = self.get(f"repos/{repository}/commits?sha={sha}&per_page=20")
        candidates = [{"path": item["path"], "sha": item["sha"], "size": item.get("size", 0)} for item in tree["tree"]
                      if item["type"] == "blob" and item.get("mode") in ("100644", "100755") and code_path(item["path"])
                      and 0 < item.get("size", 0) <= MAX_FILE_BYTES]
        return {"repository": repository, "private": meta["private"], "branch": branch, "commit": sha,
                "captured_at": now(), "truncated": bool(tree.get("truncated")) or len(candidates) > 500,
                "files": sorted(candidates, key=lambda f: f["path"])[:500],
                "commits": [{"sha": c["sha"], "date": c["commit"]["author"]["date"],
                             "author": (c.get("author") or {}).get("login", "unattributed"),
                             "message": c["commit"]["message"][:1000]} for c in history[:20]]}

    def snapshot(self, inventory, selected_paths):
        repository = repo_name(inventory["repository"])
        require(isinstance(selected_paths, list) and 1 <= len(set(selected_paths)) == len(selected_paths) <= MAX_FILES,
                "choose one to eight distinct source files")
        available = {f["path"]: f for f in inventory["files"]}
        require(all(p in available and code_path(p) for p in selected_paths), "file outside the selected repository inventory")
        require(sum(available[p]["size"] for p in selected_paths) <= MAX_TOTAL_BYTES, "selected files exceed 80 KB; select fewer")
        files, total = [], 0
        for path in selected_paths:
            item = available[path]
            require(re.fullmatch(r"[0-9a-f]{40}", item["sha"]), "invalid blob identity")
            blob = self.get(f"repos/{repository}/git/blobs/{item['sha']}")
            require(blob.get("encoding") == "base64" and blob.get("sha") == item["sha"], "unexpected blob response")
            try:
                raw = base64.b64decode(blob["content"], validate=False)
                text = raw.decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise Invalid("Select UTF-8 source files") from exc
            require(hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == item["sha"], "GitHub blob hash mismatch")
            total += len(raw)
            require(0 < len(raw) <= MAX_FILE_BYTES and total <= MAX_TOTAL_BYTES, "selected source budget exceeded")
            words(text, "repository source", MAX_FILE_BYTES)
            files.append({**item, "text": text})
        return {**inventory, "files": files, "scope": "selected code files and at most 20 recent commit summaries; no execution"}


def import_snapshot(workflow, experience, snapshot):
    """Network work is finished before this atomic local transaction begins."""
    from .skillmap import catalog
    repo = repo_name(snapshot["repository"])
    require(re.fullmatch(r"[0-9a-f]{40}", snapshot["commit"]), "invalid snapshot commit")
    require(1 <= len(snapshot["files"]) <= MAX_FILES, "repository file budget exceeded")
    result = []
    def operation(state):
        entity = next((n for n in catalog(state)["nodes"] if n["id"] == experience and n["kind"] != "skill"), None)
        require(entity is not None, "choose the experience this repository describes")
        total = 0
        for file in snapshot["files"]:
            require(code_path(file["path"]), "unsupported repository file")
            words(file["text"], "repository source", MAX_FILE_BYTES)
            raw = file["text"].encode()
            total += len(raw)
            require(len(raw) <= MAX_FILE_BYTES and total <= MAX_TOTAL_BYTES, "repository source budget exceeded")
            require(hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == file["sha"], "source blob hash mismatch")
            origin = f"github:{repo}:{file['path']}"
            related = [s for s in state["core"]["sources"] if s["origin"] == origin]
            old = next((s for s in related if s["sha256"] == digest(file["text"])), None)
            if old:
                result.append(old["id"])
                continue
            sid = uid("repo-")
            locator = f"https://github.com/{repo}/blob/{snapshot['commit']}/{quote(file['path'], safe='/')}"
            state["core"]["sources"].append({"id": sid, "kind": "observation", "origin": origin,
                "version": max((s["version"] for s in related), default=0) + 1, "text": file["text"],
                "sha256": digest(file["text"]), "locator": locator, "parents": []})
            result.append(sid)
        # Preserve bounded commit context as an observation, not proof that the
        # named author wrote or understands every line (AI/shared work exists).
        history = json.dumps({"repository": repo, "commit": snapshot["commit"], "captured_at": snapshot["captured_at"],
                              "commits": snapshot["commits"], "scope": snapshot["scope"],
                              "selected_files": [{"path": f["path"], "sha": f["sha"]} for f in snapshot["files"]]}, ensure_ascii=False, indent=2)
        related = [s for s in state["core"]["sources"] if s["origin"] == f"github:{repo}:history"]
        prior = next((s for s in related if s["sha256"] == digest(history)), None)
        if prior:
            sid = prior["id"]
            if any(c["id"] in entity["claim_ids"] and any(r["source"] == sid for r in c["sources"]) for c in state["core"]["claims"]):
                return
        else:
            sid = uid("repo-history-")
            state["core"]["sources"].append({"id": sid, "kind": "observation", "origin": f"github:{repo}:history", "version": max((s["version"] for s in related), default=0) + 1,
                "text": history, "sha256": digest(history), "locator": f"https://github.com/{repo}/commits/{snapshot['commit']}", "parents": []})
        cid = uid("c-")
        statement = f"Repository evidence selected for {entity['label']}: {repo} at {snapshot['commit']}. Code presence and commit attribution do not establish personal proficiency."
        state["core"]["claims"].append({"id": cid, "key": cid, "facet": "observed_activity", "kind": "observed",
            "text": statement, "stance": "asserts", "confidence": "strong", "status": "active",
            "sources": [{"source": sid, "quote": history}, *[{"source": s, "quote": next(v for v in state['core']['sources'] if v['id'] == s)['text'][:300]} for s in result]], "contradicts": []})
        saved = state.setdefault("skillmap", empty_map())
        manual = next((n for n in saved["entities"] if n["id"] == experience), None)
        if manual:
            manual["claim_ids"].append(cid)
        else:
            saved["entities"].append({k: entity[k] for k in ("id", "kind", "label", "category") } | {"claim_ids": [cid]})
    workflow.update(operation, "explicit selected GitHub evidence import; code never executed, no skill depth inferred")
    return result


def stage_findings(workflow, experience, findings, *, model):
    """Stage a manually authored assessment citing imported code, never mastery.

    Called after an explicitly scoped manual review. No provider is invoked.
    Findings are proposed code topics; the user reviews them through Review.
    """
    from .skillmap import catalog, SKILL_TYPES
    from .workflow import possible_matches
    require(isinstance(findings, list) and 1 <= len(findings) <= 12, "supply one to twelve code findings")
    words(model, "assessment model", 200)
    result = []
    def operation(state):
        entity = next((n for n in catalog(state)["nodes"] if n["id"] == experience and n["kind"] != "skill"), None)
        require(entity is not None, "unknown experience")
        attached_sources = {r["source"] for c in state["core"]["claims"] if c["id"] in entity["claim_ids"] for r in c["sources"]}
        sources = {s["id"]: s for s in state["core"]["sources"]}
        for finding in findings:
            words(finding["skill"], "code topic", 200)
            words(finding["text"], "finding", 3000)
            words(finding["question"], "contribution question", 1000)
            require(finding["category"] in SKILL_TYPES, "unknown code topic category")
            require(1 <= len(finding["sources"]) <= 8, "cite selected code")
            require(all(r["source"] in attached_sources and r["source"] in sources and sources[r["source"]]["origin"].startswith("github:")
                        and r["quote"] and r["quote"] in sources[r["source"]]["text"] for r in finding["sources"]), "finding needs exact imported repository passages")
            text = finding["text"] + " Personal contribution, depth and assistance remain unconfirmed."
            key = "code-topic-" + digest(experience + finding["skill"] + text)[:24]
            if any(p["claim"]["key"] == key for p in state["proposals"]):
                continue
            claim = {"key": key, "facet": "observed_activity", "kind": "interpretation", "text": text,
                     "stance": "asserts", "confidence": "moderate", "sources": finding["sources"]}
            pid = uid("p-")
            state["proposals"].append({"id": pid, "claim": claim, "status": "proposed", "matches": possible_matches(claim, state),
                "run_id": "manual-code-review-v1", "core_id": None, "replacement": None,
                "note": "Selected repository code review; " + model + "; awaiting your review. Code was not executed."})
            state.setdefault("skillmap", empty_map()).setdefault("findings", []).append({"id": uid("finding-"),
                "experience": experience, "skill": finding["skill"], "category": finding["category"], "proposal": pid,
                "question": finding["question"], "model": model, "at": now()})
            result.append(pid)
    workflow.update(operation, "manual selected-code assessment staged for review; no proficiency or authorship inferred")
    return result
