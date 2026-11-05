"""Orchestrator Agent – uses Skills to create / edit Agents and Workflows.

This module implements the core logic that:
1. Loads the agent-creator and workflow-creator Skills
2. Uses LLM to interpret natural-language requests
3. Generates YAML + Python artefacts
4. Runs validation (in-process)
5. Persists results
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
from pathlib import Path

import yaml

from config import AGENTS_DIR, AZURE_OPENAI_ENDPOINT, SKILLS_DIR, WORKFLOWS_DIR
from llm_client import chat_completion, chat_completion_json
from models import (
    AgentCreateResponse,
    AgentDefinition,
    EdgeDef,
    ExecutorDef,
    ValidationResult,
    WorkflowCreateResponse,
    WorkflowDefinition,
)
from weekend_saver.custom.definition import BUILTIN as BUILTIN_EXECUTOR_TYPE
from weekend_saver.custom.definition import DEFINITION_NAME as RESERVED_WORKFLOW_NAME

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill loading (progressive disclosure – stage 2: load full SKILL.md)
# ---------------------------------------------------------------------------

def _load_skill(name: str) -> str:
    """Read the full SKILL.md body for a named skill."""
    skill_path = SKILLS_DIR / name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill '{name}' not found at {skill_path}")
    text = skill_path.read_text(encoding="utf-8")
    # Strip YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


def _load_skill_resource(name: str, resource_path: str) -> str:
    """Read a skill resource file."""
    full_path = SKILLS_DIR / name / resource_path
    if not full_path.exists():
        raise FileNotFoundError(f"Skill resource not found: {full_path}")
    return full_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation helpers (in-process – avoids subprocess crash on --reload)
# ---------------------------------------------------------------------------

def _validate_agent_in_process(agent_dir: str) -> ValidationResult:
    """Validate agent artefacts directly (no subprocess)."""
    import ast
    errors: list[str] = []
    agent_path = Path(agent_dir)

    yaml_path = agent_path / "agent.yaml"
    if not yaml_path.exists():
        errors.append("agent.yaml not found")
    else:
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                errors.append("agent.yaml must be a YAML mapping")
            else:
                for field in ("name", "description", "instructions", "model"):
                    if field not in data:
                        errors.append(f"Missing required field: {field}")
                instructions = data.get("instructions", "")
                if isinstance(instructions, str):
                    if len(instructions) < 10:
                        errors.append(f"Instructions too short ({len(instructions)} chars, min 10)")
                    if len(instructions) > 32_000:
                        errors.append(f"Instructions too long ({len(instructions)} chars, max 32000)")
        except yaml.YAMLError as exc:
            errors.append(f"YAML parse error: {exc}")

    py_path = agent_path / "agent.py"
    if not py_path.exists():
        errors.append("agent.py not found")
    else:
        try:
            ast.parse(py_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"Python syntax error in agent.py: {exc}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def _validate_workflow_in_process(workflow_dir: str) -> ValidationResult:
    """Validate workflow artefacts directly (no subprocess)."""
    import ast
    errors: list[str] = []
    wf_path = Path(workflow_dir)

    yaml_path = wf_path / "workflow.yaml"
    if not yaml_path.exists():
        errors.append("workflow.yaml not found")
    else:
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                errors.append("workflow.yaml must be a YAML mapping")
            else:
                for field in ("name", "description", "start", "executors", "edges"):
                    if field not in data:
                        errors.append(f"Missing required field: {field}")

                executors = data.get("executors", [])
                edges = data.get("edges", [])
                start = data.get("start", "")
                executor_names = {e["name"] for e in executors if isinstance(e, dict) and "name" in e}

                if start and start not in executor_names:
                    errors.append(f"Start executor '{start}' not found in executor list")

                for i, edge in enumerate(edges):
                    if not isinstance(edge, dict):
                        errors.append(f"Edge {i} is not a mapping")
                        continue
                    src = edge.get("source", "")
                    tgt = edge.get("target", "")
                    if src not in executor_names:
                        errors.append(f"Edge {i}: source '{src}' not in executors")
                    if tgt not in executor_names:
                        errors.append(f"Edge {i}: target '{tgt}' not in executors")

                # Check graph connectivity (BFS from start)
                if start and executor_names and not errors:
                    adj: dict[str, list[str]] = {n: [] for n in executor_names}
                    for edge in edges:
                        if isinstance(edge, dict):
                            adj.setdefault(edge.get("source", ""), []).append(edge.get("target", ""))
                    visited: set[str] = set()
                    queue = [start]
                    while queue:
                        node = queue.pop(0)
                        if node in visited:
                            continue
                        visited.add(node)
                        queue.extend(adj.get(node, []))
                    unreachable = executor_names - visited
                    if unreachable:
                        errors.append(f"Unreachable executors from '{start}': {sorted(unreachable)}")

        except yaml.YAMLError as exc:
            errors.append(f"YAML parse error: {exc}")

    py_path = wf_path / "workflow.py"
    if not py_path.exists():
        errors.append("workflow.py not found")
    else:
        try:
            ast.parse(py_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"Python syntax error in workflow.py: {exc}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


# ---------------------------------------------------------------------------
# Agent creation
# ---------------------------------------------------------------------------

_AGENT_SYSTEM_PROMPT = """\
You are an expert AI agent designer for Microsoft Agent Framework.
Your task is to create a complete agent definition from the user's request.

