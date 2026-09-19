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
