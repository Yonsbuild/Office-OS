#!/usr/bin/env python3
"""
Office OS Agent Executor

Main CLI runner that orchestrates task execution across projects.
Reads task queue, executes in dependency order, logs decisions,
validates changes, and escalates failures per protocol.

Usage:
    python agent.py --project [name]        # run tasks for one project
    python agent.py --project [name] --once # run only the first task
    python agent.py --all                   # run tasks across all projects
    python agent.py --dry-run --project [name]  # simulate without changes
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

import yaml


# ============================================================================
# CONFIGURATION
# ============================================================================

def load_config():
    """
    Load system/projects.yaml and system/models.yaml.
    Resolve code paths (expand ~ to home directory).
    Validate that project directories exist.
    Return dict with both configurations.
    """
    repo_root = Path(__file__).parent

    try:
        with open(repo_root / "system" / "projects.yaml") as f:
            projects = yaml.safe_load(f)

        with open(repo_root / "system" / "models.yaml") as f:
            models = yaml.safe_load(f)

        # Expand home directory in code paths
        for project_name, config in projects.get("projects", {}).items():
            if config.get("code") and config["code"] != ".":
                config["code"] = os.path.expanduser(config["code"])

        return {
            "repo_root": repo_root,
            "projects": projects.get("projects", {}),
            "models": models.get("tiers", {})
        }
    except Exception as e:
        print(f"ERROR loading configuration: {e}", file=sys.stderr)
        sys.exit(1)


def load_system_prompt():
    """Read system/agent_prompt.txt and return as string."""
    repo_root = Path(__file__).parent
    try:
        with open(repo_root / "system" / "agent_prompt.txt") as f:
            return f.read()
    except FileNotFoundError:
        print("WARNING: system/agent_prompt.txt not found", file=sys.stderr)
        return ""


def load_principles():
    """Read system/operating_principles.md and return as string."""
    repo_root = Path(__file__).parent
    try:
        with open(repo_root / "system" / "operating_principles.md") as f:
            return f.read()
    except FileNotFoundError:
        print("WARNING: system/operating_principles.md not found", file=sys.stderr)
        return ""


def load_escalation_rules():
    """Read system/escalation_rules.md and return as string."""
    repo_root = Path(__file__).parent
    try:
        with open(repo_root / "system" / "escalation_rules.md") as f:
            return f.read()
    except FileNotFoundError:
        print("WARNING: system/escalation_rules.md not found", file=sys.stderr)
        return ""


def load_failure_protocol():
    """Read system/failure_protocol.md and return as string."""
    repo_root = Path(__file__).parent
    try:
        with open(repo_root / "system" / "failure_protocol.md") as f:
            return f.read()
    except FileNotFoundError:
        print("WARNING: system/failure_protocol.md not found", file=sys.stderr)
        return ""


# ============================================================================
# PROJECT CONTEXT
# ============================================================================

def load_memory(config, project_name):
    """
    Read projects/[name]/memory.md.
    Return as string, or empty string if not found.
    """
    memory_path = config["repo_root"] / config["projects"][project_name]["memory"]
    try:
        with open(memory_path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def load_tasks(config, project_name):
    """
    Read all tasks/[project_name]-*.yaml files.
    Parse YAML and return list of tasks sorted by priority then order.
    """
    repo_root = config["repo_root"]
    tasks_dir = repo_root / "tasks"
    prefix = config["projects"][project_name]["tasks_prefix"]

    all_tasks = []
    for task_file in sorted(tasks_dir.glob(f"{prefix}-*.yaml")):
        try:
            with open(task_file) as f:
                data = yaml.safe_load(f)
                all_tasks.extend(data.get("tasks", []))
        except Exception as e:
            print(f"WARNING: Failed to load {task_file}: {e}", file=sys.stderr)

    # Sort by priority (lower = higher), then by order in file
    indexed_tasks = [(i, t) for i, t in enumerate(all_tasks)]
    indexed_tasks.sort(key=lambda x: (x[1].get("priority", 999), x[0]))
    all_tasks = [t for _, t in indexed_tasks]
    return all_tasks


def get_next_tasks(tasks):
    """
    Filter to open tasks.
    Skip tasks whose depends_on points to a non-done task.
    Return ordered list of executable tasks.
    """
    executable = []
    done_tasks = {t["id"] for t in tasks if t.get("status") == "done"}

    for task in tasks:
        if task.get("status") == "open":
            depends_on = task.get("depends_on")
            if depends_on is None or depends_on in done_tasks:
                executable.append(task)

    return executable


def load_relevant_code(code_path, task_description, max_tokens=50000):
    """
    Scan project code directory for files relevant to task description.
    Include files whose names or content match task keywords.
    Cap at 50K tokens to avoid context window limits.
    Return dict: {file_path: content, ...}
    """
    if not code_path or not code_path.exists():
        return {}

    relevant = {}
    token_count = 0
    keywords = re.findall(r"\b[a-z_]+\b", task_description.lower())

    try:
        for file_path in code_path.rglob("*"):
            # Skip non-files and common artifacts
            if not file_path.is_file():
                continue
            if any(x in str(file_path) for x in [".git", "__pycache__", ".pyc", "node_modules", ".env"]):
                continue

            # Check if filename matches any keyword
            filename_lower = file_path.name.lower()
            matches_filename = any(kw in filename_lower for kw in keywords)

            # Read file and check content (for smaller files)
            try:
                with open(file_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                if len(content) > 100000:  # Skip very large files
                    continue

                # Check if content matches keywords
                matches_content = any(kw in content.lower() for kw in keywords)

                if matches_filename or matches_content:
                    # Estimate tokens (rough: 4 chars per token)
                    est_tokens = len(content) // 4
                    if token_count + est_tokens > max_tokens:
                        break

                    rel_path = file_path.relative_to(code_path)
                    relevant[str(rel_path)] = content
                    token_count += est_tokens

            except (IOError, UnicodeDecodeError):
                continue

    except Exception as e:
        print(f"WARNING: Error scanning code directory: {e}", file=sys.stderr)

    return relevant


# ============================================================================
# MODEL ROUTING
# ============================================================================

def select_model(task, models_config, is_subagent=False):
    """
    Route to cheap or expensive tier based on:
    - task['complexity'] field ('low' = cheap, 'high' = expensive)
    - is_subagent flag (always expensive)
    - provider_hint in task['notes'] (optional override)

    Return dict with provider, model, max_tokens.
    """
    # Subagent always gets expensive tier
    if is_subagent:
        tier = models_config.get("expensive", {})
        return {
            "provider": tier.get("provider", "openai"),
            "model": tier.get("model", "gpt-4o"),
            "max_tokens": tier.get("max_tokens", 4096)
        }

    # Check for provider hint in notes
    notes = task.get("notes", "")
    provider_match = re.search(r"provider_hint:\s*(\w+)", notes)
    if provider_match:
        hint = provider_match.group(1)
        # Find model with matching provider
        for tier_config in models_config.values():
            if tier_config.get("provider") == hint:
                return {
                    "provider": tier_config.get("provider"),
                    "model": tier_config.get("model"),
                    "max_tokens": tier_config.get("max_tokens", 4096)
                }

    # Default: use complexity field
    complexity = task.get("complexity", "low")
    tier_name = "cheap" if complexity == "low" else "expensive"
    tier = models_config.get(tier_name, {})

    return {
        "provider": tier.get("provider", "anthropic" if tier_name == "cheap" else "openai"),
        "model": tier.get("model"),
        "max_tokens": tier.get("max_tokens", 4096)
    }


def call_llm(provider, model, system_prompt, user_prompt, max_tokens):
    """
    Unified LLM caller. Routes to correct API based on provider.
    Wraps in try/except. On error, logs and returns None.
    """
    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            return response.content[0].text

        elif provider == "openai":
            import openai
            client = openai.OpenAI()
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            return response.choices[0].message.content

        else:
            print(f"ERROR: Unknown provider '{provider}'", file=sys.stderr)
            return None

    except Exception as e:
        print(f"ERROR calling {provider} API: {e}", file=sys.stderr)
        return None


# ============================================================================
# GIT OPERATIONS
# ============================================================================

def run_git(code_path, *args):
    """Helper to run git commands in a specific directory."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=code_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def ensure_clean_tree(code_path):
    """
    Check if working tree is clean at code_path.
    If dirty, stash changes and log the stash.
    Return stash reference if stashed, None if already clean.
    """
    success, stdout, stderr = run_git(code_path, "status", "--porcelain")
    if not success:
        return None

    if stdout:  # Working tree is dirty
        success, stash_ref, stderr = run_git(code_path, "stash", "push", "-u", "-m", "auto-stash-pre-agent")
        if success:
            return stash_ref

    return None


