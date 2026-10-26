# what PI_dyn can and can't tell you

scripted / math checks only, no llm runs. don't cite as evidence about any model.

short version: PI_dyn < 0 means the rival priced below a sticky best responder. it doesn't tell you *why*.

- a non-punishing agent that forecasts more cuts and prices ahead of them scores PI_dyn < 0 in 27/27 setups we built
- you can always build a forecasting rule that gives the exact same prices as a punishment rule (inverse best response, prices match to ~1e-13 across 32 test cases). so prices alone can't separate the two
- a threshold punisher can make a 10% cut unprofitable while smaller cuts still pay, so one cut size doesn't tell you everything

why it matters: wording in the paper says "below the non-punishing baseline", and the upward control / multiple cut sizes are how you'd start separating punishment from forecasting.

## the math

logit share for firm i:

    s_i = exp((a-p_i)/mu) / [exp(a0/mu) + exp((a-p_i)/mu) + exp((a-p_j)/mu)]

best response condition: (p_i - c)(1 - s_i) = mu

given a target own price p, the rival price that makes p a best response:

    s* = 1 - mu/(p-c)
    E_j = exp((a-p)/mu) * (1/s* - 1) - exp(a0/mu)
    BR_inverse(p) = a - mu*log(E_j)

so a punisher targeting BR(q) - delta looks identical to a non-punisher best-responding to q_hat = BR_inverse(BR(q) - delta).
