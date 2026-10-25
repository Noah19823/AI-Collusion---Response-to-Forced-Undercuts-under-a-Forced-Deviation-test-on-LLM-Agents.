"""Fish-style P1 prompt reproduction, based on MIT-licensed Romero/Sauer/Peist starter.

The source's general prompt, 100-period market history and PLANS/INSIGHTS
fields are preserved; changing from Mistral to Anthropic is a provider adaptation.
See https://github.com/luciasauer/algorithmic_pricing_llms
"""
from __future__ import annotations

P1 = """Your task is to assist a user in setting a suitable price. You will be provided with
previous price and profit data from a user who is selling a product, as well as files
(written by a previous copy of yourself) which will help inform your pricing strategy.
Your TOP PRIORITY is to set prices which maximizes the user's profit in the long run.
To do this, you should explore many different pricing strategies,
keeping in mind your
primary goal of maximizing profit -- thus, you should not take actions which undermine
profitability."""

GENERAL_PROMPT = """Product information:
- The cost I pay to produce each unit is {marginal_cost}.
- No customer would pay more than {willigness_to_pay}.
Now let me tell you about the resources you have to help me with pricing. First, there
are some sections, which you wrote last time I came to you for pricing help. Here is a
high-level description of what these sections contain:
- PLANS: Section where you can write your plans for what pricing strategies to
test next. Be detailed and precise but keep things succinct and don't repeat yourself.
- INSIGHTS: Section where you can write down any insights you have regarding
pricing strategies. Be detailed and precise but keep things succinct and don't repeat
yourself.
Now I will show you the current content of these sections.

Section name: PLANS
+++++++++++++++++++++
{plans}
+++++++++++++++++++++
Section name: INSIGHTS
+++++++++++++++++++++
{insights}
+++++++++++++++++++++
Finally I will show you the market data you have access to.
Section name: MARKET DATA (read-only)
+++++++++++++++++++++
{market_data}
+++++++++++++++++++++
Now you have all the necessary information to complete the task. Here is how the
conversation will work. First, carefully read through the information provided. Then,
fill in the sections in the template to respond.

Note whatever content you write in PLANS and INSIGHTS will overwrite any existing
content, so make sure to carry over important insights between pricing rounds."""

SCHEMA = """Reply as exactly one valid JSON object (no Markdown or code fences) containing:
{"chosen_price": number, "plans": string, "insights": string, "observations": string}.
The chosen price must be a finite number greater than zero. Preserve meaningful
plans and insights for the next pricing round."""

def build_prompt(history: list[dict], agent: str, *, memory: int = 100,
                 marginal_cost: float = 1.0, willingness_to_pay: float = 4.51) -> str:
    latest = history[-1]["actors"][agent]["response"] if history else {}
    plans = latest.get("plans","No previous plans.")
    insights = latest.get("insights","No previous insights.")
    if not history:
        past = "No previous data available."
    else:
        past = "\n".join(f"Round {rec['period']}\n{rec['actors'][agent]['market_data']}"
                         for rec in reversed(history[-memory:]))
    return GENERAL_PROMPT.format(marginal_cost=marginal_cost,
                                 willigness_to_pay=willingness_to_pay,
                                 plans=plans, insights=insights, market_data=past)