def create_branch(code_path, branch_prefix, task_id):
    """
    Create and checkout a new branch: [branch_prefix]-[task_id]
    Return branch name on success, None on failure.
    """
    branch_name = f"{branch_prefix}-{task_id}"
    success, _, stderr = run_git(code_path, "checkout", "-b", branch_name)
    if not success:
        print(f"ERROR creating branch {branch_name}: {stderr}", file=sys.stderr)
        return None
    return branch_name


def create_checkpoint(code_path, task_id):
    """
    Commit current state with message: "checkpoint: pre-[task_id]"
    Return commit hash on success, None on failure.
    """
    success, _, _ = run_git(code_path, "add", "-A")
    if not success:
        return None

    success, stdout, stderr = run_git(code_path, "commit", "-m", f"checkpoint: pre-{task_id}")
    if not success and "nothing to commit" not in stderr:
        return None

    # Get current HEAD hash
    success, commit_hash, _ = run_git(code_path, "rev-parse", "HEAD")
    return commit_hash if success else None


def commit_changes(code_path, task_id, message):
    """
    Stage all changes and commit with message.
    Return commit hash on success, None on failure.
    """
    success, _, _ = run_git(code_path, "add", "-A")
    if not success:
        return None

    success, stdout, stderr = run_git(code_path, "commit", "-m", message)
    if not success:
        return None

    success, commit_hash, _ = run_git(code_path, "rev-parse", "HEAD")
    return commit_hash if success else None


