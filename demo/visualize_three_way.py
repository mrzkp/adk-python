"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  VISUALIZER: Three-Way Comparison — Standard / Optimistic / Pessimistic    ║
║                                                                              ║
║  Runs all three workflows with precise instrumentation, then generates an   ║
║  interactive HTML dashboard with:                                            ║
║    • Synchronized Gantt timelines for all three modes                        ║
║    • Play / Pause / Scrub animation                                         ║
║    • Metrics comparison cards                                                ║
║    • Interleaved event console log                                           ║
║                                                                              ║
║  Usage: uv run python demo/visualize_three_way.py                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import JoinNode, SufficientJoinNode, Workflow, node
from google.genai.types import Content, Part

from _common import BOLD, CYAN, DIM, GREEN, MAGENTA, RED, RESET, WHITE, YELLOW, header, subheader

# ─── Global timeline instrumentation ──────────────────────────────────────────

_timeline: list[dict] = []
_t0 = 0.0


def record(name: str, event_type: str, **kwargs):
    _timeline.append({'name': name, 'type': event_type, 'time': time.perf_counter() - _t0, **kwargs})


# ─── Agent factories (each workflow needs its own node instances) ─────────────

def make_agents(prefix: str, filings_delay: float = 15.0):
    @node(name=f'{prefix}_news')
    async def _news(ctx, node_input: str):
        record(f'{prefix}_news', 'start', category='agent')
        await asyncio.sleep(2)
        record(f'{prefix}_news', 'end', category='agent', status='completed')
        yield (
            'BREAKING: Acme Corp CEO John Smith unexpectedly resigned yesterday,'
            ' effective immediately. Three senior VPs departed the same day.'
        )

    @node(name=f'{prefix}_sentiment')
    async def _sentiment(ctx, node_input: str):
        record(f'{prefix}_sentiment', 'start', category='agent')
        await asyncio.sleep(3)
        record(f'{prefix}_sentiment', 'end', category='agent', status='completed')
        yield (
            'Social sentiment: 84% negative across Twitter/Reddit in the past 24h.'
            ' Top trending tags: #AcmeMeltdown, #CEOResigns, #SellAcme.'
        )

    @node(name=f'{prefix}_filings')
    async def _filings(ctx, node_input: str):
        record(f'{prefix}_filings', 'start', category='agent')
        try:
            await asyncio.sleep(filings_delay)
            record(f'{prefix}_filings', 'end', category='agent', status='completed')
            yield (
                'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
                ' Net loss of $340M. Going-concern qualification.'
            )
        except asyncio.CancelledError:
            record(f'{prefix}_filings', 'end', category='agent', status='cancelled')
            raise

    return _news, _sentiment, _filings


QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."


def make_synthesizer(name: str) -> Agent:
    return Agent(
        name=name,
        model='gemini-2.5-flash',
        instruction=(
            'You are a financial analyst. Write a concise briefing (3-5 sentences)'
            f' answering: "{QUESTION}" based on the data provided.'
        ),
    )


# ─── Build three workflows ────────────────────────────────────────────────────

# 1. Standard
s_news, s_sent, s_fil = make_agents('s')
s_join = JoinNode(name='s_join')
s_synth = make_synthesizer('s_synthesizer')
standard_wf = Workflow(
    name='standard',
    edges=[
        ('START', s_news), ('START', s_sent), ('START', s_fil),
        (s_news, s_join), (s_sent, s_join), (s_fil, s_join),
        (s_join, s_synth),
    ],
)

# 2. Optimistic
o_news, o_sent, o_fil = make_agents('o')
o_join = SufficientJoinNode(
    name='o_join', original_question=QUESTION,
    evaluator_model='gemini-2.5-flash', min_predecessors=2, strategy='optimistic',
)
o_synth = make_synthesizer('o_synthesizer')
optimistic_wf = Workflow(
    name='optimistic',
    edges=[
        ('START', o_news), ('START', o_sent), ('START', o_fil),
        (o_news, o_join), (o_sent, o_join), (o_fil, o_join),
        (o_join, o_synth),
    ],
)

