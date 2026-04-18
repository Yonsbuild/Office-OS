# Failure Protocol

This document defines how the agent handles mistakes, broken code, and unexpected failures. The goal is damage containment: detect fast, stop early, recover safely, escalate honestly.

## Principle

The agent's first duty when something goes wrong is to protect working code. Recovery is secondary. Logging is mandatory. Hiding failures is never acceptable.

---

## Pre-Execution Safety

### Branch Isolation
- The agent NEVER works directly on main or master.
- Every task creates a branch: `[branch_prefix]-[task_id]` (e.g., `agent/merlin-merlin-001-fix-reanalysis-bug`).
- If branch creation fails, the task is blocked. Do not proceed.

### Checkpoint
- Before modifying any code, the agent confirms the working tree is clean (no uncommitted changes).
- If the tree is dirty, the agent stashes or commits existing changes before starting. This stash/commit is logged.
- The agent commits a checkpoint with message: `checkpoint: pre-[task_id]` before making any task-related changes.
- This checkpoint is the rollback target if recovery fails.

---

## Validation

### Post-Change Validation
- After making code changes, the agent runs the validation commands defined in `system/projects.yaml` for that project.
- If no validation commands are configured (echo placeholder), ALL code changes require manual founder review. The agent marks the task as `pending-review`, not `done`.
- If validation passes with zero new failures, the agent may proceed normally.

### Failure Detection
- A validation failure is "new" if it was NOT present at the checkpoint.
- The agent compares pre-task validation output (run at checkpoint) with post-change validation output.
- If new failures are detected, the failure cascade begins.

---

## Failure Cascade

When the agent detects that its changes introduced a problem:

### Step 1 — STOP
- The agent makes no further code changes.
- The branch is frozen in its current state.
- The agent logs: `[HH:MM] FAILURE DETECTED | project | task_id | description of failure`

### Step 2 — RECORD
The agent creates an incident entry with:
- Which files were changed (list every file path)
- What the intended fix/change was
- What the validation output said (exact error messages)
- The git diff of all changes since checkpoint
- Timestamp

This is logged in:
- `/logs/run-YYYY-MM-DD.txt` (as an incident block)
- `/projects/[project]/decisions.md` (with outcome: failed, incident field populated)

### Step 3 — ASSESS BLAST RADIUS
The agent determines scope of damage:

**Contained failure:** Validation errors reference ONLY files the agent modified. No other files, modules, or tests are affected.

**Cascading failure:** Validation errors reference files the agent did NOT modify, or errors appear in unrelated test suites, or build/compile failures affect the broader project.

- If contained → proceed to Step 4 (attempt recovery)
- If cascading → skip to Step 5 (escalate immediately, do not attempt recovery)

### Step 4 — ATTEMPT RECOVERY (contained failures only)
- The agent gets ONE recovery attempt.
- The recovery must be scoped to the same files already modified — no expanding the change set.
- After the recovery attempt, run validation again.
- If validation passes → log as self-correction in decisions.md (outcome: completed, incident: "self-corrected after initial failure"). Continue execution.
- If validation fails again → revert the entire branch to the checkpoint commit: `git reset --hard [checkpoint_commit_hash]`. Log the task as `outcome: reverted`. Proceed to Step 5.

### Step 5 — SUBAGENT REVIEW
A second LLM call reviews the situation. The subagent receives:
- The original task description and acceptance criteria
- The diff of changes that caused the failure
- The validation error output
- The agent's incident log entry

The subagent's role is strictly limited:
- Confirm the revert was clean (working tree matches checkpoint)
- Flag if any damage survived the revert
- Recommend ONE of:
  - "retry_different_approach" — the task is feasible but needs a different strategy
  - "decompose" — the task is too complex and should be broken into smaller tasks
  - "escalate_to_founder" — the task requires human judgment or context the agent doesn't have
- The subagent CANNOT make code changes
- The subagent CANNOT override the revert
- The subagent's recommendation is logged in decisions.md

### Step 6 — ESCALATE
If recovery failed, subagent flagged issues, or blast radius was cascading:
- Add to daily brief under Escalations with full incident detail
- Add blocker to project memory.md: "[task_id] failed — see incident log" | severity: high | owner: founder
- If a notification system is configured, send immediate alert (not just daily brief)
- Stop executing tasks for this project for the remainder of this run
- Other projects may continue if they have unblocked tasks

---

## Rules Summary

1. Always branch. Never touch main.
2. Always checkpoint before changes.
3. Always validate after changes.
4. New failures trigger the cascade — no exceptions.
5. One recovery attempt for contained failures. Zero for cascading.
6. Failed recovery → full revert to checkpoint.
7. Subagent reviews but cannot write code.
8. All incidents are logged in decisions.md AND run log AND daily brief.
9. Cascading failures escalate immediately — no recovery attempt.
10. The agent never hides, minimizes, or delays reporting a failure.

---

## Validation Placeholder Notice

Until real validation commands are configured in `system/projects.yaml`, the agent treats all code changes as requiring manual review. This means:
- Tasks that modify code are marked `pending-review`, not `done`
- The failure cascade only triggers on validation commands that actually run
- The founder is responsible for reviewing all code changes on agent branches until test suites are in place
- Adding real validation commands to projects.yaml is a high-priority backlog item