You MUST return a JSON object with exactly these fields:
{
  "name": "snake_case_name",
  "description": "Short description",
  "instructions": "Detailed system prompt for the agent (200-2000 chars)",
  "model": "gpt-4o",
  "tools": [],
  "temperature": 0.7
}

Guidelines:
- name: lowercase snake_case, max 64 chars, derived from description
- instructions: Be specific. Include the agent's expertise, tone, constraints,
  response format guidance, and safety guardrails.
- description: One concise sentence
- Always include out-of-scope handling in instructions

IMPORTANT – Language Rule:
- Detect the language of the user's request.
- "description" and "instructions" MUST be written in the SAME language as the
  user's request. If the user writes in Japanese, respond in Japanese. If in
  English, respond in English.
- "name" is always snake_case ASCII.
"""


async def create_agent_from_prompt(prompt: str) -> AgentCreateResponse:
    """Create an agent from a natural-language prompt."""
    # Load skill context for best practices
    skill_instructions = _load_skill("agent-creator")
    schema_ref = _load_skill_resource("agent-creator", "references/AGENT_SCHEMA.md")

    system = f"{_AGENT_SYSTEM_PROMPT}\n\n## Skill Instructions\n{skill_instructions}\n\n## Schema Reference\n{schema_ref}"

    data = await chat_completion_json(system, f"Create an agent for: {prompt}")

    definition = AgentDefinition(**data)
    return await _finalize_agent(definition)


async def create_agent_from_definition(definition: AgentDefinition) -> AgentCreateResponse:
    """Create an agent from an explicit definition."""
    return await _finalize_agent(definition)


async def edit_agent(agent_name: str, edit_prompt: str) -> AgentCreateResponse:
    """Edit an existing agent via natural language."""
    agent_dir = AGENTS_DIR / agent_name
    yaml_path = agent_dir / "agent.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Agent '{agent_name}' not found")

    current_yaml = yaml_path.read_text(encoding="utf-8")

    skill_instructions = _load_skill("agent-creator")
    schema_ref = _load_skill_resource("agent-creator", "references/AGENT_SCHEMA.md")

    system = f"""{_AGENT_SYSTEM_PROMPT}

## Current Agent Definition (to be edited)
```yaml
{current_yaml}
```

## Skill Instructions
{skill_instructions}

## Schema Reference
{schema_ref}

