# JVL Content Engine

SEO content pipeline for the JVL Echo Home B2C product stream.
Generates grounded, persona-specific article assets from a structured knowledge base.

---

## Pipeline

```
Brief Agent             →  outputs/briefs/<slug>.json
SERP Research Agent     →  outputs/serp_research/<slug>.json
Company Insight Agent   →  outputs/company_insight/<slug>.json
Writer Agent            →  (next — not yet built)
```

Each agent reads the previous stage's output. Running them in order gives the
Writer Agent a full context package: topic brief + competitive landscape + JVL-specific angles.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY at minimum
```

All three agents work without live SERP access. Mock mode is the default.

---

## Agents and CLI reference

### 1. Brief Agent

```
python main.py --topic <text> --primary-keyword <text> [options]
```

| Argument | Required | Default | Notes |
|---|---|---|---|
| `--topic` | yes | — | Article topic |
| `--primary-keyword` | yes | — | SEO keyword |
| `--funnel-stage` | no | `mid` | `top` / `mid` / `bottom` |
| `--country` | no | `US` | Target country |
| `--language` | no | `en` | Content language |
| `--output-dir` | no | `outputs/briefs` | Save location |

Output: `outputs/briefs/<keyword-slug>.json`

---

### 2. SERP / Competitor Research Agent

```
python run_serp_research.py --keyword <text> --topic <text> [options]
```

| Argument | Required | Default | Notes |
|---|---|---|---|
| `--keyword` | **yes** | — | Primary SEO keyword to research |
| `--topic` | **yes** | — | Article topic description |
| `--brief` | no | _(none)_ | Path to brief JSON from Brief Agent. Omit to run without brief context. |
| `--country` | no | `us` | Target country code |
| `--language` | no | `en` | Language code |
| `--top-n` | no | `5` | Number of SERP results to analyse |
| `--output-dir` | no | `outputs/serp_research` | Save location |

Output: `outputs/serp_research/<keyword-slug>.json`

**SERP modes:**

| `SERP_PROVIDER` env var | Behaviour |
|---|---|
| `mock` (default) | No live internet. Output is a clearly-labeled illustrative competitive pattern. All array items prefixed `[MOCK]`. `serp_status: "mock"` in output. |
| `serpapi` | Live Google results via SerpAPI. Requires `SERPAPI_KEY` in `.env`. `serp_status: "live"` in output. Falls back to mock if key is missing. |

---

### 3. Company Insight Agent

```
python run_company_insight.py --topic <text> [options]
```

| Argument | Required | Default | Notes |
|---|---|---|---|
| `--topic` | **yes** | — | Article topic description |
| `--brief` | no | _(none)_ | Path to brief JSON from Brief Agent. Omit to run on topic alone. |
| `--serp-research` | no | _(none)_ | Path to SERP research JSON. When provided, content gaps and differentiation opportunities are passed as prioritisation context. |
| `--output-dir` | no | `outputs/company_insight` | Save location |

Output: `outputs/company_insight/<topic-slug>.json`

---

## Fallback behaviour

| Situation | What happens |
|---|---|
| `--brief` omitted (either agent) | Agent runs with an empty brief dict `{}`. PAA questions default to none. Output is still valid but less focused. |
| `--serp-research` omitted (Company Insight) | Agent runs on knowledge files and brief only. No competitive context is passed. |
| Live SERP unavailable / not configured | SERP Research Agent falls back to mock mode automatically. Output is labeled `serp_status: "mock"`. No error. |
| `SERPAPI_KEY` missing when `SERP_PROVIDER=serpapi` | Logs a warning, falls back to mock. |

---

## Mock mode — what it means

`serp_status: "mock"` means **no real SERP data was retrieved**.

- `top_results` is always `[]` in mock output
- All analysis strings are prefixed `[MOCK]`
- Analysis describes illustrative competitive patterns for the keyword category — not confirmed rankings
- Do not treat mock output as live SERP research
- To confirm with real data: set `SERP_PROVIDER=serpapi` and `SERPAPI_KEY` in `.env`, then re-run

---

## Full chained example — all three topics

### how to choose a home arcade machine

```bash
python main.py \
  --topic "how to choose a home arcade machine" \
  --primary-keyword "how to choose a home arcade machine"

python run_serp_research.py \
  --keyword "how to choose a home arcade machine" \
  --topic "How to choose a home arcade machine" \
  --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json

python run_company_insight.py \
  --topic "how to choose a home arcade machine" \
  --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json \
  --serp-research outputs/serp_research/how-to-choose-a-home-arcade-machine.json
```

### best bartop arcade machine for home bar

```bash
python main.py \
  --topic "best bartop arcade machine for home bar" \
  --primary-keyword "bartop arcade machine for home bar" \
  --funnel-stage mid

python run_serp_research.py \
  --keyword "bartop arcade machine for home bar" \
  --topic "Best bartop arcade machine for home bar" \
  --brief outputs/briefs/bartop-arcade-machine-for-home-bar.json

python run_company_insight.py \
  --topic "best bartop arcade machine for home bar" \
  --brief outputs/briefs/bartop-arcade-machine-for-home-bar.json \
  --serp-research outputs/serp_research/bartop-arcade-machine-for-home-bar.json
```

### no wifi arcade machine

```bash
python main.py \
  --topic "no wifi arcade machine" \
  --primary-keyword "no wifi arcade machine" \
  --funnel-stage mid

python run_serp_research.py \
  --keyword "no wifi arcade machine" \
  --topic "Arcade machines that work without Wi-Fi" \
  --brief outputs/briefs/no-wifi-arcade-machine.json

python run_company_insight.py \
  --topic "no wifi arcade machine" \
  --brief outputs/briefs/no-wifi-arcade-machine.json \
  --serp-research outputs/serp_research/no-wifi-arcade-machine.json
```

---

## Output locations

```
outputs/
  briefs/           ← Brief Agent JSON outputs
  serp_research/    ← SERP Research Agent JSON outputs
  company_insight/  ← Company Insight Agent JSON outputs
```

---

## Environment variables

See `.env.example` for the full reference. Minimum required:

```
ANTHROPIC_API_KEY=...
```

Optional for live SERP:

```
SERP_PROVIDER=serpapi
SERPAPI_KEY=...
SERP_FETCH_PAGES=false   # set true to include page body text in live mode
```
