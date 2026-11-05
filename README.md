# Agent & Workflow Builder

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![React 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688.svg)](https://fastapi.tiangolo.com/)

**Natural-language powered AI Agent & Workflow builder** using Microsoft Agent Framework Skills.

Create, edit, visualize, and test-run AI agents & multi-step workflows — entirely from a chat interface.

<!-- Uncomment once you add screenshots:
<p align="center">
  <img src="docs/screenshot-light.png" alt="Light Mode" width="48%" />
  <img src="docs/screenshot-dark.png" alt="Dark Mode" width="48%" />
</p>
-->

> **Note:** This is a Proof-of-Concept (PoC) project. Not intended for production deployments without further hardening.

---

## Features

| Feature | Description |
|---------|-------------|
| **Natural Language Agent Creation** | Describe the agent you want in plain text; the system generates YAML definition + executable Python code |
| **Natural Language Workflow Creation** | Describe a multi-step process; automatic generation of executors, edges, and conditional branching |
| **Chat-based Editing** | Iteratively refine agents and workflows through follow-up chat messages |
| **Visual Workflow Graph** | Interactive React Flow visualization with animated edge traversal |
| **Playground** | Live execution of agents (LLM streaming) and workflows (step-by-step SSE) |
| **Build Validation** | YAML schema, Python AST, and graph connectivity checks |
| **Dark / Light Mode** | Toggle between themes; preference is persisted in localStorage |
| **Weekend Saver** | A built-in workflow that really runs: it switches Azure resources off for the weekend and back on, and can be customized with AI steps. See [docs/weekend-saver.md](docs/weekend-saver.md) |

## Architecture

```
┌─────────────────────────────────────────┐
│          Frontend (React + TS)          │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Agent Builder│ │ Workflow Builder  │  │
│  │ (NL / Manual)│ │ (NL / Edit)      │  │
│  └─────┬──────┘  └────────┬──────────┘  │
└────────┼──────────────────┼─────────────┘
         │  REST + SSE      │
┌────────┼──────────────────┼─────────────┐
│        ▼                  ▼             │
│  ┌────────────────────────────────┐     │
│  │      Orchestrator Agent        │     │
│  │  (Azure OpenAI GPT-4o / 4.1)  │     │
│  └──────┬──────────────┬─────────┘     │
│         │              │               │
│  ┌──────▼─────┐ ┌──────▼──────────┐   │
│  │ agent-     │ │ workflow-       │   │
│  │ creator    │ │ creator         │   │
│  │ Skill      │ │ Skill           │   │
│  └────────────┘ └─────────────────┘   │
│        Backend (FastAPI + Python)       │
└────────────────────────────────────────┘
```

## Skills Design

This project implements the **Microsoft Agent Framework Skills** specification:

### agent-creator Skill
- `SKILL.md` — Agent creation guidelines & prompts
- `scripts/validate_agent.py` — YAML + Python validation
- `references/AGENT_SCHEMA.md` — Agent definition schema

### workflow-creator Skill
- `SKILL.md` — Workflow creation & editing guidelines
- `scripts/validate_workflow.py` — YAML + Python validation (incl. graph connectivity)
- `references/WORKFLOW_PATTERNS.md` — Workflow pattern catalog

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **Azure OpenAI** resource with a GPT-4o (or GPT-4.1) deployment
- Azure CLI (`az login`) for DefaultAzureCredential, **or** an API key

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/agent-workflow-builder.git
cd agent-workflow-builder
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate  (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# Activate  (macOS / Linux)
# source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env with your Azure OpenAI settings
```

### 3. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

### 4. Run

```bash
# Terminal 1 — Backend
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

## Weekend Saver

The builder ships with one workflow that is executed for real instead of simulated:
`weekend_saver` stops Azure resources (VMs, scale sets, AKS, App Service, Application
Gateway, PostgreSQL and MySQL flexible servers) for the weekend and starts them again,
as the person signed in with `az login`.

- Open the **Weekend Saver** page to pick resources, do a dry run, disable or enable
  with an approval step, and set a weekly schedule.
- Customize it in plain words or as JSON: add AI steps that comment on a run, or AI
  gates that stop a disable run before anything changes. The six built-in steps
  cannot be removed or bypassed, and a model problem can never keep resources off.
- Because it changes real resources, it is unlocked with the one-time
  `Weekend Saver: open ...` link the backend prints at start-up, and the open `/api`
  endpoints cannot edit or run it.
- Try it safely with `WEEKEND_SAVER_DEMO=1`, which uses a fake Azure.

Run the backend without `--reload` when you use it. Details:
[docs/weekend-saver.md](docs/weekend-saver.md).

## Configuration

Copy `backend/.env.example` to `backend/.env` and set these variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI endpoint URL | *(required)* |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name | `gpt-4o` |
| `AZURE_OPENAI_API_VERSION` | API version | `2024-12-01-preview` |
| `AZURE_OPENAI_API_KEY` | API key (optional if using `DefaultAzureCredential`) | — |

> **Authentication:** The backend tries `DefaultAzureCredential` first (via `az login`). If that fails, it falls back to the API key.

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/agents` | Create agent (NL prompt or explicit definition) |
| `GET` | `/api/agents` | List all agents |
| `GET` | `/api/agents/{name}` | Get agent detail (YAML + code) |
| `PUT` | `/api/agents/{name}/edit` | Edit agent via natural language |
| `DELETE` | `/api/agents/{name}` | Delete agent |
| `POST` | `/api/agents/{name}/run` | Run agent in playground (SSE stream) |
| `POST` | `/api/workflows` | Create workflow (NL prompt or explicit definition) |
| `GET` | `/api/workflows` | List all workflows |
| `GET` | `/api/workflows/{name}` | Get workflow detail (YAML + code) |
| `PUT` | `/api/workflows/{name}/edit` | Edit workflow via natural language |
| `DELETE` | `/api/workflows/{name}` | Delete workflow |
| `POST` | `/api/workflows/{name}/run` | Run workflow in playground (SSE stream) |

## Project Structure

```
.
├── backend/
│   ├── main.py              # FastAPI application & endpoints
│   ├── orchestrator.py       # LLM orchestration logic
│   ├── llm_client.py         # Azure OpenAI client wrapper
│   ├── models.py             # Pydantic request/response models
│   ├── config.py             # Environment configuration
│   ├── requirements.txt      # Python dependencies
│   ├── .env.example          # Environment template
│   ├── generated/            # Runtime output (gitignored)
│   └── skills/
│       ├── agent-creator/    # Agent creation skill
│       └── workflow-creator/ # Workflow creation skill
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # Main layout, routing, dark mode
│   │   ├── index.css         # All styles (light + dark themes)
│   │   ├── components/
│   │   │   ├── AgentBuilderPage.tsx
│   │   │   ├── WorkflowBuilderPage.tsx
│   │   │   └── HomePage.tsx
│   │   └── api/
│   │       └── client.ts     # API client
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── test_api.py               # Integration tests
├── .gitignore
├── LICENSE
├── CONTRIBUTING.md
└── README.md
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite 6, React Flow (@xyflow/react) |
| Backend | FastAPI, Python 3.11, Uvicorn |
| LLM | Azure OpenAI (GPT-4o / GPT-4.1) |
| Skills | Microsoft Agent Framework Skills specification |
| Storage | Local filesystem (YAML + Python files) |

## Running Tests

```bash
# Start the backend first, then:
python test_api.py
```

The test script exercises agent creation (NL & manual), workflow creation, editing, listing, and playground execution.

The Weekend Saver workflow has its own unit tests, which need neither Azure nor a model:

```bash
cd backend
pip install -r requirements-dev.txt
pytest --cov

cd ../frontend
npm test
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the [MIT License](LICENSE).
