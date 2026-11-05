---
name: workflow-creator
description: >
  Create and edit Microsoft Agent Framework workflows from natural-language
  descriptions. Use when the user wants to build a new workflow, add/remove
  edges or executors, or modify an existing workflow graph. Outputs a
  validated workflow definition (YAML + Python code).
license: MIT
compatibility: Requires python3, agent-framework SDK
metadata:
  author: poc-team
  version: "1.0"
allowed-tools: load_skill read_skill_resource run_skill_script
---

# Workflow Creator Skill

## Purpose

This skill enables an orchestrator agent to **create**, **edit**, and **validate**
Microsoft Agent Framework workflow definitions from:

1. **Natural-language prompts** – "Build a workflow that takes customer inquiries,
   classifies them, and routes to the appropriate agent."
2. **Manual editing** – Add / remove executors and edges to an existing workflow.

## Core Concepts Reference

- **Executor**: A processing unit (AI agent or custom logic) that receives typed
  messages, processes them, and produces output. Defined with `@handler` decorator.
- **Edge**: Connection between executors. Types: Direct, Conditional, Switch-Case,
  Fan-out, Fan-in.
- **WorkflowBuilder**: Constructs the directed graph from executors + edges.

Read `references/WORKFLOW_PATTERNS.md` for detailed examples.

## Workflow

### Step 1 – Gather Requirements

Collect the following:

| Field        | Required | Description                                               |
|-------------|----------|-----------------------------------------------------------|
| `name`       | yes      | Unique snake_case workflow name                            |
| `description`| yes      | What the workflow does                                     |
| `executors`  | yes      | List of executor definitions (name, type, handler logic)   |
| `edges`      | yes      | List of edges (source → target, optional condition)        |
| `start`      | yes      | Name of the starting executor                              |

### Step 2 – Generate Workflow Definition

Produce **two artefacts**:

1. **`workflow.yaml`** – declarative definition:

```yaml
name: <name>
description: <description>
start: <start_executor_name>
executors:
  - name: classifier
    type: agent  # or "function"
    instructions: "Classify customer inquiry into: billing, technical, general"
    model: gpt-4o
  - name: billing_agent
    type: agent
    instructions: "Handle billing inquiries"
    model: gpt-4o
  - name: tech_agent
    type: agent
    instructions: "Handle technical support"
    model: gpt-4o
edges:
  - source: classifier
    target: billing_agent
    condition: "result.category == 'billing'"
  - source: classifier
    target: tech_agent
    condition: "result.category == 'technical'"
```

2. **`workflow.py`** – executable Python code:

```python
from agent_framework import (
    Executor, WorkflowBuilder, WorkflowContext, handler, executor
)

class Classifier(Executor):
    @handler
    async def classify(self, message: str, ctx: WorkflowContext[str]) -> None:
        # Classification logic
        await ctx.send_message(result)

# ... more executors ...

builder = WorkflowBuilder(start_executor=classifier)
builder.add_edge(classifier, billing_agent)
builder.add_edge(classifier, tech_agent)
workflow = builder.build()
```

### Step 3 – Validate

Run the `validate_workflow` script to check:

- YAML is well-formed and all fields present
- Every edge references valid executor names
- Start executor exists
- Graph is connected (all executors reachable from start)
- No duplicate edges
- Python code has no syntax errors

If validation fails, report errors and suggest fixes.

### Step 4 – Persist

Save to `generated/workflows/<name>/`.

## Natural Language → Workflow Generation

When the user describes a workflow in plain language:

1. **Identify executors** – Extract individual processing steps from the description.
   Each distinct task becomes an executor.
2. **Determine executor types** – If the step needs LLM reasoning → `agent` type.
   If pure logic → `function` type.
3. **Map edges** – Determine data flow. Look for keywords like "then", "if",
   "route to", "fan out", "collect", "aggregate".
4. **Identify conditions** – Extract routing conditions for conditional edges.
5. **Set start executor** – The first step in the process.

### Edge Type Selection Guide

| User language                          | Edge type      |
|----------------------------------------|----------------|
| "then", "next", "followed by"         | Direct         |
| "if … then … else"                    | Conditional    |
| "based on", "depending on", "route to"| Switch-Case    |
| "all of", "in parallel", "at the same time" | Fan-out  |
| "combine", "aggregate", "merge"       | Fan-in         |

## Editing Existing Workflows

When editing, load the current `workflow.yaml`, apply changes, and re-validate:

- **Add executor**: Append to executors list, add edges as needed
- **Remove executor**: Remove from list, remove all connected edges
- **Add edge**: Add to edges list
- **Remove edge**: Remove from edges list
- **Modify condition**: Update the condition on the specified edge
- **Change instructions**: Update executor instructions

Always re-validate after editing.
