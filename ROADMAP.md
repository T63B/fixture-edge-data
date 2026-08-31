# Roadmap — model refinements

Deliberately deferred until the daily pipeline is running reliably. Each item
must be validated the same way as everything else: a walk-forward backtest that
beats the current benchmark of **Brier 0.61262** (the de-vigged market price).
An idea that does not beat that number does not go into the forecast, however
sensible it sounds.

## Queued

1. **Separate home and away scoring ability.**
   The current model gives each club one attack rating and one defence rating,
   with a single global home-advantage term shared by every club. In reality a
   side's ability to score at home can differ materially from its ability to
   score away, and the size of home advantage varies by club (crowd, pitch,
   travel). Fit per-club home and away attack/defence, or a per-club home
   advantage term, with shrinkage toward the league mean to avoid overfitting
   the smaller samples in League One and Two.

2. **Weather.**
   Adverse conditions — heavy rain, high wind, cold — compress scoring and widen
   uncertainty, which should flatten the probability distribution toward the
   draw rather than shift it toward either side. Needs a forecast source keyed to
   venue and kickoff time. Model it as a variance/total-goals effect, not as an
   advantage to either team, unless the data says otherwise.

3. **Shot-based ratings.**
   The source workbooks carry shots, shots on target, corners and cards, all
   currently unused. Shot volume and quality stabilise faster than goals and
   should produce better ratings from the same number of matches.

4. **Tune the time-decay half-life.**
   Currently fixed at 365 days and never tuned, so the model is not even at its
   own optimum. Cheap to sweep.

5. **Promoted clubs with no league history.**
   Clubs arriving from the National League have no rating at all and currently
   fall back to market-only. A prior based on their non-league record, or on the
   average rating of recently promoted clubs, would be better than nothing.

## Standing principle

The market is the benchmark, not the enemy. The purpose of these refinements is
a model good enough to be worth blending in at all — not to justify a blend
weight that the evidence does not support.
