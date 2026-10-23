"""Bounded, offline checks of the curated public package, not the full study.

Prints issue locations/classes, never matched credential strings. Pattern
screening and manifest checks are useful safeguards, not a security guarantee.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "publication/PUBLIC_MANIFEST.json"
TEXT_SUFFIXES = {".py", ".md", ".json", ".csv", ".toml", ".txt", ".yml", ".yaml", ".svg", ".lock"}
PRIVATE_PARTS = {".aws", ".ssh", "previous codebases", "node_modules", "__pycache__", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".parquet", ".grib", ".grib2", ".nc", ".npz", ".npy", ".pt", ".pth", ".ckpt", ".safetensors", ".pem", ".key", ".pkl", ".joblib", ".docx", ".pdf"}
# Construct markers so the scanner does not flag its own pattern definitions.
SECRET_RULES = {
    "private-key": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b" + "gh[pousr]_" + r"[A-Za-z0-9]{30,}\b|\b" + "github_pat_" + r"[A-Za-z0-9_]{30,}\b"),
    "aws-access-key": re.compile(r"\b(?:" + "AKIA|ASIA" + r")[A-Z0-9]{16}\b"),
    "openai-token": re.compile(r"\b" + "sk-" + r"[A-Za-z0-9_-]{32,}\b"),
    "personal-home-path": re.compile("/" + r"(?:Users|home)/[A-Za-z0-9_.-]+/"),
}


def shipped_files():
    for path in sorted(ROOT.rglob("*")):
        parts = path.relative_to(ROOT).parts
        if ".git" in parts or any(p.startswith(".venv") for p in parts):
            continue
        if path.is_symlink():
            yield path
        elif path.is_file():
            yield path


def local_links(text):
    # Ignore fenced examples, inline code, and reference syntax inside code.
    text = re.sub(r"```[^\n]*\n.*?```|~~~[^\n]*\n.*?~~~", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    for match in re.finditer(r"!?\[[^\]\n]*\]\((<[^>\n]+>|[^)\n]+)\)", text):
        target = match.group(1).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        else:
            target = re.sub(r'\s+"[^\"]*"$', "", target)
        yield target
    for match in re.finditer(r'<(?:img|a)\b[^>]*\b(?:src|href)=["\']([^"\']+)["\']', text):
        yield match.group(1)


def check():
    issues = []
    python_count = link_count = text_count = hashed = 0
    files = list(shipped_files())
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            issues.append(f"{rel}: symlinks are not allowed")
            continue
        if any(p in PRIVATE_PARTS for p in path.relative_to(ROOT).parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            issues.append(f"{rel}: excluded artifact class")
        if path.name.startswith(".env") and path.name != ".env.example":
            issues.append(f"{rel}: environment-secret file")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"LICENSE", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8")
        text_count += 1
        for label, pattern in SECRET_RULES.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                issues.append(f"{rel}:{line}: {label}")
        if path.suffix == ".py":
            ast.parse(text, filename=rel)
            python_count += 1
        if path.suffix == ".md":
            for target in local_links(text):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = (path.parent / unquote(parsed.path)).resolve()
                if not destination.is_relative_to(ROOT) or not destination.exists():
                    issues.append(f"{rel}: broken/outside local link: {target}")
                link_count += 1
    manifest_path = ROOT / MANIFEST
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        expected = {item["path"]: item for item in manifest["files"]}
        actual = {p.relative_to(ROOT).as_posix(): p for p in files if p != manifest_path}
        for name in sorted(set(expected) ^ set(actual)):
            issues.append(f"{name}: manifest membership mismatch")
        for name in sorted(set(expected) & set(actual)):
            digest = hashlib.sha256(actual[name].read_bytes()).hexdigest()
            if digest != expected[name]["public_sha256"]:
                issues.append(f"{name}: public hash mismatch")
            hashed += 1
    else:
        issues.append("Publication manifest is absent")
    return {"status": "PASS" if not issues else "FAIL", "files": len(files),
            "text_files_screened": text_count, "python_sources_parsed": python_count,
            "local_link_targets_checked": link_count, "public_file_hashes_checked": hashed,
            "checks_do_not_read_individual_truth_or_fit_models": True,
            "limitations": "Pattern screening is not a guarantee; anchor semantics and remote URLs require review.",
            "issues": issues}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)