# 3. Pessimistic
p_news, p_sent, p_fil = make_agents('p')
p_join = SufficientJoinNode(
    name='p_join', original_question=QUESTION,
    evaluator_model='gemini-2.5-flash', min_predecessors=2, strategy='pessimistic',
)
p_synth = make_synthesizer('p_synthesizer')
pessimistic_wf = Workflow(
    name='pessimistic',
    edges=[
        ('START', p_news), ('START', p_sent), ('START', p_fil),
        (p_news, p_join), (p_sent, p_join), (p_fil, p_join),
        (p_join, p_synth),
    ],
)


# ─── Instrumented runner ─────────────────────────────────────────────────────


@dataclass
class RunResult:
    label: str
    elapsed: float = 0.0
    events: list[dict] = field(default_factory=list)
    synth_outputs: list[tuple[float, str]] = field(default_factory=list)
    reconciliation_action: str = ''


async def run_instrumented(workflow: Workflow, label: str, prefix: str) -> RunResult:
    global _t0
    _timeline.clear()
    _t0 = time.perf_counter()
    record('workflow', 'start', category='workflow', label=label)

    session_service = InMemorySessionService()
    runner = Runner(agent=workflow, app_name='viz3', session_service=session_service)
    session = await session_service.create_session(app_name='viz3', user_id='u')
    user_content = Content(role='user', parts=[Part(text=QUESTION)])

    result = RunResult(label=label)

    async for event in runner.run_async(
        user_id='u', session_id=session.id, new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if not part.text:
                    continue
                if 'SufficientJoin' in part.text:
                    sufficient = 'sufficient=True' in part.text
                    record('evaluator', 'decision', category='evaluator', sufficient=sufficient)
                if 'Reconciliation' in part.text and 'action=' in part.text:
                    action = 'merge' if 'action=merge' in part.text else 'contradict'
                    severity = 'low'
                    for s in ('low', 'medium', 'high'):
                        if f'severity={s}' in part.text:
                            severity = s
                    record('reconciler', 'decision', category='reconciler', action=action, severity=severity)
                    result.reconciliation_action = action
                if event.author and 'synthesizer' in event.author:
                    t = time.perf_counter() - _t0
                    record('synthesizer', 'output', category='synthesizer', time_at=t)
                    result.synth_outputs.append((t, part.text[:200]))

    result.elapsed = time.perf_counter() - _t0
    record('workflow', 'end', category='workflow')
    result.events = list(_timeline)
    return result


# ─── Span builder ─────────────────────────────────────────────────────────────


def build_spans(events: list[dict], total: float, prefix: str) -> list[dict]:
    """Convert raw events to span objects for the Gantt chart."""
    spans: dict[str, dict] = {}

    # Normalize names: strip prefix for display
    def display(name: str) -> str:
        return name.replace(f'{prefix}_', '')

    for ev in events:
        raw = ev['name']
        name = display(raw)
        if ev['type'] == 'start':
            spans[name] = {
                'name': name, 'start': ev['time'], 'end': total,
                'status': 'running', 'category': ev.get('category', ''),
            }
        elif ev['type'] == 'end':
            if name in spans:
                spans[name]['end'] = ev['time']
                spans[name]['status'] = ev.get('status', 'completed')
        elif ev['type'] == 'decision' and ev.get('category') == 'evaluator':
            key = 'evaluator'
            if key in spans:
                key = 'evaluator2'
            spans[key] = {
                'name': key, 'start': ev['time'] - 0.5, 'end': ev['time'],
                'status': 'decision', 'category': 'evaluator',
                'label': f'sufficient={ev.get("sufficient", "?")}',
            }
        elif ev['type'] == 'decision' and ev.get('category') == 'reconciler':
            spans['reconciler'] = {
                'name': 'reconciler', 'start': ev['time'] - 0.5, 'end': ev['time'],
                'status': 'decision', 'category': 'reconciler',
                'label': f'action={ev.get("action", "?")}',
            }

    # Enrich: add synthesizer spans from output events
    synth_outputs = [e for e in events if e['type'] == 'output' and e.get('category') == 'synthesizer']
    if synth_outputs:
        # First synthesizer run
        eval_end = next((s['end'] for s in spans.values() if s['category'] == 'evaluator'), None)
        if eval_end and 'synthesizer' not in spans:
            spans['synthesizer'] = {
                'name': 'synthesizer', 'start': eval_end + 0.1, 'end': synth_outputs[0]['time'],
                'status': 'completed', 'category': 'synthesizer',
            }
        # Second synthesizer run (pessimistic reconciliation)
        if len(synth_outputs) >= 2 and 'reconciler' in spans:
            recon_end = spans['reconciler']['end']
            spans['synthesizer_v2'] = {
                'name': 'synthesizer_v2', 'start': recon_end + 0.1, 'end': synth_outputs[-1]['time'],
                'status': 'completed', 'category': 'synthesizer',
            }

    # For standard workflow: add join span
    if prefix == 's':
        agent_ends = [s['end'] for s in spans.values() if s['category'] == 'agent' and s['status'] == 'completed']
        if agent_ends:
            max_end = max(agent_ends)
            spans.setdefault('join', {
                'name': 'join', 'start': max_end, 'end': max_end + 0.1,
                'status': 'completed', 'category': 'join',
            })
            if 'synthesizer' not in spans:
                spans['synthesizer'] = {
                    'name': 'synthesizer', 'start': max_end + 0.2, 'end': total - 0.1,
                    'status': 'completed', 'category': 'synthesizer',
                }

    return list(spans.values())


# ─── HTML Generation ──────────────────────────────────────────────────────────


def generate_html(
    std: RunResult, opt: RunResult, pes: RunResult,
    std_spans: list, opt_spans: list, pes_spans: list,
    output_path: str,
):
    max_dur = max(std.elapsed, opt.elapsed, pes.elapsed)
    pes_first = pes.synth_outputs[0][0] if pes.synth_outputs else pes.elapsed

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Three-Way Workflow Comparison Visualizer</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #f4f5f7; --card: #fff; --border: #d1d5db; --text: #1f2937;
  --dim: #6b7280; --blue: #2563eb; --blue-lt: #dbeafe; --green: #059669;
  --green-lt: #d1fae5; --red: #dc2626; --red-lt: #fee2e2; --purple: #7c3aed;
  --purple-lt: #ede9fe; --orange: #d97706; --orange-lt: #fef3c7;
  --gray: #9ca3af; --gray-lt: #e5e7eb;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Inter',system-ui,sans-serif; background:var(--bg); color:var(--text); padding:20px 24px; font-size:13px; }}
h1 {{ font-size:18px; font-weight:700; margin-bottom:2px; }}
.sub {{ font-size:11px; color:var(--dim); margin-bottom:16px; }}

/* Controls */
.controls {{ background:var(--card); border:1px solid var(--border); padding:8px 14px;
  display:flex; align-items:center; gap:10px; margin-bottom:16px; border-radius:6px; }}
.btn {{ border:1px solid var(--border); padding:5px 12px; cursor:pointer;
  font-family:inherit; font-size:11px; font-weight:600; border-radius:4px;
  display:inline-flex; align-items:center; gap:5px; }}
.btn-play {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
.btn-play:hover {{ background:#1d4ed8; }}
.btn-sec {{ background:var(--card); color:var(--text); }}
.btn-sec:hover {{ background:var(--gray-lt); }}
.slider-wrap {{ flex:1; display:flex; align-items:center; gap:8px; }}
.slider {{ width:100%; -webkit-appearance:none; background:var(--gray-lt); height:4px;
  outline:none; cursor:pointer; border-radius:2px; }}
.slider::-webkit-slider-thumb {{ -webkit-appearance:none; width:14px; height:14px;
  background:var(--blue); border-radius:50%; cursor:pointer; }}
.clock {{ font-family:'JetBrains Mono',monospace; font-size:13px; font-weight:600;
  min-width:55px; text-align:right; }}

/* Metrics */
.metrics {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-bottom:16px; }}
.metric {{ background:var(--card); border:1px solid var(--border); border-radius:6px;
  padding:12px; text-align:center; }}
.metric .val {{ font-size:20px; font-weight:700; margin-bottom:2px; }}
.metric .desc {{ font-size:10px; color:var(--dim); }}
.val-blue {{ color:var(--blue); }} .val-green {{ color:var(--green); }}
.val-red {{ color:var(--red); }} .val-purple {{ color:var(--purple); }}

/* Three columns */
.panels {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; margin-bottom:16px; }}
@media (max-width:1100px) {{ .panels {{ grid-template-columns:1fr; }} }}
.panel {{ background:var(--card); border:1px solid var(--border); border-radius:6px;
  padding:16px; overflow:hidden; }}
.panel.std {{ border-top:3px solid var(--gray); }}
.panel.opt {{ border-top:3px solid var(--blue); }}
.panel.pes {{ border-top:3px solid var(--purple); }}
.panel-head {{ display:flex; justify-content:space-between; align-items:center;
  margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--gray-lt); }}
.panel-title {{ font-size:13px; font-weight:700; }}
.badge {{ font-size:9px; font-weight:600; padding:2px 7px; border-radius:3px;
  text-transform:uppercase; letter-spacing:.3px; }}
.badge-gray {{ background:#f3f4f6; color:var(--dim); border:1px solid var(--gray-lt); }}
.badge-blue {{ background:var(--blue-lt); color:var(--blue); border:1px solid #93c5fd; }}
.badge-purple {{ background:var(--purple-lt); color:var(--purple); border:1px solid #c4b5fd; }}

/* Gantt */
.gantt-row {{ display:flex; align-items:center; margin-bottom:3px; height:22px; }}
.gantt-lbl {{ width:90px; font-size:10px; color:var(--dim); font-weight:500;
  text-align:right; padding-right:8px; flex-shrink:0; white-space:nowrap; overflow:hidden; }}
.gantt-track {{ flex:1; position:relative; height:18px; background:#f9fafb;
  border:1px solid var(--gray-lt); border-radius:2px; overflow:hidden; }}
.gantt-bar {{ position:absolute; height:100%; display:flex; align-items:center;
  padding-left:5px; font-size:8px; color:#fff; font-weight:500; white-space:nowrap;
  border-radius:1px; transition:width .05s linear, left .05s linear; }}
.bar-agent {{ background:var(--blue); }}
.bar-cancelled {{ background:var(--gray); opacity:.6; }}
.bar-evaluator {{ background:var(--orange); }}
.bar-reconciler {{ background:var(--purple); }}
.bar-synthesizer {{ background:#1e40af; }}
.bar-join {{ background:var(--gray); }}
.bar-workflow {{ background:var(--gray-lt); border:1px dashed var(--gray); color:var(--dim); }}

/* Phase markers */
.phase-marker {{ position:absolute; top:0; height:100%; border-left:2px dashed;
  z-index:2; pointer-events:none; }}
.phase-marker .phase-label {{ position:absolute; top:-14px; left:2px;
  font-size:8px; font-weight:600; white-space:nowrap; }}

/* Console */
.console-card {{ background:var(--card); border:1px solid var(--border); border-radius:6px;
  padding:12px; }}
.console {{ background:#f9fafb; border:1px solid var(--gray-lt); border-radius:4px;
  padding:8px 10px; font-family:'JetBrains Mono',monospace; font-size:10px;
  color:var(--dim); max-height:200px; overflow-y:auto; }}
.console-line {{ display:flex; gap:10px; line-height:1.7; }}
.c-time {{ color:var(--blue); font-size:9px; min-width:100px; }}
.c-name {{ color:var(--text); font-weight:500; min-width:100px; }}
.c-status {{ color:var(--blue); }}
.c-status.cancelled {{ color:var(--red); }}
.c-status.reconciler {{ color:var(--purple); }}

/* Tooltip */
.tooltip {{ position:fixed; background:#fff; border:1px solid var(--border);
  border-radius:6px; padding:10px 12px; font-size:11px; pointer-events:none;
  opacity:0; z-index:1000; box-shadow:0 4px 12px rgba(0,0,0,.1);
  max-width:280px; transition:opacity .15s; }}
.tooltip.vis {{ opacity:1; }}
.tt-title {{ font-weight:700; color:var(--blue); margin-bottom:3px; }}
.tt-row {{ color:var(--dim); font-size:10px; line-height:1.5; }}
.tt-row strong {{ color:var(--text); }}
</style>
</head>
<body>

<h1>Three-Way Workflow Comparison</h1>
<p class="sub">Standard (WaitAll) vs Optimistic (Cancel Stragglers) vs Pessimistic (Speculate + Reconcile) &middot; Interactive timeline</p>

<div class="controls">
  <button id="playBtn" class="btn btn-play">&#9654; Play</button>
  <button id="resetBtn" class="btn btn-sec">&#8635; Reset</button>
  <div class="slider-wrap">
    <input type="range" id="slider" class="slider" min="0" max="{max_dur:.2f}" step="0.05" value="0">
  </div>
  <div id="clock" class="clock">0.0s</div>
</div>

<div class="metrics">
  <div class="metric"><div class="val val-red">{std.elapsed:.1f}s</div><div class="desc">Standard Time</div></div>
  <div class="metric"><div class="val val-blue">{opt.elapsed:.1f}s</div><div class="desc">Optimistic Time</div></div>
  <div class="metric"><div class="val val-purple">{pes.elapsed:.1f}s</div><div class="desc">Pessimistic Time</div></div>
  <div class="metric"><div class="val val-green">{pes_first:.1f}s</div><div class="desc">Pessimistic 1st Report</div></div>
  <div class="metric"><div class="val val-blue">{(1 - opt.elapsed/std.elapsed)*100:.0f}%</div><div class="desc">Optimistic Speedup</div></div>
  <div class="metric"><div class="val val-purple">{pes.reconciliation_action.upper() or '—'}</div><div class="desc">Reconciliation</div></div>
</div>

<div class="panels">

  <!-- STANDARD -->
  <div class="panel std">
    <div class="panel-head">
      <span class="panel-title">Standard (WaitAll)</span>
      <span class="badge badge-gray" id="std-status">waiting</span>
    </div>
    <div id="std-gantt"></div>
  </div>

  <!-- OPTIMISTIC -->
  <div class="panel opt">
    <div class="panel-head">
      <span class="panel-title">Optimistic (Cancel)</span>
      <span class="badge badge-blue" id="opt-status">waiting</span>
    </div>
    <div id="opt-gantt"></div>
  </div>

  <!-- PESSIMISTIC -->
  <div class="panel pes">
    <div class="panel-head">
      <span class="panel-title">Pessimistic (Reconcile)</span>
      <span class="badge badge-purple" id="pes-status">waiting</span>
    </div>
    <div id="pes-gantt"></div>
  </div>

</div>

<div class="console-card">
  <div style="font-weight:700;margin-bottom:6px;">Event Log</div>
  <div id="console" class="console"></div>
</div>

<div id="tooltip" class="tooltip"></div>

<script>
const DATA = {{
  std: {{ spans: {json.dumps(std_spans)}, elapsed: {std.elapsed:.4f}, events: {json.dumps(std.events)} }},
  opt: {{ spans: {json.dumps(opt_spans)}, elapsed: {opt.elapsed:.4f}, events: {json.dumps(opt.events)} }},
  pes: {{ spans: {json.dumps(pes_spans)}, elapsed: {pes.elapsed:.4f}, events: {json.dumps(pes.events)} }},
}};
const maxDur = {max_dur:.4f};

const DISPLAY_ORDER = {{
  std: ['news','sentiment','filings','join','synthesizer'],
  opt: ['news','sentiment','filings','evaluator','synthesizer'],
  pes: ['news','sentiment','filings','evaluator','synthesizer','reconciler','synthesizer_v2'],
}};

const LABELS = {{
  news:'News Agent', sentiment:'Sentiment', filings:'Filings (slow)',
  join:'WaitAll Join', evaluator:'Evaluator', synthesizer:'Synthesizer',
  reconciler:'Reconciler', synthesizer_v2:'Synth v2', evaluator2:'Eval v2',
  workflow:'Workflow',
}};

const BAR_CLASS = {{
  agent:'bar-agent', evaluator:'bar-evaluator', reconciler:'bar-reconciler',
  synthesizer:'bar-synthesizer', join:'bar-join', workflow:'bar-workflow',
}};

// Build Gantt rows
function renderGantt(key) {{
  const el = document.getElementById(key+'-gantt');
  el.innerHTML = '';
  const order = DISPLAY_ORDER[key] || [];
  order.forEach(name => {{
    const span = DATA[key].spans.find(s => s.name === name);
    if (!span) return;
    const row = document.createElement('div');
    row.className = 'gantt-row';
    const lbl = document.createElement('div');
    lbl.className = 'gantt-lbl';
    lbl.textContent = LABELS[name] || name;
    row.appendChild(lbl);
    const track = document.createElement('div');
    track.className = 'gantt-track';
    const bar = document.createElement('div');
    bar.id = key+'-bar-'+name;
    bar.className = 'gantt-bar';

    // Tooltip
    bar.addEventListener('mouseenter', (e) => {{
      const tt = document.getElementById('tooltip');
      tt.innerHTML = '<div class="tt-title">'+(LABELS[name]||name)+'</div>'
        +'<div class="tt-row"><strong>Start:</strong> '+span.start.toFixed(2)+'s</div>'
        +'<div class="tt-row"><strong>End:</strong> '+span.end.toFixed(2)+'s</div>'
        +'<div class="tt-row"><strong>Duration:</strong> '+(span.end-span.start).toFixed(2)+'s</div>'
        +'<div class="tt-row"><strong>Status:</strong> '+span.status+'</div>';
      tt.style.left=(e.clientX+12)+'px'; tt.style.top=(e.clientY-40)+'px';
      tt.classList.add('vis');
    }});
    bar.addEventListener('mouseleave', ()=>document.getElementById('tooltip').classList.remove('vis'));
    bar.addEventListener('mousemove', (e)=>{{
      const tt=document.getElementById('tooltip');
      tt.style.left=(e.clientX+12)+'px'; tt.style.top=(e.clientY-40)+'px';
    }});

    track.appendChild(bar);
    row.appendChild(track);
    el.appendChild(row);
  }});
}}
renderGantt('std'); renderGantt('opt'); renderGantt('pes');

// State
let curTime=0, playing=false, interval=null;
const slider=document.getElementById('slider');
const clock=document.getElementById('clock');
const playBtn=document.getElementById('playBtn');
const resetBtn=document.getElementById('resetBtn');
const consoleDv=document.getElementById('console');

function updateUI(t) {{
  curTime=parseFloat(t);
  slider.value=curTime;
  clock.textContent=curTime.toFixed(1)+'s';
  ['std','opt','pes'].forEach(key => {{
    updateGantt(key,curTime);
    updateStatus(key,curTime);
  }});
  updateConsole(curTime);
}}

function updateGantt(key,t) {{
  DATA[key].spans.forEach(span => {{
    const bar=document.getElementById(key+'-bar-'+span.name);
    if(!bar) return;
    if(t < span.start) {{
      bar.style.width='0%'; bar.style.left='0%'; bar.textContent='';
      return;
    }}
    const left=(span.start/maxDur)*100;
    const curEnd=Math.min(t,span.end);
    const width=((curEnd-span.start)/maxDur)*100;
    bar.style.left=left+'%';
    bar.style.width=Math.max(0.4,width)+'%';

    let cls='gantt-bar ';
    if(span.status==='cancelled') cls+='bar-cancelled';
    else cls += (BAR_CLASS[span.category]||'bar-agent');
    bar.className=cls;

    const dur=curEnd-span.start;
    bar.textContent = dur>0.5 ? dur.toFixed(1)+'s' : '';
  }});
}}

function updateStatus(key,t) {{
  const el=document.getElementById(key+'-status');
  const elapsed=DATA[key].elapsed;
  if(t>=elapsed) {{
    el.textContent='completed';
  }} else if(t>0) {{
    el.textContent='running';
  }} else {{
    el.textContent='waiting';
  }}
}}

function updateConsole(t) {{
  consoleDv.innerHTML='';
  const all=[];
  ['std','opt','pes'].forEach(key => {{
    DATA[key].events.forEach(e => all.push({{...e, flow:key}}));
  }});
  all.sort((a,b)=>a.time-b.time);

  const flowLabels = {{ std:'STD', opt:'OPT', pes:'PES' }};
  const flowColors = {{ std:'var(--gray)', opt:'var(--blue)', pes:'var(--purple)' }};

  all.forEach(ev => {{
    if(ev.time>t) return;
    const line=document.createElement('div');
    line.className='console-line';

    const ts=document.createElement('span');
    ts.className='c-time';
    ts.style.color=flowColors[ev.flow];
    ts.textContent='['+flowLabels[ev.flow]+' '+ev.time.toFixed(2)+'s]';

    const nm=document.createElement('span');
    nm.className='c-name';
    nm.textContent=LABELS[ev.name]||ev.name;

    const st=document.createElement('span');
    let action=ev.type==='start'?'started':ev.type==='end'?(ev.status||'completed'):ev.type;
    if(ev.type==='decision' && ev.category==='evaluator') action='sufficient='+ev.sufficient;
    if(ev.type==='decision' && ev.category==='reconciler') action='action='+ev.action+' ('+ev.severity+')';
    if(ev.status==='cancelled') {{ st.className='c-status cancelled'; action='CANCELLED'; }}
    else if(ev.category==='reconciler') {{ st.className='c-status reconciler'; }}
    else {{ st.className='c-status'; }}
    st.textContent=action;

    line.appendChild(ts); line.appendChild(nm); line.appendChild(st);
    consoleDv.appendChild(line);
  }});
  consoleDv.scrollTop=consoleDv.scrollHeight;
}}

function play() {{
  if(curTime>=maxDur) curTime=0;
  playing=true;
  playBtn.innerHTML='&#9646;&#9646; Pause';
  interval=setInterval(()=>{{
    curTime+=0.1;
    if(curTime>=maxDur){{ curTime=maxDur; pause(); }}
    updateUI(curTime);
  }},50);
}}
function pause() {{
  playing=false; clearInterval(interval);
  playBtn.innerHTML='&#9654; Play';
}}
playBtn.addEventListener('click',()=>playing?pause():play());
resetBtn.addEventListener('click',()=>{{ pause(); updateUI(0); }});
slider.addEventListener('input',(e)=>{{ pause(); updateUI(e.target.value); }});

updateUI(0);
play();
</script>
</body>
</html>"""
    Path(output_path).write_text(html)
    return output_path


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    print(header('THREE-WAY VISUALIZATION'))
    print(f'{BOLD}  Running three instrumented workflows...{RESET}\n')

    print(f'  {DIM}1. Standard (WaitAll)...{RESET}', end='', flush=True)
    std = await run_instrumented(standard_wf, 'Standard', 's')
    print(f' {GREEN}✓ {std.elapsed:.1f}s{RESET}')

    print(f'  {DIM}2. Optimistic (Cancel)...{RESET}', end='', flush=True)
    opt = await run_instrumented(optimistic_wf, 'Optimistic', 'o')
    print(f' {GREEN}✓ {opt.elapsed:.1f}s{RESET}')

    print(f'  {DIM}3. Pessimistic (Reconcile)...{RESET}', end='', flush=True)
    pes = await run_instrumented(pessimistic_wf, 'Pessimistic', 'p')
    print(f' {GREEN}✓ {pes.elapsed:.1f}s{RESET}')

    std_spans = build_spans(std.events, std.elapsed, 's')
    opt_spans = build_spans(opt.events, opt.elapsed, 'o')
    pes_spans = build_spans(pes.events, pes.elapsed, 'p')

    output_dir = Path(__file__).resolve().parent / 'output'
    output_dir.mkdir(exist_ok=True)
    html_path = str(output_dir / 'three_way.html')

    generate_html(std, opt, pes, std_spans, opt_spans, pes_spans, html_path)
    print(f'\n  {GREEN}✓{RESET} Saved: {html_path}')
    print(f'  {DIM}Opening in browser...{RESET}\n')
    webbrowser.open(f'file://{html_path}')


if __name__ == '__main__':
    asyncio.run(main())
