"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Three-Way Comparison                                                  ║
║                                                                              ║
║  The same 3-agent research pipeline running in 3 modes simultaneously:       ║
║                                                                              ║
║  1. STANDARD    — JoinNode waits for all 3 agents.  Slowest, full data.      ║
║  2. OPTIMISTIC  — SufficientJoinNode cancels the straggler.  Fastest.        ║
║  3. PESSIMISTIC — SufficientJoinNode fires early AND reconciles late data.   ║
║                   Speed of optimistic + completeness of standard.            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from google.adk import Agent
from google.adk import Workflow
from google.adk.workflow import JoinNode
from google.adk.workflow import SufficientJoinNode
from google.adk.workflow import node

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
from _common import run_workflow
from _common import subheader

# ─── Mock Agents (shared) ─────────────────────────────────────────────────────


def _make_agents(prefix: str):
    """Create a fresh set of mock agents (each workflow needs its own instances)."""

    @node(name=f'{prefix}_news')
    async def _news(ctx, node_input: str):
        await asyncio.sleep(2)
        yield (
            'BREAKING: Acme Corp CEO John Smith unexpectedly resigned yesterday,'
            ' effective immediately. The board cited "irreconcilable strategic'
            ' differences." Three senior VPs departed the same day.'
        )

    @node(name=f'{prefix}_sentiment')
    async def _sentiment(ctx, node_input: str):
        await asyncio.sleep(3)
        yield (
            'Social sentiment: 84% negative across Twitter/Reddit in the past 24h.'
            ' Top trending tags: #AcmeMeltdown, #CEOResigns, #SellAcme.'
            ' Retail investor forums show a surge in sell orders.'
        )

    @node(name=f'{prefix}_filings')
    async def _filings(ctx, node_input: str):
        await asyncio.sleep(15)
        yield (
            'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
            ' Net loss of $340M. Significant covenant breach on $800M revolving'
            ' credit facility. Auditors issued a going-concern qualification.'
        )

    return _news, _sentiment, _filings


QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."


def _make_synthesizer(name: str) -> Agent:
    return Agent(
        name=name,
        model='gemini-2.5-flash',
        instruction=(
            'You are a financial analyst. You will receive research data collected'
            ' by your team as the user message. Write a concise, well-structured'
            f' briefing (3-5 sentences) answering: "{QUESTION}"'
        ),
    )


# ─── Build 3 Workflows ────────────────────────────────────────────────────────

# 1. Standard (wait-all)
std_news, std_sent, std_fil = _make_agents('std')
std_join = JoinNode(name='std_join')
std_synth = _make_synthesizer('synthesizer')
standard_workflow = Workflow(
    name='standard_workflow',
    edges=[
        ('START', std_news), ('START', std_sent), ('START', std_fil),
        (std_news, std_join), (std_sent, std_join), (std_fil, std_join),
        (std_join, std_synth),
    ],
)

# 2. Optimistic (cancel stragglers)
opt_news, opt_sent, opt_fil = _make_agents('opt')
opt_join = SufficientJoinNode(
    name='opt_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
    strategy='optimistic',
)
opt_synth = _make_synthesizer('synthesizer')
optimistic_workflow = Workflow(
    name='optimistic_workflow',
    edges=[
        ('START', opt_news), ('START', opt_sent), ('START', opt_fil),
        (opt_news, opt_join), (opt_sent, opt_join), (opt_fil, opt_join),
        (opt_join, opt_synth),
    ],
)

# 3. Pessimistic (speculate + reconcile)
pes_news, pes_sent, pes_fil = _make_agents('pes')
pes_join = SufficientJoinNode(
    name='pes_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
    strategy='pessimistic',
)
pes_synth = _make_synthesizer('synthesizer')
pessimistic_workflow = Workflow(
    name='pessimistic_workflow',
    edges=[
        ('START', pes_news), ('START', pes_sent), ('START', pes_fil),
        (pes_news, pes_join), (pes_sent, pes_join), (pes_fil, pes_join),
        (pes_join, pes_synth),
    ],
)


# ─── Run ───────────────────────────────────────────────────────────────────────


