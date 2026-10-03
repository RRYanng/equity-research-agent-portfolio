# AI Equity Research Agent

**Sanitized portfolio edition / local prototype.** A personal full-stack research prototype that combines financial calculations with LLM interpretation and selected assumptions. This public repository is a curated code example with new Git history. It is **not a deployed service**, and no production users, uptime, or investment accuracy are claimed.

[Project fact card](PROJECT_FACTS.txt) · [Sanitization details](SANITIZATION.txt) · [Personal portfolio](https://ruiyiyang.vercel.app) · [GitHub profile](https://github.com/RRYanng)

## What you can inspect and run

- React interface: ticker input, analysis progress over SSE, structured results, local report history, watchlist, and comparisons between stored runs.
- Python pipeline: eight sequential analysis stages—macro, industry, company, financial, valuation, catalyst, risk, committee—with shared Pydantic state.
- Deterministic tools: DCF/reverse-growth calculations, financial ratios, selected quality metrics, valuation routing, and supported multi-asset NAV.
- FastAPI endpoints for health, streaming analysis, reports, watchlists, and diffs; SQLite local storage.
- 170 regression tests and five **synthetic** offline workflow cases. These validate bounded behavior, not investment conclusions.

## Technology verified from code

| Layer | Implementation | Source |
| --- | --- | --- |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS 4 | [package.json](web/frontend/package.json), [Vite config](web/frontend/vite.config.ts) |
| Backend | Python 3.12 tested environment, FastAPI, Uvicorn, SSE | [requirements](requirements.txt), [API](web/api/main.py) |
| Analysis | LangGraph StateGraph, Pydantic, Anthropic Python SDK | [graph](proto/graph.py), [state](proto/state.py), [LLM interface](proto/llm.py) |
| Storage | Local SQLite checkpoints, reports, watchlists | [CLI](proto/run.py), [reports](web/api/reports.py), [watchlist](proto/watchlist.py) |
| Data adapters | yfinance, SEC EDGAR/XBRL, Finnhub, FRED, Damodaran-compatible industry data, CoinGecko | [adapters](proto/data) |

This project's frontend uses React/Vite. The separate personal portfolio website uses Next.js.

```text
data -> [preipo_gate when routed] -> macro -> industry -> company
     -> financial -> valuation -> catalyst -> risk -> committee
     -> sensitivity -> consensus -> end
```

The normal PUBLIC path executes 11 nodes; PRE_IPO executes 12, excluding START/END. The eight stages are not eight parallel agents. Consensus runs after committee and does not determine its rating.

## Start with offline validation

Use Python 3.12 and Node.js 22.12+ or a newer Node version supported by Vite. Install dependencies into your own environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m proto.eval.harness
cd web/frontend
npm ci
npm run build
```

No API keys are needed for the tests or default synthetic replay. Synthetic cases retain familiar ticker strings as routing labels; their values and narratives **are not observations about those companies**. Replay selects responses by schema shape, not by archived prompt hash. It tests graph/routing behavior and does not test current Claude output quality or exact prompt equivalence.

On 2026-10-02 (America/Los_Angeles), this sanitized edition passed **170/170 regression tests**, **27/27 checks across five synthetic workflow cases**, and the TypeScript/Vite production build. Python checks used the previously validated pinned Python 3.12 environment; frontend dependencies were installed afresh with `npm ci`. A completely fresh Python dependency installation on another machine has not been verified. No fresh paid LLM analysis was run for this publication.

## Run the local application

From the repository root:

```bash
cp proto/.env.example proto/.env
# Fill ANTHROPIC_API_KEY locally; optionally configure Finnhub/FRED.
./start.sh
```

The backend listens at `http://127.0.0.1:8011`; the frontend requests `http://localhost:5173`. Fresh analysis calls Claude and external data services and can incur charges. Reports, caches, and watchlists are created locally in ignored folders. There is no application login or multi-user authorization layer.

The SEC adapters currently use an example User-Agent contact; configure your own valid contact in the adapter configuration before live SEC requests. The Damodaran adapter ships an **empty template**, not the original provider snapshot. Obtain your own local data for this optional source; without it that source returns unavailable and other supported paths may fall back to Finnhub or LLM-estimated multiples. Live evaluation/recording bypasses the ordinary estimated cost ceiling; recorded responses are written into ignored `data_cache/eval_recordings`, not public fixtures.

## Known limitations

- This is source code for a local prototype. **No public live demo, deployed application, or production use is verified.** No product screenshots are embedded.
- An earlier live AAPL audit of the original implementation completed with risk-node degradation: `RiskView.risks_by_category` was not a dictionary. Committee continued with low confidence. That is historical evidence, not a clean live pass of this edition; the underlying LLM-output defect is not fixed here.
- LLMs generate narratives and selected numeric assumptions. Some multiples may be LLM estimates. Citations and heuristic source labels do not prove every number is correct or current; missing-data behavior includes defaults and fallbacks in some paths.
- The default USD 3 live cost ceiling uses estimated token prices and is not a billing guarantee. Synthetic replay has no Claude calls. Process-global usage accounting is not production concurrency isolation.
- If port 5173 is occupied, Vite may choose another port while backend CORS still permits only port 5173. `VITE_API_BASE` changes the browser API target, not CORS. Free the expected port or configure both sides consistently.
- SQLite checkpoint loading in the original audited environment emitted custom-type warnings. Dependency upgrades and external API availability require revalidation.

## Publication boundary

Only curated source, tests, synthetic fixtures, and public documentation are included. The original private repository, its history, credentials, databases, internal planning documents, provider snapshot, recorded LLM research outputs, generated reports, and machine-specific paths are excluded. The original private repository remains unchanged.

*Personal research prototype. Not investment advice. Not affiliated with the data providers.*
