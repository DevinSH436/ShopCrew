# ShopCrew: Multi-Agent AI Team for an E-Commerce Store

> **Instructions for Claude Code:** This README is the full spec for the project. Build it phase by phase (see "Build Plan" at the bottom). After each phase, run the app and tests, confirm they pass, then move on. Check the current CrewAI docs (docs.crewai.com) for the latest API before writing code, since the library changes often. Ask me before adding any paid service other than the LLM API.

---

## 1. What this is

ShopCrew is a team of four AI agents, built with **CrewAI**, that run the boring-but-important work of an online store. Each agent has one job. They share their findings with each other, and the last agent turns everything into a marketing campaign.

| # | Agent | Role | Output |
|---|-------|------|--------|
| 1 | **Review Analyst** | Reads customer reviews, finds sentiment, top complaints, top praised features | `review_insights.json` |
| 2 | **Price Tracker** | Compares our price vs competitors, flags where we are over/under priced, suggests a price | `pricing_report.json` |
| 3 | **SEO Writer** | Writes an SEO-optimized product title, description, bullet points and meta tags, using the review insights (real customer language) | `seo_copy.md` |
| 4 | **Marketer** (most important) | Uses all three outputs to plan a launch campaign: target audience, positioning, ad copy (Instagram, Google, email), offer/discount, and posting schedule | `campaign_plan.md` |

The point of the project: agents **collaborate**. The Marketer does not work alone, it reads what the other three found. For example, if reviews praise battery life and we are priced 10% below competitors, the campaign should lead with "longest battery life at a better price."

This is a portfolio/resume project, so code quality, a clean README, a demo UI and tests matter as much as features.

---

## 2. Tech stack

