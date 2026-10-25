# Exploratory Mechanism-Identification Audit — 25 October 2026

**Status:** Independent, post-preregistration theoretical and offline scripted checks. This document does not amend or claim to replace the locked team protocol. No experiments on Claude, OpenAI or another LLM were conducted here. Results below should NOT be cited as empirical evidence that any model colludes.

## One-paragraph summary

The team's dynamic residual PI_H^dyn successfully isolates an explicitly penalized response from a **particular sticky static-best-response null**. It does not, without further assumptions, identify why the agent moved its price. Three tests make the boundary concrete: (1) a nonpunitive memory-based forecasting rule yields PI_dyn < 0 in 27/27 *deliberately designed* configurations, and an attributed negative profit effect in 27/27; (2) a closed-form inverse-best-response construction produces arbitrarily close responder prices under a punitive policy and an alternative forecast-target policy; (3) a threshold punisher can make a 10% forced cut unprofitable while leaving smaller deviations profitable. This supports more explicit mechanism limits and **predeclared exploratory, multi-magnitude probes**, not a broad claim that collusion is absent or that this discovery is new in the literature.

## 1. Identifying a mechanism from behavior requires structural assumptions

Bertrand–logit demand for firm i:

    s_i(p_i,p_j) = exp((a-p_i)/mu) /
                   [exp(a0/mu) + exp((a-p_i)/mu) + exp((a-p_j)/mu)]

    profit_i = beta (p_i-c) s_i.

With a> a0, mu>0, c>0, the interior static best-response condition is

    (p_i-c) * (1 - s_i(p_i,p_j)) = mu.

For a candidate optimal own price p, set

    s* = 1 - mu/(p-c).
    E_j = exp((a-p)/mu) * (1/s* - 1) - exp(a0/mu).
    BR_inverse(p) = a - mu * log(E_j)

whenever s* is in (0,1) and E_j>0. Hence if a punitive rule computes target BR(q)-delta (and that target is in the reachable range of BR), a *different* policy that computes BR(q_hat) with

    q_hat = BR_inverse(BR(q)-delta)

gets the same numerical target. Applying the same inertia recurrence gives exactly matching prices at every step. Inverse best-response errors were about 1e-12 in numerical tests.

### Executed demonstration

- 4 exogenous rival-price patterns (temporary cut, persistent cut, alternating prices and random prices).
- rho = 0, 0.5, 0.8, 0.92; penalty delta = 0.05, 0.10.
- 32 constructed pairwise program comparisons.
- Maximum difference in generated prices: approximately 9.1e-14.
- Both mechanisms therefore produce the same price-based measures and profits when exposed to identical opponent actions. For a deterministic opponent policy, the equivalence extends recursively to its future choices (subject to ordinary determinism and consistent state).

**Interpretation limit:** The forecast needed for equivalence is *constructed from the other policy*. This is a formal nonidentifiability demonstration, not evidence that the implied forecasts are accurate, reasonable, sincere, or present inside any LLM. Externally verified forecasts, constrained forecast calibration or other discriminating interventions are needed before attributing a specific internal mechanism. Agent-generated explanatory text can be useful, but without faithfulness verification it is not a direct observation of intent. Do not claim that a different subjective belief automatically establishes non-collusive outcomes under every legal or game-theoretic definition; functional deterrence and motivational retaliation are different questions.

## 2. The profit-attribution check is not independent identification

For the same logit market and p_A > c:

    derivative[profit_A(p_A,p_B), p_B]
       = (beta/mu) * (p_A-c) * s_A(p_A,p_B) * s_B(p_A,p_B)
       > 0.

This identity was independently checked by central finite differences at 20 combinations of positive-margin own prices and rival prices.

Whenever the responder's realized price is below the counterfactual reference price *at each tested step*, replacing the realized price with that higher reference necessarily raises the cutter's profit **holding the cutter's price fixed**. So the sign of the direct-profit contrast then follows mathematically from the price residual. Negative PI_dyn accumulated across a horizon does not guarantee a negative direct-profit effect without those pointwise conditions; nevertheless this dependence means the proposed profit contrast cannot independently establish a retaliatory motive.

The forecasting policy in collusion/adversarial.py has **no punishment objective**. In 27 deliberately constructed parameter configurations (rho x memory decay x belief responsiveness):

| Outcome in those 27 simulated cases | Count |
| --- | ---: |
| Negative dynamic price residual after a price cut | 27 / 27 |
| Negative fixed-A-path direct profit contrast for the cutter | 27 / 27 |
| Negative total 15-period profit gain for the cutter | 22 / 27 |
| Positive dynamic residual after a rival price rise | 27 / 27 |

