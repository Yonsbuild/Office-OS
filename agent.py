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


def _format_age_seconds(age_seconds):
    """Return compact human-readable age string."""
    if age_seconds < 60:
        return f"{int(age_seconds)}s ago"
    if age_seconds < 3600:
        return f"{int(age_seconds // 60)}m ago"
    if age_seconds < 86400:
        return f"{int(age_seconds // 3600)}h ago"
    return f"{int(age_seconds // 86400)}d ago"


def print_state_status(config):
    """
    Read-only diagnostics of Office OS operating condition.
    Includes memory freshness, brief freshness, approvals health,
    task queue integrity, maintenance activity signals, and warnings.
    """
    repo_root = config["repo_root"]
    now = datetime.datetime.now().timestamp()
    today = datetime.date.today().isoformat()
    warnings = []

    print("\n=== STATE STATUS ===")
    print(f"timestamp: {datetime.datetime.now().isoformat(timespec='seconds')}")

    # Persistence + memory freshness
    print("\n[persistence / memory]")
    stale_threshold_days = 3
    stale_seconds = stale_threshold_days * 24 * 60 * 60
    missing_memory = []
    stale_memory = []

    for project_name, project_config in sorted(config.get("projects", {}).items()):
        memory_rel = project_config.get("memory", f"projects/{project_name}/memory.md")
        memory_path = repo_root / memory_rel
        if not memory_path.exists():
            missing_memory.append(project_name)
            print(f"- {project_name}: missing ({memory_rel})")
            continue

        age_seconds = max(0, now - memory_path.stat().st_mtime)
        freshness = _format_age_seconds(age_seconds)
        is_stale = age_seconds > stale_seconds
        if is_stale:
            stale_memory.append(project_name)
        status_label = "stale" if is_stale else "fresh"
        print(f"- {project_name}: {status_label} ({freshness})")

    if missing_memory:
        warnings.append(f"missing memory files: {', '.join(missing_memory)}")
    if stale_memory:
        warnings.append(f"stale memory files (> {stale_threshold_days}d): {', '.join(stale_memory)}")

    # Task queue integrity
    print("\n[task queue]")
    tasks_dir = repo_root / "tasks"
    task_files = sorted(tasks_dir.glob("*.yaml")) if tasks_dir.exists() else []
    print(f"- task files: {len(task_files)}")
    if not task_files:
        warnings.append("no tasks found")

    malformed_task_files = 0
    for task_file in task_files:
        try:
            with open(task_file) as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
                malformed_task_files += 1
        except Exception:
            malformed_task_files += 1
    print(f"- malformed task files: {malformed_task_files}")
    if malformed_task_files:
        warnings.append(f"malformed task files: {malformed_task_files}")

    # Brief writing freshness
    print("\n[brief writing]")
    briefs_dir = repo_root / "briefs"
    today_brief = briefs_dir / f"{today}.md"
    if today_brief.exists():
        age_seconds = max(0, now - today_brief.stat().st_mtime)
        print(f"- today's brief ({today}.md): present ({_format_age_seconds(age_seconds)})")
    else:
        print(f"- today's brief ({today}.md): missing")
        warnings.append("no brief for today")

    # Approvals health (read-only)
    print("\n[approvals]")
    approvals_file = repo_root / "approvals" / "pending.json"
    pending_count = 0
    malformed_approvals = False
    if approvals_file.exists():
        try:
            with open(approvals_file) as f:
                approvals_data = json.load(f)
            if isinstance(approvals_data, list):
                pending_count = len(approvals_data)
                print(f"- pending approvals: {pending_count}")
            else:
                malformed_approvals = True
                print("- pending approvals: malformed (expected list)")
        except Exception:
            malformed_approvals = True
            print("- pending approvals: malformed (invalid JSON)")
    else:
        print("- pending approvals file: missing")
        pending_count = 0

    if malformed_approvals:
        warnings.append("malformed approvals file")
    if pending_count > 0:
        warnings.append(f"pending approvals: {pending_count}")

    # Maintenance / bacteria activity signals
    print("\n[maintenance / bacteria]")
    maintenance_signals = []
    logs_dir = repo_root / "logs"
    if logs_dir.exists():
        for log_file in sorted(logs_dir.glob("run-*.txt"))[-5:]:
            try:
                text = log_file.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue
            if "maintenance" in text or "cleanup candidates" in text:
                maintenance_signals.append(log_file.name)
    print(f"- maintenance logs with signals (last 5): {len(maintenance_signals)}")
    if maintenance_signals:
        print(f"- recent signal files: {', '.join(maintenance_signals)}")

    cleanup_mentions = 0
    for project_config in config.get("projects", {}).values():
        memory_rel = project_config.get("memory")
        if not memory_rel:
            continue
        memory_path = repo_root / memory_rel
        if not memory_path.exists():
            continue
        try:
            text = memory_path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        cleanup_mentions += text.count("cleanup candidates:")
    print(f"- cleanup candidate sections in memory: {cleanup_mentions}")

    maintenance_system_exists = hasattr(sys.modules[__name__], "run_maintenance")
    if maintenance_system_exists and not maintenance_signals and cleanup_mentions == 0:
        warnings.append("maintenance logs missing despite maintenance system presence")

    # Git branch status (safe, best effort)
    print("\n[git]")
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=3
        )
        branch = (result.stdout or "").strip()
        if result.returncode == 0 and branch:
            print(f"- current branch: {branch}")
        else:
            print("- current branch: unavailable")
    except Exception:
        print("- current branch: unavailable")

    # Warning signals summary
    print("\n[warnings]")
    if warnings:
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("- none")
    print("")


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
    FIX 4: Treat infrastructure-blocked tasks as open (eligible for retry).
    Return ordered list of executable tasks.
    """
    executable = []
    done_tasks = {t["id"] for t in tasks if t.get("status") == "done"}
    infrastructure_blockers = {"checkpoint", "branch creation", "commit failed"}

    for task in tasks:
        # Check if task is open
        if task.get("status") == "open":
            depends_on = task.get("depends_on")
            if depends_on is None or depends_on in done_tasks:
                executable.append(task)
        # FIX 4: Auto-retry infrastructure-blocked tasks on next run
        elif task.get("status") == "blocked":
            notes = task.get("notes", "").lower()
            # If blocked due to transient infrastructure issues, treat as open
            if any(blocker in notes for blocker in infrastructure_blockers):
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


def load_inspection_context(code_path, max_tokens=15000):
    """
    Build structured codebase context for inspection tasks.
    Gathers real codebase data: directory structure, git history, dependencies, key source files.

    Returns formatted string ready for LLM consumption.
    Max output is capped at max_tokens (estimated at 4 chars per token).
    """
    if not code_path or not code_path.exists():
        return ""

    sections = []
    char_count = 0
    max_chars = max_tokens * 4

    # 1. Directory tree (2 levels)
    try:
        result = subprocess.run(
            ["find", ".", "-maxdepth", "2", "-not", "-path", "./.git/*", "-not", "-path", "./node_modules/*", "-not", "-path", "./__pycache__/*"],
            cwd=code_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            tree_output = result.stdout.strip()
            sections.append("=== DIRECTORY STRUCTURE ===")
            sections.append(tree_output)
            char_count += len(tree_output)
    except Exception as e:
        sections.append(f"[Directory structure unavailable: {e}]")

    if char_count > max_chars:
        return "\n".join(sections[:2])

    # 2. Git log (last 10 commits)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=code_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            git_output = result.stdout.strip()
            sections.append("\n=== RECENT GIT HISTORY ===")
            sections.append(git_output)
            char_count += len(git_output)
        else:
            sections.append("\n=== RECENT GIT HISTORY ===")
            sections.append("No git history available.")
    except Exception as e:
        sections.append(f"\n[Git history unavailable: {e}]")

    if char_count > max_chars:
        return "\n".join(sections)

    # 3. Dependency files
    sections.append("\n=== DEPENDENCIES ===")
    dependency_files = ["requirements.txt", "package.json", "Cargo.toml", "pyproject.toml", "go.mod", "Gemfile"]
    deps_added = False

    for dep_file in dependency_files:
        dep_path = code_path / dep_file
        if dep_path.exists():
            try:
                with open(dep_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if char_count + len(content) <= max_chars:
                    sections.append(f"--- {dep_file} ---")
                    sections.append(content)
                    char_count += len(content)
                    deps_added = True
            except Exception as e:
                sections.append(f"[Error reading {dep_file}: {e}]")

    if not deps_added:
        sections.append("[No dependency files found]")

    if char_count > max_chars:
        return "\n".join(sections)

    # 4. Key source files
    sections.append("\n=== KEY SOURCE FILES ===")
    entry_points = ["app.py", "main.py", "index.js", "index.ts", "server.py", "server.js",
                    "manage.py", "wsgi.py", "asgi.py", "flask_app.py", "routes.py",
                    "api.py", "config.py", "settings.py", ".env.example"]

    for entry_file in entry_points:
        entry_path = code_path / entry_file
        if entry_path.exists():
            try:
                with open(entry_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Cap each entry file at 3000 chars
                content = content[:3000]

                if char_count + len(content) <= max_chars:
                    sections.append(f"\n--- {entry_file} ---")
                    sections.append(content)
                    char_count += len(content)
            except Exception as e:
                sections.append(f"\n[Error reading {entry_file}: {e}]")

    if char_count > max_chars:
        return "\n".join(sections)

    # 5. README (last, with caveat)
    sections.append("\n=== README ===")
    sections.append("NOTE: README may be outdated. Prioritize what you observe in code, git history, and dependencies over README claims.")

    for readme_name in ["README.md", "README"]:
        readme_path = code_path / readme_name
        if readme_path.exists():
            try:
                with open(readme_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                if char_count + len(content) <= max_chars:
                    sections.append(f"\n--- {readme_name} ---")
                    sections.append(content)
                    char_count += len(content)
            except Exception as e:
                sections.append(f"\n[Error reading {readme_name}: {e}]")

    # Prepend caveat at top
    output = "NOTE: README may be outdated. Prioritize what you observe in code, git history, and dependencies over README claims.\n\n"
    output += "\n".join(sections)

    return output


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

    # Inspection tasks always use expensive tier — they need to synthesize codebase context into memory updates,
    # which requires stronger reasoning. Check before default complexity routing.
    notes_lower = task.get("notes", "").lower()
    is_readonly_task = "read-only" in notes_lower

    if not is_readonly_task and task.get("complexity") == "low":
        # Also treat as inspection if description contains keywords
        description_lower = task.get("description", "").lower()
        inspection_keywords = {"inspect", "inspection", "review", "audit", "read", "analyze", "analysis"}
        if any(kw in description_lower for kw in inspection_keywords):
            is_readonly_task = True

    if is_readonly_task:
        tier = models_config.get("expensive", {})
        return {
            "provider": tier.get("provider", "openai"),
            "model": tier.get("model", "gpt-4o"),
            "max_tokens": tier.get("max_tokens", 4096)
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


def get_default_branch(code_path):
    """
    FIX 3: Detect default branch for the repository.
    Try in order:
    1. git symbolic-ref refs/remotes/origin/HEAD (canonical)
    2. Check if 'main' exists
    3. Check if 'master' exists
    Return branch name or None.
    """
    # Try symbolic-ref first
    success, stdout, _ = run_git(code_path, "symbolic-ref", "refs/remotes/origin/HEAD")
    if success and stdout:
        # Output is "refs/remotes/origin/main" or similar
        parts = stdout.split("/")
        if parts:
            return parts[-1]

    # Fall back to checking for 'main'
    success, stdout, _ = run_git(code_path, "branch", "--list", "main")
    if success and "main" in stdout:
        return "main"

    # Fall back to checking for 'master'
    success, stdout, _ = run_git(code_path, "branch", "--list", "master")
    if success and "master" in stdout:
        return "master"

    return None


def cleanup_stale_branch(code_path, branch_name):
    """
    FIX 2: Clean up stale agent branch before creating new one.
    - Check if branch exists via 'git branch --list {branch_name}'
    - If exists and we're NOT on it, delete with 'git branch -D {branch_name}'
    - If we ARE on it, checkout default branch first, then delete
    Return True if cleanup succeeded or branch didn't exist, False if cleanup failed.
    """
    # Check if branch exists
    success, stdout, _ = run_git(code_path, "branch", "--list", branch_name)
    if not success or branch_name not in stdout:
        # Branch doesn't exist, nothing to clean up
        return True

    # Get current branch
    success, current_branch, _ = run_git(code_path, "rev-parse", "--abbrev-ref", "HEAD")
    if not success:
        return False

    current_branch = current_branch.strip()

    # If we're on the stale branch, need to checkout default branch first
    if current_branch == branch_name:
        default_branch = get_default_branch(code_path)
        if not default_branch:
            print(f"WARNING: Could not determine default branch to checkout before deleting {branch_name}", file=sys.stderr)
            return False

        success, _, stderr = run_git(code_path, "checkout", default_branch)
        if not success:
            print(f"WARNING: Failed to checkout {default_branch} before deleting {branch_name}: {stderr}", file=sys.stderr)
            return False

    # Now delete the branch
    success, _, stderr = run_git(code_path, "branch", "-D", branch_name)
    if not success:
        print(f"WARNING: Failed to delete stale branch {branch_name}: {stderr}", file=sys.stderr)
        return False

    return True


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
    Skips memory files (handled by extract_memory_changes).
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

        # Skip memory files - they are handled by extract_memory_changes()
        if "memory.md" in file_path_str or file_path_str.startswith("projects/"):
            continue

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


def extract_memory_changes(repo_root, llm_response, project_name, config):
    """
    Extract <file_change> tags targeting memory files from LLM response.
    Handles files containing "memory.md" or starting with "projects/".
    Applies changes relative to repo_root instead of code_path.

    Returns list of changed file paths.
    """
    changed_files = []
    project_config = config["projects"].get(project_name, {})
    memory_rel_path = project_config.get("memory", f"projects/{project_name}/memory.md")

    # Extract file_change blocks
    pattern = r'<file_change\s+path="([^"]+)"\s+action="(create|modify|delete)">([^<]*)</file_change>'
    matches = re.finditer(pattern, llm_response, re.DOTALL)

    for match in matches:
        file_path_str = match.group(1)
        action = match.group(2)
        content = match.group(3).strip()

        # Only process memory files
        if not ("memory.md" in file_path_str or file_path_str.startswith("projects/")):
            continue

        # Resolve the full path
        if file_path_str == "memory.md":
            # Just "memory.md" means the project's memory file
            full_path = repo_root / memory_rel_path
        else:
            # Already a full relative path (e.g., "projects/lumen/memory.md")
            full_path = repo_root / file_path_str

        try:
            if action == "create" or action == "modify":
                # Ensure parent directory exists
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)
                changed_files.append(str(file_path_str))
                print(f"[MEMORY] Updated {full_path}")

            elif action == "delete":
                if full_path.exists():
                    full_path.unlink()
                    changed_files.append(str(file_path_str))
                    print(f"[MEMORY] Deleted {full_path}")

        except Exception as e:
            print(f"WARNING: Error processing memory file {file_path_str}: {e}", file=sys.stderr)

    return changed_files


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


def load_pending_approvals(config):
    """Load approvals/pending.json, creating it as [] if missing."""
    approvals_dir = config["repo_root"] / "approvals"
    approvals_dir.mkdir(exist_ok=True)
    approvals_file = approvals_dir / "pending.json"

    if not approvals_file.exists():
        with open(approvals_file, "w") as f:
            json.dump([], f, indent=2)
        return []

    try:
        with open(approvals_file) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_pending_approvals(config, approvals):
    """Persist approvals/pending.json."""
    approvals_file = config["repo_root"] / "approvals" / "pending.json"
    with open(approvals_file, "w") as f:
        json.dump(approvals, f, indent=2)


def add_pending_approval(config, task, project_name, result):
    """Create a single pending approval for a blocked task if not already present."""
    pending = load_pending_approvals(config)
    task_id = task.get("id")
    if any(a.get("task_id") == task_id for a in pending):
        return

    approval = {
        "task_id": task_id,
        "project": project_name,
        "issue": result.get("error") or "blocked",
        "options": [
            {"id": "A", "action": "create minimal stub and continue"},
            {"id": "B", "action": "reduce scope to smallest executable unit"},
            {"id": "C", "action": "mark done and defer to backlog"}
        ]
    }
    pending.append(approval)
    save_pending_approvals(config, pending)


def send_notification(message):
    """Minimal notification hook."""
    print(f"[NOTIFY] {message}")


# ============================================================================
# MAINTENANCE MODE
# ============================================================================

def _iter_project_repos(config):
    """Yield unique project code paths that exist and contain git metadata."""
    seen = set()
    for project_config in config.get("projects", {}).values():
        code_value = project_config.get("code")
        if not code_value:
            continue
        code_path = Path(code_value)
        if not code_path.exists():
            continue
        resolved = str(code_path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        yield code_path


def _cleanup_merged_branches(code_path):
    """Delete merged local branches except main/master."""
    success, stdout, _ = run_git(code_path, "branch", "--merged")
    if not success:
        return 0

    deleted = 0
    for raw_line in stdout.splitlines():
        branch = raw_line.replace("*", "").strip()
        if not branch or branch in {"main", "master"}:
            continue
        # Safe delete only merged branches; ignore failures.
        branch_deleted, _, _ = run_git(code_path, "branch", "-d", branch)
        if branch_deleted:
            deleted += 1
    return deleted


def _find_cleanup_candidates(code_path):
    """
    Identify safe cleanup candidates only (no deletion):
    - stale files (old mtime heuristic)
    - duplicate file names
    - obvious temp/test artifacts
    """
    now = datetime.datetime.now().timestamp()
    stale_days = 90
    stale_threshold = stale_days * 24 * 60 * 60

    files_by_name = {}
    candidates = set()

    for file_path in code_path.rglob("*"):
        if not file_path.is_file():
            continue

        rel = str(file_path.relative_to(code_path))
        if any(x in rel for x in [
            ".git", "__pycache__", "node_modules",
            "venv", ".venv", ".DS_Store"
        ]):
            continue

        files_by_name.setdefault(file_path.name, []).append(rel)

        try:
            age_seconds = now - file_path.stat().st_mtime
        except OSError:
            continue

        rel_lower = rel.lower()
        name_lower = file_path.name.lower()
        obvious_temp = (
            "tmp" in name_lower
            or "temp" in name_lower
            or name_lower.endswith((".bak", ".old", ".orig", ".tmp"))
        )
        obvious_test_artifact = name_lower.startswith("test_") and age_seconds > stale_threshold

        if age_seconds > stale_threshold and (obvious_temp or obvious_test_artifact):
            if obvious_temp:
                candidates.add(f"unused file: {rel}")
            else:
                candidates.add(f"stale script: {rel}")

    # Low-signal duplicate filename detection.
    for name, rel_paths in files_by_name.items():
        if len(rel_paths) > 3:
            joined = ", ".join(sorted(rel_paths)[:3])
            candidates.add(f"duplicate filename '{name}': {joined}")

    return sorted(candidates)[:25]


def _append_cleanup_findings(memory_path, candidates):
    """Append cleanup candidates to project memory file."""
    if not candidates:
        return

    existing = set()
    if memory_path.exists():
        existing_text = memory_path.read_text()
        for line in existing_text.splitlines():
            existing.add(line.strip())

    new_candidates = [c for c in candidates if c not in existing and f"- {c}" not in existing]

    if not new_candidates:
        return

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    with open(memory_path, "a") as f:
        f.write("\ncleanup candidates:\n")
        for candidate in new_candidates:
            f.write(f"- {candidate}\n")


def run_maintenance(config):
    """
    Run deterministic maintenance tasks:
    - clean merged branches
    - log cleanup candidates to memory files
    """
    result = {
        "branches_cleaned": 0,
        "cleanup_candidates": []
    }

    for code_path in _iter_project_repos(config):
        result["branches_cleaned"] += _cleanup_merged_branches(code_path)

    for project_name, project_config in config.get("projects", {}).items():
        code_value = project_config.get("code")
        if not code_value:
            continue
        code_path = Path(code_value)
        if not code_path.exists():
            continue

        candidates = _find_cleanup_candidates(code_path)
        if candidates:
            memory_path = config["repo_root"] / project_config["memory"]
            _append_cleanup_findings(memory_path, candidates)
            result["cleanup_candidates"].extend([f"{project_name}: {c}" for c in candidates])

    return result


def promote_candidates_to_tasks(config, project_name, candidates):
    """Promote high-confidence cleanup candidates into low-complexity tasks."""
    promoted_count = config.setdefault("_maintenance_promoted_count", 0)
    if promoted_count >= 3:
        return 0

    project_config = config.get("projects", {}).get(project_name)
    if not project_config:
        return 0

    tasks_dir = config["repo_root"] / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_prefix = project_config.get("tasks_prefix", project_name)
    task_files = sorted(tasks_dir.glob(f"{tasks_prefix}-*.yaml"))
    if task_files:
        target_file = task_files[-1]
    else:
        target_file = tasks_dir / f"{tasks_prefix}-maintenance.yaml"

    existing_descriptions = set()
    for task_file in task_files:
        try:
            with open(task_file) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            continue
        for task in data.get("tasks", []):
            desc = str(task.get("description", "")).strip().lower()
            if desc:
                existing_descriptions.add(desc)

    try:
        with open(target_file) as f:
            target_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        target_data = {}
    except Exception:
        target_data = {}

    target_tasks = target_data.get("tasks")
    if not isinstance(target_tasks, list):
        target_tasks = []
    target_data["tasks"] = target_tasks

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    promoted = 0
    for candidate in candidates:
        if config["_maintenance_promoted_count"] >= 3:
            break

        candidate_text = str(candidate).strip()
        lowered = candidate_text.lower()
        if not ("unused file:" in lowered or "stale script:" in lowered):
            continue

        if lowered.startswith("unused file:"):
            path_part = candidate_text.split(":", 1)[1].strip()
            task_description = f"Remove unused file {path_part}"
        elif lowered.startswith("stale script:"):
            path_part = candidate_text.split(":", 1)[1].strip()
            task_description = f"Review stale script {path_part}"
        else:
            continue

        normalized = task_description.strip().lower()
        if normalized in existing_descriptions:
            continue

        target_tasks.append({
            "id": f"maintenance-{timestamp}-{config['_maintenance_promoted_count'] + 1}",
            "description": task_description,
            "status": "open",
            "complexity": "low",
            "notes": "generated by maintenance"
        })
        existing_descriptions.add(normalized)
        config["_maintenance_promoted_count"] += 1
        promoted += 1

    if promoted:
        with open(target_file, "w") as f:
            yaml.safe_dump(target_data, f, sort_keys=False)

    return promoted


# ============================================================================
# DAILY BRIEF
# ============================================================================

def write_brief(config, run_summary):
    """
    Append conversational run entry to briefs/YYYY-MM-DD.md.
    Creates file with header if it doesn't exist.
    Each run appends a timestamped block in plain conversational language.
    """
    repo_root = config["repo_root"]
    briefs_dir = repo_root / "briefs"
    briefs_dir.mkdir(exist_ok=True)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    brief_file = briefs_dir / f"{date_str}.md"
    time_str = datetime.datetime.now().strftime("%H:%M")

    # Initialize file with header if it doesn't exist
    if not brief_file.exists():
        try:
            with open(brief_file, "w") as f:
                f.write(f"# Daily Brief — {date_str}\n\n")
        except Exception as e:
            print(f"WARNING: Failed to create brief file: {e}", file=sys.stderr)
            return

    # Build conversational entry
    entry = _build_brief_entry(time_str, run_summary, load_pending_approvals(config))

    # Append entry to file
    try:
        with open(brief_file, "a") as f:
            f.write(entry)
    except Exception as e:
        print(f"WARNING: Failed to write brief entry: {e}", file=sys.stderr)


def _build_brief_entry(time_str, run_summary, pending_approvals=None):
    """
    Build a conversational timestamped entry from run_summary.
    Returns formatted string ready to append to brief file.
    """
    lines = ["---", f"**[{time_str}]**", ""]

    completed = run_summary.get("completed", [])
    blocked = run_summary.get("blocked", [])
    skipped = run_summary.get("skipped", [])

    # Build conversational paragraph for completed tasks
    if completed:
        para = []
        for i, task in enumerate(completed):
            task_id = task.get("id", "unknown")
            description = task.get("description", "")
            summary = task.get("summary", "")

            # Determine if read-only task
            is_readonly = "read-only" in task.get("notes", "").lower()
            if not is_readonly and task.get("complexity") == "low":
                desc_lower = description.lower()
                inspection_keywords = {"inspect", "inspection", "review", "audit", "read", "analyze", "analysis"}
                is_readonly = any(kw in desc_lower for kw in inspection_keywords)

            # Build sentence from summary if available
            if summary:
                # Extract first sentence or key points from LLM response
                first_line = summary.split("\n")[0]
                task_sentence = f"Ran {task_id} — {first_line[:100]}"
            else:
                task_sentence = f"Ran {task_id} — {description[:80]}"

            # Add read-only note if applicable
            if is_readonly:
                task_sentence += ". Didn't touch any source code."

            if i == 0:
                para.append(task_sentence)
            else:
                para.append(f"Also {task_sentence[4:]}")  # Remove "Ran " prefix for continuation

        lines.append(" ".join(para))

    # Add blocked tasks on separate sentences
    if blocked:
        lines.append("")
        for task in blocked:
            task_id = task.get("id", "unknown")
            error = task.get("error", "unknown error")
            notes = task.get("notes", "")

            # Convert error code to plain language
            error_msg = _error_to_plain_language(error, notes)
            lines.append(f"Tried {task_id} but {error_msg}.")

    # Add what's next (expectation for next run)
    if completed or blocked:
        lines.append("")
        next_items = []
        if completed:
            next_items.extend([f"{t.get('id', 'unknown')}" for t in completed])
        if blocked:
            next_items.extend([f"{t.get('id', 'unknown')}" for t in blocked if "retry" in t.get("notes", "").lower()])

        if next_items:
            next_str = ", ".join(next_items[:2])
            if len(next_items) > 2:
                next_str += " and more"
            lines.append(f"Next up: {next_str}.")

    if pending_approvals:
        lines.append("")
        lines.append("Approvals needed:")
        for approval in pending_approvals:
            lines.append(f"  {approval.get('task_id', 'unknown')} — {approval.get('issue', 'blocked')}")

    maintenance = run_summary.get("maintenance")
    if maintenance:
        lines.append("")
        lines.append("Maintenance:")
        lines.append(f"- cleaned {maintenance.get('branches_cleaned', 0)} branches")
        lines.append(f"- flagged {len(maintenance.get('cleanup_candidates', []))} cleanup candidates")

    lines.append("")
    return "\n".join(lines)


def _error_to_plain_language(error, notes):
    """Convert error codes to conversational language."""
    error_map = {
        "checkpoint_failed": "couldn't create a git checkpoint",
        "branch_creation_failed": "couldn't create a git branch",
        "commit_failed": "couldn't commit changes",
        "file_write_error": "encountered file write errors",
        "cascading_failure": "caused validation failures we couldn't safely recover from",
        "recovery_failed": "failed to recover after validation errors",
        "llm_api_error": "LLM API call failed"
    }

    for key, msg in error_map.items():
        if key in error:
            return msg

    # Check notes for infrastructure issues
    notes_lower = notes.lower()
    if "dirty working tree" in notes_lower:
        return "couldn't proceed — probably a dirty working tree"
    if "infrastructure" in notes_lower or "transient" in notes_lower:
        return "hit an infrastructure issue"

    return "encountered an error"


def _format_task_list(tasks):
    """Helper to format task lists for brief. Kept for backwards compatibility."""
    if not tasks:
        return "- None"
    return "\n".join(f"- {t.get('project', 'unknown')}/{t.get('id', 'unknown')}: {t.get('description', '')[:60]}" for t in tasks)


def _format_escalations(escalations):
    """Helper to format escalations for brief. Kept for backwards compatibility."""
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
        # 0. Determine if task is read-only (early, before context loading)
        # FIX 1: Enhanced read-only detection
        is_readonly = "read-only" in task.get("notes", "").lower()

        # Also treat as read-only if: complexity=low AND description contains inspection/analysis keywords
        if not is_readonly and task.get("complexity") == "low":
            description_lower = task.get("description", "").lower()
            readonly_keywords = {"inspect", "inspection", "review", "audit", "read", "analyze", "analysis"}
            if any(kw in description_lower for kw in readonly_keywords):
                is_readonly = True

        # 1. Load project context
        memory = load_memory(config, project_name)
        relevant_code = {}
        inspection_context = ""

        if code_path and code_path.exists():
            # Load appropriate context based on task type
            if is_readonly:
                inspection_context = load_inspection_context(code_path)
            else:
                relevant_code = load_relevant_code(code_path, task.get("description", ""))

        # 2. Select model
        model_info = select_model(task, config["models"])

        # 4. Git operations (if code task and not read-only)
        checkpoint_hash = None
        branch_name = None
        pre_validation = None

        # FIX 1: Skip ENTIRE git section for read-only tasks
        if code_path and code_path.exists() and not is_readonly:
            stash = ensure_clean_tree(code_path)
            if dry_run:
                print(f"[DRY-RUN] Would ensure clean tree: {stash}")

            branch_prefix = project_config.get("branch_prefix", f"agent/{project_name}")

            # FIX 2: Clean up stale branch before creating new one
            if not dry_run:
                cleanup_stale_branch(code_path, f"{branch_prefix}-{task_id}")

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

        # Use inspection context for read-only tasks, keyword-matched code for change tasks
        if is_readonly and inspection_context:
            code_section = f"\n\n{inspection_context}"
        elif relevant_code:
            code_section = "\n\nRelevant Code Files:\n"
            for file_path, content in relevant_code.items():
                code_section += f"\n--- {file_path} ---\n{content[:1000]}\n"

        # Resolve memory path for reference in prompt
        memory_rel_path = config["projects"][project_name].get("memory", f"projects/{project_name}/memory.md")

        user_prompt = f"""
