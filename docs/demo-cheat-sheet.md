# Demo cheat sheet: Microsoft Agent Framework, the Workflow Builder and Weekend Saver

One hour slot. 40 minutes speaking and demo, 20 minutes questions and buffer.
Deck: https://claude.ai/artifact/MB6BzgR5Am9Vfqaubv3fXC (13 slides; the .pptx is in the repo root).

## Before the session (15 minutes, the day before and again 30 minutes before)

- [ ] Fill slide 11: `[€__ per month]` and `[__ resources]`, or delete those two lines.
- [ ] `backend/.env` has `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` set. On 7 November it still held the placeholder `your-resource.openai.azure.com`; with that, chat generation and every AI step fail with a connection error. Run `az login` (needed for the model when no API key is set).
- [ ] Decide: demo mode (fake Azure, safe, recommended) or real subscription. Demo mode below.
- [ ] Terminal 1, backend (do not use `--reload`, it kills runs and the unlock link):

```powershell
cd C:\MainData\AI-Projects\agent-workflow-builder\backend
$env:WEEKEND_SAVER_DEMO = "1"
python start.py
```

- [ ] Terminal 2, frontend:

```powershell
cd C:\MainData\AI-Projects\agent-workflow-builder\frontend
npm run dev
```

- [ ] The backend opens http://localhost:5173/weekend-saver unlocked by itself. If it does not, copy the `Weekend Saver: open http://localhost:5173/ws/?token=...` line from terminal 1 into the browser.
- [ ] Warm-up: on the Workflows page, generate one workflow from chat once (proves model + sign-in). Keep it as the fallback if live generation is slow.
- [ ] On Weekend Saver: click **Reset to default** under Customize, run one **Dry run** so you have seen the dialog today.
- [ ] Browser zoom 125 percent, light theme, close other tabs, notifications off, second screen shows this sheet.
- [ ] Editor open on `backend/weekend_saver/executors.py` at the `Approval` class and `backend/weekend_saver/workflow.py` at `build_workflow`, font size 18 or more.
- [ ] Window layout: deck full screen on the projector, browser ready behind it (Alt+Tab).

## Timeline

| Time | Block | Slides | Mode |
|---|---|---|---|
| 0:00 - 0:03 | Why this matters | 1 - 2 | Deck |
| 0:03 - 0:10 | What Microsoft Agent Framework is | 3 - 5 | Deck |
| 0:10 - 0:16 | Anatomy of a workflow, enterprise gains | 6 - 7 | Deck |
| 0:16 - 0:17 | Bridge: from framework to our builder | 8 | Deck |
| 0:17 - 0:24 | Workflow Builder, live | 9 - 10 | Browser |
| 0:24 - 0:35 | Weekend Saver, live, plus two minutes of code | 11 | Browser, editor |
| 0:35 - 0:38 | Status and next steps | 12 | Deck |
| 0:38 - 0:40 | Close and the ask | 13 | Deck |
| 0:40 - 1:00 | Questions, buffer | | |

If running late at 0:24, cut the Customize part of Weekend Saver (saves 3 minutes) but keep the two minutes of code; without them the audience sees a web page, not the framework. If late at 0:17, skip the Refine step in the builder (saves 2 minutes).

## Part 1: Why this matters (3 min, slides 1 - 2)

Open: "Everyone here has seen an AI chat answer a question. The hard part in a company is letting AI take part in a process without losing control of it."

Three enterprise questions (slide 2):
- **Control**: who decides what the AI may do, and where does a person sign off?
- **Trust**: can we see what happened, step by step, afterwards?
- **Continuity**: does it survive a crash, a restart, a weekend?

"Today: Microsoft's answer to those three, and a working example on our own Azure resources."

## Part 2: What Microsoft Agent Framework is (7 min, slides 3 - 5)

Slide 3, the framework:
- Open source from Microsoft; the successor to Semantic Kernel and AutoGen, one framework instead of two.
- Version 1.0 generally available since April 2026. .NET and Python; Go in public preview.
- Four areas: **Agents**, **Harness Agent**, **Workflows**, **Integrations**.
- Model providers: Microsoft Foundry, Azure OpenAI, OpenAI, Anthropic, Ollama. Tools via MCP (Model Context Protocol). Middleware for logging and guardrails. Sessions and context providers for memory.

