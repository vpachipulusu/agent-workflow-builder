"""FastAPI application – API endpoints for Agent & Workflow creation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from config import (
    AGENTS_DIR,
    AZURE_OPENAI_ENDPOINT,
    FRONTEND_ORIGINS,
    WEEKEND_SAVER_DEMO,
    WORKFLOWS_DIR,
)
from llm_client import chat_completion
from models import (
    AgentCreateRequest,
    AgentCreateResponse,
    AgentDefinition,
    AgentEditRequest,
    EdgeDef,
    ExecutorDef,
    ValidationResult,
    WorkflowCreateRequest,
    WorkflowCreateResponse,
    WorkflowDefinition,
    WorkflowEditRequest,
)
from orchestrator import (
    create_agent_from_definition,
    create_agent_from_prompt,
    create_workflow_from_definition,
    create_workflow_from_prompt,
    RESERVED_WORKFLOW_NAME,
    ReservedWorkflowError,
    UnsafeNameError,
    edit_agent,
    edit_workflow,
)
from weekend_saver_host import MOUNT_PATH, OpenApiCors, build_hosted

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The Weekend Saver workflow really changes Azure resources, so it lives in its own
# protected app; everything under /api below stays as open as before.
weekend_saver = build_hosted(
    workflows_dir=WORKFLOWS_DIR,
    origins=FRONTEND_ORIGINS,
    model_configured=bool(AZURE_OPENAI_ENDPOINT),
    demo=WEEKEND_SAVER_DEMO,
)

_MANAGED_ELSEWHERE = (
    "The Weekend Saver workflow really changes Azure resources; "
    "run and edit it with the Weekend Saver controls."
)


def _entry_dir(base: Path, name: str) -> Path:
    """The folder of one agent or workflow; 404 unless it sits directly inside `base`.

    The name comes from the URL, where an encoded path separator would otherwise let a
    request read, write or delete folders outside the generated output.
    """
    candidate = (base / name).resolve()
    if candidate.parent != base.resolve():
        raise HTTPException(404, f"'{name}' not found")
    return candidate


def _is_weekend_saver(name: str) -> bool:
    # Compared as resolved paths: on Windows "Weekend_Saver" and "weekend_saver." name
    # the same folder as "weekend_saver"
    reserved = (WORKFLOWS_DIR / RESERVED_WORKFLOW_NAME).resolve()
    candidate = (WORKFLOWS_DIR / name).resolve()
    return os.path.normcase(candidate) == os.path.normcase(reserved)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with weekend_saver.running():
        yield


app = FastAPI(
    title="Agent & Workflow Builder",
    description="Natural-language powered Agent & Workflow creation using Microsoft Agent Framework Skills",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount(MOUNT_PATH, weekend_saver.app)

# CORS for frontend. The Weekend Saver app is left out: its page calls it same-origin,
# and no other local site should be able to read its answers.
app.add_middleware(
    OpenApiCors,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Health
# ===========================================================================
@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ===========================================================================
# Agent endpoints
# ===========================================================================
@app.post("/api/agents", response_model=AgentCreateResponse)
async def create_agent(req: AgentCreateRequest):
    """Create a new agent from natural language or explicit definition."""
    try:
        if req.prompt:
            return await create_agent_from_prompt(req.prompt)
        elif req.definition:
            return await create_agent_from_definition(req.definition)
        else:
            raise HTTPException(400, "Provide either 'prompt' or 'definition'")
    except Exception as exc:
        logger.exception("Agent creation failed")
        raise HTTPException(500, str(exc))


@app.get("/api/agents")
async def list_agents():
    """List all created agents."""
    agents = []
    if AGENTS_DIR.exists():
        for agent_dir in sorted(AGENTS_DIR.iterdir()):
            yaml_path = agent_dir / "agent.yaml"
            if yaml_path.exists():
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                agents.append({
                    "name": data.get("name", agent_dir.name),
                    "description": data.get("description", ""),
                    "model": data.get("model", ""),
                    "source_workflow": data.get("source_workflow", None),
                })
    return {"agents": agents}


@app.get("/api/agents/{name}")
async def get_agent(name: str):
    """Get a specific agent's full definition and code."""
    agent_dir = _entry_dir(AGENTS_DIR, name)
    yaml_path = agent_dir / "agent.yaml"
    py_path = agent_dir / "agent.py"

    if not yaml_path.exists():
        raise HTTPException(404, f"Agent '{name}' not found")

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    code = py_path.read_text(encoding="utf-8") if py_path.exists() else ""

    return {
        "name": name,
        "definition": data,
        "code": code,
    }