def revert_to_checkpoint(code_path, checkpoint_hash):
    """
    Hard reset to checkpoint commit.
    Return True on success, False on failure.
    """
    success, _, _ = run_git(code_path, "reset", "--hard", checkpoint_hash)
    return success


def get_diff_since_checkpoint(code_path, checkpoint_hash):
    """
    Get git diff between checkpoint and current state.
    Return diff output as string.
    """
    success, diff, _ = run_git(code_path, "diff", checkpoint_hash, "HEAD")
    return diff if success else ""


# ============================================================================
# VALIDATION
# ============================================================================

def run_validation(code_path, validation_commands):
    """
    Run each validation command for the project.
    Return dict: {passed: bool, output: str, is_placeholder: bool}
    """
    if not validation_commands:
        return {"passed": True, "output": "", "is_placeholder": True}

    output = []
    all_passed = True
    is_placeholder = False

    for cmd in validation_commands:
        # Detect placeholder echo commands
        if cmd.startswith("echo"):
            is_placeholder = True
            output.append(f"[PLACEHOLDER] {cmd}")
            continue

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=code_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            output.append(result.stdout)
            if result.returncode != 0:
                all_passed = False
                output.append(f"[FAILED] {result.stderr}")
        except Exception as e:
            all_passed = False
            output.append(f"[ERROR] {e}")

    return {
        "passed": all_passed,
        "output": "\n".join(output),
        "is_placeholder": is_placeholder
    }


def compare_validation(pre_output, post_output):
    """
    Compare pre and post validation output.
    Identify new failures (in post but not in pre).
    Return dict: {new_failures: bool, details: str}
    """
    # Simple heuristic: check for new ERROR or FAILED lines
    pre_lines = set(pre_output.split("\n"))
    post_lines = set(post_output.split("\n"))

    new_issues = post_lines - pre_lines
    new_failures = any("FAILED" in line or "ERROR" in line for line in new_issues)

    return {
        "new_failures": new_failures,
        "details": "\n".join(new_issues) if new_issues else ""
    }


# ============================================================================
# FILE CHANGES
# ============================================================================