Slide 4, building blocks (2 by 2):
- **Agent** = model + instructions + tools. Good for open-ended tasks.
- **Workflow** = graph of executors joined by edges. Good for processes with fixed steps.
- Built in: human in the loop, checkpoints, observability (spans, metrics, events), visualization, declarative YAML workflows.
- Orchestration patterns ready to use: sequential, concurrent, handoff, group chat, Magentic.

Slide 5, agent or workflow (the decision most teams get wrong):
- Agent when the path is unknown and judgement is needed.
- Workflow when the steps are known and must happen in order, with an approval.
- Quote Microsoft's own guidance: "if you can write a function, do that". AI goes in the steps that need it, not around the whole process.

## Part 3: Anatomy and gains (6 min, slides 6 - 7)

Slide 6, anatomy. Point at the six boxes; they are the real Weekend Saver steps you will show later:
1. **Load targets**: check the list of resources before anything talks to Azure.
2. **Resolve state**: read each resource's state, plan what this run does.
3. **Approval** (orange): show the plan, wait for yes or no. The run pauses here; a dry run ends here.
4. **Apply**: disable or enable.
5. **Verify**: confirm each resource reached the target state (10 attempts, 15 seconds apart).
6. **Report**: notify (webhook) and end.

Vocabulary to land:
- **Executor**: a box, plain code or an AI agent.
- **Edge**: an arrow; carries a typed message; can branch on an outcome ("valid", "invalid", "approved", "replan", "ended").
- **Human in the loop**: the run stops at approval until a person answers.
- **Checkpoint**: progress is saved, so a paused run can be resumed later, even after a restart (`weekend-saver resume --approve`).

Slide 7, six gains: one sentence each, do not read the cards. Suggested order: approvals built in, every step observable, resumable runs, model choice stays yours, standard patterns instead of custom glue, same framework in .NET and Python.

## Part 4: Bridge (1 min, slide 8)

"The framework gives you the building blocks. The builder is what we made with them: it lets a process owner describe a workflow in plain words and get a real Agent Framework definition. It is our proof of concept, not a Microsoft product."

## Part 5: Workflow Builder, live (7 min, slides 9 - 10, then browser)

Show slide 9 for 30 seconds (Describe, Generate, Visualize, Test, Refine), then Alt+Tab to http://localhost:5173/workflows.

1. **Describe**. Type in the chat:

   > When an invoice arrives, extract the fields, check them against the purchase order, and ask a manager to approve anything over the limit. Otherwise post it to accounts payable.

2. **Generate**. While it works (10 to 30 seconds), say: "It writes a YAML definition and the matching Agent Framework Python code, then validates the YAML schema, the Python syntax and that every step is connected."
3. **Visualize**. Point at the graph: executors as nodes, the conditional edge at the approval.
4. **Test**. Open the playground, run it with a sample invoice. "Here the model plays each step so we can check the shape of the process. Only Weekend Saver runs for real."
5. **Refine**. Type:

   > Add a step after extraction that flags duplicates by invoice number.

   "Every follow-up message edits the same workflow. The AI steps are also saved as agents on the Agents page."

Say once: "Models come from our own Azure OpenAI deployment, which can live in Microsoft Foundry. Sign-in is the Azure CLI or a key. Nothing leaves our tenant."

Slide 10 (benefits) is optional; if on time, one sentence per row: speed, shared picture, standard output, safe trials.

Fallback: if generation hangs, open the workflow you generated in the warm-up and continue from step 3.

## Part 6: Weekend Saver, live (11 min, slide 11, then browser)

Slide 11, 1 minute: "This one is real. It switches chosen Azure resources off for the weekend and on again. Supported: VMs, scale sets, AKS, App Service, Application Gateway, PostgreSQL and MySQL flexible servers. It runs with the signed-in person's own Azure permissions."

Say this before anyone asks: "There is no AI in the six core steps, on purpose. This is the Workflows half of Agent Framework: the graph runtime, typed messages, the pause for a human, checkpoints. Remember slide 5: if you can write a function, write a function. Switching a VM off is a function. The framework earns its place by running that function inside a governed, resumable process, and by letting us add an AI step exactly where judgement helps, which I will show at the end."

What Weekend Saver really uses from the framework (say it in these words, they are the class names):
- Each step is an **Executor** with a **handler**; it passes a typed message on with `send_message` and picks the next step by outcome.
- Approval calls **request_info**: the run suspends, a **checkpoint** is written, and a **response handler** continues it when a person answers, even from another process (`resume --approve`).
- The graph is assembled with **WorkflowBuilder**; the AI steps you add are also executors, placed into the same graph.

