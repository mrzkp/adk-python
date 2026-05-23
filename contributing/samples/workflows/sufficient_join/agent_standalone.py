"""Standalone version of agent.py for direct script execution (no package context)."""

from __future__ import annotations

from google.adk import Agent
from google.adk import Workflow
from google.adk.workflow import JoinNode
from google.adk.workflow import SufficientJoinNode

from mock_agents import agent_filings
from mock_agents import agent_news
from mock_agents import agent_sentiment

ORIGINAL_QUESTION = "Why is Acme Corp's stock dropping? Summarize what we know."

# Shared synthesizer
synthesizer = Agent(
    name='synthesizer',
    instruction=(
        'You are a financial analyst. You will receive research data collected'
        ' by your team as the user message. Write a concise, well-structured'
        ' briefing (3-5 sentences) that directly answers the question:'
        f' "{ORIGINAL_QUESTION}"'
    ),
)

# Control: standard JoinNode (WaitAll)
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

# Experimental: SufficientJoinNode
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
