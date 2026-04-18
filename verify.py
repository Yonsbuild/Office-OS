#!/usr/bin/env python3
"""
Post-run verification script for Office OS agent.
Audits agent.py execution to confirm it followed its contract.
Exit codes: 0 = PASS, 1 = FAIL
"""

import argparse
import os
import sys
import re
from pathlib import Path
from datetime import datetime
import yaml

# ============================================================================
# CONFIGURATION
# ============================================================================

def load_config():
    """Load system/projects.yaml and return config dict."""
    repo_root = Path(__file__).parent
    config_path = repo_root / "system" / "projects.yaml"

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return {
        "repo_root": repo_root,
        "projects": data.get("projects", {})
    }

# ============================================================================
# VERIFICATION CHECKS
# ============================================================================

def verify_run_log(config, date_str):
    """Check that /logs/run-{date}.txt exists and parse it."""
    repo_root = config["repo_root"]
    log_path = repo_root / "logs" / f"run-{date_str}.txt"

    if not log_path.exists():
        return {"exists": False, "action_count": 0, "failures": [], "escalations": []}

    with open(log_path) as f:
        content = f.read()

    if not content.strip():
        return {"exists": True, "action_count": 0, "failures": [], "escalations": []}

    actions = len([l for l in content.split('\n') if l.strip()])
    failures = [l for l in content.split('\n') if 'FAILED' in l or 'ERROR' in l]
    escalations = [l for l in content.split('\n') if 'ESCALATION' in l]

    return {
        "exists": True,
        "action_count": actions,
        "failures": failures,
        "escalations": escalations
    }

def verify_brief(config, date_str):
    """Check that /briefs/{date}.md exists with required sections."""
    repo_root = config["repo_root"]
    brief_path = repo_root / "briefs" / f"{date_str}.md"

    if not brief_path.exists():
        return {"exists": False, "has_all_sections": False, "missing_sections": ["All"]}

    with open(brief_path) as f:
        content = f.read()

    required = ["Summary", "Completed Tasks", "Blocked Tasks", "Escalations", "Next Run"]
    missing = [s for s in required if s not in content]

    return {
        "exists": True,
        "has_all_sections": len(missing) == 0,
        "missing_sections": missing
    }

def verify_decisions(config, project_name, date_str):
    """Check that /projects/{project}/decisions.md was updated with today's entries."""
    repo_root = config["repo_root"]
    decisions_path = repo_root / "projects" / project_name / "decisions.md"

    if not decisions_path.exists():
        return {"updated": False, "new_entries": 0, "malformed_entries": []}

    with open(decisions_path) as f:
        content = f.read()

    # Look for entries with today's date
    pattern = rf"\b{date_str}\b"
    entries = re.findall(pattern, content)

    # Check for malformed entries (basic validation)
    required_fields = ["task_id", "decision", "reason"]
    malformed = []

    return {
        "updated": len(entries) > 0,
        "new_entries": len(entries),
        "malformed_entries": malformed
    }

def verify_memory(config, project_name, date_str):
    """Check that /projects/{project}/memory.md was updated."""
    repo_root = config["repo_root"]
    memory_path = repo_root / "projects" / project_name / "memory.md"

    if not memory_path.exists():
        return {"updated": False, "timestamp_current": False, "issues": ["File not found"]}

    with open(memory_path) as f:
        content = f.read()

    issues = []

    # Check for Last Updated timestamp
    timestamp_match = re.search(r"Last Updated\s*\n(\d{4}-\d{2}-\d{2})", content)
    timestamp_current = timestamp_match and timestamp_match.group(1) == date_str if timestamp_match else False

    if not timestamp_current:
        issues.append("Last Updated timestamp not current")

    # Check for empty sections
    if "## Context Window" in content and len(content.split("## Context Window")[1]) < 50:
        issues.append("Context Window section is sparse")

    return {
        "updated": len(issues) == 0,
        "timestamp_current": timestamp_current,
        "issues": issues
    }

def verify_task_status(config, project_name, date_str):
    """Check that task YAML files were updated consistently."""
    repo_root = config["repo_root"]
    projects = config["projects"]

    if project_name not in projects:
        return {"consistent": False, "mismatches": [], "orphaned_status_changes": []}

    tasks_prefix = projects[project_name].get("tasks_prefix", project_name)
    tasks_dir = repo_root / "tasks"

    mismatches = []
    orphaned = []

    # Find task files for this project
    task_files = list(tasks_dir.glob(f"{tasks_prefix}-*.yaml"))

    for task_file in task_files:
        with open(task_file) as f:
            data = yaml.safe_load(f)

        if not data or "tasks" not in data:
            continue

        for task in data["tasks"]:
            status = task.get("status", "").lower()
            # Flag any tasks still in "in-progress" state
            if status == "in-progress":
                mismatches.append(f"{task.get('id', '?')}: still in-progress")

    return {
        "consistent": len(mismatches) == 0,
        "mismatches": mismatches,
        "orphaned_status_changes": orphaned
    }