Project Memory:
{memory}

Task: {task.get('description')}

Acceptance Criteria:
{task.get('acceptance_criteria')}

Operating Principles:
{system_files['principles'][:500]}

{code_section}

INSTRUCTIONS FOR FILE CHANGES:

For code changes: Use paths relative to the project code directory.

For memory updates: If this task involves inspection, analysis, or review (read-only operations), you MUST output a <file_change> tag to update the project memory file. The memory file path is: {memory_rel_path}

Update memory.md to reflect the CURRENT STATE of the project after this task completes. Update these sections with concise, scannable information:
- Current Milestone: One or two sentences about what's actually true now
- Backlog: Concrete next steps as short bullet points (not paragraphs)
- Context Window: Key facts the next agent run needs (tech stack, key files, architecture in brief bullets)
- Blockers: Add new ones discovered, remove resolved ones (one line each)

Keep memory.md concise and scannable. It is a snapshot showing current state, NOT a report. Detailed analysis and reasoning belong in your response text, not in memory.md.

Preserve all existing section headers: Vision, Current Milestone, Active Offer, Positioning, Backlog, Queue, Blockers, Context Window, Last Updated.

Wrap code changes and memory updates in XML tags:
<file_change path="relative/path" action="create|modify|delete">
content
</file_change>