Apply the user's edit request to the current agent.
Return the COMPLETE updated agent definition as JSON (not just the changes).
"""

    data = await chat_completion_json(system, f"Edit this agent: {edit_prompt}")

    definition = AgentDefinition(**data)
    return await _finalize_agent(definition)


async def _finalize_agent(definition: AgentDefinition) -> AgentCreateResponse:
    """Generate code, validate, and persist an agent definition."""
    agent_dir = AGENTS_DIR / definition.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Write agent.yaml
    yaml_data = definition.model_dump()
    yaml_data["tools"] = [t.model_dump() for t in definition.tools] if definition.tools else []
    yaml_path = agent_dir / "agent.yaml"
    yaml_path.write_text(yaml.dump(yaml_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Generate agent.py
    code = _generate_agent_code(definition)
    py_path = agent_dir / "agent.py"
    py_path.write_text(code, encoding="utf-8")

    # Validate (in-process to avoid subprocess crash during --reload)
    validation = _validate_agent_in_process(str(agent_dir))

    return AgentCreateResponse(
        name=definition.name,
        definition=definition,
        code=code,
        validation=validation,
        message="Agent created successfully" if validation.valid else f"Agent created with validation errors: {validation.errors}",
    )


def _generate_agent_code(defn: AgentDefinition) -> str:
    """Generate executable Python code for an agent using Agent Framework's Agent class."""
    tools_import = ""
    tools_list = ""
    if defn.tools:
        tools_import = "\nfrom agent_framework.tools import Tool"
        tool_defs = []
        for t in defn.tools:
            desc = t.description.replace('"', '\\"') if t.description else t.name
            tool_defs.append(f'    Tool(name="{t.name}", description="{desc}"),')
        tools_list = "\nTOOLS = [\n" + "\n".join(tool_defs) + "\n]\n"

    instructions_escaped = defn.instructions.replace('"""', '\\"\\"\\"')

    lines = [
        f'"""Agent: {defn.name} – {defn.description}',
        '',
        'Auto-generated by the Agent Creator skill.',
        'Uses Microsoft Agent Framework\'s Agent class directly.',
        '"""',
        '',
        'import asyncio',
        'import os',
        '',
        'from azure.identity.aio import DefaultAzureCredential',
        'from agent_framework import Agent',
        'from agent_framework.azure import AzureOpenAIChatClient',
    ]
    if tools_import:
        lines.append(tools_import)
    lines += [
        '',
        f'ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "{AZURE_OPENAI_ENDPOINT}")',
        f'DEPLOYMENT = "{defn.model}"',
        '',
        'INSTRUCTIONS = """\\',
        instructions_escaped,
        '"""',
    ]
    if tools_list:
        lines.append(tools_list)
    lines += [
        '',
        '',
        'async def create_agent() -> Agent:',
        '    """Create and return the configured Agent instance."""',
        '    credential = DefaultAzureCredential()',
        '    client = AzureOpenAIChatClient(',
        '        credential=credential,',
        '        endpoint=ENDPOINT,',
        '        deployment=DEPLOYMENT,',
        '    )',
        '',
        '    agent = Agent(',
        f'        name="{defn.name}",',
        '        instructions=INSTRUCTIONS,',
        '        model_client=client,',
    ]
    if defn.tools:
        lines.append('        tools=TOOLS,')
    lines += [
        f'        model_settings={{"temperature": {defn.temperature}}},',
        '    )',
        '    return agent',
        '',
        '',
        'async def main():',
        '    """Run the agent with a sample message."""',
        '    agent = await create_agent()',
        '    response = await agent.run("Hello! What can you help me with?")',
        '    print(response.text)',
        '',
        '',
        'if __name__ == "__main__":',
        '    asyncio.run(main())',
        '',
    ]
    return '\n'.join(lines)


