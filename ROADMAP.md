# Roadmap — model refinements

Deliberately deferred until the daily pipeline is running reliably. Each item
must be validated the same way as everything else: a walk-forward backtest that
beats the current benchmark of **Brier 0.61262** (the de-vigged market price).
An idea that does not beat that number does not go into the forecast, however
sensible it sounds.

## Done or settled (see MODEL.md for the numbers)

* **Per-club home advantage — tested and rejected.** Fitting it made the model
  worse (0.6415 against 0.6409), even with shrinkage. Kept as a single global
  term. Worth recording because it is an intuitive idea that the data refused.
* **Shot-based ratings — implemented.** A shots-on-target fit is blended with
  the goals fit at 0.4/0.6. A small gain, and dwarfed by staleness.
* **Time-decay half-life — swept.** 365 days is at or near the optimum
  (180 → 0.6427, 730 → 0.6414). No further tuning warranted.
* **Log durability — done, 29 Sep 2026.** The log lives in the artifact's
  database as well as in the page, so publishing can no longer destroy it. See
  PROJECT_STATE.md. This was the highest-priority item on this list and it was
  not a modelling one: an accurate model with no track record is worth less
  than a mediocre one whose record survives.

## Queued

1. **Keep the ratings fresh.** *(by far the largest known lever)*
   The model's gap to the market roughly doubles as ratings age: +0.011 fresh,
   +0.018 at 90-150 days. That is about 24x any structural tweak tested. The
   weekly refit now handles this; the item stays on the list because every
   future change should be judged against it rather than in isolation.

2. **Weather.**
   Adverse conditions — heavy rain, high wind, cold — compress scoring and widen
   uncertainty, which should flatten the probability distribution toward the
   draw rather than shift it toward either side. Needs a forecast source keyed to
   venue and kickoff time. Model it as a variance/total-goals effect, not as an
   advantage to either team, unless the data says otherwise.

3. **Promoted clubs with no league history.**
   Clubs arriving from the National League have no rating at all and currently
   fall back to market-only. A prior based on their non-league record, or on the
   average rating of recently promoted clubs, would be better than nothing.

## Standing principle

The market is the benchmark, not the enemy. The purpose of these refinements is
a model good enough to be worth blending in at all — not to justify a blend
weight that the evidence does not support.