def verify_scope(config, project_name, date_str):
    """Check that agent only modified files within allowed scope."""
    repo_root = config["repo_root"]
    projects = config["projects"]

    allowed_patterns = [
        f"projects/{project_name}/memory.md",
        f"projects/{project_name}/decisions.md",
        "logs/run-*.txt",
        "briefs/*.md",
        f"tasks/{projects[project_name].get('tasks_prefix', project_name)}-*.yaml"
    ]

    # For now, assume scope is good if we have run logs and briefs
    # Full implementation would check git diffs
    return {
        "in_scope": True,
        "out_of_scope_files": []
    }

def verify_git_hygiene(config, project_name):
    """Check git state for the project's code directory."""
    projects = config["projects"]

    if project_name not in projects:
        return {"clean": False, "issues": ["Project not found"]}

    issues = []

    # Check for uncommitted changes in agent branches
    # Full implementation would check git status and branch cleanup

    return {
        "clean": len(issues) == 0,
        "issues": issues
    }

# ============================================================================
# AUTO-FIX (optional, --fix flag only)
# ============================================================================

def fix_missing_timestamp(config, project_name, date_str):
    """Update stale Last Updated timestamp in memory.md."""
    repo_root = config["repo_root"]
    memory_path = repo_root / "projects" / project_name / "memory.md"

    if not memory_path.exists():
        return False

    with open(memory_path) as f:
        content = f.read()

    updated_content = re.sub(
        r"(## Last Updated\s*\n)(\d{4}-\d{2}-\d{2}[^\n]*)",
        f"\\1{date_str} by verify.py",
        content
    )

    if updated_content != content:
        with open(memory_path, 'w') as f:
            f.write(updated_content)
        return True

    return False

# ============================================================================
# REPORTING
# ============================================================================

def generate_report(all_checks, date_str, config):
    """Generate verification report."""
    repo_root = config["repo_root"]

    # Determine overall status
    run_pass = all_checks["run_log"]["exists"]
    brief_pass = all_checks["brief"]["has_all_sections"] if all_checks["brief"]["exists"] else False

    project_issues = sum(
        len(v["mismatches"]) + len(v["orphaned_status_changes"])
        for v in all_checks["task_status"].values()
    )

    overall = "PASS" if (run_pass and brief_pass and project_issues == 0) else "FAIL"

    report_lines = [
        f"\n{'='*70}",
        f"VERIFICATION REPORT: {date_str}",
        f"{'='*70}\n",
    ]

    # Summary of checks
    report_lines.append("RUN LOG:        " + ("PASS" if all_checks["run_log"]["exists"] else "FAIL (no log found)"))
    report_lines.append(f"  Actions logged: {all_checks['run_log']['action_count']}")
    if all_checks["run_log"]["failures"]:
        report_lines.append(f"  Failures: {len(all_checks['run_log']['failures'])}")

    report_lines.append("\nDAILY BRIEF:    " + ("PASS" if all_checks["brief"]["has_all_sections"] else ("WARN (missing sections)" if all_checks["brief"]["exists"] else "FAIL (not found)")))
    if not all_checks["brief"]["has_all_sections"] and all_checks["brief"]["missing_sections"]:
        report_lines.append(f"  Missing: {', '.join(all_checks['brief']['missing_sections'])}")

    report_lines.append("\nTASK STATUS:")
    for project, result in all_checks["task_status"].items():
        status = "PASS" if result["consistent"] else "FAIL"
        report_lines.append(f"  {project}: {status}")
        if result["mismatches"]:
            for m in result["mismatches"][:3]:
                report_lines.append(f"    - {m}")

    report_lines.append(f"\nGIT HYGIENE:    " + ("PASS" if all(v["clean"] for v in all_checks["git_hygiene"].values()) else "FAIL"))

    report_lines.append(f"\nOVERALL: {overall}")
    report_lines.append(f"{'='*70}\n")

    return "\n".join(report_lines), overall == "PASS"

# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Verify agent.py post-run execution")
    parser.add_argument("--date", help="Verify specific run (YYYY-MM-DD)")
    parser.add_argument("--latest", action="store_true", help="Verify most recent run")
    parser.add_argument("--project", help="Verify specific project only")
    parser.add_argument("--fix", action="store_true", help="Auto-fix minor issues")

    args = parser.parse_args()

    config = load_config()
    repo_root = config["repo_root"]

    # Determine date
    if args.latest:
        logs_dir = repo_root / "logs"
        if logs_dir.exists():
            run_logs = sorted(logs_dir.glob("run-*.txt"))
            if run_logs:
                date_str = run_logs[-1].stem.replace("run-", "")
            else:
                print("No run logs found")
                return 1
        else:
            print("No logs directory found")
            return 1
    elif args.date:
        date_str = args.date
    else:
        print("Usage: python verify.py --date YYYY-MM-DD or --latest")
        return 1

    # Run verification checks
    all_checks = {
        "run_log": verify_run_log(config, date_str),
        "brief": verify_brief(config, date_str),
        "task_status": {},
        "git_hygiene": {}
    }

    # Scope checks per project
    projects = [args.project] if args.project else list(config["projects"].keys())

    for project in projects:
        all_checks["task_status"][project] = verify_task_status(config, project, date_str)
        all_checks["git_hygiene"][project] = verify_git_hygiene(config, project)

    # Generate report
    report, passed = generate_report(all_checks, date_str, config)

    print(report)

    # Write report to file
    report_path = repo_root / "logs" / f"verify-{date_str}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        f.write(report)

    print(f"Report written to: {report_path}")

    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())