Go to http://localhost:5173/weekend-saver. Say up front: "This is demo mode, an in-memory copy of Azure, so I can switch things off in front of you."

### 6.1 Resources (2 min)
- Top: sign-in status. In demo mode it shows a demo account.
- Click **Manage resources**. Open the subscription **Demo Dev/Test**, then **rg-shop-dev**. "Each level loads when you open it, so a large tenant is never listed in full."
- Already ticked: shop-web-dev, shop-api-dev, shop-worker-dev, shop-db-dev, build-agent.
- Points to make while hovering:
  - **shop-db-dev** has order 10: disabled last, enabled first, so the apps never run without their database.
  - **jumpbox** is tagged `weekend-saver=skip`: the workflow leaves it alone.
  - **build-agent** is already stopped: the plan will say "skip, already stopped".
  - Tick **Show other types**: storage and Key Vault appear greyed out. "We only touch what we can safely start again."

### 6.2 Dry run (1 min)
- Click **Dry run**. Watch the graph animate: Load targets, Resolve state, Approval, then it ends. "A dry run stops at the approval step. Nothing changed."
- Read the plan: stop or skip per resource, with the reason.

### 6.3 Disable with approval (3 min)
- Click **Disable now**. The run pauses at the orange **Approval** node and the dialog shows the plan.
- Say: "This is the human in the loop from slide 6. The workflow is suspended with a checkpoint. If I closed the laptop now, it could be resumed later."
- Click **Approve and disable**. Apply and Verify light up; each resource takes about a second in demo mode. Report ends the run.
- Scroll to **Managed resources**: "now switched off: 4" and the last change of each resource. Click one resource to load its history. "Every change is recorded, one line per resource and change, in `activity.jsonl`. Nothing is ever deleted from it."

### 6.4 Enable (1 min)
- Click **Enable now**, approve. "Enable only starts what a disable run stopped; it reads its own record, so a machine someone stopped on purpose stays stopped. The record expires after six days, so an old record cannot start the wrong thing."

### 6.5 Show the code (2 min, this is where the framework becomes visible)
Switch to the editor, two files, no scrolling:
- `backend/weekend_saver/executors.py`, the `Approval` class: the `@handler` that calls `ctx.request_info(...)`, and the `@response_handler` that continues the run with the person's answer. "This is human in the loop as the framework defines it. The run is not blocked in a thread; it is suspended and checkpointed."
- `backend/weekend_saver/workflow.py`, `build_workflow`: six executors wired with `WorkflowBuilder`. "Same classes any Agent Framework workflow uses, in .NET or Python."
- Optional, terminal: `python -m weekend_saver resume --checkpoint-dir <dir> --approve` is how a paused run is resumed from a checkpoint later.

### 6.6 Customize in plain words (3 min, cut if late)
- Open **Customize**. Type:

  > Add an AI step that summarizes the plan in two sentences before approval

  The graph gains a node before Approval. Run **Dry run** again: the note shows on the node and in the approval dialog.
- Second edit, a gate:

  > Before planning, stop a disable run if more than ten resources are listed

  "A gate can stop a disable run before anything changes. Gates are only allowed before Apply, and they can never hold back an enable run. A model problem can never leave resources switched off."
- Wording for these AI steps: "Each AI step is an Agent Framework agent: its instructions are the step's instructions, its input is the run description, and it runs on the framework's chat client over our Azure OpenAI deployment. So this is an Agent Framework agent inside an Agent Framework workflow." If someone wants proof, `AgentModel` in `backend/weekend_saver_host.py` is twelve lines: `Agent(client, instructions=...)` and `agent.run(...)`.
- Show the list under the Customize box: added steps and changed settings are always visible. Mention **Edit as JSON** and **Reset to default**; click Reset to default at the end.
- Rules worth saying: the six built-in steps cannot be removed, renamed, bypassed or reordered; an edit that breaks a rule is refused with the reasons and nothing is saved; at most six AI steps, each waits at most 45 seconds.

### 6.7 Schedule (30 seconds)
- Open **Schedule**: weekly disable and enable in local time, approved in advance. "A missed enable runs when the backend next starts; a missed disable is skipped and reported." Leave it off.

## Part 7: Status and next steps (3 min, slide 12)

