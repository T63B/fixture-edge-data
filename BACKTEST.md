# Backtest evidence

This file records why the model carries zero weight in the published forecast.
**Do not change `MODEL_WEIGHT` in `generate.py` without re-running this and beating
the numbers below.**

## Method

Walk-forward evaluation on football-data.co.uk results for the four English
divisions, 2022-23 to 2025-26 (8,144 matches, 98 clubs).

Starting from 3,000 matches of training data, the Dixon-Coles model was refitted
and used to forecast the next 500 matches, repeatedly, to the end of the data.
The model never sees its own test data. 5,103 out-of-sample forecasts resulted,
each compared against Bet365's de-vigged price on the same fixture.

Scoring is the three-outcome Brier score, averaged per match. Lower is better.

## Headline result

| Forecaster | Brier | Top-pick hit rate |
|---|---|---|
| Bet365, de-vigged | **0.6126** | **49.2%** |
| Dixon-Coles model | 0.6255 | 47.3% |

The market is better, in every division:

| Division | n | Model | Market |
|---|---|---|---|
| Premier League | 969 | 0.5965 | 0.5802 |
| Championship | 1,383 | 0.6338 | 0.6227 |
| League One | 1,396 | 0.6193 | 0.6102 |
| League Two | 1,355 | 0.6442 | 0.6281 |

## Blend sweep

The question that matters is not whether the model beats the market alone, but
whether it carries independent signal worth blending in. It does not:

| Weight on model | Brier |
|---|---|
| **0.00** | **0.61262** |
| 0.05 | 0.61273 |
| 0.10 | 0.61290 |
| 0.15 | 0.61312 |
| 0.25 | 0.61373 |
| 0.50 | 0.61626 |
| 1.00 | 0.62554 |

Monotonic. Every gram of model makes the forecast worse. The optimum sits exactly
at zero, and the improvement available over the market is 0.000%.

## What follows from this

1. The published forecast is the de-vigged market price, not a blend.
2. The model is kept for two honest jobs: a fallback when a fixture has no quoted
   odds, and a visible comparison column so divergence is legible.
3. "Edges" are only flagged when researched team news gives a concrete reason to
   move off the price. Model-versus-market disagreement is **not** an edge signal;
   treating it as one would be selling noise.
4. Any future claim that this tool beats the bookmakers has to clear 0.61262 on a
   fresh walk-forward run first.

## Honest caveats on the caveats

- football-data.co.uk's Bet365 columns are closing-ish prices. This tool runs at
  07:00 and uses morning prices, which are marginally less efficient. That gap is
  small and is not measured here, so it is not claimed as an advantage.
- The model uses goals only. Shots, shots on target and cards are present in the
  source data and unused. A shot-based or xG-style model would likely score
  better than this one — but "better than a weak model" is not "beats the market",
  and that work has not been done.
- A single fixed time-decay half-life (365 days) was used throughout. It was not
  tuned, so the model is not at its own optimum. Tuning it would narrow the gap
  to the market; there is no evidence it would close it.