def _generate_agent_code_raw(name: str, description: str, instructions: str, model: str) -> str:
    """Generate agent Python code using Agent Framework's Agent class directly.
    
    Does not require an AgentDefinition object (useful for workflow executor
    names that may not pass Pydantic validation).
    """
    instructions_escaped = instructions.replace('"""', '\\"\\"\\"')
    lines = [
        f'"""Agent: {name} – {description}',
        '',
        'Auto-generated from workflow executor.',
        'Uses Microsoft Agent Framework\'s Agent class directly.',
        '"""',
        '',
        'import asyncio',
        'import os',
        '',
        'from azure.identity.aio import DefaultAzureCredential',
        'from agent_framework import Agent',
        'from agent_framework.azure import AzureOpenAIChatClient',
        '',
        f'ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "{AZURE_OPENAI_ENDPOINT}")',
        f'DEPLOYMENT = "{model}"',
        '',
        'INSTRUCTIONS = """\\',
        instructions_escaped,
        '"""',
        '',
        '',
        'async def create_agent() -> Agent:',
        '    """Create and return the configured Agent instance."""',
        '    credential = DefaultAzureCredential()',
        '    client = AzureOpenAIChatClient(',
        '        credential=credential,',
        '        endpoint=ENDPOINT,',
        '        deployment=DEPLOYMENT,',
        '    )',
        '',
        '    agent = Agent(',
        f'        name="{name}",',
        '        instructions=INSTRUCTIONS,',
        '        model_client=client,',
        '        model_settings={"temperature": 0.7},',
        '    )',
        '    return agent',
        '',
        '',
        'async def main():',
        '    """Run the agent with a sample message."""',
        '    agent = await create_agent()',
        '    response = await agent.run("Hello! What can you help me with?")',
        '    print(response.text)',
        '',
        '',
        'if __name__ == "__main__":',
        '    asyncio.run(main())',
        '',
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Workflow creation
# ---------------------------------------------------------------------------

_WORKFLOW_SYSTEM_PROMPT = """\
You are an expert workflow designer for Microsoft Agent Framework.
Your task is to create a complete workflow definition from the user's request.

You MUST return a JSON object with exactly these fields:
{
  "name": "snake_case_name",
  "description": "What the workflow does",
  "start": "name_of_starting_executor",
  "executors": [
    {
      "name": "executor_name",
      "type": "agent|function",
      "instructions": "What this executor does",
      "model": "gpt-4o"
    }
  ],
  "edges": [
    {
      "source": "source_executor_name",
      "target": "target_executor_name",
      "condition": "optional condition description or null",
      "fan_in": false
    }
  ]
}

Guidelines:
- Identify each processing step as an executor
- If a step needs LLM reasoning → type "agent"
- If a step is pure logic/transformation → type "function"
- Map data flow with edges:
  - "then/next" → direct edge
  - "if ... else" → conditional edges
  - "in parallel" → fan-out (multiple edges from same source)
  - "combine/merge" → fan-in edges
- All executor names must be snake_case
- Every executor must be reachable from start

IMPORTANT – Language Rule:
- Detect the language of the user's request.
- "description" and all executor "instructions" MUST be written in the SAME
  language as the user's request. If the user writes in Japanese, respond in
  Japanese. If in English, respond in English.
- "name" fields are always snake_case ASCII.
"""


async def create_workflow_from_prompt(prompt: str) -> WorkflowCreateResponse:
    """Create a workflow from a natural-language prompt."""
    skill_instructions = _load_skill("workflow-creator")
    patterns_ref = _load_skill_resource("workflow-creator", "references/WORKFLOW_PATTERNS.md")

    system = f"{_WORKFLOW_SYSTEM_PROMPT}\n\n## Skill Instructions\n{skill_instructions}\n\n## Workflow Patterns\n{patterns_ref}"

    data = await chat_completion_json(system, f"Create a workflow for: {prompt}")

    # Parse executors and edges
    executors = [ExecutorDef(**e) for e in data.get("executors", [])]
    edges = [EdgeDef(**e) for e in data.get("edges", [])]

    definition = WorkflowDefinition(
        name=data["name"],
        description=data["description"],
        start=data["start"],
        executors=executors,
        edges=edges,
    )
    return await _finalize_workflow(definition)


async def create_workflow_from_definition(definition: WorkflowDefinition) -> WorkflowCreateResponse:
    """Create a workflow from an explicit definition."""
    return await _finalize_workflow(definition)


async def request_workflow_edit(current_yaml: str, edit_prompt: str, guidance: str = "") -> dict:
    """Ask the LLM for the complete, edited workflow definition; nothing is saved.

    `guidance` adds rules for the workflow being edited (e.g. built-in steps that
    must be kept).
    """
    skill_instructions = _load_skill("workflow-creator")

    system = f"""{_WORKFLOW_SYSTEM_PROMPT}

## Current Workflow Definition (to be edited)
```yaml
{current_yaml}
```

## Skill Instructions
{skill_instructions}

{guidance}

Apply the user's edit request to the current workflow.
Return the COMPLETE updated workflow definition as JSON (not just the changes).
"""

    return await chat_completion_json(system, f"Edit this workflow: {edit_prompt}")


async def edit_workflow(workflow_name: str, edit_prompt: str) -> WorkflowCreateResponse:
    """Edit an existing workflow via natural language."""
    wf_dir = WORKFLOWS_DIR / workflow_name
    yaml_path = wf_dir / "workflow.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Workflow '{workflow_name}' not found")

    current_yaml = yaml_path.read_text(encoding="utf-8")

    data = await request_workflow_edit(current_yaml, edit_prompt)

    executors = [ExecutorDef(**e) for e in data.get("executors", [])]
    edges = [EdgeDef(**e) for e in data.get("edges", [])]

    definition = WorkflowDefinition(
        name=data["name"],
        description=data["description"],
        start=data["start"],
        executors=executors,
        edges=edges,
    )
    return await _finalize_workflow(definition)


