"""ShopCrew dashboard: pick a product, run the crew, watch each agent work, read results.

Run with ``uv run streamlit run app/dashboard.py``.
"""

from __future__ import annotations

import io
import json
import queue
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from shopcrew.datasource import get_data_source
from shopcrew.exceptions import ShopCrewError
from shopcrew.guardrails import CLAIM_WARNING
from shopcrew.llm import configured_model, is_mock
from shopcrew.runner import OUTPUTS_DIR, STAGES, RunEvent, run_crew

load_dotenv()
st.set_page_config(page_title="ShopCrew", page_icon="🛒", layout="wide")

# ---- design tokens (dark) --------------------------------------------------------------
# Validated with the dataviz palette validator against the #1a1a19 chart surface.
SURFACE = "#1a1a19"
TEXT = "#f0efec"
TEXT_2 = "#c3c2b7"
MUTED = "#8a8983"
GRID = "#2c2c2a"
BLUE = "#3987e5"  # us / positive
NEUTRAL = "#6b6a65"  # competitors / neutral (diverging midpoint)
RED = "#e66767"  # negative
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"

st.markdown(
    f"""
<style>
.block-container {{ padding-top: 2rem; max-width: 1280px; }}
.sc-card {{
  border: 1px solid {GRID}; border-radius: 12px; padding: 14px 16px; background: {SURFACE};
  min-height: 104px; transition: border-color .2s, background .2s;
}}
.sc-card .icon {{ font-size: 1.4rem; line-height: 1; }}
.sc-card .title {{ font-weight: 600; color: {TEXT}; margin-top: 6px; }}
.sc-card .status {{ color: {MUTED}; font-size: .85rem; margin-top: 4px; }}
.sc-card.running {{ border-color: {BLUE}; animation: sc-pulse 1.2s ease-in-out infinite; }}
.sc-card.done {{ border-color: {GOOD}; background: #12210f; }}
.sc-card.done .status {{ color: #7ed67e; }}
.sc-card.failed {{ border-color: {CRITICAL}; background: #2a1414; }}
.sc-card.failed .status {{ color: #ff9b9b; }}
@keyframes sc-pulse {{ 50% {{ box-shadow: 0 0 0 4px rgba(57,135,229,.25); }} }}
.sc-chip {{
  display: inline-block; padding: 3px 10px; margin: 0 6px 6px 0; border-radius: 999px;
  border: 1px solid {GRID}; color: {TEXT_2}; font-size: .85rem;
}}
.sc-badge {{ padding: 2px 8px; border-radius: 6px; font-size: .8rem; font-weight: 600; }}
.sc-badge.demo {{ background: #3a2f0b; color: #fab219; }}
.sc-badge.live {{ background: #0f2a17; color: #7ed67e; }}
</style>
""",
    unsafe_allow_html=True,
)


# ---- helpers ---------------------------------------------------------------------------


def card_html(icon: str, title: str, state: str, status: str) -> str:
    """One agent progress card. ``state`` is pending | running | done | failed."""
    mark = {"done": " ✓", "failed": " ✕"}.get(state, "")
    return (
        f'<div class="sc-card {state}"><div class="icon">{icon}</div>'
        f'<div class="title">{title}{mark}</div><div class="status">{status}</div></div>'
    )


def render_cards(slots: list[Any], states: dict[str, tuple[str, str]]) -> None:
    """Draw the four agent cards into their placeholders."""
    for slot, stage in zip(slots, STAGES, strict=True):
        state, status = states.get(stage.key, ("pending", "Waiting"))
        slot.markdown(
            card_html(stage.icon, stage.agent, state, status),
            unsafe_allow_html=True,
        )


def apply_event(states: dict[str, tuple[str, str]], event: RunEvent) -> None:
    """Update card states from a run event."""
    if event.stage is None:
        return
    if event.kind == "started":
        states[event.stage] = ("running", "Working…")
    elif event.kind == "tool":
        states[event.stage] = ("running", event.message.split("(")[0] + "…")
    elif event.kind == "completed":
        states[event.stage] = ("done", "Done")
    elif event.kind == "failed":
        states[event.stage] = ("failed", "Failed: " + event.message[:60])


