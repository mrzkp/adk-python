"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Workflow Visualization — Flame Graph + Sequence Diagram               ║
║                                                                              ║
║  Runs the blackboard_workflow with full instrumentation and generates:        ║
║    1. Terminal ASCII timeline (immediate)                                     ║
║    2. Interactive HTML flame graph (opens in browser)                         ║
║                                                                              ║
║  Usage: uv run python demo/visualize.py                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import webbrowser
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from google.adk import Agent
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import JoinNode
from google.adk.workflow import SufficientJoinNode
from google.adk.workflow import Workflow
from google.adk.workflow import node
from google.genai.types import Content
from google.genai.types import Part

from _common import BOLD
from _common import CYAN
from _common import DIM
from _common import GREEN
from _common import MAGENTA
from _common import RED
from _common import RESET
from _common import WHITE
from _common import YELLOW
from _common import header
from _common import subheader


# ─── Instrumented Mock Agents ──────────────────────────────────────────────────

# Global timeline collector
timeline_events: list[dict] = []
t0 = 0.0


def record(name: str, event_type: str, **kwargs):
    """Record a timeline event."""
    timeline_events.append({
        'name': name,
        'type': event_type,
        'time': time.perf_counter() - t0,
        **kwargs,
    })


@node()
async def agent_news(ctx, node_input: str):
    record('agent_news', 'start', category='agent')
    await asyncio.sleep(2)
    output = (
        'BREAKING: Acme Corp CEO John Smith unexpectedly resigned yesterday,'
        ' effective immediately. The board cited "irreconcilable strategic'
        ' differences." Three senior VPs departed the same day.'
    )
    record('agent_news', 'end', category='agent', status='completed')
    yield output


@node()
async def agent_sentiment(ctx, node_input: str):
    record('agent_sentiment', 'start', category='agent')
    await asyncio.sleep(3)
    output = (
        'Social sentiment: 84% negative across Twitter/Reddit in the past 24h.'
        ' Top trending tags: #AcmeMeltdown, #CEOResigns, #SellAcme.'
        ' Retail investor forums show a surge in sell orders.'
    )
    record('agent_sentiment', 'end', category='agent', status='completed')
    yield output


@node()
async def agent_filings(ctx, node_input: str):
    record('agent_filings', 'start', category='agent')
    try:
        await asyncio.sleep(20)
        output = (
            'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
            ' Net loss of $340M.'
        )
        record('agent_filings', 'end', category='agent', status='completed')
        yield output
    except asyncio.CancelledError:
        record('agent_filings', 'end', category='agent', status='cancelled')
        raise


# ─── Workflow Definitions ──────────────────────────────────────────────────────

QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."

synthesizer = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. Write a concise briefing (3-5 sentences)'
        f' answering: "{QUESTION}" based on the data provided.'
    ),
)

sufficient_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
)

blackboard_workflow = Workflow(
    name='blackboard_workflow',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news, sufficient_join),
        (agent_sentiment, sufficient_join),
        (agent_filings, sufficient_join),
        (sufficient_join, synthesizer),
    ],
)

# Also build standard for comparison
synthesizer_std = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. Write a concise briefing (3-5 sentences)'
        f' answering: "{QUESTION}" based on the data provided.'
    ),
)

standard_join = JoinNode(name='standard_join')

standard_workflow = Workflow(
    name='standard_workflow',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news, standard_join),
        (agent_sentiment, standard_join),
        (agent_filings, standard_join),
        (standard_join, synthesizer_std),
    ],
)


# ─── Runner ───────────────────────────────────────────────────────────────────


