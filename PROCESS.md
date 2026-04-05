# PROCESS.md — Agent Development Process

## Planning (MANDATORY before any new work)

Before starting any new work, you MUST follow this process. No exceptions.

### Step 1: Write a Plan
Create a plan document at `plans/<descriptive-name>.md`. The plan MUST include:
1. **Motivation** — Why is this work needed?
2. **Acceptance Criteria** — Concrete, testable criteria that define "done"
3. **Approach** — How the work will be achieved

### Step 2: Verify Your Plan
- Search the web for relevant prior art
- Read the actual USD source code you'll be working with
- Verify compatibility with the current codebase

### Step 3: Implement with TDD
- Write failing tests first
- Implement to make them pass
- Commit frequently
