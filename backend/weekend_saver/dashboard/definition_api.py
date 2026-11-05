"""API routes for viewing and changing the customizable workflow definition.

They are added to the protected dashboard app, so changing what the scheduled runs do
needs the same session as starting a run.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from weekend_saver.custom.catalog import CORE_BY_ID, catalog_to_json
from weekend_saver.custom.compiler import DefinitionError
from weekend_saver.custom.definition import (
    BUILTIN,
    WorkflowDef,
    default_definition,
    definition_to_dict,
    parse_definition,
)
from weekend_saver.custom.store import DefinitionStore
from weekend_saver.custom.validation import validate
from weekend_saver.errors import ConfigError
from weekend_saver.executors import describe_error

logger = logging.getLogger(__name__)

# Given the current definition and what the user asked for, propose a whole new one
DefinitionEditor = Callable[[dict[str, Any], str], Awaitable[dict[str, Any]]]

_NO_EDITOR = (
    "Chat edits need a language model, and none is configured for this server. "
    "You can still edit the definition directly."
)
# A model that does not answer must not leave the page waiting on its own retries
EDIT_TIMEOUT_SECONDS = 120.0


class DefinitionBody(BaseModel):
    definition: dict[str, Any]


class EditBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


def add_definition_routes(
    app: FastAPI, definitions: DefinitionStore, editor: DefinitionEditor | None
) -> None:
    @app.get("/api/definition")
    def get_definition() -> JSONResponse:
        return _ok(_view(definitions))

    @app.put("/api/definition")
    def save_definition(body: DefinitionBody) -> JSONResponse:
        return _save(definitions, body.definition)

    @app.post("/api/definition/edit")
    async def edit_definition(body: EditBody) -> JSONResponse:
        if editor is None:
            return _fail(400, _NO_EDITOR)
        current = definition_to_dict(_load_or_default(definitions))
        try:
            proposal = await asyncio.wait_for(
                editor(current, body.prompt), timeout=EDIT_TIMEOUT_SECONDS
            )
        except Exception as exc:
            logger.exception("The model did not produce a workflow edit")
            return _fail(
                502,
                f"The model did not return a usable workflow ({describe_error(exc)}). "
                "Nothing was changed; try again or reword the request.",
            )
        return _save(definitions, restore_core_fields(proposal, current))

    @app.post("/api/definition/reset")
    def reset_definition() -> JSONResponse:
        definitions.reset()
        return _ok(_view(definitions))


def restore_core_fields(proposal: Any, current: dict[str, Any]) -> Any:
    """Put back what a model tends to drop from the built-in steps.

    A model asked to return the whole definition often leaves out `ref` and `config`,
    which it has no reason to change. The step still has to pass validation afterwards.
    """
    if not isinstance(proposal, dict) or not isinstance(proposal.get("executors"), list):
        return proposal
    current_config = {item["name"]: item.get("config", {}) for item in current["executors"]}
    executors = [
        {
            **item,
            "type": BUILTIN,
            "ref": CORE_BY_ID[item["name"]].ref,
            "config": item["config"]
            if isinstance(item.get("config"), dict)
            else current_config.get(item["name"], {}),
        }
        if isinstance(item, dict) and _is_core_name(item.get("name"))
        else item
        for item in proposal["executors"]
    ]
    return {**proposal, "executors": executors}


def _is_core_name(name: Any) -> bool:
    # A model can return anything here, including values that cannot be looked up
    return isinstance(name, str) and name in CORE_BY_ID


def _save(definitions: DefinitionStore, data: Any) -> JSONResponse:
    try:
        definitions.save(parse_definition(data))
    except DefinitionError as exc:
        return _fail(400, "The workflow was not saved because it breaks a rule.", exc.errors)
    except ConfigError as exc:
        return _fail(400, f"The workflow was not saved: {exc}", (str(exc),))
    return _ok(_view(definitions))


def _load_or_default(definitions: DefinitionStore) -> WorkflowDef:
    try:
        return definitions.load()
    except ConfigError:
        logger.exception("The saved workflow is unreadable; editing starts from the default")
        return default_definition()


def _view(definitions: DefinitionStore) -> dict[str, Any]:
    try:
        definition = definitions.load()
        errors = list(validate(definition))
    except ConfigError as exc:
        # Show the default so the page has something to draw, and say why
        definition, errors = default_definition(), [str(exc)]
    return {
        "definition": definition_to_dict(definition),
        "errors": errors,
        "is_default": definition == default_definition(),
        "catalog": catalog_to_json(),
    }


def _ok(data: Any) -> JSONResponse:
    return JSONResponse({"success": True, "data": data, "error": None})


def _fail(status_code: int, message: str, errors: tuple[str, ...] = ()) -> JSONResponse:
    return JSONResponse(
        {"success": False, "data": {"errors": list(errors)}, "error": message},
        status_code=status_code,
    )