- **Python 3.11+**
- **CrewAI** (agents, tasks, crew orchestration) + `crewai-tools` where useful
- **LLM:** Anthropic Claude via CrewAI's LLM wrapper (LiteLLM format, e.g. `anthropic/claude-sonnet-5-5`). Make the model configurable via `.env` so OpenAI/Gemini/Ollama also work.
- **Pydantic** for structured agent outputs (use CrewAI's `output_pydantic` on tasks)
- **Streamlit** for the demo dashboard
- **pytest** for tests
- **python-dotenv** for config
- Package manager: `uv` (fallback to `pip` + `requirements.txt`)

---

## 3. Data sources

Do **not** scrape real websites by default (legal/ToS issues, flaky). Use local sample data so the demo always works:

- `data/products.json`: 3 to 5 sample products (e.g. wireless earbuds, smartwatch, water bottle). Fields: `id`, `name`, `category`, `our_price` (USD), `current_description`, `features`.
- `data/reviews.json`: 30+ realistic reviews per product, mixed sentiment. Fields: `product_id`, `rating` (1 to 5), `text`, `date`.
- `data/competitor_prices.csv`: columns `product_id, competitor, price, in_stock, last_checked`. At least 4 competitors per product.

Create custom CrewAI tools that read these files:
- `ReviewLoaderTool(product_id)` returns reviews for a product
- `CompetitorPriceTool(product_id)` returns competitor price rows
- `ProductInfoTool(product_id)` returns product details

Design the tools behind a small interface so a real data source (Shopify API, a CSV upload, a scraper) can be swapped in later. Add a `--source` option stub but only implement `local` now.

---

## 4. Project structure

```
shopcrew/
├── README.md
├── pyproject.toml
├── .env.example
├── data/
│   ├── products.json
│   ├── reviews.json
│   └── competitor_prices.csv
├── src/shopcrew/
│   ├── __init__.py
│   ├── main.py              # CLI entry: python -m shopcrew.main --product earbuds-01
│   ├── crew.py              # builds the Crew
│   ├── config/
│   │   ├── agents.yaml      # role, goal, backstory per agent
│   │   └── tasks.yaml       # description, expected_output per task
│   ├── tools/
│   │   ├── review_tool.py
│   │   ├── price_tool.py
│   │   └── product_tool.py
│   ├── models.py            # Pydantic output schemas
│   └── llm.py               # LLM setup from env
├── app/
│   └── dashboard.py         # Streamlit UI
├── outputs/                 # generated reports, one folder per run
└── tests/
    ├── test_tools.py
    ├── test_models.py
    └── test_crew_smoke.py   # runs crew with a mocked LLM
```

Use CrewAI's YAML config pattern (`agents.yaml` / `tasks.yaml` with the `@CrewBase` decorator) since it is the recommended structure.

---

## 5. Agents and tasks in detail

### Review Analyst
- **Goal:** Turn raw reviews into clear, actionable insights.
- **Task output (Pydantic `ReviewInsights`):** `average_rating`, `sentiment_breakdown` (positive/neutral/negative %), `top_praises` (list), `top_complaints` (list), `customer_phrases` (exact words customers use, for SEO), `summary`.

### Price Tracker
- **Goal:** Keep our pricing competitive.
- **Task output (`PricingReport`):** `our_price`, `competitor_min`, `competitor_max`, `competitor_avg`, `position` (`cheapest` / `below_avg` / `above_avg` / `most_expensive`), `recommended_price`, `reasoning`.
- Do the math (min/max/avg) in the **tool**, not the LLM, so numbers are always correct. The agent only interprets.

### SEO Writer
- **Goal:** Write product copy that ranks and converts.
- **Context:** receives Review Analyst output.
- **Task output (`SEOCopy`):** `title` (max 70 chars), `meta_description` (max 160 chars), `bullet_points` (5), `long_description` (150 to 250 words), `keywords` (list).
- Must reuse `customer_phrases` and lead with `top_praises`. Must not claim features the product does not have.

### Marketer
- **Goal:** Launch a campaign that sells.
- **Context:** receives all three previous task outputs.
- **Task output (`CampaignPlan`):** `target_audience`, `positioning_statement`, `key_message`, `offer` (discount/bundle based on pricing position), `instagram_caption`, `google_ad` (headline + description), `email` (subject + body), `7_day_schedule` (list of day/channel/action), `how_we_address_complaints`.

### Process
- Start with `Process.sequential`: Reviews → Prices → SEO → Marketing, using each task's `context` to pass outputs forward.
- Phase 4 adds a `Process.hierarchical` option with a manager agent, selectable via CLI flag, so I can show both in interviews.

---

## 6. How it should run

### CLI
```bash
uv sync
cp .env.example .env        # add ANTHROPIC_API_KEY
uv run python -m shopcrew.main --product earbuds-01
uv run python -m shopcrew.main --all          # run for every product
uv run python -m shopcrew.main --product earbuds-01 --process hierarchical
```
Each run saves to `outputs/<product_id>_<timestamp>/` with the four output files plus a `run_log.txt` showing what each agent did.

### Dashboard
```bash
uv run streamlit run app/dashboard.py
```
The dashboard should:
- Let me pick a product and click **Run Crew**
- Show live progress per agent (4 cards: Reviews ⭐, Prices $, SEO ¶, Marketing ↗) turning green with a check as each finishes
- Show each agent's output in its own tab (charts for sentiment and price comparison, formatted copy for SEO and campaign)
- Let me download all outputs as a zip
- Have a dark theme

---

## 7. Configuration (`.env.example`)

```
ANTHROPIC_API_KEY=
MODEL=anthropic/claude-sonnet-5-5
TEMPERATURE=0.3
VERBOSE=true
DATA_SOURCE=local
```

---

## 8. Quality requirements

- Type hints everywhere, docstrings on public functions
- No API keys in code; `.env` in `.gitignore`
- Tests must pass **without** an API key (mock the LLM in the smoke test)
- Validate all agent outputs against Pydantic models; retry once on invalid output
- Handle missing product IDs and empty review lists with clear error messages
- Track and print token usage / estimated cost at the end of each run
- `ruff` for linting and formatting

---

## 9. Build plan (do these in order)

**Phase 1: Foundation**
Project skeleton, `pyproject.toml`, `.env.example`, sample data files with realistic content, the three tools, Pydantic models, and tests for tools and models.
*Done when:* `pytest` passes and tools return correct data.

**Phase 2: Single agents**
Set up `llm.py`, `agents.yaml`, `tasks.yaml`. Get the Review Analyst and Price Tracker working on their own.
*Done when:* each produces valid JSON for one product.

**Phase 3: Full crew**
Add the SEO Writer and Marketer, wire up `context` so outputs flow forward, build the CLI, save outputs per run.
*Done when:* `--product earbuds-01` produces all four files, and the campaign clearly references review insights and pricing.

**Phase 4: Hierarchical mode + polish**
Add the manager-agent option, token/cost tracking, error handling, retry logic, mocked-LLM smoke test.

**Phase 5: Dashboard**
Build the Streamlit app described in section 6.

**Phase 6: Portfolio polish**
Rewrite this README for humans: project overview, architecture diagram (Mermaid), screenshots/GIF placeholders, sample output, "what I learned" section, and resume bullet points I can copy. Add a GitHub Actions workflow that runs `ruff` and `pytest`.

---

## 10. Stretch ideas (only after Phase 6, ask me first)

- Real data source: Shopify or WooCommerce API connector
- Scheduled daily price checks with alerts when a competitor drops price
- Memory, so agents remember last week's findings and report changes
- A fifth agent: **Inventory Planner** that uses review trends and pricing to suggest restock quantities
- Deploy the dashboard to Streamlit Community Cloud