@app.delete("/api/agents/{name}")
async def delete_agent(name: str):
    """Delete an agent."""
    agent_dir = _entry_dir(AGENTS_DIR, name)
    if not agent_dir.exists():
        raise HTTPException(404, f"Agent '{name}' not found")
    import shutil
    shutil.rmtree(agent_dir)
    return {"message": f"Agent '{name}' deleted"}


@app.put("/api/agents/{name}/edit", response_model=AgentCreateResponse)
async def edit_agent_endpoint(name: str, req: AgentEditRequest):
    """Edit an existing agent via natural language."""
    _entry_dir(AGENTS_DIR, name)
    try:
        return await edit_agent(name, req.prompt)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.exception("Agent edit failed")
        raise HTTPException(500, str(exc))


# ===========================================================================
# Workflow endpoints
# ===========================================================================
@app.post("/api/workflows", response_model=WorkflowCreateResponse)
async def create_workflow(req: WorkflowCreateRequest):
    """Create a new workflow from natural language or explicit definition."""
    try:
        if req.prompt:
            return await create_workflow_from_prompt(req.prompt)
        elif req.definition:
            return await create_workflow_from_definition(req.definition)
        else:
            raise HTTPException(400, "Provide either 'prompt' or 'definition'")
    except ReservedWorkflowError as exc:
        raise HTTPException(403, str(exc))
    except UnsafeNameError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception("Workflow creation failed")
        raise HTTPException(500, str(exc))