async def run_instrumented(workflow: Workflow, label: str) -> float:
    """Run workflow and capture timeline events."""
    global t0
    timeline_events.clear()
    t0 = time.perf_counter()

    record('workflow', 'start', category='workflow', label=label)

    session_service = InMemorySessionService()
    runner = Runner(agent=workflow, app_name='viz', session_service=session_service)
    session = await session_service.create_session(app_name='viz', user_id='u')
    user_content = Content(role='user', parts=[Part(text=QUESTION)])

    async for event in runner.run_async(
        user_id='u', session_id=session.id, new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text and 'SufficientJoin' in part.text:
                    sufficient = 'sufficient=True' in part.text
                    record('evaluator', 'decision', category='evaluator',
                           sufficient=sufficient)
                if part.text and event.author == 'synthesizer':
                    record('synthesizer', 'end', category='synthesizer',
                           status='completed')

    elapsed = time.perf_counter() - t0
    record('workflow', 'end', category='workflow')
    return elapsed


# ─── ASCII Timeline ───────────────────────────────────────────────────────────


def print_ascii_timeline(events: list[dict], total_time: float):
    """Print a Gantt-chart style ASCII timeline to terminal."""
    WIDTH = 60

    # Build spans from start/end pairs
    spans: dict[str, dict] = {}
    for ev in events:
        name = ev['name']
        if ev['type'] == 'start':
            spans[name] = {'start': ev['time'], 'end': total_time, 'status': 'running', 'category': ev.get('category', '')}
        elif ev['type'] == 'end':
            if name in spans:
                spans[name]['end'] = ev['time']
                spans[name]['status'] = ev.get('status', 'completed')
        elif ev['type'] == 'decision':
            spans[name] = {'start': ev['time'] - 0.3, 'end': ev['time'], 'status': 'decision', 'category': 'evaluator'}

    print(subheader('EXECUTION TIMELINE'))
    print(f'  {DIM}0s{"":>{WIDTH-4}}{total_time:.1f}s{RESET}')
    print(f'  {DIM}│{"─" * (WIDTH - 2)}│{RESET}')

    # Order: workflow first, then agents, then evaluator, then synthesizer
    order = ['workflow', 'agent_news', 'agent_sentiment', 'agent_filings',
             'evaluator', 'synthesizer']

    for name in order:
        if name not in spans:
            continue
        span = spans[name]
        start_pos = int((span['start'] / total_time) * WIDTH)
        end_pos = int((span['end'] / total_time) * WIDTH)
        bar_len = max(1, end_pos - start_pos)

        # Choose color and character
        if span['status'] == 'cancelled':
            bar = f'{RED}{"░" * bar_len}{RESET}'
            suffix = f' {RED}✗ cancelled{RESET}'
        elif span['status'] == 'decision':
            bar = f'{CYAN}{"█" * bar_len}{RESET}'
            suffix = f' {CYAN}🧠 sufficient!{RESET}'
        elif span['category'] == 'workflow':
            bar = f'{DIM}{"─" * bar_len}{RESET}'
            suffix = f' {DIM}{span["end"]:.1f}s{RESET}'
        elif span['category'] == 'synthesizer':
            bar = f'{MAGENTA}{"█" * bar_len}{RESET}'
            suffix = f' {MAGENTA}✓ report{RESET}'
        else:
            bar = f'{GREEN}{"█" * bar_len}{RESET}'
            suffix = f' {GREEN}✓ {span["end"]:.1f}s{RESET}'

        padding = ' ' * start_pos
        label = f'{name:<18}'
        print(f'  {label}{DIM}│{RESET}{padding}{bar}{suffix}')

    print(f'  {DIM}│{"─" * (WIDTH - 2)}│{RESET}')
    print(f'  {DIM}{"":>1}Time →{RESET}')


# ─── Timeline Enrichment Helper ────────────────────────────────────────────────

def enrich_timeline_events(events: list[dict], elapsed: float, is_blackboard: bool):
    """Enrich events list with start/end events for implicit steps like Join and Synthesizer."""
    agent_ends = {}
    for ev in events:
        if ev['type'] == 'end' and ev.get('category') == 'agent':
            agent_ends[ev['name']] = ev['time']
            
    if is_blackboard:
        eval_decision = None
        for ev in events:
            if ev['name'] == 'evaluator' and ev['type'] == 'decision':
                eval_decision = ev['time']
                
        if eval_decision:
            if not any(e['name'] == 'evaluator' and e['type'] == 'start' for e in events):
                events.append({'name': 'evaluator', 'type': 'start', 'time': eval_decision - 0.5, 'category': 'evaluator'})
                events.append({'name': 'evaluator', 'type': 'end', 'time': eval_decision, 'category': 'evaluator', 'status': 'completed'})
            
            synth_start = eval_decision + 0.1
            if not any(e['name'] == 'synthesizer' and e['type'] == 'start' for e in events):
                events.append({'name': 'synthesizer', 'type': 'start', 'time': synth_start, 'category': 'synthesizer'})
            if not any(e['name'] == 'synthesizer' and e['type'] == 'end' for e in events):
                events.append({'name': 'synthesizer', 'type': 'end', 'time': elapsed - 0.05, 'category': 'synthesizer', 'status': 'completed'})
    else:
        if agent_ends:
            max_agent_end = max(agent_ends.values())
            events.append({'name': 'standard_join', 'type': 'start', 'time': max_agent_end, 'category': 'join'})
            events.append({'name': 'standard_join', 'type': 'end', 'time': max_agent_end + 0.1, 'category': 'join', 'status': 'completed'})
            
            synth_start = max_agent_end + 0.1
            if not any(e['name'] == 'synthesizer' and e['type'] == 'start' for e in events):
                events.append({'name': 'synthesizer', 'type': 'start', 'time': synth_start, 'category': 'synthesizer'})
            if not any(e['name'] == 'synthesizer' and e['type'] == 'end' for e in events):
                events.append({'name': 'synthesizer', 'type': 'end', 'time': elapsed - 0.05, 'category': 'synthesizer', 'status': 'completed'})


# ─── HTML Flame Graph ─────────────────────────────────────────────────────────


def generate_html(
    standard_events: list[dict],
    standard_elapsed: float,
    blackboard_events: list[dict],
    blackboard_elapsed: float,
    output_path: str,
):
    """Generate an interactive HTML timeline and state machine visualization comparing workflows."""
    
    def build_spans(events, total_time):
        span_map: dict[str, dict] = {}
        for ev in events:
            name = ev['name']
            if ev['type'] == 'start':
                span_map[name] = {
                    'name': name,
                    'start': ev['time'],
                    'end': total_time,
                    'status': 'running',
                    'category': ev.get('category', ''),
                    'label': ev.get('label', name),
                }
            elif ev['type'] == 'end':
                if name in span_map:
                    span_map[name]['end'] = ev['time']
                    span_map[name]['status'] = ev.get('status', 'completed')
            elif ev['type'] == 'decision':
                span_map[name] = {
                    'name': name,
                    'start': ev['time'] - 0.5,
                    'end': ev['time'],
                    'status': 'decision',
                    'category': 'evaluator',
                    'label': f'Evaluator: sufficient={ev.get("sufficient", "?")}',
                }
        return list(span_map.values())

    standard_spans = build_spans(standard_events, standard_elapsed)
    blackboard_spans = build_spans(blackboard_events, blackboard_elapsed)
    
    max_duration = max(standard_elapsed, blackboard_elapsed)
    time_saved = standard_elapsed - blackboard_elapsed
    pct_saved = (time_saved / standard_elapsed) * 100

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WaitAll vs Speculative Join — Workflow Execution Visualizer</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
    --bg-dark: #07090e;
    --card-bg: rgba(22, 28, 45, 0.4);
    --border-glow: rgba(255, 255, 255, 0.08);
    --text-primary: #f0f6fc;
    --text-secondary: #8b949e;
    --accent-blue: #1f6feb;
    --accent-blue-glow: rgba(31, 111, 235, 0.4);
    
    /* Status Colors */
    --completed: #3fb950;
    --completed-bg: rgba(63, 185, 80, 0.12);
    --completed-border: rgba(63, 185, 80, 0.3);
    
    --cancelled: #f85149;
    --cancelled-bg: rgba(248, 81, 73, 0.12);
    --cancelled-border: rgba(248, 81, 73, 0.3);
    
    --running: #f59e0b;
    --running-bg: rgba(245, 158, 11, 0.12);
    --running-border: rgba(245, 158, 11, 0.3);
    
    --pending: #484f58;
    --pending-bg: rgba(72, 79, 88, 0.12);
    --pending-border: rgba(72, 79, 88, 0.2);
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: 'Outfit', sans-serif;
    background-color: var(--bg-dark);
    color: var(--text-primary);
    padding: 30px;
    min-height: 100vh;
    overflow-x: hidden;
    position: relative;
}}

