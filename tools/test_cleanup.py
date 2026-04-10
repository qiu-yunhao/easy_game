from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import logging
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import tomllib


DEFAULT_CONFIG: dict[str, Any] = {
    "scan": {
        "root": "tests",
        "include": ["test_*.py", "*_test.py"],
        "exclude": [
            "__pycache__/**",
            "**/__pycache__/**",
            "_archive/**",
            "**/_archive/**",
            "_cleanup_reports/**",
            "**/_cleanup_reports/**",
        ],
    },
    "decision": {
        "min_score": 3,
        "comment_lookback_lines": 4,
        "require_all_test_cases": True,
        "allow_file_level_cleanup": True,
    },
    "archive": {
        "root": "tests/_archive",
        "report_root": "tests/_cleanup_reports",
        "purge_after_days": 30,
    },
    "rules": {
        "age": {
            "enabled": True,
            "stale_days": 180,
            "score": 1,
        },
        "decorators": {
            "enabled": True,
            "candidate": [
                "deprecated_test",
                "obsolete_test",
                "cleanup_candidate",
                "pytest.mark.expired",
                "pytest.mark.deprecated",
                "pytest.mark.cleanup_candidate",
            ],
            "protect": [
                "do_not_cleanup",
                "pytest.mark.keep",
                "pytest.mark.smoke",
                "pytest.mark.critical",
            ],
            "score": 4,
        },
        "comments": {
            "enabled": True,
            "candidate_keywords": [
                "cleanup: obsolete",
                "cleanup: expired",
                "cleanup: deprecated",
                "status: obsolete",
                "status: deprecated",
            ],
            "protect_keywords": [
                "cleanup: keep",
                "do-not-cleanup",
                "active-test",
            ],
            "score": 3,
        },
        "expiry": {
            "enabled": True,
            "date_patterns": [
                r"(?i)cleanup:\s*expire(?:-on)?\s*=\s*(?P<date>\d{4}-\d{2}-\d{2})",
                r"(?i)@expires\s*(?P<date>\d{4}-\d{2}-\d{2})",
                r"(?i)TODO_REMOVE_BEFORE\s*(?P<date>\d{4}-\d{2}-\d{2})",
            ],
            "score": 5,
        },
        "paths": {
            "enabled": True,
            "candidate": [
                "legacy/**",
                "**/legacy/**",
                "deprecated/**",
                "**/deprecated/**",
            ],
            "protect": [
                "smoke/**",
                "**/smoke/**",
                "sanity/**",
                "**/sanity/**",
            ],
            "score": 2,
        },
    },
}


@dataclass
class Reason:
    rule: str
    score: int
    message: str
    evidence: str
    level: str = "candidate"


@dataclass
class CaseDecision:
    name: str
    kind: str
    start_line: int
    end_line: int
    decorators: list[str]
    score: int
    candidate: bool
    protected: bool
    reasons: list[Reason] = field(default_factory=list)
    protected_by: list[Reason] = field(default_factory=list)


@dataclass
class FileDecision:
    path: str
    absolute_path: str
    modified_at: str
    age_days: int
    score: int
    candidate: bool
    protected: bool
    action: str
    rationale: str
    reasons: list[Reason] = field(default_factory=list)
    protected_by: list[Reason] = field(default_factory=list)
    cases: list[CaseDecision] = field(default_factory=list)


def merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path | None) -> tuple[dict[str, Any], str | None]:
    if config_path is None:
        return DEFAULT_CONFIG, None

    with config_path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return merge_dict(DEFAULT_CONFIG, loaded), str(config_path.resolve())


def resolve_path(root: Path, configured: str) -> Path:
    target = Path(configured)
    if target.is_absolute():
        return target
    return (root / target).resolve()


def to_posix_path(path: Path) -> str:
    return path.as_posix()


