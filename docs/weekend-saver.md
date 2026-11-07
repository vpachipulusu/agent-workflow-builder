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
WEEKEND_SAVER_DEMO=1 python start.py
```

`start.py` stops whatever already serves port 8000 before it starts, so an older copy of
the backend cannot keep answering in its place. If the Weekend Saver page reports
"Request failed (HTTP 404)", that is what happened: an older backend is still running.

Demo mode uses an in-memory fake of Azure and a throwaway data folder. Start the
frontend as usual (`npm run dev` in `frontend/`).

## Unlocking the page

Start the backend with `python start.py` and the frontend with `npm run dev`, in either
order. As soon as both run, the backend opens the Weekend Saver page in your default
browser, already unlocked. There is nothing to copy.

Behind that is a one-time link, which the backend also prints:

```
Weekend Saver: open http://localhost:5173/ws/?token=...
```

It works once, sets a session cookie, and sends the browser to the Weekend Saver page.
Without it the page explains that it is locked. Restart the backend to get a new link.
Open the printed link yourself when:

- you want another browser than the default one;
- no tab opened (the backend waits ten minutes for the frontend, then gives up);
- you start the backend with `uvicorn main:app` or with `--reload`, which only print
  the link unless you set `WEEKEND_SAVER_OPEN_LINK=1` yourself, or you set it to `0`.

Run the backend **without `--reload`** (the default of `start.py`) when you use Weekend
Saver. The builder writes generated `.py` files under `backend/generated/`, which makes
`--reload` restart the server: a restart ends a run in progress and invalidates the link.

## Using it for real

1. Sign in with `az login` (the page also offers a browser sign-in). Your own Azure
   permissions apply: you need the right to start and stop the resources you pick.
2. Start the backend without `WEEKEND_SAVER_DEMO`; the page opens unlocked.
3. **Manage resources**: open a subscription, then a resource group, and tick what
   should be switched off. Each level is loaded when you open it, so a large tenant
   does not have to be listed in full. Supported types are virtual machines, scale
   sets, AKS clusters, App Service apps, Application Gateways, and PostgreSQL and MySQL
   flexible servers. Everything else is hidden until you tick **Show other types**,
   and then listed greyed out. What is already managed is listed at the top under
   **Selected**, and stays managed whether or not you open its group.
4. **Dry run** shows the plan and changes nothing. **Disable now** and **Enable now**
   show the plan and wait for your approval.
5. **Schedule** (off by default) runs disable and enable once a week, in this
   computer's local time. Scheduled runs are approved in advance and only happen while
   the backend is running and the computer is awake. A missed enable runs when the
   backend next starts; a missed disable is skipped and reported.

Enable only starts what a disable run stopped, using a record kept in your user data
folder (`%LOCALAPPDATA%\weekend-saver` on Windows, `~/.local/state/weekend-saver`
elsewhere). A resource tagged `weekend-saver=skip` is left alone.

### What was switched off and on

The workflow keeps a record of every change it makes, in `activity.jsonl` in the same
folder: one line per resource and change, with the time, whether it was a disable or
an enable, and whether it worked. Runs from the page, the schedule and the command
line all add to it; a dry run, a rejected plan and a resource that was skipped do not.

On the page, **Managed resources** shows how many resources Weekend Saver has switched
off right now and the last change of each one. Click a resource to load its history.
The record is never shortened; the page reads its newest two megabytes, which is about
ten thousand changes.

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

AI steps and chat edits use the Azure OpenAI deployment from `backend/.env`. Each AI
step runs as an Agent Framework `Agent` whose instructions are the step's instructions,
on the framework's chat client over the builder's signed-in Azure OpenAI client, so a
note or gate is a framework agent inside the framework workflow. Without
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
  use for untrusted local apps. `python start.py` unlocks it in your default browser;
  if that is not the one you want, set `WEEKEND_SAVER_OPEN_LINK=0` and open the
  printed link where you do.
- The rest of the builder is still a local proof of concept: its `/api` endpoints have
  no sign-in and no Host check.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `WEEKEND_SAVER_DEMO` | unset | `1` runs against the in-memory fake of Azure |
| `WEEKEND_SAVER_OPEN_LINK` | `1` with `python start.py`, otherwise unset | `1` opens the one-time link in the browser at start-up; `0` only prints it |
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