def parse_and_apply_changes(code_path, llm_response):
    """
    Extract <file_change> XML tags from LLM response and write files to disk.
    Format: <file_change path="relative/path" action="create|modify|delete">
            content here
            </file_change>
    Return dict: {success: bool, changed_files: [list], errors: [list]}
    """
    changed_files = []
    errors = []

    # Extract file_change blocks
    pattern = r'<file_change\s+path="([^"]+)"\s+action="(create|modify|delete)">([^<]*)</file_change>'
    matches = re.finditer(pattern, llm_response, re.DOTALL)

    for match in matches:
        file_path_str = match.group(1)
        action = match.group(2)
        content = match.group(3).strip()

        file_path = code_path / file_path_str

        try:
            if action == "create" or action == "modify":
                # Ensure parent directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w") as f:
                    f.write(content)
                changed_files.append(file_path_str)

            elif action == "delete":
                if file_path.exists():
                    file_path.unlink()
                    changed_files.append(file_path_str)

        except Exception as e:
            errors.append(f"Error processing {file_path_str}: {e}")

    return {
        "success": len(errors) == 0,
        "changed_files": changed_files,
        "errors": errors
    }


# ============================================================================
# FAILURE CASCADE
# ============================================================================

def assess_blast_radius(validation_output):
    """
    Simplified blast radius assessment.
    If validation output contains errors: assume it needs review.
    Return "contained" or "cascading".
    """
    # For now, treat all new failures as potentially cascading
    # (conservative approach pending real validation integration)
    if "ERROR" in validation_output or "FAILED" in validation_output:
        return "cascading"
    return "contained"


def attempt_recovery(code_path, task, failure_details, config, system_files):
    """
    Make one recovery attempt using expensive model.
    Constrain fix to already-modified files.
    Run validation again after recovery.
    Return dict: {success: bool, details: str}
    """
    # Build recovery prompt
    recovery_prompt = f"""
Previous task failed with validation errors:
{failure_details}

Task: {task.get('description')}
Acceptance criteria: {task.get('acceptance_criteria')}

Please fix the issue using the same files that were already modified.
Do not expand the change set.

Wrap file changes in XML tags:
<file_change path="relative/path" action="create|modify|delete">
content
</file_change>
"""

    models_config = config["models"]
    model_info = select_model(task, models_config)

    system_prompt = system_files["agent_prompt"] + "\n\nYou are in recovery mode."

    response = call_llm(
        model_info["provider"],
        model_info["model"],
        system_prompt,
        recovery_prompt,
        model_info["max_tokens"]
    )

    if not response:
        return {"success": False, "details": "LLM call failed during recovery"}

    # Parse and apply changes
    changes = parse_and_apply_changes(code_path, response)

    if not changes["success"]:
        return {"success": False, "details": "\n".join(changes["errors"])}

    # Run validation again
    project_name = task.get("project")
    validation_cmds = config["projects"][project_name].get("validation", [])
    val_result = run_validation(code_path, validation_cmds)

    return {
        "success": val_result["passed"],
        "details": val_result["output"]
    }


def run_subagent_review(task, diff_output, error_output, incident_log, config, system_files):
    """
    Separate LLM call (always expensive tier).
    Receives: task, diff, errors, incident log.
    Returns one of: retry_different_approach | decompose | escalate_to_founder
    """
    review_prompt = f"""
INCIDENT REPORT

Task: {task.get('description')}
Acceptance Criteria: {task.get('acceptance_criteria')}

DIFF:
{diff_output[:1000]}

ERRORS:
{error_output[:500]}

INCIDENT LOG:
{incident_log}

Based on this, recommend ONE of:
1. retry_different_approach — the task is feasible but needs a different strategy
2. decompose — the task is too complex and should be broken into smaller tasks
3. escalate_to_founder — requires human judgment or context

Respond with ONLY the recommendation keyword.
"""

    models_config = config["models"]
    expensive = models_config.get("expensive", {})

    response = call_llm(
        expensive.get("provider", "openai"),
        expensive.get("model", "gpt-4o"),
        system_files["agent_prompt"],
        review_prompt,
        expensive.get("max_tokens", 4096)
    )

    if not response:
        return "escalate_to_founder"

    response = response.lower().strip()
    if "retry_different" in response:
        return "retry_different_approach"
    elif "decompose" in response:
        return "decompose"
    else:
        return "escalate_to_founder"


# ============================================================================
# LOGGING
# ============================================================================

