# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SufficientJoinNode — semantic early-exit join for Workflow fan-in.

Supports two strategies:

* ``optimistic`` ("blind optimism"): cancels remaining predecessors on
  sufficiency.  Fastest possible time-to-result, but discards late data.
* ``pessimistic`` ("pessimistic optimism"): fires the downstream pipeline
  speculatively on sufficiency, but keeps remaining predecessors running.
  When they complete the node is re-triggered and runs a *reconciliation
  evaluator* that classifies the late data as ``merge`` (supplementary) or
  ``contradict`` (invalidating).  The full dataset is then forwarded
  downstream, causing the pipeline to re-execute with complete information.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from typing_extensions import override

from ..agents.context import Context
from ..events.event import Event
from ._base_node import BaseNode


class _SufficiencyVerdict(BaseModel):
  sufficient: bool = Field(
      description=(
          'True if the collected data is semantically sufficient to fully'
          ' answer the original question. False if critical information is'
          ' still missing.'
      )
  )
  reasoning: str = Field(
      description=(
          'One sentence explaining why the data is or is not sufficient.'
      )
  )


class _ReconciliationVerdict(BaseModel):
  action: Literal['merge', 'contradict'] = Field(
      description=(
          "'merge' if the late data supplements the existing data without"
          " contradiction. 'contradict' if it conflicts with or invalidates"
          " the existing data or conclusions drawn from it."
      )
  )
  severity: Literal['low', 'medium', 'high'] = Field(
      description=(
          "Impact magnitude. 'low' = minor addition or cosmetic correction,"
          " 'medium' = notable new information or partial disagreement,"
          " 'high' = fundamental contradiction that invalidates prior"
          ' conclusions.'
      )
  )
  reasoning: str = Field(
      description='One sentence explaining the reconciliation decision.'
  )


