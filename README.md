> **New front end:** run `python -m serve.api` and open http://localhost:8000. The home page has one card per tool (MedResearch Chat, Genomics, Pharmacovigilance); click a card to open that tool, and use the top bar to switch. Direct pages: `/chat`, `/genomics`, `/pharmacovigilance`. Setup and run commands are unchanged.

# Latest package: drug safety evidence extension

Start with [PV_README.md](PV_README.md) for installation, the new workflow and its limits. This ZIP includes the previous genomics module and MedResearch app. Previous documentation follows for background.

# New: genomics evidence + classifier

See [GENOMICS_README.md](GENOMICS_README.md) for the combined VCF/ClinVar/gnomAD/PubMed module, measured held-out-gene test sample, and simple startup. Run `bash setup_genomics.sh` for this lightweight install.

# Medical Research Agent

> **Research prototype, not medical advice.** Do not submit personal health information. Verify every citation and claim. A public deployment is a demo, not a pharmacovigilance system.


Agentic AI that answers medical research questions by planning, using real
tools, and citing real sources. A LangGraph agent drives four working tools:
PubMed literature search, openFDA adverse events + drug labels, and
ClinicalTrials.gov trials, plus a FAISS RAG layer over a medical paper
corpus (adapted from FinSight).

This is a research and information tool that cites its sources.
It does not give medical advice.

## Architecture

```text
Browser / CLI -> FastAPI -> LangGraph planner -> six-tool registry
                                      |-> PubMed live (Entrez)
                                      |-> openFDA events and labels
                                      |-> ClinicalTrials.gov API v2
                                      |-> local FAISS abstracts (full local install)
                                      |-> read-only SQLite FAERS snapshot
                     -> cross-check -> cited answer + source links + trace
```

`tools/mcp_server.py` separately exposes these tools through FastMCP. The graph currently calls Python functions directly, not through an MCP client.

## Demo media

Add a screenshot of the running UI and a short screen recording after reviewing that they contain no personal data. These media are **not included yet**.

## Run it (Mac)

Install Python 3.11 or newer first. A fresh ZIP extracts to `medresearch-agent`.
Open Terminal, then run these commands one at a time (without a numbered prefix):

```sh
cd ~/Downloads/medresearch-agent
bash setup.sh
source .venv/bin/activate
```

Create `.env` with a Groq API key from https://console.groq.com. Type the
real key in place of `PASTE_KEY_HERE`, keeping the quotes. Do not share the
key in chat, code, screenshots, or GitHub:

```sh
echo "GROQ_API_KEY=PASTE_KEY_HERE" > .env
python -m serve.api
```

The browser opens at http://localhost:8000/. Ask a question there. Leave the
terminal running while using the browser; Ctrl+C stops the server. If the
browser does not open, visit http://localhost:8000/ manually. If port 8000 is
already in use, stop the earlier server with Ctrl+C before starting this one.
The full dependency install downloads a large ML stack and can take minutes.
Running `bash setup.sh` again is safe, but re-activate the venv in each new
terminal (`source .venv/bin/activate`).

Optional: to enable the PubMed source, add your own email address as
`NCBI_EMAIL=you@example.com` on a second line in `.env`, then restart.
Without it, PubMed searches report the missing email; other sources still
work. The key is needed for answering through Groq. This is a research
prototype, not a clinical tool; verify claims against original sources.

On Windows: same four steps with `setup.bat` (Command Prompt) or
`setup.ps1` (PowerShell); tick "Add python.exe to PATH" in the Python
installer.

## Layout

    agent/    LangGraph graph, nodes, state, LLM client (Groq/Ollama)
    tools/    Tool clients (pubmed, openfda, trials) + registry + MCP server
    rag/      FAISS retrieval (from FinSight) + RAGAS-style LLM judge
    eval/     MedQA harness
    data/     FAERS sqlite, paper corpus, FAISS index, eval samples
    finetune/ LoRA notebook (Colab), merge + quantize script
    serve/    vLLM serving config

