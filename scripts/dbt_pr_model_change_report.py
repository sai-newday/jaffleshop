#!/usr/bin/env python3
"""Analyze changed dbt model SQL files in a PR and post a GitHub comment.

This script compares base/head revisions for changed model SQL files, classifies
whether each model changed in SELECT columns, non-column SQL, or both, and
includes dbt node metadata from target/manifest.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib import error, request

COMMENT_MARKER = "<!-- dbt-model-change-report -->"


@dataclass
class SelectInfo:
    start_line: int
    end_line: int
    columns: Dict[str, str]


@dataclass
class ModelAnalysis:
    file_path: str
    model_name: str
    unique_id: str
    change_type: str
    added_columns: List[str]
    removed_columns: List[str]
    modified_columns: List[str]
    node: dict


def run_git(args: List[str]) -> str:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def read_git_file(rev: str, file_path: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "show", f"{rev}:{file_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def normalize_sql_expr(expr: str) -> str:
    expr = re.sub(r"\s+", " ", expr.strip())
    return expr.lower()


def split_top_level_by_comma(text: str) -> List[str]:
    items: List[str] = []
    buff: List[str] = []
    depth = 0
    quote: Optional[str] = None

    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buff.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and i + 1 < len(text):
                i += 1
                buff.append(text[i])
        else:
            if ch in ("'", '"', "`"):
                quote = ch
                buff.append(ch)
            elif ch == "(":
                depth += 1
                buff.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1)
                buff.append(ch)
            elif ch == "," and depth == 0:
                piece = "".join(buff).strip()
                if piece:
                    items.append(piece)
                buff = []
            else:
                buff.append(ch)
        i += 1

    piece = "".join(buff).strip()
    if piece:
        items.append(piece)

    return items


def infer_column_name(expr: str) -> str:
    alias_match = re.search(r"(?is)\bas\s+([a-zA-Z_][\w$]*)\s*$", expr)
    if alias_match:
        return alias_match.group(1).lower()

    cleaned = expr.strip()
    tail_match = re.search(r"([a-zA-Z_][\w$]*)\s*$", cleaned)
    if tail_match:
        return tail_match.group(1).lower()

    return normalize_sql_expr(expr)


def find_main_select_columns(sql: str) -> Optional[SelectInfo]:
    lowered = sql.lower()
    depth = 0
    quote: Optional[str] = None
    select_positions: List[int] = []

    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and i + 1 < len(sql):
                i += 1
        else:
            if ch in ("'", '"', "`"):
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and lowered.startswith("select", i):
                before_ok = i == 0 or not lowered[i - 1].isalnum()
                after_idx = i + 6
                after_ok = after_idx >= len(lowered) or not lowered[after_idx].isalnum()
                if before_ok and after_ok:
                    select_positions.append(i)
        i += 1

    if not select_positions:
        return None

    select_idx = select_positions[-1]
    j = select_idx + 6

    depth = 0
    quote = None
    from_idx: Optional[int] = None
    while j < len(sql):
        ch = sql[j]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and j + 1 < len(sql):
                j += 1
        else:
            if ch in ("'", '"', "`"):
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and lowered.startswith("from", j):
                before_ok = j == 0 or not lowered[j - 1].isalnum()
                after_idx = j + 4
                after_ok = after_idx >= len(lowered) or not lowered[after_idx].isalnum()
                if before_ok and after_ok:
                    from_idx = j
                    break
        j += 1

    if from_idx is None:
        return None

    columns_text = sql[select_idx + 6 : from_idx]

    select_start_line = sql.count("\n", 0, select_idx) + 1
    from_line = sql.count("\n", 0, from_idx) + 1

    columns: Dict[str, str] = {}
    for part in split_top_level_by_comma(columns_text):
        col_name = infer_column_name(part)
        columns[col_name] = normalize_sql_expr(part)

    if not columns:
        return None

    return SelectInfo(
        start_line=select_start_line,
        end_line=max(select_start_line, from_line - 1),
        columns=columns,
    )


def parse_unified_diff_ranges(diff_text: str) -> Tuple[List[int], List[int]]:
    base_changed: List[int] = []
    head_changed: List[int] = []

    for line in diff_text.splitlines():
        if not line.startswith("@@"):
            continue
        m = re.match(r"@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", line)
        if not m:
            continue
        b_start = int(m.group(1))
        b_len = int(m.group(2) or "1")
        h_start = int(m.group(3))
        h_len = int(m.group(4) or "1")

        if b_len > 0:
            base_changed.extend(range(b_start, b_start + b_len))
        if h_len > 0:
            head_changed.extend(range(h_start, h_start + h_len))

    return base_changed, head_changed


def in_range(lines: List[int], start: int, end: int) -> Tuple[bool, bool]:
    inside = False
    outside = False
    for ln in lines:
        if start <= ln <= end:
            inside = True
        else:
            outside = True
    return inside, outside


def map_file_to_node(manifest: dict, file_path: str) -> Tuple[str, dict]:
    nodes = manifest.get("nodes", {})
    for unique_id, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        if node.get("original_file_path") == file_path:
            return unique_id, node

    model_name = os.path.splitext(os.path.basename(file_path))[0]
    return f"model.unknown.{model_name}", {
        "name": model_name,
        "original_file_path": file_path,
        "note": "Node not found in manifest. Ensure dbt parse ran successfully.",
    }


def analyze_model_change(
    file_path: str,
    base_sql: Optional[str],
    head_sql: Optional[str],
    diff_text: str,
    node_info: Tuple[str, dict],
) -> ModelAnalysis:
    unique_id, node = node_info
    model_name = node.get("name") or os.path.splitext(os.path.basename(file_path))[0]

    base_select = find_main_select_columns(base_sql or "") if base_sql is not None else None
    head_select = find_main_select_columns(head_sql or "") if head_sql is not None else None

    base_cols = base_select.columns if base_select else {}
    head_cols = head_select.columns if head_select else {}

    added_cols = sorted([c for c in head_cols if c not in base_cols])
    removed_cols = sorted([c for c in base_cols if c not in head_cols])
    modified_cols = sorted([c for c in base_cols if c in head_cols and base_cols[c] != head_cols[c]])

    base_changed, head_changed = parse_unified_diff_ranges(diff_text)

    inside_base = outside_base = False
    inside_head = outside_head = False

    if base_changed:
        if base_select:
            inside_base, outside_base = in_range(base_changed, base_select.start_line, base_select.end_line)
        else:
            outside_base = True

    if head_changed:
        if head_select:
            inside_head, outside_head = in_range(head_changed, head_select.start_line, head_select.end_line)
        else:
            outside_head = True

    column_change = bool(added_cols or removed_cols or modified_cols or inside_base or inside_head)
    non_column_change = bool(outside_base or outside_head)

    if column_change and non_column_change:
        change_type = "both (columns + other SQL)"
    elif column_change:
        change_type = "columns_only"
    elif non_column_change:
        change_type = "other_sql_only"
    else:
        change_type = "undetermined"

    return ModelAnalysis(
        file_path=file_path,
        model_name=model_name,
        unique_id=unique_id,
        change_type=change_type,
        added_columns=added_cols,
        removed_columns=removed_cols,
        modified_columns=modified_cols,
        node=node,
    )


def build_comment(analyses: List[ModelAnalysis], changed_files: List[str]) -> str:
    lines: List[str] = [
        COMMENT_MARKER,
        "## dbt Model Change Report",
        "",
        f"Changed files in PR: {len(changed_files)}",
        f"Changed dbt model SQL files: {len(analyses)}",
        "",
    ]

    if not analyses:
        lines.append("No changes were detected in `models/**/*.sql` files.")
        return "\n".join(lines)

    for item in analyses:
        lines.extend(
            [
                f"### {item.model_name}",
                f"- Model file: `{item.file_path}`",
                f"- Model unique_id: `{item.unique_id}`",
                f"- Type of change: **{item.change_type}**",
            ]
        )

        if item.added_columns or item.removed_columns or item.modified_columns:
            lines.append("- Column changes:")
            lines.append(
                f"  - Added: {', '.join(item.added_columns) if item.added_columns else '(none)'}"
            )
            lines.append(
                f"  - Removed: {', '.join(item.removed_columns) if item.removed_columns else '(none)'}"
            )
            lines.append(
                f"  - Modified: {', '.join(item.modified_columns) if item.modified_columns else '(none)'}"
            )
        else:
            lines.append("- Column changes: (none detected)")

        node_json = json.dumps(item.node, indent=2, sort_keys=True)
        lines.append("<details>")
        lines.append("<summary>Node details</summary>")
        lines.append("")
        lines.append("```json")
        lines.append(node_json)
        lines.append("```")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def github_api_request(method: str, url: str, token: str, data: Optional[dict] = None) -> dict:
    payload = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=payload, method=method, headers=headers)
    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code}: {detail}") from exc


def upsert_pr_comment(repository: str, pr_number: str, body: str, token: str) -> None:
    comments_url = f"https://api.github.com/repos/{repository}/issues/{pr_number}/comments"
    comments = github_api_request("GET", comments_url, token)

    existing = None
    for c in comments:
        if COMMENT_MARKER in c.get("body", ""):
            existing = c
            break

    if existing:
        update_url = f"https://api.github.com/repos/{repository}/issues/comments/{existing['id']}"
        github_api_request("PATCH", update_url, token, {"body": body})
        print(f"Updated existing PR comment: {existing['id']}")
    else:
        github_api_request("POST", comments_url, token, {"body": body})
        print("Created new PR comment")


def main() -> int:
    base_sha = os.environ.get("BASE_SHA")
    head_sha = os.environ.get("HEAD_SHA")
    repository = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    token = os.environ.get("GITHUB_TOKEN")

    if not all([base_sha, head_sha, repository, pr_number, token]):
        print("Missing required environment variables.", file=sys.stderr)
        return 2

    manifest_path = os.environ.get("MANIFEST_PATH", "target/manifest.json")
    if not os.path.exists(manifest_path):
        print(f"Manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    changed_output = run_git(["diff", "--name-only", base_sha, head_sha])
    changed_files = [line.strip() for line in changed_output.splitlines() if line.strip()]

    model_files = [p for p in changed_files if p.startswith("models/") and p.endswith(".sql")]

    analyses: List[ModelAnalysis] = []
    for model_file in model_files:
        diff_text = run_git(["diff", "--unified=0", base_sha, head_sha, "--", model_file])
        base_sql = read_git_file(base_sha, model_file)
        head_sql = read_git_file(head_sha, model_file)

        node_info = map_file_to_node(manifest, model_file)
        analyses.append(analyze_model_change(model_file, base_sql, head_sql, diff_text, node_info))

    body = build_comment(analyses, changed_files)
    upsert_pr_comment(repository, pr_number, body, token)

    summary = {
        "changed_files": len(changed_files),
        "changed_model_files": len(model_files),
        "analyzed_models": len(analyses),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