def log_action(config, project, task_id, action, result):
    """
    Append to /logs/run-YYYY-MM-DD.txt
    Format: [HH:MM] project | task_id | action | result
    """
    repo_root = config["repo_root"]
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"run-{date_str}.txt"

    time_str = datetime.datetime.now().strftime("%H:%M")
    line = f"[{time_str}] {project} | {task_id} | {action} | {result}\n"

    try:
        with open(log_file, "a") as f:
            f.write(line)
    except Exception as e:
        print(f"WARNING: Failed to log action: {e}", file=sys.stderr)


def log_decision(config, project_name, task_id, decision, reason, alternatives, outcome, incident=None):
    """
    Append structured entry to projects/[name]/decisions.md.
    """
    decisions_path = config["repo_root"] / config["projects"][project_name]["decisions"]

    entry = f"""
## {task_id} - {datetime.datetime.now().isoformat()}
- Decision: {decision}
- Reason: {reason}
- Alternatives: {alternatives}
- Outcome: {outcome}
"""
    if incident:
        entry += f"- Incident: {incident}\n"

    try:
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with open(decisions_path, "a") as f:
            f.write(entry)
    except Exception as e:
        print(f"WARNING: Failed to log decision: {e}", file=sys.stderr)


def log_incident(config, project, task_id, changed_files, intended_change, error_output, diff):
    """
    Append detailed incident block to run log.
    """
    repo_root = config["repo_root"]
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"run-{date_str}.txt"

    incident_entry = f"""
--- INCIDENT: {task_id} ---
Time: {datetime.datetime.now().isoformat()}
Project: {project}
Changed Files: {', '.join(changed_files)}
Intended: {intended_change}
Errors:
{error_output}
Diff:
{diff}
--- END INCIDENT ---
"""

    try:
        with open(log_file, "a") as f:
            f.write(incident_entry)
    except Exception as e:
        print(f"WARNING: Failed to log incident: {e}", file=sys.stderr)


# ============================================================================
# MEMORY UPDATES
# ============================================================================

def update_memory(config, project_name, task_id, status, blocker=None):
    """
    Read memory.md, update:
    - Queue: mark task as done/blocked
    - Blockers: add new blocker if provided
    - Last Updated: set to current timestamp
    - Context Window: append brief note
    Write updated memory.md.
    """
    memory_path = config["repo_root"] / config["projects"][project_name]["memory"]

    try:
        if memory_path.exists():
            with open(memory_path) as f:
                memory_content = f.read()
        else:
            memory_content = ""

        # Update queue section
        if "## Queue" in memory_content:
            # Simple pattern replacement for the task in queue
            task_pattern = rf"- \[.\]\s+{re.escape(task_id)}"
            check = "[x]" if status == "done" else "[!]" if status == "blocked" else "[ ]"
            memory_content = re.sub(task_pattern, f"- {check} {task_id}", memory_content)
        else:
            memory_content += f"\n## Queue\n- [{{'x' if status == 'done' else '!'}}] {task_id}"

        # Add blocker if provided
        if blocker and status == "blocked":
            if "## Blockers" not in memory_content:
                memory_content += "\n\n## Blockers"
            memory_content += f"\n- {task_id}: {blocker}"

        # Update timestamp
        timestamp = datetime.datetime.now().isoformat()
        if "## Last Updated" in memory_content:
            memory_content = re.sub(r"## Last Updated.*", f"## Last Updated\n{timestamp}", memory_content, flags=re.DOTALL)
        else:
            memory_content += f"\n\n## Last Updated\n{timestamp}"

        with open(memory_path, "w") as f:
            f.write(memory_content)

    except Exception as e:
        print(f"WARNING: Failed to update memory: {e}", file=sys.stderr)