/* Glowing Animated Background Blobs */
.glow-blob {{
    position: absolute;
    border-radius: 50%;
    filter: blur(140px);
    opacity: 0.12;
    z-index: -1;
    pointer-events: none;
    animation: floatBlob 12s ease-in-out infinite alternate;
}}
.blob-red {{
    top: 10%;
    left: 10%;
    width: 350px;
    height: 350px;
    background: var(--cancelled);
}}
.blob-green {{
    bottom: 10%;
    right: 10%;
    width: 400px;
    height: 400px;
    background: var(--completed);
    animation-delay: -4s;
}}
.blob-blue {{
    top: 40%;
    left: 45%;
    width: 300px;
    height: 300px;
    background: var(--accent-blue);
    animation-delay: -8s;
}}

@keyframes floatBlob {{
    0% {{ transform: translate(0, 0) scale(1); }}
    100% {{ transform: translate(60px, 40px) scale(1.15); }}
}}

header {{
    text-align: center;
    margin-bottom: 24px;
}}
h1 {{
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.5px;
    background: linear-gradient(135deg, #fff 30%, #8b949e 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
}}
.subtitle {{
    color: var(--text-secondary);
    font-size: 14px;
    font-weight: 400;
}}

/* Simulation Controller Panel */
.simulator-panel {{
    background: var(--card-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--border-glow);
    border-radius: 12px;
    padding: 16px 24px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 20px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}}
.control-btn {{
    background: var(--accent-blue);
    border: none;
    color: white;
    font-family: 'Outfit', sans-serif;
    font-weight: 600;
    padding: 8px 16px;
    border-radius: 6px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    transition: all 0.2s ease;
    font-size: 13px;
}}
.control-btn:hover {{
    background: #2f81f7;
    box-shadow: 0 0 12px var(--accent-blue-glow);
    transform: translateY(-1px);
}}
.control-btn-sec {{
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border-glow);
}}
.control-btn-sec:hover {{
    background: rgba(255,255,255,0.12);
}}
.slider-container {{
    flex: 1;
    display: flex;
    align-items: center;
    gap: 12px;
}}
.timeline-slider {{
    width: 100%;
    -webkit-appearance: none;
    background: rgba(255,255,255,0.1);
    height: 6px;
    border-radius: 3px;
    outline: none;
    cursor: pointer;
}}
.timeline-slider::-webkit-slider-thumb {{
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--accent-blue);
    box-shadow: 0 0 8px var(--accent-blue-glow);
    transition: transform 0.1s;
}}
.timeline-slider::-webkit-slider-thumb:hover {{
    transform: scale(1.2);
}}
.time-clock {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    font-weight: 700;
    min-width: 80px;
    text-align: right;
    color: var(--accent-blue);
}}

/* Main Comparative Workspace */
.dashboard-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-bottom: 24px;
}}
@media (max-width: 1000px) {{
    .dashboard-grid {{ grid-template-columns: 1fr; }}
}}

.workflow-card {{
    background: var(--card-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--border-glow);
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
    position: relative;
    overflow: hidden;
    transition: border-color 0.3s ease;
}}
.workflow-card.standard {{ border-top: 4px solid var(--cancelled); }}
.workflow-card.blackboard {{ border-top: 4px solid var(--completed); }}

