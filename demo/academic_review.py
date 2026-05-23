"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEMO: Academic Paper Review — Semantic Early-Exit                            ║
║                                                                              ║
║  A researcher asks: "Is this paper's methodology sound?"                      ║
║  3 agents analyze different sections:                                         ║
║    • agent_abstract (2s)     — reads abstract + conclusion                    ║
║    • agent_citations (4s)    — checks citation validity                       ║
║    • agent_fulltext (25s)    — reads entire 50-page paper (SLOW)              ║
║                                                                              ║
║  Abstract + citations are usually sufficient for a methodology assessment.    ║
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
from google.adk.workflow import SufficientJoinNode
from google.adk.workflow import node

from _common import BOLD
from _common import CYAN
from _common import DIM
from _common import GREEN
from _common import RED
from _common import RESET
from _common import WHITE
from _common import YELLOW
from _common import header
from _common import metrics_table
from _common import run_workflow
from _common import subheader

# ─── Mock Agents ───────────────────────────────────────────────────────────────


@node()
async def agent_abstract(ctx, node_input: str):
    """Abstract + conclusion reader — fast (~2s)."""
    await asyncio.sleep(2)
    yield (
        'Abstract: "We propose a novel transformer architecture for protein'
        ' folding prediction. Our method achieves 94.2% accuracy on CASP15'
        ' benchmark, outperforming AlphaFold2 by 3.1pp."'
        ' Methodology: Supervised learning on 12M protein structures from PDB.'
        ' Train/val/test split: 80/10/10 by protein family to prevent leakage.'
        ' Conclusion: "Results demonstrate generalization across unseen families."'
    )


@node()
async def agent_citations(ctx, node_input: str):
    """Citation validator — moderate (~4s)."""
    await asyncio.sleep(4)
    yield (
        'Citation analysis: 47 references total. 42 verified (published,'
        ' peer-reviewed). 3 are preprints (arXiv, not yet peer-reviewed).'
        ' 2 are self-citations. Key methodological citations (attention'
        ' mechanisms, protein databases) are all from top venues (Nature,'
        ' ICML, NeurIPS). No retracted papers cited. Dataset source (PDB)'
        ' is well-established and appropriate for this domain.'
    )


@node()
async def agent_fulltext(ctx, node_input: str):
    """Full 50-page paper reader — very slow (~25s)."""
    await asyncio.sleep(25)
    yield (
        'Full-text analysis: Section 3.2 describes training procedure in detail.'
        ' Hyperparameter search over 200 configurations. Ablation study in'
        ' Table 4 shows each component contributes. Statistical significance'
        ' tests (paired t-test, p<0.001) reported for all comparisons.'
        ' Appendix B contains full reproducibility checklist.'
    )


# ─── Workflow Definition ───────────────────────────────────────────────────────

QUESTION = (
    'Is the methodology of this protein folding paper sound?'
    ' Check for data leakage, citation quality, and experimental rigor.'
)

synthesizer = Agent(
    name='synthesizer',
    instruction=(
        'You are an academic peer reviewer. You will receive analysis from'
        ' your review team. Write a concise methodology assessment (3-5'
        f' sentences) addressing: "{QUESTION}"'
    ),
)

sufficient_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
)

workflow = Workflow(
    name='academic_review',
    edges=[
        ('START', agent_abstract),
        ('START', agent_citations),
        ('START', agent_fulltext),
        (agent_abstract, sufficient_join),
        (agent_citations, sufficient_join),
        (agent_fulltext, sufficient_join),
        (sufficient_join, synthesizer),
    ],
)

# ─── Run ───────────────────────────────────────────────────────────────────────


async def main():
    print(header('ACADEMIC PAPER REVIEW — Semantic Early-Exit Demo'))

    print(f'{BOLD}  Question:{RESET} {QUESTION[:70]}...')
    print(subheader('Agents'))
    print(f'  {GREEN}●{RESET} agent_abstract    {DIM}(~2s, abstract + conclusion){RESET}')
    print(f'  {GREEN}●{RESET} agent_citations   {DIM}(~4s, citation validation){RESET}')
    print(f'  {RED}●{RESET} agent_fulltext    {DIM}(~25s, full paper — STALLER){RESET}')
    print(subheader('Execution'))

    result = await run_workflow(workflow, QUESTION, log_events=True)

    print(f'\n  {GREEN}✓{RESET} Peer review assessment:')
    print(f'  {DIM}"{result.final_output[:250]}"{RESET}')

    print(metrics_table(
        standard_time=25.0 + 4.0,
        blackboard_time=result.elapsed,
        cancelled_count=1,
    ))
    print()


if __name__ == '__main__':
    asyncio.run(main())