def zip_folder(folder: Path) -> bytes:
    """Zip every file in ``folder``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.iterdir()):
            if path.is_file():
                zf.write(path, arcname=f"{folder.name}/{path.name}")
    return buffer.getvalue()


def past_runs() -> list[Path]:
    """Run folders that contain a summary, newest first."""
    if not OUTPUTS_DIR.exists():
        return []
    runs = [p for p in OUTPUTS_DIR.iterdir() if (p / "run_summary.json").exists()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def base_layout(fig: go.Figure, height: int) -> go.Figure:
    """Shared dark chart styling: recessive grid, text-colored labels."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"color": TEXT_2, "size": 13},
        hoverlabel={"bgcolor": "#262625", "font": {"color": TEXT}},
        showlegend=False,
        bargap=0.25,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def sentiment_chart(breakdown: dict[str, float]) -> go.Figure:
    """One 100% bar split positive / neutral / negative, each segment labelled."""
    fig = go.Figure()
    for name, color, text_color in (
        ("positive", BLUE, "#ffffff"),
        ("neutral", NEUTRAL, "#ffffff"),
        ("negative", RED, SURFACE),
    ):
        value = breakdown[name]
        fig.add_bar(
            x=[value],
            y=["Sentiment"],
            orientation="h",
            name=name.title(),
            marker={"color": color, "line": {"color": SURFACE, "width": 2}},
            text=[f"{name.title()} {value:.0f}%" if value >= 8 else ""],
            textposition="inside",
            insidetextanchor="middle",
            textfont={"color": text_color},
            hovertemplate=f"{name.title()}: %{{x:.1f}}%<extra></extra>",
        )
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    fig.update_yaxes(visible=False)
    return base_layout(fig, 110)