Be plain:
- Today: a proof of concept one person runs locally. Only Weekend Saver runs for real; other workflows are simulated. One Azure OpenAI deployment. Each workflow keeps its own copy of its AI steps.
- Protection today: Weekend Saver answers only on localhost, needs the one-time link, a session cookie, a custom header and the builder's origin. The rest of the builder's API has no sign-in.
- Proposed (a proposal, not a commitment): Entra ID sign-in and roles; run every workflow for real with approvals and checkpoints; a shared agent library; telemetry into our monitoring; a hosted deployment. Most of it is wiring the builder to what the framework already offers.

## Part 8: Close (2 min, slide 13)

"Start with one process." Pick one that repeats, has clear steps and one approval. Build it in the builder with the process owner in the room. Measure before choosing the next one. Then: questions.

## Likely questions

- **Is this a Microsoft product?** The framework is Microsoft's and open source. The builder and Weekend Saver are ours, built on it.
- **Where is the AI in Weekend Saver? It looks like a plain workflow.** Correct, and deliberate. The six core steps are code, because stopping a VM needs no model and must never depend on one. What the framework provides is the runtime around them: executors and typed edges, the suspend-and-resume approval, checkpoints, and a place to add AI steps. The AI steps are the Customize part: notes and gates, each a framework agent with its own instructions on our Azure OpenAI deployment. Workflows and agents are the two halves of Agent Framework, and the Customize demo shows both in one graph.
- **Are those AI steps Agent Framework agents?** Yes. Each one is the framework's `Agent` class with the step's instructions, run on the framework's OpenAI chat client pointed at our Azure OpenAI deployment, inside an executor of the workflow graph. That is what makes the framework's tool calling, middleware and sessions available to those steps later.
- **Does the builder's generated code use the agent half?** Yes: each generated agent is an `Agent` on an Azure OpenAI chat client, and each generated workflow wires those agents as executors. That code is generated and validated but not executed by the builder today; the playground simulates the run.
- **Which models can it use?** Any Azure OpenAI deployment, including one in Microsoft Foundry. The framework itself also supports OpenAI, Anthropic and local Ollama; the builder is wired to Azure OpenAI today.
- **What stops the AI from doing damage?** The six core steps use no model at all. AI steps can only add a note or stop a disable run; they cannot change a plan or hold back an enable. Resource names are treated as data by the model, and subscription IDs and tags are never sent to it.
- **What does it cost?** Tokens only for AI steps and chat edits. A default Weekend Saver run calls no model.
- **Who can run it?** Whoever unlocks the page, acting with their own `az login` permissions. Role-based access is the first proposed next step.
- **What about Semantic Kernel or AutoGen code we have?** Agent Framework is their successor; Microsoft publishes migration guides for both.
- **Does it need the laptop on?** Today yes. Scheduled runs happen only while the backend runs. Hosting it is on the proposed list.
- **Can we add our own steps in code?** Yes, an executor is a Python class; the catalog of built-in steps is how Weekend Saver exposes its six.
- **Where are workflows stored?** `backend/generated/workflows/<name>/workflow.yaml` plus generated Python; agents under `backend/generated/agents/`.

## If something goes wrong

| Symptom | Do this |
|---|---|
| Weekend Saver page says it is locked | Copy the `Weekend Saver: open ...` link from the backend terminal into the browser. Restart the backend for a new link. |
| "Request failed (HTTP 404)" | An older backend is still answering. Stop it and run `python start.py` again. |
| Chat generation slow or failing | Use the warm-up workflow; say the model endpoint is busy. For Weekend Saver, JSON edits still work without a model. |
| AI note says no model is configured | `.env` endpoint missing or sign-in expired; run `az login` in terminal 1 and restart the backend. |
| Graph does not animate | Reload the page; the run keeps going on the backend and the state comes back. |
| Need to abandon the demo | Slides 6 and 11 carry the story; narrate the six steps from the deck. |

## Numbers to have ready

| Item | Value |
|---|---|
| Framework 1.0 GA | April 2026 |
| Languages | .NET, Python; Go preview |
| Weekend Saver core steps | 6, fixed order |
| Verify | 10 attempts, 15 s apart |
| Enable record validity | 6 days |
| AI steps per workflow | at most 6, 45 s timeout each |
| Demo resources managed | 5 ticked, 1 skipped by tag, 1 already stopped |