For rho=0.8, decay=0.8, forecast gain=0.75: PI_dyn≈-0.242414, immediate gain≈+0.061580, total gain≈-0.100116, and direct responder contribution≈-0.124068 (beta=1 normalized profit).

This **does not** imply that an unprofitable deviation cannot be functionally deterred by a nonpunitive response. It means the joint signs alone do not identify the hypothesized strategic-punishment mechanism, especially under a misspecified nonpunitive counterfactual.

## 3. One tested deviation magnitude is not a global deterrence test

Scripted threshold defender: baseline p=1.90; rho=0.8; target follows sticky BR; after seeing a **10% or larger** one-period cut, subtracts delta=0.10 from its target for 10 periods. Cutter returns to p=1.90 for the 15 continuation periods; all figures are normalized beta=1 and *undiscounted*. This is a simplified scripted control, **not** the team's actual endogenous two-LLM continuation protocol.

| Temporary forced cut | Immediate gain | 15-period cumulative gain | Trigger |
| --- | ---: | ---: | --- |
| 5.0% | +0.0387 | +0.0207 | No |
| 8.5% | +0.0567 | +0.0251 | No |
| 9.5% | +0.0602 | +0.0245 | No |
| 10.0% | +0.0616 | -0.4357 | Yes |
| 12.0% | +0.0651 | -0.4406 | Yes |
| 20.0% | +0.0438 | -0.4958 | Yes |

A 10% undercut fails, but a smaller cut remains profitable. The largest observed gain over a grid of cuts 0..25% in 0.5% increments is ~+0.02509 at 8.5%. This is not an exact all-history optimal deviation; it is a **one-period deviation size grid** under a defined scripted continuation.

This is not an originality claim. The October 20 Tran–Yu paper itself examines several cut sizes, and Lopes de Moraes–De-Losso (October 15) explicitly compare a standard tested deviation against an optimal response for Q-learners.

## 4. Suggested low-cost exploratory extension to the sprint

Keep the original 10%-cut protocol intact. If there is budget for *additional exploratory evidence*, freeze a small source-fork subset **before inspecting any real-model results**. Compare at least a smaller cut (e.g. 5%) and a larger cut (e.g. 20%) against the same sham source, with full saved checkpoint state and the same 15-period horizon. Allocate roles/seed subsets before launch, count the 12 independent base runs as clusters, and report each cut separately; do not mine the most significant shock size.

The additional 12 intervention branches (two extra shock sizes on six fixed forks) are about 12 x 15 x 2 = 360 further agent model decisions, excluding retries. This is a budgetary illustration, not an execution authorization.

A stronger but more invasive complementary intervention would constrain or externally validate the responder's price forecasts. Merely asserting a future rival-price commitment inside the model prompt changes the information environment, so differences from the original prompt cannot automatically be interpreted as proof of punishment. Elicited PLANS/INSIGHTS likewise do not constitute verified internal beliefs.

## 5. Evidence, limitations, next decision

The reproducible implementation is in:

- collusion/identification_audit.py — inverse BR, 32 equivalences, direct-profit derivative, forecast-induced profit checks and 0.5%-grid shock sweep.
- tests/test_identification_audit.py — executable independent assertions.
- Existing collusion/adversarial.py — forecasting policy family.
- logs/offline_identifiability_* — primitive CSV and checksummed reproducibility record (synthetic only, ignored by Git).

**Claim boundary:** The proposed dynamic measure establishes behavior *relative to the selected restricted null*. It does not identify retaliation uniquely under unrestricted beliefs, nor prove incentive-compatible repeated-game enforcement from one shock magnitude. Positive policy outcomes might still be considered functionally deterrent in some definitions. The authors should use precise, mechanism-sensitive terminology and clearly mark any new controls as exploratory amendments.

**Decision:** ADD AS EXPLORATORY ADVERSARIAL CONTROL; do not rewrite the frozen original protocol, do not assert novelty over the prior literature, and do not launch live-model experiments on the strength of these synthetic tests alone.

### Related research (for context, not independent validation of these results)

- Hieu Tran & Hong Yu, *Is Anyone Enforcing the Cartel? What Reinforcement Learning Teaches LLM Agents in Markets* (20 Oct 2026), https://arxiv.org/abs/2610.28787 — forced-deviation auditing, price-size sensitivity, by-product enforcement.
- Kauê Lopes de Moraes & Rodrigo De-Losso, *Algorithmic Collusion Without Deterrence: Auditing the Punishment Mechanism in Q-Learning Pricing Agents* (15 Oct 2026), https://arxiv.org/abs/2610.21867 — directional perturbations, alternative explanations and profitable optimal deviations.
- Sara Fish, Yannai A. Gonczarowski & Ran I. Shorrer, *Algorithmic Collusion by Large Language Models*, https://arxiv.org/abs/2404.00806 — motivating prompting and economic environment.
