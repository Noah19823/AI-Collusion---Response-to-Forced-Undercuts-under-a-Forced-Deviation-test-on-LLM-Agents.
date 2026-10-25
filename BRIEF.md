# Calling the Bluff

Do forced-deviation audits of LLM pricing agents miss punishment that comes slowly?

Apart Research AI Collusion Research Sprint, October 23 to 25, 2026. Tracks 1 and 2.

## Abstract (draft, brackets filled after runs)

A cartel holds only if a member who cheats gets punished, so recent audits of LLM pricing agents force one agent to cut its price in a cloned market and compare the rival's response with an undeviated copy. These audits read the response one period after the cut. LLM agents adjust prices slowly, and an agent that punishes slowly barely moves in that first period. Using scripted agents with known strategies, we show that the one-period test classifies every punisher with stickiness of 0.5 or more as a non-punisher. A corrected measure, which compares the rival with a sticky agent that does not punish, classifies every scripted agent correctly. Re-auditing Claude Haiku 4.5 under the Fish et al. protocol across [12] runs and [48] forks, we estimate stickiness at [rho] and find that the two measures [agree / disagree]: [result, with interval]. Audits should account for how fast agents move before calling them non-punishers.

## The idea

If two LLM pricing agents keep prices high, that alone does not mean they collude. Prices can end up high for other reasons. What makes it collusion is that cheating gets punished. So the right test is to make one agent cheat and see whether the other hits back harder than plain profit-seeking would.

Tran and Yu (2026) built that test for LLM agents. They clone a market, force one agent to cut for one period, and compare the rival's price one period later against the copy where nothing happened. By their test most prompted LLMs do not punish, and only GPT-5.2 does.

Our question is about the test itself. LLM agents tend to be sticky and move only part of the way each period. A sticky agent that fully means to punish a cut might barely move in the first period. A test that only looks one period out would call it a non-punisher. Tran and Yu name this as a limit of their test ("a strategy that punishes only persistent or large deviations would escape"), but nobody has measured how much it matters or fixed it.

## What we do

**Part 1. Does the one-period test see slow punishers?** We build scripted agents with known stickiness (rho from 0 to 0.92) and known punishment (none, or 0.05 or 0.10 below their profit-seeking price for 10 periods), and run them through the same fork-and-compare pipeline. We compare three measures: the one-period test, a static sum over 15 periods, and our dynamic baseline, which compares the rival to a sticky agent that sees the same prices and never punishes.

We already ran this without noise. The one-period test only catches the punisher that moves all at once. At rho = 0.5 a punisher scores +0.001, and at rho = 0.92 it scores +0.086. Both read as no punishment. The static sum works for a brief cut but breaks when the cut persists. The dynamic baseline gets every case right. This part costs nothing to run and is a result whatever happens with the LLM runs.

**Part 2. Re-audit a real LLM.** We run Claude Haiku 4.5, a provider Tran and Yu did not test, under the Fish et al. protocol with written plans. 12 independent runs, 4 forks each. At each fork there is a cut copy and a sham copy, plus a second sham on 12 forks to measure how much copies drift on their own, and a forced price raise on 12 forks to check the agent is reacting to cuts specifically and not to any change. We estimate the model's stickiness from the base runs before any fork, then report all three measures on the same forks. That way our numbers line up with Tran and Yu's and we can see whether the verdict changes.

**Deterrence.** We check whether cheating lost the cutter money, counting from the cut period itself. Then we separate how much of that loss came from the rival's response and how much from the cutter's own pricing afterward, by swapping in the non-punishing baseline for the rival and recomputing. Tran and Yu point out that gains alone do not separate punishers from best responders, and this addresses that.

**Say versus do.** For each fork we check whether the rival wrote a threat before the cut, and whether it punished. With 48 forks this is a descriptive 2 × 2, not a prediction model.

## Why this matters

If audits miss slow punishers, then "prompted LLMs rarely punish" could partly come from how the test is built, and a regulator using it would under-detect collusion. If the corrected measure agrees with the one-period test on a real model, Tran and Yu's finding holds for a new provider and a stricter test, which is also worth knowing. Either way, anyone running these audits learns what they need to measure first.

## Why this is ours

The forking audit is Tran and Yu's, and we say so up front. So are the upward deviation, the myopic placebo and reading the agents' plans for matching rules. Their own paper notes that sticky replies can shrink measured responses, and it ends by asking for longer horizons and more frontier models. Their verdicts for prompted models rest on the response one period after the cut. What we add is a check on the audit's own reliability, done with agents whose answer we already know, plus a fix that passes that check, plus the first application of it to a non-OpenAI model under the Fish protocol. Arslan et al. handle stickiness in the long run, but on a small model answering with a bare number and with an inconclusive result. Lopes de Moraes and De-Losso question what impulse responses identify, but only for Q-learners. No one has shown the one-period LLM audit misreads sticky punishers, or corrected it and validated the correction.

This follows what the winning sprint papers did. They asked one clear question, tested whether the measuring tool works before trusting it, put a headline number against a known baseline, paired the diagnosis with a fix, and stated their limits plainly. The OWL paper and the Anchored paper both won by showing a method looked right but measured the wrong thing.

## What we report

1. The Part 1 table: for each scripted agent, what each measure says and how often it gets it right.
2. The LLM's estimated stickiness, and all three measures on its forks side by side, with the dynamic measure across a range of rho.
3. Deterrence, total and the part caused by the rival.
4. The threat-by-punishment 2 × 2.
5. Limits: one model, one market, rho has to be estimated and the result depends on it, the copies drift because the API has no seeds, and scripted agents are simpler than LLMs.

## Plan

Tonight: unit tests, scripted agents, the three measures, and the Part 1 table. Then the monopoly pretest and base runs. Saturday night into Sunday: estimate rho, run forks, run the second sham and upward copies, then code the text. Sunday: analysis, the audit script that recomputes every number from the raw logs, and the report. If time runs short we drop the upward copy first, then the text coding, then a fork per run. We never drop the 12 runs, the second sham or Part 1.

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
