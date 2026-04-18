# Escalation Rules

These define when the agent must stop executing and flag the founder for input. Escalation is not failure — it is the agent recognizing the boundary of its authority.

## Must Escalate

The agent MUST stop and flag the founder when:

- A task requires sending communications to real people (email, LinkedIn, SMS, any external channel)
- A task requires access to external systems not yet integrated (APIs, databases, services the agent cannot reach)
- A blocker is marked severity: critical in any project's memory.md
- The agent is unsure whether a task is complete — ambiguity about "done" is an escalation, not a judgment call
- The task output could affect live revenue, active client relationships, or deployed production systems
- Three consecutive tasks in the same project are blocked (indicates systemic issue, not isolated blocker)
- A task requires making pricing, offer structure, or positioning decisions
- A task involves deleting, archiving, or permanently modifying existing data or production code

## Must Not Escalate

The agent should NOT escalate for:

- Tasks that are clearly scoped and have explicit acceptance criteria
- Creating or modifying files within the project's own directory
- Updating memory.md, decisions.md, or log files
- Marking tasks as blocked when the reason is clear
- Skipping dependent tasks after a blocker — this is expected behavior, not an exception
