# Calling the Bluff

Do forced-deviation audits of LLM pricing agents miss punishment that comes slowly?

Apart Research AI Collusion Research Sprint, October 23 to 25, 2026. Tracks 1 and 2.

## Abstract (draft, brackets get filled after the runs)

A cartel holds only if a member who cheats gets punished. Because of this, recent audits of LLM pricing agents force one agent to cut its price in a cloned market and compare the rival's response with a copy where no cut happened. These audits look at the rival's price one period after the cut. LLM agents usually change their prices a little at a time, so an agent that punishes slowly hardly moves in that first period. We built scripted agents with known strategies and ran them through the test. The one-period test labels every punisher with stickiness of 0.5 or more as a non-punisher. We then compare the rival with a sticky agent that does not punish, and this labels every scripted agent correctly. We re-audit Claude Haiku 4.5 under the Fish et al. protocol across [12] runs and [48] forks, estimate its stickiness at [rho], and find that the two measures [agree / disagree]: [result, with interval]. Audits need to account for how fast agents change prices before calling them non-punishers.

## The idea

Two LLM pricing agents keeping prices high does not on its own mean they are colluding, since prices can end up high for other reasons. In economics, collusion means a firm that cheats gets punished by the others. So to test for it, you make one agent cheat and see whether the other one cuts its price by more than it would if it was only trying to make money that period.

Tran and Yu (2026) built this test for LLM agents. They copy a running market, force one agent to cut its price for one period in the copy, and compare the rival's price one period later between the copy and the original. Using that test, they found most prompted LLMs do not punish, and GPT-5.2 does.

We want to know if the test can catch an agent that punishes slowly. LLM agents tend to move only part of the way toward a new price each period. If an agent like that decides to punish, it might only move a little in the first period and keep moving after that. A test that only checks one period later would say it is not punishing. Tran and Yu mention this in their limitations ("a strategy that punishes only persistent or large deviations would escape"), and their paper ends by asking for audits over longer horizons. As far as we can find, nobody has measured how much this matters or corrected for it.

## What we do

**Part 1. Can the one-period test see a slow punisher?** We write scripted agents in code. Each one has a set stickiness (rho between 0 and 0.92) and a set amount of punishment (none, 0.05, or 0.10 below its profit-seeking price, for 10 periods). We run them through the same copy-and-compare setup and score them three ways: the one-period test, a plain sum of the gap over 15 periods, and a dynamic baseline. The dynamic baseline works out what a sticky agent that never punishes would have done after seeing the same prices, and compares the real agent to that.

We already ran this without noise. The one-period test only catches the punisher with rho = 0, the one that moves all at once. A punisher with rho = 0.5 scores +0.001 and one with rho = 0.92 scores +0.086, and both of those read as no punishment. The plain sum works when the cut lasts one period but gets it wrong when the cut lasts longer. The dynamic baseline gets every case right. This part costs nothing in API calls and doesn't depend on the LLM runs working.

**Part 2. Re-audit an LLM.** We run Claude Haiku 4.5 under the Fish et al. protocol, which gives agents written plans. Tran and Yu did not test any non-OpenAI model in the pricing game. We do 12 separate runs with 4 forks each. Each fork gets a cut copy and a copy with no cut. On 12 of the forks we also run a second no-cut copy, to measure how much two copies drift apart by chance, and a copy where the price is forced up instead of down, to check whether the agent reacts to any change or to cuts specifically. We estimate the model's stickiness from the runs before forking, and then report all three measures on the same forks, so the numbers can be compared with Tran and Yu's.

**Deterrence.** We also check whether the cut lost the cutter money, counting from the period of the cut. Part of any loss could come from the cutter's own pricing after the cut rather than from the rival, so we recompute the cutter's profit with the rival replaced by the non-punishing baseline and take the difference. Tran and Yu point out that profit gains alone can't separate a punisher from a rival that just best responds, and this is our way of handling that.

**Say versus do.** For each fork we look at whether the rival's notes from right before the cut threaten to punish a cut, and whether it actually punished. With 48 forks this is a 2 × 2 table of counts, not a prediction model.

## Why it matters

If the one-period test misses slow punishers, then part of the finding that prompted LLMs rarely punish could come from how the test is set up, and a regulator using it would catch less collusion than is there. If both measures agree on Haiku, then Tran and Yu's finding holds for another provider under a stricter test. In both cases, people running these audits find out whether they need to measure stickiness first.

## How this relates to what has been done

The forking audit comes from Tran and Yu, and so do the forced price rise, the myopic placebo, and reading agents' plans for rules that match a rival's cut. Their own paper says sticky replies can shrink the responses they measure. Their verdicts for prompted models are based on the response one period after the cut.

Arslan et al. (2026) sum responses over a horizon and handle stickiness in the long run, but they used a small model that answers with only a number, with no reasoning or written plans, and their result was inconclusive. Lopes de Moraes and De-Losso (2026) show that for Q-learners a forced price rise gets the same response as a cut, which is why we run the upward copy.

What we add is a check of whether the one-period LLM audit misreads sticky punishers, a corrected measure that passes that check on scripted agents, and a re-audit of a non-OpenAI model under the Fish protocol using both measures.

## What we will report

1. The Part 1 table, showing what each measure says about each scripted agent and how often it is right.
2. The LLM's estimated stickiness, and the three measures on its forks next to each other, with the dynamic measure shown across a range of rho values.
3. Deterrence, both the total and the part that came from the rival.
4. The threat by punishment 2 × 2.
5. Limitations: one model in one market, the result depends on estimating rho, copies drift because the API has no seed setting, and the scripted agents are simpler than LLMs.

## Plan

Tonight we do the unit tests, the scripted agents, the three measures and the Part 1 table, then the monopoly pretest and base runs. Overnight into Sunday we estimate rho, run the forks and the extra copies, and code the notes. Sunday is analysis, a script that recomputes every number from the raw logs, and the report. If we run out of time, the upward copy goes first, then the note coding, then one fork per run. We keep the 12 runs, the second no-cut copy, and Part 1 no matter what.

## References

- Tran and Yu (2026). Is Anyone Enforcing the Cartel? What Reinforcement Learning Teaches LLM Agents in Markets. arXiv:2610.28787.
- Fish, Gonczarowski and Shorrer (2024, revised 2026). Algorithmic Collusion by Large Language Models. arXiv:2404.00806.
- Calvano, Calzolari, Denicolò and Pastorello (2020). Artificial Intelligence, Algorithmic Pricing, and Collusion. AER 110(10).
- Arslan, Xiao and Kim (2026). Persistent Partners Raise Prices Among Learning Agents. arXiv:2609.35402.
- Lopes de Moraes and De-Losso (2026). Algorithmic Collusion Without Deterrence: Auditing the Punishment Mechanism in Q-Learning Pricing Agents. arXiv:2610.21867.
- Lee and Park (2026). Faithful yet Collusive. Findings of EMNLP 2026.
- Nakamura, Bagdasarian et al. (2026). Colosseum.
- Garra (2026). Mitigating Emergent Collusion in LLM Pricing Agents. arXiv:2609.13037.
- Lambin (2024). Less than meets the eye. SSRN 4498926.