For memory: use the exact path "{memory_rel_path}"
For code: use paths relative to the project code directory
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

        # Save brief summary of LLM response for brief writing
        result["summary"] = response[:500]

        # 6. Apply LLM output
        changed_files = []

        # Extract and apply memory.md changes (always, even for read-only tasks)
        memory_changes = extract_memory_changes(config["repo_root"], response, project_name, config)
        changed_files.extend(memory_changes)

        # Extract and apply code changes (for non-read-only tasks with code)
        if code_path and code_path.exists():
            changes = parse_and_apply_changes(code_path, response)
            changed_files.extend(changes["changed_files"])

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

    finally:
        # FIX 3: Always return to default branch after task execution
        if branch_name and code_path and code_path.exists() and not dry_run:
            default_branch = get_default_branch(code_path)
            if default_branch:
                success, _, stderr = run_git(code_path, "checkout", default_branch)
                if success:
                    print(f"[CLEANUP] Checked out {default_branch} after task {task_id}")
                else:
                    print(f"WARNING: Failed to checkout {default_branch} after task {task_id}: {stderr}", file=sys.stderr)

    if not result.get("summary"):
        if result.get("status") == "done":
            result["summary"] = task.get("description") or task.get("id")
        elif result.get("status") == "blocked":
            result["summary"] = result.get("error") or "blocked"
        else:
            result["summary"] = "skipped"
    return result