class SufficientJoinNode(BaseNode):
  """A join node that fires as soon as collected data is semantically sufficient.

  Unlike ``JoinNode`` (which waits for *all* predecessors), this node is
  triggered after *each* predecessor completion.  On every trigger it runs a
  fast, cheap LLM evaluator that decides whether the accumulated partial data
  is already enough to answer the original question.

  **Optimistic strategy** (default, ``strategy='optimistic'``):

  * If the evaluator returns ``sufficient=True`` the node yields the partial
    results immediately and sets ``ctx.state['_sufficient_exit'] = True``.
    The ``Workflow._run_loop`` detects that flag, cancels every remaining
    pending predecessor task, and continues to the downstream synthesizer.
  * If the evaluator returns ``sufficient=False`` the node produces no output
    (``wait_for_output=True`` keeps it WAITING) and it will be re-triggered
    when the next predecessor completes.

  **Pessimistic strategy** (``strategy='pessimistic'``):

  * On ``sufficient=True`` the node yields partial results (triggering the
    downstream pipeline) but does **not** cancel remaining predecessors.
  * When a straggler completes, the workflow re-triggers this node with the
    full dataset.  The node detects that a speculative output was already
    produced (via session state) and enters *reconciliation mode*: a second
    LLM evaluator classifies the late data as ``merge`` or ``contradict``.
  * The full (or reconciled) data is yielded again, causing the downstream
    pipeline to re-execute with complete information.

  Usage::

      from google.adk.workflow import SufficientJoinNode, Workflow

      join = SufficientJoinNode(
          name='join',
          original_question='Why is Acme Corp stock dropping?',
          evaluator_model='gemini-2.5-flash',
          min_predecessors=2,
          strategy='pessimistic',   # or 'optimistic'
      )

      root = Workflow(
          name='research',
          edges=[
              ('START', agent_news),
              ('START', agent_sentiment),
              ('START', agent_filings),
              (agent_news,      join),
              (agent_sentiment, join),
              (agent_filings,   join),
              (join, synthesizer),
          ],
      )

  Args:
    original_question: The user's original prompt, used as the semantic
      constraint for the evaluator.  The evaluator will not declare
      sufficiency unless this question can be answered with the available
      data.
    evaluator_model: Model name to use for the sufficiency check.  Should be
      a fast/cheap model (e.g. ``'gemini-2.5-flash'``).
    min_predecessors: Minimum number of completed predecessors before the
      evaluator is even called.  Defaults to ``1``.
    strategy: ``'optimistic'`` cancels stragglers on sufficiency.
      ``'pessimistic'`` keeps them running and reconciles late arrivals.
  """

  wait_for_output: bool = Field(default=True, frozen=True)
  rerun_on_resume: bool = Field(default=True, frozen=True)

  original_question: str
  evaluator_model: str = 'gemini-2.5-flash'
  min_predecessors: int = 1
  strategy: Literal['optimistic', 'pessimistic'] = 'optimistic'

  @property
  @override
  def _requires_partial_predecessors(self) -> bool:
    return True

  @property
  @override
  def _requires_all_predecessors(self) -> bool:
    return False

  @override
  def _validate_input_data(self, data: Any) -> Any:
    if self.input_schema and isinstance(data, dict):
      return {
          k: self._validate_schema(v, self.input_schema)
          for k, v in data.items()
      }
    return super()._validate_input_data(data)

  # -------------------------------------------------------------------
  # Main entry point
  # -------------------------------------------------------------------

  @override
  async def _run_impl(
      self,
      *,
      ctx: Context,
      node_input: Any,
  ) -> AsyncGenerator[Any, None]:
    """Called once per predecessor completion with accumulated partial outputs.

    ``node_input`` is a ``dict[str, Any]`` mapping completed predecessor names
    to their outputs.  Nodes that have not yet completed are absent from the
    dict.

    Flow:
      1. If session state contains ``_sufficient_join_speculative_output``,
         this is a *re-trigger* after a speculative completion.  Enter
         reconciliation mode.
      2. Otherwise, run the sufficiency evaluator.  On ``sufficient=True``,
         store speculative output in state and yield.
    """
    if not isinstance(node_input, dict):
      return

    available = {k: v for k, v in node_input.items() if v is not None}

    # --- Reconciliation path (pessimistic, re-triggered after speculative) --
    speculative = ctx.state.get('_sufficient_join_speculative_output')
    if speculative is not None:
      new_agents = {
          k: v for k, v in available.items() if k not in speculative
      }
      if not new_agents:
        yield available
        return

      verdict = await self._run_reconciliation_evaluator(
          ctx, speculative, new_agents
      )
      if verdict:
        yield Event(
            message=(
                f'[Reconciliation] action={verdict.action}'
                f' | severity={verdict.severity}'
                f' | late_agents={list(new_agents.keys())}'
                f' | reason: {verdict.reasoning}'
            )
        )
        ctx.state['_reconciliation_action'] = verdict.action
        ctx.state['_reconciliation_severity'] = verdict.severity
        ctx.state['_reconciliation_reasoning'] = verdict.reasoning
        ctx.state['_reconciliation_late_agents'] = list(new_agents.keys())

      # Update speculative set so further late arrivals diff correctly.
      ctx.state['_sufficient_join_speculative_output'] = dict(available)
      yield available
      return

    # --- First-evaluation path -------------------------------------------
    if len(available) < self.min_predecessors:
      return

    verdict = await self._run_sufficiency_evaluator(ctx, available)
    if verdict is None:
      return

    yield Event(
        message=(
            f'[SufficientJoin] sufficient={verdict.sufficient}'
            f' | reason: {verdict.reasoning}'
            f' | data from: {list(available.keys())}'
        )
    )

    if verdict.sufficient:
      ctx.state['_sufficient_join_speculative_output'] = dict(available)
      ctx.state['_sufficient_data'] = available
      ctx.state['_evaluator_reasoning'] = verdict.reasoning
      ctx.state['_completed_agents'] = list(available.keys())

      if self.strategy == 'optimistic':
        ctx.state['_sufficient_exit'] = True

      yield available

  # -------------------------------------------------------------------
  # Evaluators
  # -------------------------------------------------------------------

  async def _run_sufficiency_evaluator(
      self,
      ctx: Context,
      available: dict[str, Any],
  ) -> _SufficiencyVerdict | None:
    """Run the fast LLM that decides whether partial data is sufficient."""
    partial_data_text = '\n'.join(
        f'[{agent_name}]: {output}'
        for agent_name, output in available.items()
    )

    from ..agents.llm_agent import Agent  # local import — avoids circular dep

    evaluator = Agent(
        name=f'_evaluator_{self.name}',
        model=self.evaluator_model,
        instruction=(
            'You are a sufficiency evaluator. Your ONLY job is to decide'
            ' whether the provided data is enough to fully answer the question'
            ' below.\n'
            'Do NOT do any research. Do NOT add information of your own.\n'
            'Only evaluate what is explicitly given.\n\n'
            f'Original question: {self.original_question}\n\n'
            f'Collected data so far:\n{partial_data_text}'
        ),
        output_schema=_SufficiencyVerdict,
    )

    verdict_output = await ctx.run_node(
        evaluator,
        node_input='Is the collected data sufficient?',
    )
    if verdict_output is None:
      return None
    return _SufficiencyVerdict.model_validate(verdict_output)

  async def _run_reconciliation_evaluator(
      self,
      ctx: Context,
      speculative: dict[str, Any],
      new_agents: dict[str, Any],
  ) -> _ReconciliationVerdict | None:
    """Classify late-arriving data as *merge* or *contradict*."""
    speculative_text = '\n'.join(
        f'[{k}]: {v}' for k, v in speculative.items()
    )
    new_text = '\n'.join(
        f'[{k}]: {v}' for k, v in new_agents.items()
    )

    from ..agents.llm_agent import Agent  # local import — avoids circular dep

    reconciler = Agent(
        name=f'_reconciler_{self.name}',
        model=self.evaluator_model,
        instruction=(
            'You are a data reconciliation evaluator. Your ONLY job is to'
            ' decide whether newly arrived data CONTRADICTS or SUPPLEMENTS'
            ' the data that was already used to produce an answer.\n'
            'Do NOT do any research. Do NOT add information of your own.\n\n'
            f'Original question: {self.original_question}\n\n'
            'Data that was already used to answer the question:\n'
            f'{speculative_text}\n\n'
            'New late-arriving data:\n'
            f'{new_text}\n\n'
            'Evaluate: does the new data fundamentally contradict the'
            ' existing data, or does it merely add to / supplement it?'
        ),
        output_schema=_ReconciliationVerdict,
    )

    result = await ctx.run_node(
        reconciler,
        node_input=(
            'Does the new late-arriving data contradict or supplement the'
            ' existing data?'
        ),
    )
    if result is None:
      return None
    return _ReconciliationVerdict.model_validate(result)