@app.put("/api/workflows/{name}/edit", response_model=WorkflowCreateResponse)
async def edit_workflow_endpoint(name: str, req: WorkflowEditRequest):
    """Edit an existing workflow via natural language."""
    if _is_weekend_saver(name):
        raise HTTPException(403, _MANAGED_ELSEWHERE)
    _entry_dir(WORKFLOWS_DIR, name)
    try:
        return await edit_workflow(name, req.prompt)
    except ReservedWorkflowError as exc:
        raise HTTPException(403, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.exception("Workflow edit failed")
        raise HTTPException(500, str(exc))


@app.get("/api/workflows")
async def list_workflows():
    """List all created workflows."""
    workflows = []
    if WORKFLOWS_DIR.exists():
        for wf_dir in sorted(WORKFLOWS_DIR.iterdir()):
            yaml_path = wf_dir / "workflow.yaml"
            if yaml_path.exists():
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                workflows.append({
                    "name": data.get("name", wf_dir.name),
                    "description": data.get("description", ""),
                    "executors_count": len(data.get("executors", [])),
                    "edges_count": len(data.get("edges", [])),
                })
    return {"workflows": workflows}


@app.get("/api/workflows/{name}")
async def get_workflow(name: str):
    """Get a specific workflow's full definition and code."""
    wf_dir = _entry_dir(WORKFLOWS_DIR, name)
    yaml_path = wf_dir / "workflow.yaml"
    py_path = wf_dir / "workflow.py"

    if not yaml_path.exists():
        raise HTTPException(404, f"Workflow '{name}' not found")

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    code = py_path.read_text(encoding="utf-8") if py_path.exists() else ""

    return {
        "name": name,
        "definition": data,
        "code": code,
    }


@app.delete("/api/workflows/{name}")
async def delete_workflow(name: str):
    """Delete a workflow."""
    if _is_weekend_saver(name):
        raise HTTPException(403, _MANAGED_ELSEWHERE)
    wf_dir = _entry_dir(WORKFLOWS_DIR, name)
    if not wf_dir.exists():
        raise HTTPException(404, f"Workflow '{name}' not found")
    import shutil
    shutil.rmtree(wf_dir)
    return {"message": f"Workflow '{name}' deleted"}


# ===========================================================================
# Playground – Agent
# ===========================================================================
@app.post("/api/agents/{name}/run")
async def run_agent(name: str, body: dict):
    """Run a created agent in playground mode.

    Uses the agent's instructions as a system prompt and streams the LLM response
    via Server-Sent Events.
    """
    agent_dir = _entry_dir(AGENTS_DIR, name)
    yaml_path = agent_dir / "agent.yaml"
    if not yaml_path.exists():
        raise HTTPException(404, f"Agent '{name}' not found")

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    instructions = data.get("instructions", "You are a helpful assistant.")
    user_message = body.get("message", "")
    history: list[dict] = body.get("history", [])

    if not user_message:
        raise HTTPException(400, "message is required")

    async def generate() -> AsyncGenerator[str, None]:
        """Stream agent response as SSE."""
        try:
            # Build conversation messages
            messages_text = ""
            if history:
                for msg in history[-10:]:  # last 10 turns
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    messages_text += f"\n[{role}]: {content}"
                messages_text += f"\n[user]: {user_message}"
            else:
                messages_text = user_message

            response = await chat_completion(
                instructions,
                messages_text,
                temperature=data.get("temperature", 0.7),
            )

            # Stream word-by-word for UX
            words = response.split()
            buffer = ""
            for i, word in enumerate(words):
                buffer += word + " "
                if i % 3 == 2 or i == len(words) - 1:
                    yield f"data: {json.dumps({'type': 'token', 'content': buffer})}\n\n"
                    buffer = ""
                    await asyncio.sleep(0.02)

            yield f"data: {json.dumps({'type': 'done', 'content': response})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ===========================================================================
# Condition evaluation helper
# ===========================================================================
async def _evaluate_conditions(
    node_output: str, conditional_edges: list[dict]
) -> set[str]:
    """Use LLM to decide which conditional edges match the node output.

    Returns a set of target executor names whose conditions are satisfied.
    """
    conditions_desc = "\n".join(
        f"- Edge to '{e['target']}': condition = \"{e['condition']}\""
        for e in conditional_edges
    )
    system = (
        "You are a workflow condition evaluator. Given the output of a node "
        "and a list of conditional edges, determine which edge(s) should be "
        "taken.\n\n"
        "Return a JSON object: {\"matched_targets\": [\"target_name\", ...]}\n"
        "Only include targets whose conditions are clearly satisfied by the output.\n"
        "If none match, return {\"matched_targets\": []}.\n"
        "Always return exactly ONE best match unless the output explicitly "
        "satisfies multiple conditions."
    )
    user_msg = (
        f"Node output:\n{node_output[:1000]}\n\n"
        f"Conditional edges:\n{conditions_desc}"
    )
    try:
        from llm_client import chat_completion_json
        result = await chat_completion_json(system, user_msg)
        targets = set(result.get("matched_targets", []))
        logger.info("Condition evaluation: matched %s", targets)
        return targets
    except Exception as exc:
        logger.exception("Condition evaluation failed, taking first edge")
        # Fallback: take first conditional edge
        return {conditional_edges[0]["target"]} if conditional_edges else set()


# ===========================================================================
# Playground – Workflow
# ===========================================================================
@app.post("/api/workflows/{name}/run")
async def run_workflow(name: str, body: dict):
    """Simulate running a workflow and stream step-by-step execution as SSE.

    Each SSE event describes which executor is currently active and its output,
    allowing the frontend to animate edge-by-edge data flow.
    """
    if _is_weekend_saver(name):
        # A simulation of this one would look like a real run that did nothing
        raise HTTPException(403, _MANAGED_ELSEWHERE)
    wf_dir = _entry_dir(WORKFLOWS_DIR, name)
    yaml_path = wf_dir / "workflow.yaml"
    if not yaml_path.exists():
        raise HTTPException(404, f"Workflow '{name}' not found")

    wf_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    user_input = body.get("message", "Hello")
    executors = wf_data.get("executors", [])
    edges = wf_data.get("edges", [])
    start = wf_data.get("start", "")

    # Build adjacency for traversal
    adj: dict[str, list[dict]] = {}
    for ex in executors:
        adj[ex["name"]] = []
    for edge in edges:
        adj.setdefault(edge["source"], []).append(edge)

    # Pre-compute executor map
    exec_map = {ex["name"]: ex for ex in executors}

    async def simulate() -> AsyncGenerator[str, None]:
        """BFS-style execution through the workflow graph."""
        visited: set[str] = set()
        queue: list[tuple[str, str]] = [(start, user_input)]  # (executor_name, input_data)
        step_id = 0

        # Signal start
        yield f"data: {json.dumps({'type': 'start', 'workflow': name, 'input': user_input})}\n\n"
        await asyncio.sleep(0.3)

        while queue:
            current_name, current_input = queue.pop(0)
            if current_name in visited:
                continue
            visited.add(current_name)

            executor = exec_map.get(current_name)
            if not executor:
                continue

            step_id += 1

            # Signal: entering node
            yield f"data: {json.dumps({'type': 'node_enter', 'step': step_id, 'node': current_name, 'input': current_input[:2000]})}\n\n"
            await asyncio.sleep(0.5)

            # Actually process: use LLM for agent executors, simple transform for function executors
            if executor.get("type") == "agent":
                try:
                    output = await chat_completion(
                        executor.get("instructions", "Process the input."),
                        f"Input data: {current_input}",
                        temperature=0.5,
                    )
                except Exception as exc:
                    output = f"[Error: {exc}]"
            else:
                # Function executor – simulate transformation
                output = f"[{current_name}] processed: {current_input[:100]}"
                await asyncio.sleep(0.3)

            # Signal: node complete
            yield f"data: {json.dumps({'type': 'node_complete', 'step': step_id, 'node': current_name, 'output': output[:5000]})}\n\n"
            await asyncio.sleep(0.3)

            # Traverse outgoing edges — evaluate conditions
            outgoing = adj.get(current_name, [])
            conditional_edges = [e for e in outgoing if e.get("condition")]
            unconditional_edges = [e for e in outgoing if not e.get("condition")]

            if conditional_edges:
                # Use LLM to evaluate which condition(s) match the output
                matched_targets = await _evaluate_conditions(
                    output, conditional_edges
                )
                for edge in conditional_edges:
                    target = edge["target"]
                    if target in matched_targets and target not in visited:
                        yield f"data: {json.dumps({'type': 'edge_active', 'source': current_name, 'target': target, 'condition': edge.get('condition', ''), 'matched': True, 'data_preview': output[:100]})}\n\n"
                        await asyncio.sleep(0.5)
                        queue.append((target, output))
                    elif target not in visited:
                        yield f"data: {json.dumps({'type': 'edge_skipped', 'source': current_name, 'target': target, 'condition': edge.get('condition', ''), 'matched': False})}\n\n"

                # If no conditional edge matched, fall through to unconditional
                if not matched_targets:
                    for edge in unconditional_edges:
                        target = edge["target"]
                        if target not in visited:
                            yield f"data: {json.dumps({'type': 'edge_active', 'source': current_name, 'target': target, 'data_preview': output[:100]})}\n\n"
                            await asyncio.sleep(0.5)
                            queue.append((target, output))
            else:
                # No conditional edges — follow all (fan-out)
                for edge in outgoing:
                    target = edge["target"]
                    if target not in visited:
                        yield f"data: {json.dumps({'type': 'edge_active', 'source': current_name, 'target': target, 'data_preview': output[:100]})}\n\n"
                        await asyncio.sleep(0.5)
                        queue.append((target, output))

        # Signal: workflow complete
        yield f"data: {json.dumps({'type': 'done', 'steps': step_id})}\n\n"

    return StreamingResponse(simulate(), media_type="text/event-stream")
