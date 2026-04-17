<!-- This file is updated by both founder and agent. Do not treat as static. -->

# Sales — Memory

## Vision
Outreach and pipeline engine that generates qualified conversations converting to revenue. Uses Office OS infrastructure to drive adoption of Lumen (primary) and Merlin (secondary).

## Current Milestone
Queue and outreach generation partially wired. Missing real send layer, real lead ingestion, and response handling feedback loop. Current system can simulate work but not produce outcomes. Autonomy score from production audit: 11/100.

## Active Offer
Founder to define — depends on which product is being pushed through the pipeline.

## Positioning
Sales is the discovery engine, not just execution. All sales activity feeds back into product improvements, messaging refinement, and targeting precision.

## Backlog
- Define ideal customer profile (loan officers for Lumen)
- Establish outreach channel strategy
- Build lead scoring criteria
- Integrate real send layer (SMTP/SendGrid)
- Build reply detection
- Close the feedback loop (responses → messaging iteration)

## Queue
<!-- Founder populates after reviewing backlog -->

## Blockers
- No execution layer — system generates messages but cannot send them | severity: critical | owner: agent
- No lead sourcing — leads are manually entered into JSON | severity: critical | owner: agent
- No reply detection — no inbox monitoring | severity: critical | owner: agent

## Context Window
Sales exists to drive Lumen adoption first. The three critical integrations (send, source, detect) are the minimum fix set from the production audit. Until these work, the sales engine is a simulation.

## Last Updated
2026-04-17 12:00 by founder
