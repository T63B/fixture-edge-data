# The model, and how it was chosen

Every choice here was made by walk-forward backtest, not preference. The protocol:
refit on everything before a cutoff, forecast the next 500 matches, repeat to the
end of the data. 8,144 matches across four seasons and all four English divisions;
5,103 out-of-sample forecasts.

## What is published

Dixon-Coles attack and defence ratings on a single cross-division scale, so
promoted and relegated clubs carry their form across boundaries. Two fits are made
-- one on goals, one on shots on target -- and their predicted scoring rates are
blended geometrically at **weight 0.4 on goals, 0.6 on shots**.

| | Brier | Hit rate |
|---|---|---|
| Goals only (previous) | 0.6255 | 47.3% |
| **Goals + shots blend** | **0.6249** | 47.3% |
| De-vigged market | 0.6126 | 49.1% |

Shots on target stabilise faster than goals, so they carry more weight. The gain is
real but small: 0.0007.

## Tested and rejected

**Per-club home advantage** (each club its own home term, shrunk toward the league
mean). Made things slightly worse: 0.6415 against 0.6409 on a held-out split. It is
an intuitive idea and the data does not support it. Do not reintroduce without new
evidence.

**Half-life.** 365 days is near-optimal; 180 (0.6427) and 730 (0.6414) were both
worse than 365 (0.6409) on the same split.

## What actually matters most: staleness

The largest controllable error source is not model structure, it is how old the
ratings are. Measured by fitting at five cut dates and scoring forward:

| Days since refit | Model | Market | Gap |
|---|---|---|---|
| 0-30 | 0.6168 | 0.6061 | +0.011 |
| 30-60 | 0.6300 | 0.6158 | +0.014 |
| 60-90 | 0.6298 | 0.6169 | +0.013 |
| 90-150 | 0.6336 | 0.6157 | **+0.018** |

The gap to the market roughly doubles as ratings age. Refitting is worth about
**0.017 Brier -- roughly twenty-four times the gain from the shots blend.**

Run `fit_model.py` weekly. If you maintain one thing in this repo, maintain that.

## The honest position

The market is the better forecaster and this tool publishes the other one. That is
a deliberate choice: an independent view can be measured, criticised and improved,
where a restatement of the odds cannot. But the Track Record has so far agreed with
the backtest -- and on the fixtures where model and market disagreed by 10 points or
more, the market has been the more accurate of the two. That comparison is on the
dashboard, and it is the number to watch.

## Not yet tried

Weather (as a variance effect, not an advantage to either side); feeding the daily
run's injury and suspension research into the ratings rather than discarding it;
priors for clubs promoted from the National League with no league history. Each must
beat the current benchmark on a fresh walk-forward run before it ships.

## Probability shrinkage -- tested 17 Oct 2026, REJECTED

The live record showed a suggestive split: on 71 graded fixtures the model picked
the right outcome MORE often than the market (50.7% against 46.5%) while scoring
WORSE on Brier (0.6399 against 0.6194). That is the signature of a model that is
directionally decent and overconfident, and the textbook fix is to shrink each
forecast toward the base rate: p' = w*p + (1-w)*base.

Swept on each dataset, it looks like a clear win:

    reconstructed (228)   raw 0.6516 -> 0.6430 at w=0.5   (gain 0.0086)
    live (71)             raw 0.6399 -> 0.6379 at w=0.7   (gain 0.0020)

Both of those are in-sample: w and the base rates were chosen on the same
fixtures they were then scored on. The only honest test is to fit on one period
and apply to the other. Fitting w=0.5 and the base rates on the reconstruction
and applying them to the 71 live fixtures:

    raw 0.6399 -> shrunk 0.6525      WORSE by 0.0126
    gap to market widens from +0.0205 to +0.0332

So it is rejected. The reason is visible in the base rates themselves, which are
nothing like stable between the two windows:

    reconstructed   H 43 / D 33 / A 24
    live            H 39 / D 24 / A 37

Shrinking toward a base rate measured elsewhere drags forecasts toward the wrong
centre. At 71 and 228 fixtures these rates are mostly sampling noise, and any
method that depends on them inherits that noise.

The underlying observation still stands and is worth returning to with more data:
the model is better at ranking outcomes than at pricing them. A calibration fix
is still the most promising direction -- but it has to be validated out-of-sample
on the big walk-forward (5,103 matches), not on a few dozen live fixtures where
an in-sample sweep will always find something that looks like a gain.

## Market drift, 07:00 to kick-off -- first read, 17 Oct 2026 (69 fixtures)

The question: when the model disagrees with the morning price, does the market
move toward it by kick-off? If so the model holds information the morning market
has not absorbed, which would be the first real evidence an independent view is
worth having.

Measured both ways, because our 07:00 price and the archive's closing price come
from different book sets and that alone could manufacture apparent movement:

                              mean absolute move   model anticipates it
    our 07:00 -> close              1.54pp         r = +0.066  (52% of rows)
    archive open -> close           1.58pp         r = -0.073  (51% of rows)

Two things follow.

**The book-set worry was unfounded** -- 1.54 against 1.58, a difference of
0.05pp. The cruder measure is fine to keep using.

**There is very little movement to predict.** The market shifts about 1.6
points per outcome between morning and kick-off, against model-market
disagreements that routinely run to 10-20 points on flagged fixtures. Even a
model that called the direction perfectly would be extracting a small amount of
information.

And it does not call the direction: 51-52% of outcome-rows, a coin flip, with
the correlation flipping SIGN between the two measures. That sign flip is the
tell -- it is what noise looks like, and it is why the +0.199 estimate from 49
fixtures in September should not have been quoted hopefully.

Also worth recording: the closing price was NOT sharper than the opening price
here (0.6175 against 0.6155 on the same books, gap not significant), which runs
against the usual assumption that closing lines are sharper. At n=69 that is
noise too, but do not assume the closing line is the better benchmark without
checking it on this data.

POWER, so nobody re-runs this too early:

    if the true r is 0.20  ->  ~190 fixtures   (~5 weeks at 40/week)
    if the true r is 0.15  ->  ~350 fixtures   (~9 weeks)
    if the true r is 0.10  ->  ~780 fixtures   (~20 weeks)
    if the true r is 0.07  -> ~1800 fixtures   (~45 weeks)

Do not re-test below about 190 graded fixtures carrying closing odds. The
dashboard's Timing note now reports the running figure and says plainly when the
sample is still too small, so this needs no manual analysis in the meantime.