def attempt_blocker_resolution(blocked_task, all_tasks, project_name, config, system_files, dry_run=False):
    """
    Attempt to resolve a blocked task by executing its dependency.

    If depends_on is missing → return False
    Find dependency task in all_tasks
    If dependency not found or already "done" → return False
    Execute dependency using execute_task()
    Update dependency status in YAML via update_task_status()
    Return True only if dependency finishes with "done"
    """
    depends_on = blocked_task.get("depends_on")
    if not depends_on:
        return False

    # Find dependency task
    dep_task = None
    for t in all_tasks:
        if t.get("id") == depends_on:
            dep_task = t
            break

    if not dep_task:
        return False

    # Prevent re-running same dependency in same run
    if dep_task.get("_attempted"):
        return False

    dep_task["_attempted"] = True

    # If dependency already done, nothing to do
    if dep_task.get("status") == "done":
        return False

    # Execute dependency
    result = execute_task(dep_task, project_name, config, system_files, dry_run=dry_run)

    # Update dependency status in YAML
    task_files = list((config["repo_root"] / "tasks").glob(f"{project_name}-*.yaml"))
    for task_file in task_files:
        update_task_status(config, project_name, task_file, depends_on, result["status"])

    # Return True only if dependency finished with "done"
    if result["status"] != "done":
        return False

    return True