class ReservedWorkflowError(ValueError):
    """The request would create or change the Weekend Saver workflow from the open API."""


class UnsafeNameError(ValueError):
    """An executor name that cannot be used as a folder and Python identifier."""


_EXECUTOR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _refuse_unsafe_names(definition: WorkflowDefinition) -> None:
    # Each agent executor gets a folder named after it, and the generated code uses the
    # name as a variable, so a name with a path separator must not get that far.
    for executor in definition.executors:
        if not _EXECUTOR_NAME.match(executor.name):
            raise UnsafeNameError(
                f"Executor name '{executor.name}' is not usable; names may contain "
                "letters, digits and underscores only."
            )


def _refuse_reserved(definition: WorkflowDefinition) -> None:
    # That workflow really changes Azure resources, so it is only saved through the
    # protected Weekend Saver routes, which also validate it.
    uses_builtin = any(ex.type == BUILTIN_EXECUTOR_TYPE for ex in definition.executors)
    if definition.name == RESERVED_WORKFLOW_NAME or uses_builtin:
        raise ReservedWorkflowError(
            f"The '{RESERVED_WORKFLOW_NAME}' workflow and its built-in steps are managed "
            "on the Weekend Saver page."
        )


async def _finalize_workflow(definition: WorkflowDefinition) -> WorkflowCreateResponse:
    """Generate code, validate, and persist a workflow definition."""
    _refuse_reserved(definition)
    _refuse_unsafe_names(definition)
    wf_dir = WORKFLOWS_DIR / definition.name
    wf_dir.mkdir(parents=True, exist_ok=True)

    # Write workflow.yaml
    yaml_data = definition.model_dump()
    yaml_path = wf_dir / "workflow.yaml"
    yaml_path.write_text(yaml.dump(yaml_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Generate workflow.py
    code = _generate_workflow_code(definition)
    py_path = wf_dir / "workflow.py"
    py_path.write_text(code, encoding="utf-8")

    # Auto-register agent-type executors as standalone agents
    _register_workflow_agents(definition)

    # Validate (in-process to avoid subprocess crash during --reload)
    validation = _validate_workflow_in_process(str(wf_dir))

    return WorkflowCreateResponse(
        name=definition.name,
        definition=definition,
        code=code,
        validation=validation,
        message="Workflow created successfully" if validation.valid else f"Workflow created with validation errors: {validation.errors}",
    )


def _register_workflow_agents(definition: WorkflowDefinition) -> None:
    """Auto-register each agent-type executor as a standalone agent."""
    for executor in definition.executors:
        if executor.type != "agent":
            continue

        try:
            agent_dir = AGENTS_DIR / executor.name
            agent_dir.mkdir(parents=True, exist_ok=True)

            # Build agent definition
            description = (executor.instructions[:120] if executor.instructions
                           else f"Agent node from workflow '{definition.name}'")
            instructions = (executor.instructions
                            or f"You are {executor.name}. Process the input and produce a result.")

            agent_yaml = {
                "name": executor.name,
                "description": description,
                "instructions": instructions,
                "model": executor.model or "gpt-4o",
                "tools": [],
                "temperature": 0.7,
                "source_workflow": definition.name,
            }
            yaml_path = agent_dir / "agent.yaml"
            yaml_path.write_text(
                yaml.dump(agent_yaml, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            # Generate agent.py using safe construction (skip Pydantic validation
            # which may reject names that are valid workflow executor names)
            instructions_escaped = instructions.replace('"""', '\\"\\"\\"')
            code = _generate_agent_code_raw(
                name=executor.name,
                description=description[:256],
                instructions=instructions,
                model=executor.model or "gpt-4o",
            )
            py_path = agent_dir / "agent.py"
            py_path.write_text(code, encoding="utf-8")

            logger.info("Auto-registered agent '%s' from workflow '%s'", executor.name, definition.name)
        except Exception:
            logger.exception("Failed to register agent '%s' from workflow '%s'", executor.name, definition.name)


def _generate_workflow_code(defn: WorkflowDefinition) -> str:
    """Generate executable Python code for a workflow using Agent Framework.

    Architecture:
    - Agent-type executors are imported from generated/agents/{name}/agent.py
      via their `create_agent()` function, then passed directly to
      WorkflowBuilder (which auto-wraps them in AgentExecutor).
    - Function-type executors remain as inline Executor subclasses.
    - Conditional edges use `add_switch_case_edge_group` with Case/Default.
    - Edits to agents in the Agent tab are automatically reflected in the
      workflow because the agent modules are imported, not duplicated.
    """

    agent_executors = [ex for ex in defn.executors if ex.type == "agent"]
    func_executors = [ex for ex in defn.executors if ex.type != "agent"]

    # --- Imports ----------------------------------------------------------
    imports: list[str] = [
        f'"""Workflow: {defn.name} – {defn.description}',
        '',
        'Auto-generated by the Workflow Creator skill.',
        'Uses Microsoft Agent Framework with AgentExecutor wrapping Agent instances.',
        '',
        'Agent-type nodes are imported from the agents tab (generated/agents/).',
        'Editing an agent in the Agent tab will be automatically reflected here.',
        '"""',
        '',
        'import asyncio',
        'import os',
        'import sys',
        '',
        '# Add the generated agents directory to the import path',
        '# so we can import each agent module by folder name.',
        '_AGENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "agents")',
        'if _AGENTS_DIR not in sys.path:',
        '    sys.path.insert(0, _AGENTS_DIR)',
        '',
    ]

    # Conditional imports based on what's needed
    framework_items: list[str] = ['WorkflowBuilder']
    if func_executors:
        framework_items.extend(['Executor', 'WorkflowContext', 'handler'])

    # Check if we need Case/Default for switch-case edge groups
    has_conditions = any(e.condition for e in defn.edges)
    if has_conditions:
        framework_items.extend(['Case', 'Default'])

    imports.append(f'from agent_framework import {", ".join(framework_items)}')
    imports.append('')

    # --- Agent imports (from agents tab) ----------------------------------
    agent_import_lines: list[str] = []
    agent_import_lines.append('')
    agent_import_lines.append('# -- Import agents from the Agent tab ------------------------------------')
    agent_import_lines.append('# These are auto-registered when the workflow is created.')
    agent_import_lines.append('# Edit them in the Agent tab and changes are reflected here automatically.')
    agent_import_lines.append('')
    for ex in agent_executors:
        # Import create_agent as create_{name}
        alias = f'create_{ex.name}'
        agent_import_lines.append(
            f'from {ex.name}.agent import create_agent as {alias}'
            f'  # noqa: E402'
        )
    agent_import_lines.append('')

    # --- Function executor classes ----------------------------------------
    func_class_lines: list[str] = []
    func_instance_lines: list[str] = []
    if func_executors:
        func_class_lines.append('')
        func_class_lines.append(
            '# -- Function Executors '
            '-------------------------------------------------'
        )
        func_class_lines.append('')
        for ex in func_executors:
            class_name = "".join(w.capitalize() for w in ex.name.split("_"))
            instr_escaped = ex.instructions.replace('"""', '\\"\\"\\"')
            func_class_lines.extend([
                f'class {class_name}(Executor):',
                f'    """Function Executor: {ex.name} – {ex.instructions[:80]}"""',
                '',
                '    @handler',
                '    async def handle(self, message, ctx: WorkflowContext) -> None:',
                f'        # {instr_escaped[:200]}',
                f'        result = f"[{ex.name}] processed: {{message}}"',
                '        await ctx.send_message(result)',
                '',
                '',
            ])
            func_instance_lines.append(f'{ex.name} = {class_name}()')

    # --- Build workflow function ------------------------------------------
    build_lines: list[str] = [
        '',
        '# -- Build Workflow '
        '-----------------------------------------------------',
        '',
        'async def build_workflow():',
        '    """Create Agent instances and assemble the workflow graph.',
        '',
        '    Agent instances are created by calling create_agent() from each',
        '    agent module. WorkflowBuilder auto-wraps them in AgentExecutor.',
        '    """',
    ]

    # Create agent instances
    if agent_executors:
        build_lines.append('    # Create agents (imported from agents tab)')
        for ex in agent_executors:
            build_lines.append(f'    {ex.name} = await create_{ex.name}()')
        build_lines.append('')

    # Build workflow
    build_lines.append(f'    builder = WorkflowBuilder(start_executor={defn.start})')
    build_lines.append('')

    # --- Edges ------------------------------------------------------------
    # Group edges by source to detect switch-case patterns
    edges_by_source: dict[str, list] = {}
    for edge in defn.edges:
        edges_by_source.setdefault(edge.source, []).append(edge)

    fan_in_targets: dict[str, list[str]] = {}

    for source_name, source_edges in edges_by_source.items():
        # Separate fan-in from regular edges
        regular = [e for e in source_edges if not e.fan_in]
        fan_in = [e for e in source_edges if e.fan_in]

        for e in fan_in:
            fan_in_targets.setdefault(e.target, []).append(e.source)

        conditional = [e for e in regular if e.condition]
        unconditional = [e for e in regular if not e.condition]

        if conditional:
            # Use switch-case pattern: Case for each condition, Default for
            # the last one if there's no explicit default
            build_lines.append(f'    # Conditional routing from {source_name}')
            build_lines.append(f'    builder.add_switch_case_edge_group(')
            build_lines.append(f'        {source_name},')
            build_lines.append(f'        [')
            for i, ce in enumerate(conditional):
                cond_str = ce.condition.replace('"', '\\"')
                # For the last conditional edge, make it Default if no
                # unconditional edges exist
                if i == len(conditional) - 1 and not unconditional:
                    build_lines.append(
                        f'            Default(target={ce.target}),'
                        f'  # fallback: {cond_str}'
                    )
                else:
                    build_lines.append(
                        f'            Case('
                        f'condition=lambda data: '
                        f'"{ce.condition.lower()}" in str(data).lower(), '
                        f'target={ce.target}),  # {cond_str}'
                    )
            if unconditional:
                # Add the first unconditional edge as Default
                build_lines.append(
                    f'            Default(target={unconditional[0].target}),'
                )
            build_lines.append(f'        ],')
            build_lines.append(f'    )')
            # Add remaining unconditional edges as regular edges
            for ue in unconditional[1:]:
                build_lines.append(
                    f'    builder.add_edge({source_name}, {ue.target})'
                )
        else:
            for ue in unconditional:
                build_lines.append(
                    f'    builder.add_edge({source_name}, {ue.target})'
                )

    # Fan-in edges
    for target, sources in fan_in_targets.items():
        sources_str = ", ".join(sources)
        build_lines.append(
            f'    builder.add_fan_in_edges([{sources_str}], {target})'
        )

    build_lines.extend([
        '',
        '    return builder.build()',
    ])

    # --- Main -------------------------------------------------------------
    main_lines = [
        '',
        '',
        'async def main():',
        '    workflow = await build_workflow()',
        '    events = await workflow.run("Hello, start the workflow!")',
        '    print(f"Workflow output: {events.get_outputs()}")',
        '',
        '',
        'if __name__ == "__main__":',
        '    asyncio.run(main())',
        '',
    ]

    # --- Assemble ---------------------------------------------------------
    all_lines = imports + agent_import_lines
    if func_class_lines:
        all_lines += func_class_lines
    if func_instance_lines:
        all_lines += [''] + func_instance_lines
    all_lines += build_lines + main_lines

    return '\n'.join(all_lines)