def rating_chart(histogram: dict[int, int]) -> go.Figure:
    """Review count per star rating (single series)."""
    stars = [5, 4, 3, 2, 1]
    counts = [histogram.get(s, 0) for s in stars]
    fig = go.Figure(
        go.Bar(
            x=counts,
            y=[f"{s} ★" for s in stars],
            orientation="h",
            marker={"color": BLUE, "cornerradius": 4},
            text=counts,
            textposition="outside",
            textfont={"color": TEXT_2},
            hovertemplate="%{y}: %{x} reviews<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(range=[0, max(counts) * 1.2 + 1])
    return base_layout(fig, 220)


def price_chart(product_name: str, our_price: float, rows: list[dict], avg: float) -> go.Figure:
    """Dot plot of competitor prices (neutral) vs ours (blue) with a dashed average line.

    A dot plot rather than bars: prices cluster far from zero, and bars on a truncated
    axis would exaggerate the gaps.
    """
    items = [
        (r["competitor"] + ("" if r["in_stock"] else " (out of stock)"), r["price"], False)
        for r in rows
    ]
    items.append((f"Us · {product_name.split()[0]}", our_price, True))
    items.sort(key=lambda item: item[1])
    prices = [i[1] for i in items]
    fig = go.Figure(
        go.Scatter(
            x=prices,
            y=[i[0] for i in items],
            mode="markers+text",
            marker={
                "color": [BLUE if i[2] else NEUTRAL for i in items],
                "size": [16 if i[2] else 12 for i in items],
                "line": {"color": SURFACE, "width": 2},
            },
            text=[f"${p:,.0f}" for p in prices],
            textposition="middle right",
            textfont={"color": TEXT_2},
            hovertemplate="%{y}: $%{x:,.0f}<extra></extra>",
            cliponaxis=False,
        )
    )
    span = max(prices) - min(prices) or max(prices) * 0.1
    fig.add_vline(x=avg, line={"color": TEXT_2, "dash": "dash", "width": 1.5})
    fig.add_annotation(
        x=avg,
        y=1.06,
        yref="paper",
        text=f"Market avg ${avg:,.0f}",
        showarrow=False,
        font={"color": TEXT_2, "size": 12},
        xanchor="left",
    )
    fig.update_xaxes(range=[min(prices) - span * 0.15, max(prices) + span * 0.3], tickprefix="$")
    fig.update_yaxes(showgrid=True)
    return base_layout(fig, 320)


# ---- results view ----------------------------------------------------------------------


def show_results(run_dir: Path) -> None:
    """Render a saved run (fresh or historical) from its ``run_summary.json``."""
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    product = summary["product"]
    insights = summary["review_insights"]
    pricing = summary["pricing_report"]
    seo = summary["seo_copy"]
    plan = summary["campaign_plan"]
    cost = summary["cost"]
    source = get_data_source()

    top = st.columns([3, 1])
    with top[0]:
        st.subheader(product["name"])
        usd = "n/a" if cost["usd"] is None else f"${cost['usd']:.4f}"
        st.caption(
            f"`{run_dir.name}` · {summary['process']} · model `{summary['model']}` · "
            f"{summary['duration_s']:.1f}s · {cost['total_tokens']:,} tokens · est. cost {usd}"
        )
    with top[1]:
        st.download_button(
            "⬇ Download all outputs (.zip)",
            data=zip_folder(run_dir),
            file_name=f"{run_dir.name}.zip",
            mime="application/zip",
            use_container_width=True,
        )

    notes: list[str] = summary.get("notes", [])
    claim_notes = [n for n in notes if n.startswith(CLAIM_WARNING)]
    if claim_notes:
        st.warning(
            "**Check before publishing:** the agents kept claims the product data doesn't "
            "support, even after one rewrite.\n\n"
            + "\n".join(f"- {n.split(': ', 1)[1]}" for n in claim_notes)
        )
    if other_notes := [n for n in notes if not n.startswith(CLAIM_WARNING)]:
        with st.expander(f"Guardrail fixes applied ({len(other_notes)})"):
            st.markdown("\n".join(f"- {n}" for n in other_notes))

    tabs = st.tabs(["⭐ Reviews", "$ Prices", "¶ SEO", "↗ Marketing", "Run log"])

    with tabs[0]:
        reviews = source.get_reviews(product["id"])
        histogram = {s: sum(1 for r in reviews if r.rating == s) for s in range(1, 6)}
        m = st.columns(3)
        m[0].metric("Average rating", f"{insights['average_rating']:.2f} / 5")
        m[1].metric("Reviews analysed", len(reviews))
        m[2].metric("Positive", f"{insights['sentiment_breakdown']['positive']:.0f}%")
        st.plotly_chart(sentiment_chart(insights["sentiment_breakdown"]), use_container_width=True)
        left, right = st.columns(2)
        with left:
            st.markdown("**Ratings**")
            st.plotly_chart(rating_chart(histogram), use_container_width=True)
        with right:
            st.markdown("**Top praises**")
            st.markdown("\n".join(f"- {p}" for p in insights["top_praises"]))
            st.markdown("**Top complaints**")
            st.markdown("\n".join(f"- {c}" for c in insights["top_complaints"]))
        st.markdown("**Customer phrases** (reused by the SEO Writer)")
        st.markdown(
            "".join(f'<span class="sc-chip">“{p}”</span>' for p in insights["customer_phrases"]),
            unsafe_allow_html=True,
        )
        st.info(insights["summary"])

    with tabs[1]:
        rows = [r.model_dump() for r in source.get_competitor_prices(product["id"])]
        m = st.columns(4)
        m[0].metric("Our price", f"${pricing['our_price']:,.0f}")
        m[1].metric("Market average", f"${pricing['competitor_avg']:,.0f}")
        m[2].metric("Position", pricing["position"].replace("_", " ").title())
        delta = pricing["recommended_price"] - pricing["our_price"]
        m[3].metric("Recommended", f"${pricing['recommended_price']:,.0f}", f"{delta:+,.0f}")
        st.plotly_chart(
            price_chart(product["name"], pricing["our_price"], rows, pricing["competitor_avg"]),
            use_container_width=True,
        )
        st.markdown(f"**Reasoning.** {pricing['reasoning']}")
        with st.expander("Table view"):
            st.dataframe(rows, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.markdown(f"#### {seo['title']}")
        st.caption(
            f"Title {len(seo['title'])}/70 chars · Meta {len(seo['meta_description'])}/160 chars"
        )
        st.markdown(f"*{seo['meta_description']}*")
        st.markdown("\n".join(f"- {b}" for b in seo["bullet_points"]))
        st.write(seo["long_description"])
        st.caption(f"{len(seo['long_description'].split())} words")
        st.markdown(
            "".join(f'<span class="sc-chip">{k}</span>' for k in seo["keywords"]),
            unsafe_allow_html=True,
        )

    with tabs[3]:
        st.markdown(f"### {plan['key_message']}")
        a, b = st.columns(2)
        a.markdown(f"**Target audience**\n\n{plan['target_audience']}")
        b.markdown(f"**Offer**\n\n{plan['offer']}")
        st.markdown(f"**Positioning.** {plan['positioning_statement']}")
        c1, c2, c3 = st.columns(3)
        with c1.container(border=True):
            st.markdown("**Instagram**")
            st.write(plan["instagram_caption"])
        with c2.container(border=True):
            st.markdown("**Google ad**")
            st.markdown(f"**{plan['google_ad']['headline']}**")
            st.write(plan["google_ad"]["description"])
        with c3.container(border=True):
            st.markdown("**Email**")
            st.markdown(f"**{plan['email']['subject']}**")
            st.text(plan["email"]["body"])
        st.markdown("**7-day schedule**")
        st.dataframe(plan["7_day_schedule"], use_container_width=True, hide_index=True)
        st.markdown(f"**How we address complaints.** {plan['how_we_address_complaints']}")

    with tabs[4]:
        st.code((run_dir / "run_log.txt").read_text(encoding="utf-8"), language="text")


# ---- page ------------------------------------------------------------------------------

st.title("🛒 ShopCrew")
st.caption(
    "Four AI agents that analyse reviews, track prices, write SEO copy and plan a launch campaign."
)

try:
    products = get_data_source().list_products()
except ShopCrewError as err:
    st.error(str(err))
    st.stop()

model = configured_model()
with st.sidebar:
    st.header("Run settings")
    names = {p.id: f"{p.name} ({p.id})" for p in products}
    product_id = st.selectbox("Product", list(names), format_func=names.get)
    process = st.radio(
        "Process",
        ["sequential", "hierarchical"],
        help="Hierarchical adds a Store Manager agent that delegates each task.",
    )
    demo = is_mock(model)
    badge = (
        '<span class="sc-badge demo">DEMO MODE</span>'
        if demo
        else '<span class="sc-badge live">LIVE</span>'
    )
    st.markdown(f"Model: `{model}` {badge}", unsafe_allow_html=True)
    if demo:
        st.caption(
            "Offline demo agents (no API key needed). Set MODEL and ANTHROPIC_API_KEY "
            "for real LLM output."
        )
    run_clicked = st.button("▶ Run Crew", type="primary", use_container_width=True)

    runs = past_runs()
    if runs:
        st.divider()
        st.header("Past runs")
        chosen = st.selectbox(
            "Open a previous run",
            [None, *runs],
            format_func=lambda p: "—" if p is None else p.name,
        )
        if chosen is not None and not run_clicked:
            st.session_state["run_dir"] = str(chosen)

card_slots = [col.empty() for col in st.columns(4)]
states: dict[str, tuple[str, str]] = {}
if "run_dir" in st.session_state and not run_clicked:
    states = {s.key: ("done", "Done") for s in STAGES}
render_cards(card_slots, states)

if run_clicked:
    events: queue.Queue[RunEvent] = queue.Queue()
    outcome: dict[str, Any] = {}

    def worker() -> None:
        """Run the crew off the UI thread; events stream back through the queue."""
        try:
            outcome["result"] = run_crew(
                product_id, process=process, on_event=events.put, verbose=False
            )
        except Exception as err:  # shown in the UI below
            outcome["error"] = err

    thread = threading.Thread(target=worker, daemon=True)
    started = time.time()
    thread.start()
    status = st.status("Running the crew…", expanded=False)
    while thread.is_alive() or not events.empty():
        while not events.empty():
            event = events.get()
            apply_event(states, event)
            status.write(event.line())
        render_cards(card_slots, states)
        time.sleep(0.3)
    thread.join()
    render_cards(card_slots, states)
    if "error" in outcome:
        status.update(label="Run failed", state="error")
        st.error(f"{type(outcome['error']).__name__}: {outcome['error']}")
    else:
        status.update(label=f"Done in {time.time() - started:.1f}s", state="complete")
        st.session_state["run_dir"] = str(outcome["result"].out_dir)

if "run_dir" in st.session_state and Path(st.session_state["run_dir"]).exists():
    st.divider()
    show_results(Path(st.session_state["run_dir"]))
elif not run_clicked:
    st.info("Pick a product and click **Run Crew** to start.")