def path_matches(path_value: str, patterns: list[str]) -> str | None:
    normalized = path_value.replace("\\", "/")
    name = PurePosixPath(normalized).name
    for pattern in patterns:
        cleaned = pattern.replace("\\", "/")
        if (
            fnmatch.fnmatchcase(normalized, cleaned)
            or fnmatch.fnmatchcase(name, cleaned)
            or PurePosixPath(normalized).match(cleaned)
        ):
            return cleaned
    return None


def value_matches(value: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatchcase(value, pattern):
            return pattern
    return None


def append_reason(target: list[Reason], reason: Reason) -> None:
    exists = any(
        item.rule == reason.rule
        and item.message == reason.message
        and item.evidence == reason.evidence
        and item.level == reason.level
        for item in target
    )
    if not exists:
        target.append(reason)


def extract_decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return extract_decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = extract_decorator_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def is_test_function(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")


def discover_test_cases(tree: ast.Module) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    for node in tree.body:
        if is_test_function(node):
            discovered.append(
                {
                    "name": node.name,
                    "kind": "function",
                    "start_line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "decorators": [extract_decorator_name(item) for item in node.decorator_list if extract_decorator_name(item)],
                }
            )
            continue

        if isinstance(node, ast.ClassDef):
            class_decorators = [
                extract_decorator_name(item) for item in node.decorator_list if extract_decorator_name(item)
            ]
            for child in node.body:
                if is_test_function(child):
                    discovered.append(
                        {
                            "name": f"{node.name}.{child.name}",
                            "kind": "method",
                            "start_line": child.lineno,
                            "end_line": child.end_lineno or child.lineno,
                            "decorators": class_decorators
                            + [extract_decorator_name(item) for item in child.decorator_list if extract_decorator_name(item)],
                        }
                    )
    return discovered


def find_test_files(project_root: Path, config: dict[str, Any]) -> list[Path]:
    scan_cfg = config["scan"]
    scan_root = resolve_path(project_root, scan_cfg["root"])
    include = scan_cfg["include"]
    exclude = scan_cfg["exclude"]
    if not scan_root.exists():
        return []

    files: list[Path] = []
    for path in scan_root.rglob("*.py"):
        if not path.is_file():
            continue
        relative = to_posix_path(path.relative_to(scan_root))
        if path_matches(relative, exclude):
            continue
        if not path_matches(relative, include):
            continue
        files.append(path)
    return sorted(files)


def get_text_window(lines: list[str], start_line: int, end_line: int, lookback: int) -> str:
    start_index = max(0, start_line - 1 - lookback)
    end_index = min(len(lines), end_line)
    return "\n".join(lines[start_index:end_index])


def parse_iso_date(raw_value: str) -> date | None:
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def build_reason(rule: str, score: int, message: str, evidence: str, level: str) -> Reason:
    return Reason(rule=rule, score=score, message=message, evidence=evidence, level=level)


def evaluate_signals(
    *,
    text: str,
    decorators: list[str],
    relative_path: str,
    age_days: int | None,
    today: date,
    config: dict[str, Any],
) -> tuple[list[Reason], list[Reason]]:
    rules = config["rules"]
    reasons: list[Reason] = []
    protected: list[Reason] = []
    lower_text = text.lower()

    age_rule = rules["age"]
    if age_days is not None and age_rule["enabled"] and age_days >= age_rule["stale_days"]:
        append_reason(
            reasons,
            build_reason(
                rule="age",
                score=age_rule["score"],
                message=f"last modified {age_days} days ago",
                evidence=f">= {age_rule['stale_days']} days",
                level="candidate",
            ),
        )

    decorator_rule = rules["decorators"]
    if decorator_rule["enabled"]:
        for decorator in decorators:
            matched = value_matches(decorator, decorator_rule["candidate"])
            if matched:
                append_reason(
                    reasons,
                    build_reason(
                        rule="decorator",
                        score=decorator_rule["score"],
                        message=f"matched cleanup decorator '{decorator}'",
                        evidence=matched,
                        level="candidate",
                    ),
                )
            protected_match = value_matches(decorator, decorator_rule["protect"])
            if protected_match:
                append_reason(
                    protected,
                    build_reason(
                        rule="decorator",
                        score=0,
                        message=f"matched keep decorator '{decorator}'",
                        evidence=protected_match,
                        level="protect",
                    ),
                )

    comment_rule = rules["comments"]
    if comment_rule["enabled"]:
        for keyword in comment_rule["candidate_keywords"]:
            if keyword.lower() in lower_text:
                append_reason(
                    reasons,
                    build_reason(
                        rule="comment",
                        score=comment_rule["score"],
                        message=f"matched cleanup keyword '{keyword}'",
                        evidence=keyword,
                        level="candidate",
                    ),
                )
        for keyword in comment_rule["protect_keywords"]:
            if keyword.lower() in lower_text:
                append_reason(
                    protected,
                    build_reason(
                        rule="comment",
                        score=0,
                        message=f"matched keep keyword '{keyword}'",
                        evidence=keyword,
                        level="protect",
                    ),
                )

    expiry_rule = rules["expiry"]
    if expiry_rule["enabled"]:
        for pattern in expiry_rule["date_patterns"]:
            for match in re.finditer(pattern, text):
                expiry_date = parse_iso_date(match.group("date"))
                if expiry_date is None:
                    continue
                if expiry_date < today:
                    append_reason(
                        reasons,
                        build_reason(
                            rule="expiry",
                            score=expiry_rule["score"],
                            message=f"expiry marker is past due ({expiry_date.isoformat()})",
                            evidence=pattern,
                            level="candidate",
                        ),
                    )
                else:
                    append_reason(
                        protected,
                        build_reason(
                            rule="expiry",
                            score=0,
                            message=f"expiry marker has not elapsed ({expiry_date.isoformat()})",
                            evidence=pattern,
                            level="protect",
                        ),
                    )

    path_rule = rules["paths"]
    if path_rule["enabled"]:
        matched = path_matches(relative_path, path_rule["candidate"])
        if matched:
            append_reason(
                reasons,
                build_reason(
                    rule="path",
                    score=path_rule["score"],
                    message=f"path matched cleanup pattern '{matched}'",
                    evidence=matched,
                    level="candidate",
                ),
            )
        protected_match = path_matches(relative_path, path_rule["protect"])
        if protected_match:
            append_reason(
                protected,
                build_reason(
                    rule="path",
                    score=0,
                    message=f"path matched keep pattern '{protected_match}'",
                    evidence=protected_match,
                    level="protect",
                ),
            )

    return reasons, protected


def analyze_file(path: Path, project_root: Path, config: dict[str, Any], logger: logging.Logger) -> FileDecision:
    relative_path = to_posix_path(path.relative_to(project_root))
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
    age_days = (datetime.now().astimezone() - modified_at).days
    file_text = path.read_text(encoding="utf-8", errors="replace")
    today = date.today()

    file_reasons, file_protected = evaluate_signals(
        text=file_text,
        decorators=[],
        relative_path=relative_path,
        age_days=age_days,
        today=today,
        config=config,
    )

    cases: list[CaseDecision] = []
    try:
        tree = ast.parse(file_text, filename=str(path))
        lines = file_text.splitlines()
        lookback = config["decision"]["comment_lookback_lines"]
        for case in discover_test_cases(tree):
            case_text = get_text_window(lines, case["start_line"], case["end_line"], lookback)
            reasons, protected = evaluate_signals(
                text=case_text,
                decorators=case["decorators"],
                relative_path=relative_path,
                age_days=None,
                today=today,
                config=config,
            )
            case_score = sum(item.score for item in reasons)
            cases.append(
                CaseDecision(
                    name=case["name"],
                    kind=case["kind"],
                    start_line=case["start_line"],
                    end_line=case["end_line"],
                    decorators=case["decorators"],
                    score=case_score,
                    candidate=case_score >= config["decision"]["min_score"] and not protected,
                    protected=bool(protected),
                    reasons=reasons,
                    protected_by=protected,
                )
            )
    except SyntaxError as exc:
        append_reason(
            file_protected,
            build_reason(
                rule="parse_error",
                score=0,
                message=f"AST parse failed: {exc.msg}",
                evidence=f"line {exc.lineno}",
                level="protect",
            ),
        )

    file_score = sum(item.score for item in file_reasons)
    keep_reasons = list(file_protected)
    for case in cases:
        for item in case.protected_by:
            append_reason(keep_reasons, item)

    require_all_cases = config["decision"]["require_all_test_cases"]
    allow_file_level = config["decision"]["allow_file_level_cleanup"]
    all_cases_candidate = bool(cases) and all(case.candidate for case in cases)
    any_case_candidate = any(case.candidate for case in cases)
    candidate = False
    rationale = "no cleanup signal matched"

    if keep_reasons:
        rationale = "protected by keep rule"
    elif allow_file_level and file_score >= config["decision"]["min_score"]:
        candidate = True
        rationale = "file-level cleanup rules matched"
    elif require_all_cases and all_cases_candidate:
        candidate = True
        rationale = "all discovered test cases are cleanup candidates"
    elif not require_all_cases and any_case_candidate:
        candidate = True
        rationale = "at least one discovered test case is a cleanup candidate"
    elif any_case_candidate:
        rationale = "contains candidate test cases, but file also has active cases"

    if candidate:
        action = "would_archive"
    elif keep_reasons:
        action = "skip_protected"
    elif any_case_candidate:
        action = "report_only"
    else:
        action = "skip"

    logger.info(
        "%s | action=%s | score=%s | rationale=%s",
        relative_path,
        action,
        file_score,
        rationale,
    )

    return FileDecision(
        path=relative_path,
        absolute_path=str(path.resolve()),
        modified_at=modified_at.isoformat(),
        age_days=age_days,
        score=file_score,
        candidate=candidate,
        protected=bool(keep_reasons),
        action=action,
        rationale=rationale,
        reasons=file_reasons,
        protected_by=keep_reasons,
        cases=cases,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Test Cleanup Report",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- command: `{report['command']}`",
        f"- dry_run: `{report['dry_run']}`",
        f"- project_root: `{report['project_root']}`",
        f"- scanned_files: `{summary['scanned_files']}`",
        f"- candidate_files: `{summary['candidate_files']}`",
        f"- report_only_files: `{summary['report_only_files']}`",
        f"- protected_files: `{summary['protected_files']}`",
        f"- archived_files: `{summary['archived_files']}`",
        "",
        "## Files",
        "",
    ]

    for decision in report.get("decisions", []):
        lines.append(f"### `{decision['path']}`")
        lines.append("")
        lines.append(f"- action: `{decision['action']}`")
        lines.append(f"- rationale: {decision['rationale']}")
        lines.append(f"- file_score: `{decision['score']}`")
        lines.append(f"- age_days: `{decision['age_days']}`")
        if decision["reasons"]:
            lines.append("- candidate reasons:")
            for reason in decision["reasons"]:
                lines.append(
                    f"  - `{reason['rule']}`: {reason['message']} (evidence: `{reason['evidence']}`, score={reason['score']})"
                )
        if decision["protected_by"]:
            lines.append("- protected by:")
            for reason in decision["protected_by"]:
                lines.append(f"  - `{reason['rule']}`: {reason['message']} (evidence: `{reason['evidence']}`)")
        if decision["cases"]:
            lines.append("- cases:")
            for case in decision["cases"]:
                state = "candidate" if case["candidate"] else "keep"
                lines.append(
                    f"  - `{case['name']}` [{state}] lines {case['start_line']}-{case['end_line']} score={case['score']}"
                )
        lines.append("")

    archived = report.get("archived_items", [])
    if archived:
        lines.append("## Archived Items")
        lines.append("")
        for item in archived:
            lines.append(f"- `{item['original_path']}` -> `{item['archive_path']}`")
        lines.append("")

    purge_items = report.get("purged_items", [])
    if purge_items:
        lines.append("## Purged Archive Runs")
        lines.append("")
        for item in purge_items:
            lines.append(f"- `{item['path']}` ({item['age_days']} days old)")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_report(report_root: Path, run_id: str, report: dict[str, Any]) -> tuple[Path, Path]:
    report_root.mkdir(parents=True, exist_ok=True)
    json_path = report_root / f"{run_id}.json"
    markdown_path = report_root / f"{run_id}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def write_archive_manifest(archive_root: Path, run_id: str, payload: dict[str, Any]) -> Path:
    run_root = archive_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def decisions_to_dict(decisions: list[FileDecision]) -> list[dict[str, Any]]:
    return [asdict(item) for item in decisions]


def build_summary(
    decisions: list[FileDecision],
    *,
    archived_files: int = 0,
    purged_runs: int = 0,
) -> dict[str, int]:
    return {
        "scanned_files": len(decisions),
        "candidate_files": sum(1 for item in decisions if item.candidate),
        "report_only_files": sum(1 for item in decisions if item.action == "report_only"),
        "protected_files": sum(1 for item in decisions if item.action == "skip_protected"),
        "archived_files": archived_files,
        "purged_archive_runs": purged_runs,
    }


def archive_candidates(
    *,
    decisions: list[FileDecision],
    project_root: Path,
    archive_root: Path,
    run_id: str,
    apply_changes: bool,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    archived_items: list[dict[str, Any]] = []
    candidates = [item for item in decisions if item.candidate]
    if not candidates:
        return archived_items

    archive_run_root = archive_root / run_id / "files"
    if apply_changes:
        archive_run_root.mkdir(parents=True, exist_ok=True)

    for decision in candidates:
        source = project_root / decision.path
        target = archive_run_root / decision.path
        item = {
            "original_path": str(source.resolve()),
            "archive_path": str(target.resolve()),
            "sha256": sha256_file(source),
            "size_bytes": source.stat().st_size,
        }
        archived_items.append(item)
        if apply_changes:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            decision.action = "archived"
            logger.info("Archived %s -> %s", source, target)
        else:
            decision.action = "would_archive"

    return archived_items


def ensure_path_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def purge_archive(
    *,
    archive_root: Path,
    apply_changes: bool,
    older_than_days: int,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    purged_items: list[dict[str, Any]] = []
    if not archive_root.exists():
        return purged_items

    cutoff = datetime.now().astimezone() - timedelta(days=older_than_days)
    for child in sorted(archive_root.iterdir()):
        if not child.is_dir():
            continue
        child_modified = datetime.fromtimestamp(child.stat().st_mtime).astimezone()
        age_days = (datetime.now().astimezone() - child_modified).days
        if child_modified > cutoff:
            continue
        if not ensure_path_under_root(child, archive_root):
            logger.warning("Skipped purge target outside archive root: %s", child)
            continue

        purged_items.append(
            {
                "path": str(child.resolve()),
                "age_days": age_days,
                "would_delete": not apply_changes,
            }
        )
        if apply_changes:
            shutil.rmtree(child)
            logger.info("Purged archived run %s", child)

    return purged_items


def run_scan_or_clean(
    *,
    command: str,
    project_root: Path,
    config: dict[str, Any],
    config_path: str | None,
    apply_changes: bool,
    logger: logging.Logger,
) -> tuple[dict[str, Any], Path, Path]:
    files = find_test_files(project_root, config)
    decisions = [analyze_file(path, project_root, config, logger) for path in files]

    archive_root = resolve_path(project_root, config["archive"]["root"])
    report_root = resolve_path(project_root, config["archive"]["report_root"])
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    archive_manifest_path = (
        str((archive_root / run_id / "manifest.json").resolve())
        if apply_changes and command == "clean"
        else None
    )
    archived_items = archive_candidates(
        decisions=decisions,
        project_root=project_root,
        archive_root=archive_root,
        run_id=run_id,
        apply_changes=apply_changes and command == "clean",
        logger=logger,
    )

    report = {
        "run_id": run_id,
        "command": command,
        "dry_run": not apply_changes,
        "generated_at": datetime.now().astimezone().isoformat(),
        "project_root": str(project_root.resolve()),
        "config_path": config_path,
        "config": config,
        "archive_manifest": archive_manifest_path,
        "summary": build_summary(
            decisions,
            archived_files=sum(1 for item in decisions if item.action == "archived"),
        ),
        "decisions": decisions_to_dict(decisions),
        "archived_items": archived_items,
    }
    json_path, markdown_path = write_report(report_root, run_id, report)
    if archive_manifest_path and archived_items:
        write_archive_manifest(
            archive_root,
            run_id,
            {
                "run_id": run_id,
                "generated_at": report["generated_at"],
                "project_root": report["project_root"],
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
                "archived_items": archived_items,
            },
        )
    return report, json_path, markdown_path


def run_purge_archive(
    *,
    project_root: Path,
    config: dict[str, Any],
    config_path: str | None,
    apply_changes: bool,
    logger: logging.Logger,
    older_than_days: int,
) -> tuple[dict[str, Any], Path, Path]:
    archive_root = resolve_path(project_root, config["archive"]["root"])
    report_root = resolve_path(project_root, config["archive"]["report_root"])
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    purged_items = purge_archive(
        archive_root=archive_root,
        apply_changes=apply_changes,
        older_than_days=older_than_days,
        logger=logger,
    )
    report = {
        "run_id": run_id,
        "command": "purge-archive",
        "dry_run": not apply_changes,
        "generated_at": datetime.now().astimezone().isoformat(),
        "project_root": str(project_root.resolve()),
        "config_path": config_path,
        "config": config,
        "summary": {
            "scanned_files": 0,
            "candidate_files": 0,
            "report_only_files": 0,
            "protected_files": 0,
            "archived_files": 0,
            "purged_archive_runs": len(purged_items),
        },
        "decisions": [],
        "purged_items": purged_items,
    }
    json_path, markdown_path = write_report(report_root, run_id, report)
    return report, json_path, markdown_path


def configure_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    return logging.getLogger("test_cleanup")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan test assets, generate cleanup reports, archive candidates, and purge old archives safely."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="scan",
        choices=["scan", "clean", "purge-archive"],
        help="scan only, archive cleanup candidates, or purge old archive runs",
    )
    parser.add_argument("--config", help="path to a TOML configuration file")
    parser.add_argument("--project-root", default=".", help="repository root used to resolve relative paths")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute changes. Without this flag the script always runs in dry-run mode.",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        help="override archive.purge_after_days when running purge-archive",
    )
    parser.add_argument("--log-level", default="INFO", help="logging level, for example INFO or DEBUG")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = configure_logging(args.log_level)

    project_root = Path(args.project_root).resolve()
    config_path = Path(args.config).resolve() if args.config else None
    config, loaded_from = load_config(config_path)

    if args.command == "scan":
        apply_changes = False
    else:
        apply_changes = bool(args.apply)

    if args.command == "purge-archive":
        older_than_days = args.older_than_days or int(config["archive"]["purge_after_days"])
        report, json_path, markdown_path = run_purge_archive(
            project_root=project_root,
            config=config,
            config_path=loaded_from,
            apply_changes=apply_changes,
            logger=logger,
            older_than_days=older_than_days,
        )
    else:
        report, json_path, markdown_path = run_scan_or_clean(
            command=args.command,
            project_root=project_root,
            config=config,
            config_path=loaded_from,
            apply_changes=apply_changes,
            logger=logger,
        )

    logger.info("JSON report: %s", json_path)
    logger.info("Markdown report: %s", markdown_path)
    print(
        json.dumps(
            {
                "run_id": report["run_id"],
                "command": report["command"],
                "dry_run": report["dry_run"],
                "summary": report["summary"],
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