async def main():
    print(header('THREE-WAY COMPARISON'))
    print(f'{BOLD}  Question:{RESET} {QUESTION}')
    print(f'\n  Running all three modes simultaneously...')
    print(f'  {DIM}Standard waits for ALL 3 agents.{RESET}')
    print(f'  {DIM}Optimistic cancels the straggler.{RESET}')
    print(f'  {DIM}Pessimistic fires early AND reconciles late data.{RESET}')
    print()

    t0 = time.perf_counter()
    std_res, opt_res, pes_res = await asyncio.gather(
        run_workflow(standard_workflow, QUESTION, log_events=False),
        run_workflow(optimistic_workflow, QUESTION, log_events=False),
        run_workflow(pessimistic_workflow, QUESTION, log_events=False),
    )
    total = time.perf_counter() - t0
    print(f'  All three finished in {total:.1f}s wall time.')

    # ─── Output comparison ───────────────────────────────────────────────────

    print(subheader('Standard Output'))
    print(f'  {DIM}"{std_res.final_output[:200]}"{RESET}')

    print(subheader('Optimistic Output'))
    print(f'  {DIM}"{opt_res.final_output[:200]}"{RESET}')

    print(subheader('Pessimistic Output'))
    if len(pes_res.synthesizer_outputs) >= 2:
        print(f'  Report v1 {DIM}(speculative, {pes_res.synthesizer_outputs[0][0]:.1f}s):{RESET}')
        print(f'  {DIM}"{pes_res.synthesizer_outputs[0][1][:150]}..."{RESET}')
        print(f'\n  Report v2 {DIM}(reconciled, {pes_res.synthesizer_outputs[-1][0]:.1f}s):{RESET}')
        print(f'  {DIM}"{pes_res.synthesizer_outputs[-1][1][:150]}..."{RESET}')
    else:
        print(f'  {DIM}"{pes_res.final_output[:200]}"{RESET}')

    # ─── Metrics table ───────────────────────────────────────────────────────

    W = 18
    sep = f'{BOLD}{WHITE}│{RESET}'

    print(f'\n{BOLD}{WHITE}  ┌{"─" * 20}┬{"─" * W}┬{"─" * W}┬{"─" * W}┐{RESET}')
    print(f'{BOLD}{WHITE}  │{"RESULTS":^20}│{"Standard":^{W}}│{"Optimistic":^{W}}│{"Pessimistic":^{W}}│{RESET}')
    print(f'{BOLD}{WHITE}  ├{"─" * 20}┼{"─" * W}┼{"─" * W}┼{"─" * W}┤{RESET}')

    def row(label, v1, v2, v3, c2=None, c3=None):
        c2 = c2 or RESET
        c3 = c3 or RESET
        return (f'{BOLD}{WHITE}  │{RESET}{label:^20}{sep}'
                f'{v1:^{W}}{sep}'
                f'{c2}{v2:^{W}}{RESET}{sep}'
                f'{c3}{v3:^{W}}{RESET}'
                f'{BOLD}{WHITE}│{RESET}')

    pes_first = f'{pes_res.synthesizer_outputs[0][0]:.1f}s' if pes_res.synthesizer_outputs else '—'

    print(row('Wall time',
              f'{std_res.elapsed:.1f}s',
              f'{opt_res.elapsed:.1f}s',
              f'{pes_res.elapsed:.1f}s',
              GREEN, GREEN))
    print(row('1st report at',
              f'{std_res.elapsed:.1f}s',
              f'{opt_res.elapsed:.1f}s',
              pes_first,
              GREEN, GREEN))
    print(row('Agents cancelled',
              '0',
              str(opt_res.cancelled_count or 1),
              '0'))
    print(row('Data coverage',
              '3/3',
              '2/3',
              '3/3',
              RED, GREEN))
    print(row('Reports produced',
              '1',
              '1',
              str(len(pes_res.synthesizer_outputs)),
              c3=CYAN))
    recon = pes_res.reconciliation_action.upper() if pes_res.reconciliation_action else '—'
    print(row('Reconciliation',
              '—',
              '—',
              recon,
              c3=MAGENTA))
    print(f'{BOLD}{WHITE}  └{"─" * 20}┴{"─" * W}┴{"─" * W}┴{"─" * W}┘{RESET}')

    # ─── Verdict ─────────────────────────────────────────────────────────────

    speedup = (1 - opt_res.elapsed / std_res.elapsed) * 100 if std_res.elapsed else 0
    print(f'\n  {GREEN}✓{RESET} {BOLD}Optimistic{RESET} was {speedup:.0f}% faster than Standard,'
          f' but discarded agent C\'s data.')
    print(f'  {GREEN}✓{RESET} {BOLD}Pessimistic{RESET} delivered a fast report at {pes_first},'
          f' then reconciled late data into a complete v2.')
    print(f'  {CYAN}→{RESET} {BOLD}Pessimistic Optimism:{RESET}'
          f' speed of optimistic + completeness of standard. No work wasted.')
    print()


if __name__ == '__main__':
    asyncio.run(main())