def update_task_status(config, project_name, task_file_path, task_id, new_status, notes=None):
    """
    Read task YAML, find task by id, update status field.
    Optionally update notes field.
    Write updated YAML.
    """
    try:
        with open(task_file_path) as f:
            data = yaml.safe_load(f)

        for task in data.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = new_status
                if notes:
                    task["notes"] = notes
                break

        with open(task_file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        return True
    except Exception as e:
        print(f"ERROR updating task status: {e}", file=sys.stderr)
        return False


# ============================================================================
# DAILY BRIEF
# ============================================================================

def write_brief(config, run_summary):
    """
    Create briefs/YYYY-MM-DD.md from run_summary dict.
    """
    repo_root = config["repo_root"]
    briefs_dir = repo_root / "briefs"
    briefs_dir.mkdir(exist_ok=True)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    brief_file = briefs_dir / f"{date_str}.md"

    content = f"""# Daily Brief — {date_str}

## Summary
- Tasks completed: {len(run_summary.get('completed', []))}
- Tasks blocked: {len(run_summary.get('blocked', []))}
- Tasks skipped: {len(run_summary.get('skipped', []))}

## Completed Tasks
{_format_task_list(run_summary.get('completed', []))}

## Blocked Tasks
{_format_task_list(run_summary.get('blocked', []))}

## Skipped Tasks
{_format_task_list(run_summary.get('skipped', []))}

## Escalations
{_format_escalations(run_summary.get('escalations', []))}

## Next Run
Expected tasks:
{_format_task_list(run_summary.get('next', []))}
"""

    try:
        with open(brief_file, "w") as f:
            f.write(content)
    except Exception as e:
        print(f"WARNING: Failed to write brief: {e}", file=sys.stderr)


def _format_task_list(tasks):
    """Helper to format task lists for brief."""
    if not tasks:
        return "- None"
    return "\n".join(f"- {t.get('project', 'unknown')}/{t.get('id', 'unknown')}: {t.get('description', '')[:60]}" for t in tasks)


def _format_escalations(escalations):
    """Helper to format escalations for brief."""
    if not escalations:
        return "- None"
    return "\n".join(f"- {e.get('project')}/{e.get('task_id')}: {e.get('reason', '')}" for e in escalations)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def execute_task(task, project_name, config, system_files, dry_run=False):
    """
    Full task execution lifecycle with failure cascade and subagent review.
    Returns dict with execution result.
    """
    task_id = task.get("id")
    project_config = config["projects"].get(project_name, {})
    code_path = Path(project_config.get("code", ".")) if project_config.get("code") else None

    result = {
        "task_id": task_id,
        "project": project_name,
        "success": False,
        "status": "open",
        "error": None
    }

    try:
        # 1. Load project context
        memory = load_memory(config, project_name)
        relevant_code = {}
        if code_path and code_path.exists():
            relevant_code = load_relevant_code(code_path, task.get("description", ""))

        # 2. Select model
        model_info = select_model(task, config["models"])

        # 3. Check if task is read-only
        is_readonly = "read-only" in task.get("notes", "").lower()

        # 4. Git operations (if code task and not read-only)
        checkpoint_hash = None
        branch_name = None
        pre_validation = None

        if code_path and code_path.exists() and not is_readonly:
            stash = ensure_clean_tree(code_path)
            if dry_run:
                print(f"[DRY-RUN] Would ensure clean tree: {stash}")

            branch_prefix = project_config.get("branch_prefix", f"agent/{project_name}")
            branch_name = create_branch(code_path, branch_prefix, task_id)

            if not branch_name and not dry_run:
                result["status"] = "blocked"
                result["error"] = "branch_creation_failed"
                log_action(config, project_name, task_id, "branch", "FAILED")
                log_decision(config, project_name, task_id, "attempt_execution", "task requires code changes",
                           "none", "blocked", incident="branch creation failed")
                update_memory(config, project_name, task_id, "blocked", "branch creation failed")
                return result

            if dry_run:
                print(f"[DRY-RUN] Would create branch: {branch_name}")
            else:
                checkpoint_hash = create_checkpoint(code_path, task_id)
                if not checkpoint_hash:
                    result["status"] = "blocked"
                    result["error"] = "checkpoint_failed"
                    log_action(config, project_name, task_id, "checkpoint", "FAILED")
                    log_decision(config, project_name, task_id, "attempt_execution", "task requires code changes",
                               "none", "blocked", incident="checkpoint creation failed")
                    update_memory(config, project_name, task_id, "blocked", "checkpoint creation failed")
                    return result

                # Run pre-task validation baseline
                validation_cmds = project_config.get("validation", [])
                pre_validation = run_validation(code_path, validation_cmds)

        # 4. Build prompt
        system_prompt = system_files["agent_prompt"]
        code_section = ""
        if relevant_code:
            code_section = "\n\nRelevant Code Files:\n"
            for file_path, content in relevant_code.items():
                code_section += f"\n--- {file_path} ---\n{content[:1000]}\n"

        user_prompt = f"""
Project Memory:
{memory}

Task: {task.get('description')}

Acceptance Criteria:
{task.get('acceptance_criteria')}

Operating Principles:
{system_files['principles'][:500]}

{code_section}

Please execute this task and wrap any file changes in:
<file_change path="relative/path" action="create|modify|delete">
content
</file_change>
"""

        if dry_run:
            print(f"\n=== DRY RUN: {task_id} ===")
            print(f"Project: {project_name}")
            print(f"Complexity: {task.get('complexity', 'low')}")
            print(f"Model: {model_info['provider']}/{model_info['model']}")
            print(f"\nPrompt:\n{user_prompt[:500]}...\n")
            result["success"] = True
            result["status"] = "open"
            return result

        # 5. Call LLM
        response = call_llm(
            model_info["provider"],
            model_info["model"],
            system_prompt,
            user_prompt,
            model_info["max_tokens"]
        )

        if not response:
            result["status"] = "blocked"
            result["error"] = "llm_api_error"
            log_action(config, project_name, task_id, "llm_call", "FAILED")
            log_decision(config, project_name, task_id, "call_llm", "execute task",
                       "none", "blocked", incident="LLM API error")
            update_memory(config, project_name, task_id, "blocked", "LLM API error")
            return result

        # 6. Apply LLM output
        changed_files = []
        if code_path and code_path.exists():
            changes = parse_and_apply_changes(code_path, response)
            changed_files = changes["changed_files"]

            if not changes["success"] and changes["errors"]:
                result["status"] = "blocked"
                result["error"] = "file_write_error"
                log_action(config, project_name, task_id, "file_write", "FAILED")
                log_decision(config, project_name, task_id, "apply_changes", "write LLM-generated files",
                           "none", "blocked", incident="; ".join(changes["errors"]))
                update_memory(config, project_name, task_id, "blocked", "file write error")
                return result

            # 7. Validate changes (skip for read-only tasks)
            if not is_readonly:
                validation_cmds = project_config.get("validation", [])
                post_validation = run_validation(code_path, validation_cmds)

                if pre_validation and not post_validation["passed"] and not post_validation["is_placeholder"]:
                    # Compare with baseline
                    comparison = compare_validation(pre_validation["output"], post_validation["output"])

                    if comparison["new_failures"]:
                        # FAILURE CASCADE triggered
                        log_action(config, project_name, task_id, "validation", "FAILED")

                        # Get diff for incident log
                        diff = get_diff_since_checkpoint(code_path, checkpoint_hash)
                        incident_msg = f"Validation failed with new errors. Files changed: {', '.join(changed_files)}"
                        log_incident(config, project_name, task_id, changed_files,
                                   task.get("description", ""), comparison["details"], diff)

                        # Assess blast radius
                        radius = assess_blast_radius(comparison["details"])

                        if radius == "cascading":
                            # Escalate immediately without recovery attempt
                            result["status"] = "blocked"
                            result["error"] = "cascading_failure"
                            revert_to_checkpoint(code_path, checkpoint_hash)
                            log_decision(config, project_name, task_id, "assess_blast_radius",
                                       "determine failure scope", "contained recovery attempt", "escalated",
                                       incident=incident_msg)
                            update_memory(config, project_name, task_id, "blocked", incident_msg)
                            return result

                        # Attempt recovery (contained failures only)
                        recovery = attempt_recovery(code_path, task, comparison["details"], config, system_files)

                        if not recovery["success"]:
                            # Recovery failed - revert to checkpoint
                            revert_to_checkpoint(code_path, checkpoint_hash)

                            # Get updated diff for subagent review
                            diff = get_diff_since_checkpoint(code_path, checkpoint_hash)

                            # Run subagent review
                            subagent_rec = run_subagent_review(task, diff, comparison["details"],
                                                              incident_msg, config, system_files)

                            result["status"] = "blocked"
                            result["error"] = f"recovery_failed-{subagent_rec}"
                            log_decision(config, project_name, task_id, "recovery_attempt",
                                       "fix new validation failures", "skip recovery attempt", "failed",
                                       incident=f"{incident_msg}. Subagent recommendation: {subagent_rec}")
                            update_memory(config, project_name, task_id, "blocked",
                                        f"recovery failed. Subagent recommendation: {subagent_rec}")
                            return result

                        # Recovery succeeded
                        log_decision(config, project_name, task_id, "recovery_attempt",
                                   "fix new validation failures", "escalate", "completed",
                                   incident="self-corrected after initial failure")

        # 8. Commit changes (skip for read-only tasks)
        if code_path and code_path.exists() and checkpoint_hash and changed_files and not is_readonly:
            message = f"Complete {task_id}: {task.get('description', '')[:50]}"
            commit = commit_changes(code_path, task_id, message)
            if not commit:
                result["status"] = "blocked"
                result["error"] = "commit_failed"
                log_action(config, project_name, task_id, "commit", "FAILED")
                log_decision(config, project_name, task_id, "commit_changes", "stage and commit task changes",
                           "none", "blocked", incident="commit failed")
                update_memory(config, project_name, task_id, "blocked", "commit failed")
                return result

        # 9. Mark as done
        result["success"] = True
        result["status"] = "done"
        log_action(config, project_name, task_id, "execute", "SUCCESS")
        log_decision(config, project_name, task_id, "execute_task", "complete assigned work",
                   "skip task", "completed")
        update_memory(config, project_name, task_id, "done")

    except Exception as e:
        result["error"] = str(e)
        result["status"] = "blocked"
        print(f"ERROR executing task {task_id}: {e}", file=sys.stderr)
        traceback.print_exc()
        log_action(config, project_name, task_id, "execute", f"ERROR: {e}")
        log_decision(config, project_name, task_id, "execute_task", "complete assigned work",
                   "none", "blocked", incident=str(e))
        update_memory(config, project_name, task_id, "blocked", f"execution error: {e}")

    return result


def run(args):
    """
    Main entry point.
    Parse CLI args, load config, execute tasks, write brief.
    """
    config = load_config()

    # Load system files
    system_files = {
        "agent_prompt": load_system_prompt(),
        "principles": load_principles(),
        "escalation_rules": load_escalation_rules(),
        "failure_protocol": load_failure_protocol()
    }

    dry_run = args.dry_run
    once = args.once

    # Determine projects to run
    if args.all:
        projects_to_run = config["projects"].keys()
    else:
        projects_to_run = [args.project]

    run_summary = {
        "completed": [],
        "blocked": [],
        "skipped": [],
        "escalations": [],
        "next": []
    }

    # Execute tasks
    for project_name in projects_to_run:
        if project_name not in config["projects"]:
            print(f"ERROR: Project '{project_name}' not found in configuration", file=sys.stderr)
            continue

        tasks = load_tasks(config, project_name)
        executable = get_next_tasks(tasks)

        max_tasks = 1 if once else 3
        executed = 0

        for task in executable:
            if executed >= max_tasks:
                break

            result = execute_task(task, project_name, config, system_files, dry_run=dry_run)
            executed += 1

            # Update task status
            task_files = list((config["repo_root"] / "tasks").glob(f"{project_name}-*.yaml"))
            for task_file in task_files:
                update_task_status(config, project_name, task_file, task["id"], result["status"])

            # Track result
            if result["status"] == "done":
                run_summary["completed"].append(task)
            elif result["status"] == "blocked":
                run_summary["blocked"].append(task)
            else:
                run_summary["skipped"].append(task)

    # Write brief
    if not dry_run:
        write_brief(config, run_summary)

    # Print summary
    print(f"\n=== RUN SUMMARY ===")
    print(f"Completed: {len(run_summary['completed'])}")
    print(f"Blocked: {len(run_summary['blocked'])}")
    print(f"Skipped: {len(run_summary['skipped'])}")


def main():
    """Parse CLI args and run."""
    parser = argparse.ArgumentParser(
        description="Office OS Task Executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument("--project", help="Project name to run")
    parser.add_argument("--all", action="store_true", help="Run all projects")
    parser.add_argument("--once", action="store_true", help="Execute only first task")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without changes")

    args = parser.parse_args()

    # Validate args
    if not args.all and not args.project:
        parser.error("Must specify --project or --all")

    run(args)


if __name__ == "__main__":
    main()
