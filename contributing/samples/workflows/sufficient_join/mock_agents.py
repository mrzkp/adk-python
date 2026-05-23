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

"""Mock research agents with controllable latency for the sufficient_join demo.

Each agent simulates a real-world data source:
  - agent_news:      Fast.  Returns breaking news in ~2 seconds.
  - agent_sentiment: Fast.  Returns social-media sentiment in ~3 seconds.
  - agent_filings:   Slow.  Simulates reading a large SEC PDF (~20 seconds).

The slow agent is the "staller" that the SufficientJoinNode will cancel once
the fast agents return enough data to answer the original question.
"""

from __future__ import annotations

import asyncio

from google.adk.agents.context import Context
from google.adk.workflow import node


@node()
async def agent_news(ctx: Context, node_input: str):
  """Simulates a fast news-scraper agent (~2 s)."""
  await asyncio.sleep(2)
  yield (
      'BREAKING: Acme Corp CEO John Smith unexpectedly resigned yesterday,'
      ' effective immediately. The board cited "irreconcilable strategic'
      ' differences." Three senior VPs departed the same day.'
  )


@node()
async def agent_sentiment(ctx: Context, node_input: str):
  """Simulates a fast social-media sentiment agent (~3 s)."""
  await asyncio.sleep(3)
  yield (
      'Social sentiment: 84% negative across Twitter/Reddit in the past 24 h.'
      ' Top trending tags: #AcmeMeltdown, #CEOResigns, #SellAcme.'
      ' Retail investor forums show a surge in sell orders.'
  )


@node()
async def agent_filings(ctx: Context, node_input: str):
  """Simulates a slow SEC 10-K filing reader (~20 s).

  This agent intentionally stalls to demonstrate the SufficientJoinNode
  cancellation path.  In a real system this latency would come from reading
  a large PDF over a slow API or a rate-limited data provider.
  """
  await asyncio.sleep(20)
  yield (
      'SEC 10-K (FY2025): Revenue declined 38% YoY to $1.2B.'
      ' Net loss of $340M. Significant covenant breach on $800M revolving'
      ' credit facility. Auditors issued a going-concern qualification.'
  )
