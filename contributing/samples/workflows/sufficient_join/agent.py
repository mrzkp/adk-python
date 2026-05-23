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

"""Sufficient-join demo: two workflows running the same research pipeline.

standard_workflow  — uses JoinNode (WaitAll hard barrier, blocks on agent_filings)
blackboard_workflow — uses SufficientJoinNode (fires as soon as data is sufficient)

Both share the same three mock research agents and the same synthesizer.
Run either as root_agent via `adk run` / `adk web`, or import both and run
side-by-side in app.py.
"""

from __future__ import annotations

from typing import Any

from google.adk import Agent
from google.adk import Event
from google.adk import Workflow
from google.adk.workflow import JoinNode
from google.adk.workflow import SufficientJoinNode

from .mock_agents import agent_filings
from .mock_agents import agent_news
from .mock_agents import agent_sentiment

ORIGINAL_QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."

# ---------------------------------------------------------------------------
# Shared synthesizer — receives the aggregated research dict and writes a report
# ---------------------------------------------------------------------------

synthesizer = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. You will receive research data collected'
        ' by your team as the user message. Write a concise, well-structured'
        ' briefing (3-5 sentences) that directly answers the question:'
        f' "{ORIGINAL_QUESTION}"'
    ),
)

# ---------------------------------------------------------------------------
# Control group: standard JoinNode (WaitAll — blocks until ALL agents finish)
# ---------------------------------------------------------------------------

standard_join = JoinNode(name='standard_join')

standard_workflow = Workflow(
    name='standard_workflow',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news,      standard_join),
        (agent_sentiment, standard_join),
        (agent_filings,   standard_join),
        (standard_join,   synthesizer),
    ],
)

# ---------------------------------------------------------------------------
# Experimental group: SufficientJoinNode (fires as soon as data is sufficient)
# ---------------------------------------------------------------------------

sufficient_join = SufficientJoinNode(
    name='sufficient_join',
    original_question=ORIGINAL_QUESTION,
    evaluator_model='gemini-2.5-flash',
    min_predecessors=2,
)

blackboard_workflow = Workflow(
    name='blackboard_workflow',
    edges=[
        ('START', agent_news),
        ('START', agent_sentiment),
        ('START', agent_filings),
        (agent_news,      sufficient_join),
        (agent_sentiment, sufficient_join),
        (agent_filings,   sufficient_join),
        (sufficient_join, synthesizer),
    ],
)

# Default entry point for `adk run / adk web` — change to standard_workflow
# to demo the control group.
root_agent = blackboard_workflow