def run(args):
    """
    Main entry point.
    Parse CLI args, load config, execute tasks, write brief.
    """
    config = load_config()

    if args.run:
        args.all = True

    if args.approvals:
        args.approval = "list"

    if args.approve:
        args.approval = args.approve

    if args.state_status:
        print_state_status(config)
        return

    if args.brief or args.logs:
        briefs_dir = config["repo_root"] / "briefs"
        if not briefs_dir.exists():
            print("No briefs found.")
            return

        brief_files = sorted(briefs_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
        if not brief_files:
            print("No briefs found.")
            return

        latest_brief = brief_files[-1]
        print(latest_brief.read_text())
        return

    pending_approvals = load_pending_approvals(config)
    if pending_approvals:
        send_notification(f"{len(pending_approvals)} approvals pending")

    if args.approval is not None:
        if args.approval == "list":
            print("\nPending approvals:")
            if pending_approvals:
                for approval in pending_approvals:
                    print(f"  {approval.get('task_id')} ({approval.get('project')}) — {approval.get('issue')}")
                    for option in approval.get("options", []):
                        print(f"    {option.get('id')}: {option.get('action')}")
            else:
                print("  no pending approvals")
            return

        if not pending_approvals:
            print("No pending approvals to apply.")
            return

        selected = args.approval.upper()
        approval = pending_approvals[0]
        task_id = approval.get("task_id")
        project_name = approval.get("project")
        note = None
        new_status = "open"

        if selected == "A":
            note = "approved: stub implementation"
        elif selected == "B":
            note = "approved: reduced scope"
        elif selected == "C":
            new_status = "done"
        else:
            print(f"Unknown approval option: {args.approval}")
            return

        task_files = list((config["repo_root"] / "tasks").glob(f"{project_name}-*.yaml"))
        for task_file in task_files:
            update_task_status(config, project_name, task_file, task_id, new_status, notes=note)

        pending_approvals = pending_approvals[1:]
        save_pending_approvals(config, pending_approvals)
        print(f"Applied approval {selected} to {project_name}/{task_id}")
        return

    if args.status:
        print("\n=== CHECK-IN ===\n")

        if args.all or not args.project:
            projects = config["projects"].keys()
        else:
            projects = [args.project]

        for project_name in projects:
            tasks = load_tasks(config, project_name)
            executable = get_next_tasks(tasks)

            done = [t for t in tasks if t.get("status") == "done"]
            blocked = [t for t in tasks if t.get("status") == "blocked"]
            open_tasks = [t for t in tasks if t.get("status") == "open"]

            print(f"{project_name}:")

            if done:
                last = done[-1]
                print(f"  worked on {last.get('id')} — {last.get('description', '')[:60]}")
            elif open_tasks:
                next_task = executable[0] if executable else open_tasks[0]
                print(f"  working on {next_task.get('id')} — {next_task.get('description', '')[:60]}")
            else:
                print("  no active work right now")

            if blocked:
                b = blocked[0]
                print(f"  ran into blocker on {b.get('id')} — {b.get('notes', b.get('error', 'needs attention'))}")
            else:
                print("  no other issues — everything looks good")

            if executable:
                nxt = executable[0]
                print(f"  next up: {nxt.get('id')} — {nxt.get('description', '')[:60]}")
            else:
                print("  nothing queued next")

            if len(blocked) > 1:
                print(f"  keep an eye on {blocked[1].get('id')} — may need attention")
            elif len(open_tasks) > 1:
                print(f"  keep an eye on {open_tasks[1].get('id')} — coming up next")

            print("")

        print("Pending approvals:")
        pending_approvals = load_pending_approvals(config)
        if pending_approvals:
            for approval in pending_approvals:
                print(f"  {approval.get('task_id')} — {approval.get('issue')}")
        else:
            print("  no pending approvals")
        print("")
        return

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
    any_executable_work = False
    for project_name in projects_to_run:
        if project_name not in config["projects"]:
            print(f"ERROR: Project '{project_name}' not found in configuration", file=sys.stderr)
            continue

        tasks = load_tasks(config, project_name)
        executable = get_next_tasks(tasks)
        if executable:
            any_executable_work = True

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

            # Track result — merge task dict with result (includes summary for completed tasks)
            task_with_result = {**task, **result}
            if result["status"] == "done":
                run_summary["completed"].append(task_with_result)
            elif result["status"] == "blocked":
                dependency_attempted = False
                # Try to automatically resolve dependency blocker
                if not dry_run and task.get("depends_on"):
                    dependency_attempted = True
                    if attempt_blocker_resolution(task, tasks, project_name, config, system_files):
                        # Retry original task
                        result = execute_task(task, project_name, config, system_files, dry_run=dry_run)
                        executed += 1

                        # Update task status
                        for task_file in task_files:
                            update_task_status(config, project_name, task_file, task["id"], result["status"])

                        # Recompute task_with_result with new result
                        task_with_result = {**task, **result}
                if not dry_run and result["status"] == "blocked":
                    depends_on = task.get("depends_on")
                    unresolved_dependency = True
                    if depends_on:
                        dep_task = next((t for t in tasks if t.get("id") == depends_on), None)
                        unresolved_dependency = bool(dep_task and dep_task.get("status") != "done")
                    if not unresolved_dependency:
                        add_pending_approval(config, task, project_name, result)

                # Append to appropriate bucket based on final result
                if result["status"] == "done":
                    run_summary["completed"].append(task_with_result)
                else:
                    reason = (
                        task_with_result.get("error")
                        or task.get("notes")
                        or task.get("depends_on")
                        or "unknown"
                    )

                    run_summary["blocked"].append({
                        **task_with_result,
                        "block_reason": str(reason).split("\n")[0]
                    })
            else:
                run_summary["skipped"].append(task_with_result)

    if not dry_run and not any_executable_work:
        maintenance_result = run_maintenance(config)
        run_summary["maintenance"] = maintenance_result
        config["_maintenance_promoted_count"] = 0
        for entry in maintenance_result.get("cleanup_candidates", []):
            if config["_maintenance_promoted_count"] >= 3:
                break
            if ":" not in entry:
                continue
            project_name, candidate = entry.split(":", 1)
            promote_candidates_to_tasks(config, project_name.strip(), [candidate.strip()])
        send_notification("maintenance cycle completed")

    # Write brief
    if not dry_run:
        write_brief(config, run_summary)

    # Print summary
    print(f"\n=== RUN SUMMARY ===")
    print(f"Completed: {len(run_summary['completed'])}")
    print(f"Blocked: {len(run_summary['blocked'])}")
    if run_summary["blocked"]:
        print("\nBlocked tasks:")
        for t in run_summary["blocked"]:
            print(f"  {t.get('id')} — {t.get('block_reason')}")
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
    parser.add_argument("--status", action="store_true", help="Show system status (no execution)")
    parser.add_argument("--state-status", action="store_true", help="Show Office OS operating condition diagnostics")
    parser.add_argument("--approval", nargs="?", const="list")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--brief", action="store_true")
    parser.add_argument("--approvals", action="store_true")
    parser.add_argument("--approve", type=str)
    parser.add_argument("--logs", action="store_true")

    args = parser.parse_args()

    # Validate args
    if (
        not args.all
        and not args.project
        and not args.status
        and not args.state_status
        and args.approval is None
        and not args.run
        and not args.brief
        and not args.approvals
        and args.approve is None
        and not args.logs
    ):
        parser.error("Must specify --project or --all")

    run(args)


if __name__ == "__main__":
    main()
