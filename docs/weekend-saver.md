# Weekend Saver

A workflow that switches Azure resources off for the weekend and back on afterwards,
built with Microsoft Agent Framework. Unlike the builder's other workflows, which are
generated and then simulated, this one really runs: it stops and starts resources as
the person signed in to Azure.

It shows up in the builder as the `weekend_saver` workflow and has its own page,
**Weekend Saver**, where you customize it, run it, and schedule it.

## Try it without Azure

```bash
cd backend
# Windows PowerShell: $env:WEEKEND_SAVER_DEMO = "1"
WEEKEND_SAVER_DEMO=1 uvicorn main:app --port 8000
```

Demo mode uses an in-memory fake of Azure and a throwaway data folder. Start the
frontend as usual (`npm run dev` in `frontend/`).

## Unlocking the page

When the backend starts it prints a line like:

```
Weekend Saver: open http://localhost:5173/ws/?token=...
```

Open that link. It works once, sets a session cookie, and sends you to the builder.
Without it the Weekend Saver page explains that it is locked. Restart the backend to
get a new link.

Run the backend **without `--reload`** when you use Weekend Saver. The builder writes
generated `.py` files under `backend/generated/`, which makes `--reload` restart the
server: a restart ends a run in progress and invalidates the link.

## Using it for real

1. Sign in with `az login` (the page also offers a browser sign-in). Your own Azure
   permissions apply: you need the right to start and stop the resources you pick.
2. Start the backend without `WEEKEND_SAVER_DEMO` and open the printed link.
3. **Manage resources**: tick what should be switched off. Supported types are virtual
   machines, scale sets, AKS clusters, App Service apps, Application Gateways, and
   PostgreSQL and MySQL flexible servers. Everything else is listed greyed out.
4. **Dry run** shows the plan and changes nothing. **Disable now** and **Enable now**
   show the plan and wait for your approval.
5. **Schedule** (off by default) runs disable and enable once a week, in this
   computer's local time. Scheduled runs are approved in advance and only happen while
   the backend is running and the computer is awake. A missed enable runs when the
   backend next starts; a missed disable is skipped and reported.

Enable only starts what a disable run stopped, using a record kept in your user data
folder (`%LOCALAPPDATA%\weekend-saver` on Windows, `~/.local/state/weekend-saver`
elsewhere). A resource tagged `weekend-saver=skip` is left alone.

## Customizing the workflow

The workflow has six built-in steps, which stay in this order:

| Step | What it does | Settings |
|---|---|---|
| `load_targets` | Checks the list of resources | |
| `resolve_state` | Reads each resource's state and plans the run | `max_snapshot_age_days` (1-30, default 6) |
| `approval` | Shows the plan and waits for yes or no | `require_approval` (default true) |
| `apply` | Disables or enables the resources | |
| `verify` | Confirms each one reached its target state | `attempts` (1-60, default 10), `interval_seconds` (0-300, default 15) |
| `report` | Sends the notification and ends the run | `notify` (default true) |

Around them you can add:

- **AI note steps.** The model reads a description of the run at that point and its
  answer is attached as a note: on the graph, in the approval dialog, in the report
  and in the webhook message. The run itself is passed on unchanged.
- **AI gates.** An AI step with a stop condition, for example "it is a public-holiday
  week". If the model says the condition holds, a disable run ends with the status
  "stopped" before anything changes. Gates are only allowed before `apply`.
- **Pass-through steps** (`function`), placeholders that do nothing yet.

Describe the change in the **Customize** box, for example:

- "Add an AI step that summarizes the results in two sentences before the report"
- "Before planning, stop a disable run if more than ten resources are listed"
- "Do not ask for approval on manual runs"

or use **Edit as JSON** to change the definition directly. **Reset to default** removes
every change. The previous working version is kept next to the definition as
`workflow.yaml.bak`. Added steps and every setting that differs from its default are
listed under the Customize box, so a change made by a chat edit is always visible.

A workflow can have at most six AI steps, and each waits at most 45 seconds for the
model, so AI steps cannot hold a run up for long.

Rules that an edit cannot break (it is refused, with the reasons, and nothing is saved):

- The six built-in steps cannot be removed, renamed, bypassed or reordered.
- AI steps cannot create or change a plan. They add notes, or stop a disable run.
- Gates never hold back an **enable** run, and a failing AI step never does either, so
  a model problem cannot leave resources switched off.
- A gate that gets no usable answer stops the **disable** run and reports a failure:
  nothing is disabled.
- If the saved definition is broken (for example edited by hand), enable runs use the
  default workflow and say so in a note; disable runs do not start.

AI steps and chat edits use the Azure OpenAI deployment from `backend/.env`. Without
`AZURE_OPENAI_ENDPOINT` they say so at once: note steps leave a note that no model is
configured, gates stop disable runs, and chat edits are unavailable (JSON edits still
work). A step placed before `approval` runs twice in an approved run, because the plan
is worked out again after approval; its second note is the one kept.

### What the model sees

Resource names, types, power states, the decision for each resource and its reason,
the run's status, and today's date. Subscription IDs and tags are not sent. Resource
names are text chosen by other people, so the model is told to treat the description
as data; and whatever it answers, it can only add a note or stop a disable run.

## How it is protected

The builder's own `/api` endpoints are open to anything on your machine that can reach
the port; they only write files and simulate runs. Weekend Saver can change Azure, so
it is a separate app mounted at `/ws`:

- it answers only on `localhost` / `127.0.0.1`;
- every call needs the session cookie set by the one-time link;
- every change also needs a custom header and must come from the builder's page
  (`FRONTEND_ORIGINS`), which a page on another site cannot do;
- the open endpoints refuse to create, edit, delete or simulate the `weekend_saver`
  workflow, or any workflow that uses built-in steps;
- the builder's CORS rules do not apply to it, so another site on a local port cannot
  read its answers.

Two fixes to the builder's open API came with this, because they could reach the
Weekend Saver folder: agent, workflow and executor names can no longer contain path
separators (`..%5C..` used to delete or write outside `generated/`).

What is still true, and worth knowing:

- Browsers send a `localhost` cookie to every local port. The session cookie is limited
  to `/ws`, but a hostile program serving a site on another local port, opened in the
  same browser, could still capture it. Unlock Weekend Saver in a browser you do not
  use for untrusted local apps.
- The rest of the builder is still a local proof of concept: its `/api` endpoints have
  no sign-in and no Host check.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `WEEKEND_SAVER_DEMO` | unset | `1` runs against the in-memory fake of Azure |
| `FRONTEND_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Pages allowed to drive Weekend Saver; the first is used in the printed link |
| `WEEKEND_SAVER_WEBHOOK_URL` | unset | HTTPS webhook that receives each run report |
| `BACKEND_URL` (frontend) | `http://localhost:8000` | Where the Vite dev server forwards `/api` and `/ws` |

## Command line

The same workflow, with the default steps, can be run without the builder:

```bash
cd backend
python -m weekend_saver disable --resources resources.yaml --dry-run
python -m weekend_saver enable --resources resources.yaml --yes
python -m weekend_saver dashboard --demo      # the original stand-alone dashboard
```

`resources.example.yaml` shows the file format.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest --cov          # no Azure and no model needed
ruff check .

cd ../frontend
npm test
npm run build
```