## What works today

    python -m agent.graph "any medical question"   # the full agent, cited answer
    python -m tools.sql_tool "Which reactions are most reported for semaglutide?"
    python -m tools.mcp_server                      # MCP server, all 6 tools, stdio
    python -m eval.run_eval                         # 6-question eval, score table
    python -m serve.api                             # browser UI at http://localhost:8000
    python -m rag.build_index                       # fetch PubMed corpus, build FAISS
    python -m rag.retrieve                          # RAG smoke test (toy corpus)
    python -m tools.pubmed_tool "any medical query" # individual tools, direct
    python -m tools.openfda_tool metformin
    python -m tools.trials_tool "metformin lactic acidosis"

The agent's planner now picks from 6 tools: live PubMed, openFDA adverse
events, FDA labels, ClinicalTrials.gov, literature_rag (local FAISS index of
real PubMed abstracts - build it once with python -m rag.build_index), and query_faers_db (text-to-SQL).

## FAERS data: actual reports and the demo fallback

The archive now includes `data/faers_real.db`, a **bounded snapshot of actual
public openFDA drug-event safety reports**, retrieved on 28 September 2026.
It is not the full FAERS database. For each of six searched drugs, the fetcher
reads at most 3,000 matching reports using the API's `search_after` cursor;
retatrutide has fewer matching reports and all available matches were read.
The search matches the reported medicinal-product name; a report can mention
multiple drugs and reactions, so these rows do **not** prove which drug caused
an event. Counts are neither incidence nor comparative risk.

Refresh the local database (network required):

    python -m tools.fetch_faers

The script builds into a temporary SQLite file, checks all six drug queries,
and replaces `data/faers_real.db` only after success. It records source URL,
retrieval time, API `last_updated`, total API matches, sampled reports,
report-reaction row counts and selection rule in `_provenance`.
One `faers_reports` row is a distinct (searched drug, safetyreportid, reaction)
triple. Use `COUNT(DISTINCT primaryid)` for the number of reports mentioning a
reaction. Search order is API order, **not a random or representative sample**.
The snapshot can lag FDA reporting, and the API can itself lag releases.
Source: https://open.fda.gov/apis/drug/event/ ; paging:
https://open.fda.gov/apis/paging/ .

`tools/sql_tool.py` uses the real snapshot when present. If the real DB is
absent it falls back to `data/faers_demo.db`, still **450 synthetic rows**,
with its old seed script (`python -m tools.seed_faers_demo`) untouched.
The browser's data notice reads the active source dynamically. The live
openFDA adverse-event API tool is separate from this local snapshot, so its
whole-dataset counts should **not** be confused with local sampled counts.

## Public demo preparation (Render)

The repository includes `render.yaml` for a **free Render web service** using
the Dockerfile and port 10000. Sign in to Render with GitHub, choose **New >
Blueprint**, select this repository and check that its service plan says
**Free**. Enter `GROQ_API_KEY` and `NCBI_EMAIL` in Render's secret prompts;
`LLM_MODEL` is already configured. Do not put keys in GitHub, the README, or
chat. Confirm the deployment at `/api/health`, then test a question at `/`.
If Render's UI asks to upgrade or enter a payment method, stop and check
before proceeding. The free service may sleep after 15 minutes; its first
request after sleep can take around a minute. Its filesystem is ephemeral,
so refreshes run inside the container will not survive restart. The baked
SQLite snapshot remains available after restart. The 512 MB free plan is too
small for the embedding/RAG stack, which is **disabled** there; local full
install is needed for RAG. Public prompts go to the configured Groq service.
Do not claim that deployment or a public URL exists until tested.

Render free service terms: https://render.com/docs/free ; blueprint syntax:
https://render.com/docs/blueprint-spec . This setup uses no Azure service;
there is **no Azure deployment claim**.

## Browser UI + API (FastAPI)

    python -m serve.api     # automatically opens http://localhost:8000

The local command opens the default browser after the server starts. Set `AUTO_OPEN_BROWSER=off` for headless local runs; Docker/Render does not auto-open a browser.