.card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}}
.card-title {{
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.3px;
}}
.card-badge {{
    font-size: 11px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.badge-red {{ background: var(--cancelled-bg); color: var(--cancelled); border: 1px solid var(--cancelled-border); }}
.badge-green {{ background: var(--completed-bg); color: var(--completed); border: 1px solid var(--completed-border); }}

/* State Machine Flow Diagram Layout */
.state-machine-container {{
    display: flex;
    justify-content: center;
    padding: 10px 0;
    margin-bottom: 24px;
}}
.flow-svg {{
    width: 100%;
    height: auto;
    max-height: 520px;
}}

/* SVG Custom Nodes & States Styling */
.node-box {{
    fill: #161b22;
    stroke: #30363d;
    stroke-width: 1.5px;
    transition: all 0.3s ease;
}}
.node-text-title {{
    font-family: 'Outfit', sans-serif;
    font-size: 11px;
    font-weight: 700;
    fill: var(--text-primary);
    text-anchor: middle;
}}
.node-text-sub {{
    font-family: 'Outfit', sans-serif;
    font-size: 9px;
    fill: var(--text-secondary);
    text-anchor: middle;
}}

/* Active Marching Edges */
.edge-line {{
    stroke: #30363d;
    stroke-width: 1.5px;
    fill: none;
    transition: all 0.3s ease;
}}
@keyframes march {{
    to {{ stroke-dashoffset: -20; }}
}}
.active-edge {{
    stroke: var(--accent-blue) !important;
    stroke-width: 2px !important;
    stroke-dasharray: 6, 4;
    animation: march 0.8s linear infinite;
}}
.completed-edge {{
    stroke: var(--completed) !important;
    stroke-width: 2px !important;
}}
.cancelled-edge {{
    stroke: var(--cancelled) !important;
    stroke-width: 1.5px !important;
    stroke-dasharray: 4, 3;
}}

/* Dynamic SVG Classes mapped in JS */
.node-g.pending .node-box {{ fill: #11141a; stroke: #21262d; opacity: 0.4; }}
.node-g.pending text {{ opacity: 0.3; }}

.node-g.running .node-box {{
    fill: var(--running-bg);
    stroke: var(--running);
    stroke-width: 2px;
    filter: drop-shadow(0 0 6px rgba(245,158,11,0.25));
}}
.node-g.running .node-badge {{ fill: var(--running); }}

.node-g.completed .node-box {{
    fill: var(--completed-bg);
    stroke: var(--completed);
    stroke-width: 2px;
    filter: drop-shadow(0 0 6px rgba(63,185,80,0.25));
}}
.node-g.completed .node-text-sub {{ fill: #a3e635; }}

.node-g.cancelled .node-box {{
    fill: var(--cancelled-bg);
    stroke: var(--cancelled);
    stroke-width: 1.5px;
    stroke-dasharray: 4, 2;
    opacity: 0.65;
}}
.node-g.cancelled text {{ fill-opacity: 0.6; }}

/* Flame Gantt-Chart Timelines */
.gantt-section {{
    border-top: 1px solid var(--border-glow);
    padding-top: 20px;
}}
.gantt-row {{
    display: flex;
    align-items: center;
    margin-bottom: 8px;
    height: 32px;
}}
.gantt-label {{
    width: 110px;
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
    text-align: right;
    padding-right: 12px;
    flex-shrink: 0;
}}
.gantt-track {{
    flex: 1;
    position: relative;
    height: 24px;
    background: rgba(255,255,255,0.02);
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.03);
    overflow: hidden;
}}
.gantt-bar {{
    position: absolute;
    height: 100%;
    border-radius: 3px;
    display: flex;
    align-items: center;
    padding-left: 8px;
    font-size: 10px;
    color: white;
    font-weight: 600;
    white-space: nowrap;
    transition: width 0.05s linear, left 0.05s linear;
    cursor: pointer;
}}
.gantt-bar.agent {{ background: linear-gradient(135deg, #1b682e, var(--completed)); }}
.gantt-bar.cancelled {{ background: linear-gradient(135deg, #b91c1c, var(--cancelled)); opacity: 0.7; }}
.gantt-bar.evaluator {{ background: linear-gradient(135deg, #094cb4, var(--accent-blue)); }}
.gantt-bar.synthesizer {{ background: linear-gradient(135deg, #6d28d9, #a371f7); }}
.gantt-bar.workflow {{ background: #21262d; border: 1px dashed var(--pending); }}

/* Summary & High-End Metrics Card */
.comparison-card {{
    background: var(--card-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--border-glow);
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
    margin-bottom: 24px;
}}
.metrics-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 20px;
}}
@media (max-width: 768px) {{
    .metrics-row {{ grid-template-columns: 1fr 1fr; }}
}}
.metric-box {{
    background: rgba(255,255,255,0.02);
    border: 1px solid var(--border-glow);
    border-radius: 12px;
    padding: 16px;
    text-align: center;
}}
.metric-value {{
    font-size: 32px;
    font-weight: 700;
    color: var(--accent-blue);
    margin-bottom: 4px;
}}
.metric-value.green {{ color: var(--completed); }}
.metric-value.red {{ color: var(--cancelled); }}
.metric-desc {{
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
}}

/* Detailed Log Console */
.console-card {{
    background: #0b0e14;
    border: 1px solid var(--border-glow);
    border-radius: 12px;
    padding: 20px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #8b949e;
    max-height: 250px;
    overflow-y: auto;
    box-shadow: inset 0 4px 12px rgba(0,0,0,0.5);
}}
.console-line {{
    margin-bottom: 4px;
    display: flex;
    gap: 16px;
}}
.console-time {{ color: var(--accent-blue); }}
.console-name {{ color: var(--text-primary); font-weight: 500; }}
.console-status {{ color: var(--completed); }}
.console-status.cancelled {{ color: var(--cancelled); }}

/* Tooltip */
.tooltip {{
    position: absolute;
    background: #151b23;
    border: 1px solid var(--border-glow);
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 11px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 1000;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
}}
.tooltip.visible {{ opacity: 1; }}
.tooltip-title {{ color: var(--accent-blue); font-weight: bold; margin-bottom: 4px; }}
.tooltip-row {{ color: var(--text-secondary); margin-top: 2px; }}

</style>
</head>
<body>

<div class="glow-blob blob-red"></div>
<div class="glow-blob blob-green"></div>
<div class="glow-blob blob-blue"></div>

<header>
    <h1>WaitAll vs Speculative Join Visualizer</h1>
    <div class="subtitle">Semantic early-exit vs traditional synchronization barrier comparison &middot; Wall time analysis</div>
</header>

<!-- Interactive Control Panel -->
<div class="simulator-panel">
    <button id="playBtn" class="control-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polygon points="5 3 19 12 5 21 5 3" fill="currentColor"/>
        </svg>
        <span>Play Simulation</span>
    </button>
    <button id="resetBtn" class="control-btn control-btn-sec">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <path d="M2.5 2v6h6M21.5 22v-6h-6"/>
            <path d="M22 11.5A10 10 0 1 0 9.5 21.5"/>
        </svg>
        <span>Reset</span>
    </button>
    <div class="slider-container">
        <input type="range" id="timeSlider" class="timeline-slider" min="0" max="{max_duration:.2f}" step="0.05" value="0">
    </div>
    <div id="clock" class="time-clock">0.0s</div>
</div>

<!-- High-End Metrics Card -->
<div class="comparison-card">
    <div class="metrics-row">
        <div class="metric-box">
            <div class="metric-value red">{standard_elapsed:.1f}s</div>
            <div class="metric-desc">Traditional WaitAll Time</div>
        </div>
        <div class="metric-box">
            <div class="metric-value green">{blackboard_elapsed:.1f}s</div>
            <div class="metric-desc">Speculative Early-Exit Time</div>
        </div>
        <div class="metric-box">
            <div class="metric-value green">{time_saved:.1f}s</div>
            <div class="metric-desc">Total Execution Saved</div>
        </div>
        <div class="metric-box">
            <div class="metric-value green">{pct_saved:.0f}%</div>
            <div class="metric-desc">Wall-Clock Speedup</div>
        </div>
    </div>
</div>

<!-- Main Grid comparing the two workflows -->
<div class="dashboard-grid">
    
    <!-- LEFT PANEL: STANDARD PIPELINE -->
    <div class="workflow-card standard">
        <div class="card-header">
            <h2 class="card-title">Traditional Workflow (WaitAll Join)</h2>
            <span class="card-badge badge-red" id="std-workflow-status">stalled</span>
        </div>
        
        <!-- Vertical Top-Down State Machine -->
        <div class="state-machine-container">
            <svg class="flow-svg" viewBox="0 0 400 520">
                <defs>
                    <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6" fill="#30363d"/>
                    </marker>
                    <marker id="arrow-blue" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                        <path d="M0,0 L6,3 L0,6" fill="var(--accent-blue)"/>
                    </marker>
                </defs>
                
                <!-- Edges -->
                <!-- START to news -->
                <path id="std-edge-start-news" d="M 200,60 L 80,120" class="edge-line" marker-end="url(#arrow)"/>
                <!-- START to sentiment -->
                <path id="std-edge-start-sentiment" d="M 200,65 L 200,120" class="edge-line" marker-end="url(#arrow)"/>
                <!-- START to filings -->
                <path id="std-edge-start-filings" d="M 200,60 L 320,120" class="edge-line" marker-end="url(#arrow)"/>
                
                <!-- News to Join -->
                <path id="std-edge-news-join" d="M 80,170 L 200,250" class="edge-line" marker-end="url(#arrow)"/>
                <!-- Sentiment to Join -->
                <path id="std-edge-sentiment-join" d="M 200,170 L 200,250" class="edge-line" marker-end="url(#arrow)"/>
                <!-- Filings to Join -->
                <path id="std-edge-filings-join" d="M 320,170 L 200,250" class="edge-line" marker-end="url(#arrow)"/>
                
                <!-- Join to Synthesizer -->
                <path id="std-edge-join-synth" d="M 200,310 L 200,370" class="edge-line" marker-end="url(#arrow)"/>
                <!-- Synthesizer to END -->
                <path id="std-edge-synth-end" d="M 200,420 L 200,470" class="edge-line" marker-end="url(#arrow)"/>
                
                <!-- START Node -->
                <g class="node-g completed">
                    <circle cx="200" cy="40" r="18" fill="#161b22" stroke="var(--completed)" stroke-width="2"/>
                    <text x="200" y="44" font-family="Outfit" font-size="9" font-weight="bold" fill="white" text-anchor="middle">START</text>
                </g>
                
                <!-- News Agent Node -->
                <g id="std-node-agent_news" class="node-g">
                    <rect x="30" y="120" width="100" height="50" rx="6" class="node-box"/>
                    <text x="80" y="142" class="node-text-title">News Agent</text>
                    <text x="80" y="157" class="node-text-sub" id="std-time-agent_news">~2.0s</text>
                </g>
                
                <!-- Sentiment Agent Node -->
                <g id="std-node-agent_sentiment" class="node-g">
                    <rect x="150" y="120" width="100" height="50" rx="6" class="node-box"/>
                    <text x="200" y="142" class="node-text-title">Sentiment Agent</text>
                    <text x="200" y="157" class="node-text-sub" id="std-time-agent_sentiment">~3.0s</text>
                </g>
                
                <!-- Filings Agent Node -->
                <g id="std-node-agent_filings" class="node-g">
                    <rect x="270" y="120" width="100" height="50" rx="6" class="node-box"/>
                    <text x="320" y="142" class="node-text-title">Filings Agent</text>
                    <text x="320" y="157" class="node-text-sub" id="std-time-agent_filings">~20.0s (slow)</text>
                </g>
                
                <!-- Traditional Join Barrier Node -->
                <g id="std-node-standard_join" class="node-g">
                    <rect x="130" y="250" width="140" height="60" rx="8" class="node-box"/>
                    <text x="200" y="278" class="node-text-title">WaitAll JoinNode</text>
                    <text x="200" y="293" class="node-text-sub">Blocks until N/N complete</text>
                </g>
                
                <!-- Synthesizer Node -->
                <g id="std-node-synthesizer" class="node-g">
                    <rect x="140" y="370" width="120" height="50" rx="6" class="node-box"/>
                    <text x="200" y="392" class="node-text-title">Synthesizer</text>
                    <text x="200" y="407" class="node-text-sub" id="std-time-synthesizer">LLM Report</text>
                </g>
                
                <!-- END Node -->
                <g id="std-node-end" class="node-g">
                    <circle cx="200" cy="485" r="15" fill="#161b22" stroke="#30363d" stroke-width="1.5" class="node-box"/>
                    <text x="200" y="489" font-family="Outfit" font-size="8" font-weight="bold" fill="white" text-anchor="middle">END</text>
                </g>
            </svg>
        </div>
        
        <!-- Gantt chart timeline -->
        <div class="gantt-section">
            <div id="std-gantt"></div>
        </div>
    </div>
    
    <!-- RIGHT PANEL: BLACKBOARD PIPELINE -->
    <div class="workflow-card blackboard">
        <div class="card-header">
            <h2 class="card-title">Speculative Workflow (Ours)</h2>
            <span class="card-badge badge-green" id="bb-workflow-status">completed</span>
        </div>
        
        <!-- Vertical Top-Down State Machine -->
        <div class="state-machine-container">
            <svg class="flow-svg" viewBox="0 0 400 520">
                <!-- Edges -->
                <!-- START to news -->
                <path id="bb-edge-start-news" d="M 200,60 L 80,120" class="edge-line" marker-end="url(#arrow)"/>
                <!-- START to sentiment -->
                <path id="bb-edge-start-sentiment" d="M 200,65 L 200,120" class="edge-line" marker-end="url(#arrow)"/>
                <!-- START to filings -->
                <path id="bb-edge-start-filings" d="M 200,60 L 320,120" class="edge-line" marker-end="url(#arrow)"/>
                
                <!-- News to Join -->
                <path id="bb-edge-news-join" d="M 80,170 L 200,250" class="edge-line" marker-end="url(#arrow)"/>
                <!-- Sentiment to Join -->
                <path id="bb-edge-sentiment-join" d="M 200,170 L 200,250" class="edge-line" marker-end="url(#arrow)"/>
                <!-- Filings to Join -->
                <path id="bb-edge-filings-join" d="M 320,170 L 200,250" class="edge-line" marker-end="url(#arrow)"/>
                
                <!-- Join to Synthesizer -->
                <path id="bb-edge-join-synth" d="M 200,310 L 200,370" class="edge-line" marker-end="url(#arrow)"/>
                <!-- Synthesizer to END -->
                <path id="bb-edge-synth-end" d="M 200,420 L 200,470" class="edge-line" marker-end="url(#arrow)"/>
                
                <!-- START Node -->
                <g class="node-g completed">
                    <circle cx="200" cy="40" r="18" fill="#161b22" stroke="var(--completed)" stroke-width="2"/>
                    <text x="200" y="44" font-family="Outfit" font-size="9" font-weight="bold" fill="white" text-anchor="middle">START</text>
                </g>
                
                <!-- News Agent Node -->
                <g id="bb-node-agent_news" class="node-g">
                    <rect x="30" y="120" width="100" height="50" rx="6" class="node-box"/>
                    <text x="80" y="142" class="node-text-title">News Agent</text>
                    <text x="80" y="157" class="node-text-sub" id="bb-time-agent_news">~2.0s</text>
                </g>
                
                <!-- Sentiment Agent Node -->
                <g id="bb-node-agent_sentiment" class="node-g">
                    <rect x="150" y="120" width="100" height="50" rx="6" class="node-box"/>
                    <text x="200" y="142" class="node-text-title">Sentiment Agent</text>
                    <text x="200" y="157" class="node-text-sub" id="bb-time-agent_sentiment">~3.0s</text>
                </g>
                
                <!-- Filings Agent Node -->
                <g id="bb-node-agent_filings" class="node-g">
                    <rect x="270" y="120" width="100" height="50" rx="6" class="node-box"/>
                    <text x="320" y="142" class="node-text-title">Filings Agent</text>
                    <text x="320" y="157" class="node-text-sub" id="bb-time-agent_filings">~20.0s</text>
                </g>
                
                <!-- Speculative Join Node -->
                <g id="bb-node-evaluator" class="node-g">
                    <rect x="130" y="250" width="140" height="60" rx="8" class="node-box"/>
                    <text x="200" y="272" class="node-text-title">SufficientJoin</text>
                    <text x="200" y="285" class="node-text-sub" style="fill:var(--accent-blue);font-weight:bold;">LLM Evaluator</text>
                    <text x="200" y="298" class="node-text-sub" id="bb-eval-state">Deciding...</text>
                </g>
                
                <!-- Synthesizer Node -->
                <g id="bb-node-synthesizer" class="node-g">
                    <rect x="140" y="370" width="120" height="50" rx="6" class="node-box"/>
                    <text x="200" y="392" class="node-text-title">Synthesizer</text>
                    <text x="200" y="407" class="node-text-sub" id="bb-time-synthesizer">LLM Report</text>
                </g>
                
                <!-- END Node -->
                <g id="bb-node-end" class="node-g">
                    <circle cx="200" cy="485" r="15" fill="#161b22" stroke="#30363d" stroke-width="1.5" class="node-box"/>
                    <text x="200" y="489" font-family="Outfit" font-size="8" font-weight="bold" fill="white" text-anchor="middle">END</text>
                </g>
            </svg>
        </div>
        
        <!-- Gantt chart timeline -->
        <div class="gantt-section">
            <div id="bb-gantt"></div>
        </div>
    </div>

</div>

<!-- Real-time Event Console Log -->
<div class="workflow-card" style="margin-bottom: 0px;">
    <h2 class="card-title" style="margin-bottom: 12px; font-size: 16px;">System Event Stream Log</h2>
    <div id="console" class="console-card"></div>
</div>

<div id="tooltip" class="tooltip"></div>

<!-- JavaScript Engine for scrubber / simulator -->
<script>
const stdSpans = {json.dumps(standard_spans)};
const bbSpans = {json.dumps(blackboard_spans)};
const stdEvents = {json.dumps(standard_events)};
const bbEvents = {json.dumps(blackboard_events)};

const stdElapsed = {standard_elapsed};
const bbElapsed = {blackboard_elapsed};
const maxDuration = {max_duration};

// Node name mappings for state machines
const stdNodeOrder = ['agent_news', 'agent_sentiment', 'agent_filings', 'standard_join', 'synthesizer', 'end'];
const bbNodeOrder = ['agent_news', 'agent_sentiment', 'agent_filings', 'evaluator', 'synthesizer', 'end'];

const labels = {{
    'workflow': 'Workflow',
    'agent_news': 'News Agent',
    'agent_sentiment': 'Sentiment Agent',
    'agent_filings': 'Filings Agent',
    'standard_join': 'Join Node',
    'evaluator': 'Evaluator Node',
    'synthesizer': 'Synthesizer',
    'end': 'END Node'
}};

const gLabels = {{
    'workflow': 'Workflow',
    'agent_news': 'News Agent',
    'agent_sentiment': 'Sentiment Agent',
    'agent_filings': 'Filings Agent',
    'standard_join': 'WaitAll Join',
    'evaluator': 'SufficientJoin',
    'synthesizer': 'Synthesizer',
}};

// Build Gantt bars once
function renderGantt(spans, parentId, isBB) {{
    const parent = document.getElementById(parentId);
    parent.innerHTML = '';
    
    const displayOrder = isBB 
        ? ['workflow', 'agent_news', 'agent_sentiment', 'agent_filings', 'evaluator', 'synthesizer']
        : ['workflow', 'agent_news', 'agent_sentiment', 'agent_filings', 'standard_join', 'synthesizer'];
        
    displayOrder.forEach(name => {{
        const span = spans.find(s => s.name === name);
        if (!span) return;
        
        const row = document.createElement('div');
        row.className = 'gantt-row';
        
        const label = document.createElement('div');
        label.className = 'gantt-label';
        label.textContent = gLabels[name] || name;
        row.appendChild(label);
        
        const track = document.createElement('div');
        track.className = 'gantt-track';
        
        const bar = document.createElement('div');
        bar.id = `${{isBB ? 'bb' : 'std'}}-bar-${{name}}`;
        bar.className = 'gantt-bar';
        
        // Tooltip interaction
        bar.addEventListener('mouseenter', (e) => {{
            const tooltip = document.getElementById('tooltip');
            tooltip.innerHTML = `
                <div class="tooltip-title">${{labels[name] || name}}</div>
                <div class="tooltip-row">Start: ${{span.start.toFixed(2)}}s</div>
                <div class="tooltip-row">End: ${{span.end.toFixed(2)}}s</div>
                <div class="tooltip-row">Duration: ${{(span.end - span.start).toFixed(2)}}s</div>
                <div class="tooltip-row">Status: ${{span.status}}</div>
            `;
            tooltip.style.left = (e.pageX + 10) + 'px';
            tooltip.style.top = (e.pageY - 60) + 'px';
            tooltip.classList.add('visible');
        }});
        
        bar.addEventListener('mouseleave', () => {{
            document.getElementById('tooltip').classList.remove('visible');
        }});
        
        track.appendChild(bar);
        row.appendChild(track);
        parent.appendChild(row);
    }});
}}

renderGantt(stdSpans, 'std-gantt', false);
renderGantt(bbSpans, 'bb-gantt', true);

// Simulation State variables
let currentTime = 0.0;
let isPlaying = false;
let simInterval = null;

const timeSlider = document.getElementById('timeSlider');
const clock = document.getElementById('clock');
const playBtn = document.getElementById('playBtn');
const resetBtn = document.getElementById('resetBtn');
const consoleDiv = document.getElementById('console');

function updateUI(timeVal) {{
    currentTime = parseFloat(timeVal);
    timeSlider.value = currentTime;
    clock.textContent = currentTime.toFixed(1) + 's';
    
    // Update Standard Pipeline Visual State
    updateWorkflowState(stdSpans, 'std', stdElapsed, currentTime, stdNodeOrder);
    // Update Blackboard Pipeline Visual State
    updateWorkflowState(bbSpans, 'bb', bbElapsed, currentTime, bbNodeOrder);
    
    // Update Timeline Gantt sizes dynamically based on scrubber
    updateGanttBars(stdSpans, 'std', stdElapsed, currentTime);
    updateGanttBars(bbSpans, 'bb', bbElapsed, currentTime);
    
    // Update Event Console
    updateConsoleLog(currentTime);
}}

function updateWorkflowState(spans, prefix, elapsed, timeVal, nodeOrder) {{
    // 1. Workflow global status
    const statusLabel = document.getElementById(`${{prefix}}-workflow-status`);
    if (timeVal >= elapsed) {{
        statusLabel.textContent = prefix === 'std' ? 'completed (stalled)' : 'completed';
        statusLabel.className = `card-badge badge-green`;
    }} else {{
        statusLabel.textContent = prefix === 'std' ? 'stalled / running' : 'running';
        statusLabel.className = prefix === 'std' ? `card-badge badge-red` : `card-badge badge-green`;
    }}

    // 2. Node states
    nodeOrder.forEach(name => {{
        const nodeEl = document.getElementById(`${{prefix}}-node-${{name}}`);
        if (!nodeEl) return;
        
        const span = spans.find(s => s.name === name);
        
        // END node mapping
        if (name === 'end') {{
            if (timeVal >= elapsed) {{
                nodeEl.setAttribute('class', 'node-g completed');
            }} else {{
                nodeEl.setAttribute('class', 'node-g pending');
            }}
            return;
        }}
        
        if (!span) return;
        
        if (timeVal < span.start) {{
            nodeEl.setAttribute('class', 'node-g pending');
        }} else if (timeVal >= span.start && timeVal < span.end) {{
            nodeEl.setAttribute('class', 'node-g running');
            // update sub text dynamically
            const sub = document.getElementById(`${{prefix}}-time-${{name}}`);
            if (sub) sub.textContent = `Running... (${{(timeVal - span.start).toFixed(1)}}s)`;
        }} else {{
            // completed / cancelled
            if (span.status === 'cancelled') {{
                nodeEl.setAttribute('class', 'node-g cancelled');
                const sub = document.getElementById(`${{prefix}}-time-${{name}}`);
                if (sub) sub.textContent = `Cancelled (${{span.end.toFixed(1)}}s)`;
            }} else {{
                nodeEl.setAttribute('class', 'node-g completed');
                const sub = document.getElementById(`${{prefix}}-time-${{name}}`);
                if (sub) sub.textContent = `Done (${{(span.end - span.start).toFixed(1)}}s)`;
            }}
        }}
    }});
    
    // Custom evaluator badge updates
    if (prefix === 'bb') {{
        const evalState = document.getElementById('bb-eval-state');
        const evalSpan = spans.find(s => s.name === 'evaluator');
        if (timeVal < evalSpan.start) {{
            evalState.textContent = 'Waiting for inputs...';
            evalState.style.fill = 'var(--text-secondary)';
        }} else if (timeVal >= evalSpan.start && timeVal < evalSpan.end) {{
            evalState.textContent = 'Evaluating sufficiency...';
            evalState.style.fill = 'var(--running)';
        }} else {{
            evalState.textContent = 'sufficient=True';
            evalState.style.fill = 'var(--completed)';
        }}
    }}

    // 3. Edges states
    updateEdges(prefix, timeVal, spans);
}}

function updateEdges(prefix, timeVal, spans) {{
    const getSpan = (name) => spans.find(s => s.name === name) || {{ start: 9999, end: 9999 }};
    
    const news = getSpan('agent_news');
    const sentiment = getSpan('agent_sentiment');
    const filings = getSpan('agent_filings');
    const joinName = prefix === 'std' ? 'standard_join' : 'evaluator';
    const join = getSpan(joinName);
    const synth = getSpan('synthesizer');
    
    // Edges start -> agents
    toggleEdge(`${{prefix}}-edge-start-news`, timeVal > 0, timeVal >= news.start, 'completed');
    toggleEdge(`${{prefix}}-edge-start-sentiment`, timeVal > 0, timeVal >= sentiment.start, 'completed');
    toggleEdge(`${{prefix}}-edge-start-filings`, timeVal > 0, timeVal >= filings.start, 'completed');
    
    // Edges agents -> join
    toggleEdge(`${{prefix}}-edge-news-join`, timeVal >= news.end, timeVal >= join.start, 'completed');
    toggleEdge(`${{prefix}}-edge-sentiment-join`, timeVal >= sentiment.end, timeVal >= join.start, 'completed');
    
    if (prefix === 'std') {{
        toggleEdge(`${{prefix}}-edge-filings-join`, timeVal >= filings.end, timeVal >= join.start, 'completed');
    }} else {{
        // Blackboard edge to join: green if completed, red dash if cancelled
        if (filings.status === 'cancelled' && timeVal >= filings.end) {{
            toggleEdge(`${{prefix}}-edge-filings-join`, true, true, 'cancelled');
        }} else {{
            toggleEdge(`${{prefix}}-edge-filings-join`, timeVal >= filings.end, timeVal >= join.start, 'completed');
        }}
    }}
    
    // Join to Synth
    toggleEdge(`${{prefix}}-edge-join-synth`, timeVal >= join.end, timeVal >= synth.start, 'completed');
    // Synth to End
    toggleEdge(`${{prefix}}-edge-synth-end`, timeVal >= synth.end, timeVal >= synth.end, 'completed');
}}

function toggleEdge(edgeId, isRunning, isCompleted, type) {{
    const el = document.getElementById(edgeId);
    if (!el) return;
    
    if (isCompleted) {{
        el.setAttribute('class', `edge-line ${{type}}-edge`);
    }} else if (isRunning) {{
        el.setAttribute('class', 'edge-line active-edge');
    }} else {{
        el.setAttribute('class', 'edge-line');
    }}
}}

function updateGanttBars(spans, prefix, elapsed, timeVal) {{
    spans.forEach(span => {{
        const bar = document.getElementById(`${{prefix}}-bar-${{span.name}}`);
        if (!bar) return;
        
        if (timeVal < span.start) {{
            bar.style.width = '0%';
            bar.style.left = '0%';
            bar.textContent = '';
        }} else {{
            const left = (span.start / maxDuration) * 100;
            const currentEnd = Math.min(timeVal, span.end);
            const width = ((currentEnd - span.start) / maxDuration) * 100;
            
            bar.style.left = left + '%';
            bar.style.width = Math.max(0.5, width) + '%';
            
            let barClass = 'gantt-bar ';
            if (span.status === 'cancelled') barClass += 'cancelled';
            else if (span.category === 'evaluator') barClass += 'evaluator';
            else if (span.category === 'synthesizer') barClass += 'synthesizer';
            else if (span.category === 'workflow') barClass += 'workflow';
            else barClass += 'agent';
            bar.className = barClass;
            
            if (currentEnd > span.start + 0.3) {{
                bar.textContent = (currentEnd - span.start).toFixed(1) + 's';
            }} else {{
                bar.textContent = '';
            }}
        }}
    }});
}}

function updateConsoleLog(timeVal) {{
    consoleDiv.innerHTML = '';
    
    const combinedEvents = [];
    stdEvents.forEach(e => combinedEvents.push({{ ...e, flow: 'Standard' }}));
    bbEvents.forEach(e => combinedEvents.push({{ ...e, flow: 'Ours (BB)' }}));
    
    combinedEvents.sort((a, b) => a.time - b.time);
    
    combinedEvents.forEach(ev => {{
        if (ev.time <= timeVal) {{
            const line = document.createElement('div');
            line.className = 'console-line';
            
            const timeSpan = document.createElement('span');
            timeSpan.className = 'console-time';
            timeSpan.textContent = `[${{ev.flow}} - ${{ev.time.toFixed(2)}}s]`;
            
            const nameSpan = document.createElement('span');
            nameSpan.className = 'console-name';
            nameSpan.textContent = labels[ev.name] || ev.name;
            
            const actionSpan = document.createElement('span');
            let isCancelled = ev.status === 'cancelled';
            actionSpan.className = 'console-status' + (isCancelled ? ' cancelled' : '');
            
            let actionText = ev.type === 'start' ? 'started' : 'completed';
            if (ev.status === 'cancelled') actionText = 'cancelled (early-exit)';
            if (ev.type === 'decision') actionText = `evaluator decided: sufficient=${{ev.sufficient}}`;
            actionSpan.textContent = actionText;
            
            line.appendChild(timeSpan);
            line.appendChild(nameSpan);
            line.appendChild(actionSpan);
            consoleDiv.appendChild(line);
        }}
    }});
    
    // Auto scroll console to bottom
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}}

// Simulator Loop Controls
function play() {{
    if (currentTime >= maxDuration) currentTime = 0;
    isPlaying = true;
    playBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <rect x="6" y="4" width="4" height="16" fill="currentColor"/>
            <rect x="14" y="4" width="4" height="16" fill="currentColor"/>
        </svg>
        <span>Pause</span>
    `;
    
    simInterval = setInterval(() => {{
        currentTime += 0.1;
        if (currentTime >= maxDuration) {{
            currentTime = maxDuration;
            pause();
        }}
        updateUI(currentTime);
    }}, 50);
}}

function pause() {{
    isPlaying = false;
    clearInterval(simInterval);
    playBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polygon points="5 3 19 12 5 21 5 3" fill="currentColor"/>
        </svg>
        <span>Play Simulation</span>
    `;
}}

playBtn.addEventListener('click', () => {{
    if (isPlaying) pause();
    else play();
}});

resetBtn.addEventListener('click', () => {{
    pause();
    updateUI(0);
}});

timeSlider.addEventListener('input', (e) => {{
    pause();
    updateUI(e.target.value);
}});

// Initialize
updateUI(0);
play();

</script>
</body>
</html>"""

    Path(output_path).write_text(html)
    return output_path


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    print(header('WORKFLOW EXECUTION VISUALIZATION'))
    print(f'{BOLD}  Running instrumented workflows side-by-side...{RESET}')
    print(f'  {DIM}Capturing precise timing data for both pipelines.{RESET}\n')

    # 1. Run Standard Workflow (WaitAll Join)
    print(f'  {YELLOW}▶ Running Standard Workflow (WaitAll Join)...{RESET}')
    standard_elapsed = await run_instrumented(standard_workflow, 'standard')
    standard_events = list(timeline_events)
    enrich_timeline_events(standard_events, standard_elapsed, is_blackboard=False)
    print(f'    {GREEN}✓ Completed in {standard_elapsed:.1f}s{RESET}\n')

    # 2. Run Blackboard Workflow (Sufficient Early-Exit)
    print(f'  {CYAN}▶ Running Blackboard Workflow (Sufficient Early-Exit)...{RESET}')
    blackboard_elapsed = await run_instrumented(blackboard_workflow, 'blackboard')
    blackboard_events = list(timeline_events)
    enrich_timeline_events(blackboard_events, blackboard_elapsed, is_blackboard=True)
    print(f'    {GREEN}✓ Completed in {blackboard_elapsed:.1f}s{RESET}\n')

    # Print ASCII timeline
    print_ascii_timeline(blackboard_events, blackboard_elapsed)

    # Print event log
    print(subheader('EVENT LOG'))
    for ev in blackboard_events:
        t = ev['time']
        name = ev['name']
        etype = ev['type']
        status = ev.get('status', '')
        extra = ''
        if 'sufficient' in ev:
            extra = f' sufficient={ev["sufficient"]}'
        color = GREEN if status == 'completed' else RED if status == 'cancelled' else CYAN if ev.get('category') == 'evaluator' else DIM
        print(f'  {color}{t:6.2f}s{RESET}  {name:<20} {etype:<10} {status}{extra}')

    # Generate HTML
    print(subheader('GENERATING HTML VISUALIZATION'))
    output_dir = Path(__file__).resolve().parent / 'output'
    output_dir.mkdir(exist_ok=True)
    html_path = str(output_dir / 'timeline.html')
    generate_html(standard_events, standard_elapsed, blackboard_events, blackboard_elapsed, html_path)
    print(f'  {GREEN}✓{RESET} Saved to: {html_path}')
    print(f'  {DIM}Opening in browser...{RESET}\n')

    webbrowser.open(f'file://{html_path}')


if __name__ == '__main__':
    asyncio.run(main())
