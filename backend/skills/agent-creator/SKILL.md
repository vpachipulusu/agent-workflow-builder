---
name: agent-creator
description: >
  Create a new Microsoft Agent Framework agent from a natural-language
  description or manual instruction edits. Use when the user wants to
  build a new AI agent, modify an existing agent's instructions, or
  generate an agent configuration. Outputs a validated agent definition
  (YAML + Python code) that can be deployed to Azure AI Foundry.
license: MIT
compatibility: Requires python3, agent-framework SDK
metadata:
  author: poc-team
  version: "1.0"
allowed-tools: load_skill read_skill_resource run_skill_script
---

# Agent Creator Skill

## Purpose

This skill enables an orchestrator agent to **create** and **validate** Microsoft
Agent Framework agent definitions from either:

1. **Natural-language prompts** – The user describes the agent they want in plain
   language, analogous to creating a GPT in ChatGPT.
2. **Manual instruction editing** – The user provides explicit instruction text,
   tool lists, and model parameters.

## Workflow

### Step 1 – Gather Requirements

Collect the following from the user or from the orchestrator context:

| Field               | Required | Default            | Description                                                    |
|---------------------|----------|--------------------|----------------------------------------------------------------|
| `name`              | yes      | —                  | Unique snake_case agent name (max 64 chars)                    |
| `description`       | yes      | —                  | One-line description of the agent                              |
| `instructions`      | yes      | —                  | System prompt / instruction text for the agent                 |
| `model`             | no       | `gpt-4o`           | Azure OpenAI deployment name                                   |
| `tools`             | no       | `[]`               | List of tools the agent may call                               |
| `context_providers` | no       | `[]`               | Context providers (e.g., SkillsProvider)                       |
| `temperature`       | no       | `0.7`              | Sampling temperature                                           |

### Step 2 – Generate Agent Definition

Produce **two artefacts**:

1. **`agent.yaml`** – declarative agent configuration:

```yaml
name: <name>
description: <description>
model: <model>
instructions: |
  <instructions>
tools: <tools>
temperature: <temperature>
```

2. **`agent.py`** – executable Python code using `agent_framework`:

```python
from agent_framework import AzureOpenAIChatClient
from azure.identity.aio import DefaultAzureCredential

agent = AzureOpenAIChatClient(
    credential=DefaultAzureCredential(),
    endpoint="<AZURE_OPENAI_ENDPOINT>",
    deployment="<model>",
).as_agent(
    name="<name>",
    instructions="""<instructions>""",
)
```

### Step 3 – Validate

Run the `validate_agent` script to check:

- YAML is well-formed
- Required fields present
- `agent.py` has no syntax errors
- Instructions length < 32,000 chars

If validation fails, report the errors and suggest fixes.

### Step 4 – Persist

Save both files to `generated/agents/<name>/`.

## Natural Language → Agent Generation

When the user provides a natural-language description like "I want an agent that
helps with expense reports", generate appropriate:

1. **Name** – derive from the description (e.g., `expense_report_assistant`)
2. **Instructions** – craft detailed system prompt capturing expertise, tone,
   constraints, and response format
3. **Tools** – suggest relevant tools based on the domain
4. **Description** – concise summary

### Quality Guidelines

- Instructions should be 200–2000 characters
- Be specific about the agent's domain and boundaries
- Include output format guidance where applicable
- Add safety guardrails (out-of-scope handling, refusal policies)