Chat UI in the browser: question in, cited answer + confidence + sources +
expandable agent trace out. POST /api/ask takes {"question": "..."} for
programmatic use. Share a pre-filled question with /?q=your+question.

Docker (one command for anyone):

    docker build -t medresearch-agent .
    docker run -p 8000:8000 --env-file .env medresearch-agent

The image uses requirements-serve.txt (slim: no torch/RAG weights) and ships
the same real FAERS snapshot. Inside the container, literature_rag reports
a gap until the embedding stack and index are supplied. Other tools remain
available when their keys and network access are set.

## Build order

1. Weekend 1 (done): API clients, LangGraph agent, FinSight RAG layer.
2. Weekend 2 (mostly done): text-to-SQL on the real FAERS snapshot with demo fallback, MCP server,
   MedQA-style eval harness. Real openFDA snapshot: done. Remaining: comprehensive/representative FAERS
load and validated medical evaluation.
3. Weekend 3: LoRA fine-tune on free GPU, vLLM serving, benchmark table.

See the project blueprint PDF for the full plan.

## License

MIT, see `LICENSE`. Source-code license does not make the FDA reports medically validated.

## Standard MedQA exam benchmark

The six project-written questions in `eval/run_eval.py` remain smoke tests.
For an independent test of answer selection, run:

    python -m eval.medqa_eval --n 50 --seed 42

This downloads the open [MedQA USMLE four-option test split](https://huggingface.co/datasets/GBaker/MedQA-USMLE-4-options), selects 50 test rows with a fixed seed, asks the full agent each question and scores **exact A/B/C/D choice**, counting unanswered/errors as wrong. It prints per-question choices and a summary, saving a JSON record in `eval/results/`. The default 12-second minimum pace may be too fast for some Groq free-tier quotas; it retries temporary 429 errors and you can use `--pace 30` or a smaller `--n 3` trial. The exact runtime depends on model quota, network and tool calls; 50 questions can take well over 10 minutes, especially with retries. It uses your configured model and public APIs, so check their current terms and limits before running a large sample.

Optional `--judge` adds the project's **custom RAGAS-style** LLM judge (faithfulness, answer relevance, context precision, 40/40/20), only when successful tool evidence exists. It adds three model calls per scored question and may exhaust a free-tier quota. It is **not** the official RAGAS package's published score. No MedQA accuracy is claimed until the real run finishes. USMLE-style exam questions test medical exam choice selection; this is a harder, different task from adverse-event research. A result does not establish pharmacovigilance quality or clinical safety. Dataset license: CC BY 4.0 per the dataset page; credit GBaker/MedQA-USMLE-4-options in any published result.

## Speed and evaluation controls

Independent tools run in parallel (at most four worker threads); answers and
cross-checks still make sequential model calls. Public API searches and FDA
label/count lookups are cached for 24 hours in ignored `data/cache/`. The SQL
snapshot and local RAG are **not** cached. Set `TOOL_CACHE=off` in your own
`.env` to bypass the cache. The browser's `/api/ask/stream` sends NDJSON token
and completion events; `/api/ask` stays buffered for scripts. In the terminal,
`python -m agent.graph "your question"` streams the final answer. Streaming
shortens time to first visible text, not the time spent planning/retrieving.
If a stream fails after text appears, the UI reports it instead of hiding a
partial answer; failures before the first token fall back to buffered mode.

The MedQA eval now asks for a short clinical rationale and an explicit final
A/B/C/D line, without changing the ordinary research answer style. If the
model emits a fake tool call, one stricter plain-text retry is attempted. A
413/TPM error triggers one retry with shorter evidence after a one-minute
cooldown. The summary reports accuracy on valid questions, answered-only
accuracy and raw correct/all, and counts infrastructure errors separately.
For repeated independent completions use `--vote` (three votes) or
`--vote 5`; ties are abstentions. Each extra vote uses the model and counts
against free-tier quota. Fifty questions with three votes may take 45-90+
minutes, possibly longer with rate-limit retries; use a three-question trial
first. This is a new evaluation configuration and cannot be compared directly
with a one-vote run. No improved accuracy is claimed before a full rerun.
# Medresearch---agent
