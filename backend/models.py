"""Pydantic models for API request / response schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent models
# ---------------------------------------------------------------------------
class AgentTool(BaseModel):
    name: str
    description: str = ""


class AgentDefinition(BaseModel):
    """Declarative agent definition (mirrors agent.yaml)."""

    name: str = Field(..., max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(..., max_length=256)
    instructions: str = Field(..., min_length=10, max_length=32_000)
    model: str = "gpt-4o"
    tools: list[AgentTool] = []
    temperature: float = 0.7


class AgentCreateRequest(BaseModel):
    """Request to create an agent – either via natural language or explicit fields."""

    # If provided, the orchestrator will generate the definition from NL
    prompt: Optional[str] = None
    # If provided, these are used directly (manual mode)
    definition: Optional[AgentDefinition] = None


class AgentCreateResponse(BaseModel):
    name: str
    definition: AgentDefinition
    code: str  # generated Python source
    validation: ValidationResult
    message: str


class AgentEditRequest(BaseModel):
    """Request to edit an existing agent via natural language."""

    agent_name: str
    prompt: str  # natural language edit instruction


# ---------------------------------------------------------------------------
# Workflow models
# ---------------------------------------------------------------------------
class ExecutorDef(BaseModel):
    name: str
    type: str = "agent"  # "agent" | "function"
    instructions: str = ""
    model: str = "gpt-4o"


class EdgeDef(BaseModel):
    source: str
    target: str
    condition: Optional[str] = None
    fan_in: bool = False


class WorkflowDefinition(BaseModel):
    """Declarative workflow definition (mirrors workflow.yaml)."""

    name: str = Field(..., max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(..., max_length=512)
    start: str
    executors: list[ExecutorDef]
    edges: list[EdgeDef]


class WorkflowCreateRequest(BaseModel):
    """Request to create a workflow – NL prompt or explicit definition."""

    prompt: Optional[str] = None
    definition: Optional[WorkflowDefinition] = None


class WorkflowEditRequest(BaseModel):
    """Request to edit an existing workflow via natural language."""

    workflow_name: str
    prompt: str  # natural language edit instruction


class WorkflowCreateResponse(BaseModel):
    name: str
    definition: WorkflowDefinition
    code: str
    validation: ValidationResult
    message: str


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []


# Rebuild forward-ref models
AgentCreateResponse.model_rebuild()
WorkflowCreateResponse.model_rebuild()
