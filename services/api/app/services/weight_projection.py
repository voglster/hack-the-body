"""Exponential-decay weight-loss projection.

Fits `W(t) = W_inf + (W_0 - W_inf) * exp(-k * t)` against weigh-ins, where
`W_inf` is the asymptote ("plateau at current effort") and `k` is the decay
constant in weeks^-1. The asymptote is found via golden-section search over
candidate values; at each candidate, the model is linear in `ln(W - W_inf)`
vs `t`, so the inner fit is closed-form linear regression.

This avoids a scipy dependency on the API image (~100 MB) for a one-purpose
calculation. The fit is reliable once there are ~21+ days of data; below
that the asymptote is underdetermined and we return None.

Why decay instead of linear regression: weight loss is a decay process — the
deficit shrinks as the body adapts (NEAT, T3, leptin). Linear models project
your current slope forever and drift later week over week. The decay model
already anticipates the slowdown, so the projected goal-date stabilizes
quickly once the model has enough data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

MIN_DAYS_FOR_FIT = 21
SECONDS_PER_WEEK = 7 * 86_400


@dataclass(frozen=True)
class DecayFit:
    asymptote_lb: float            # W_inf — plateau at current effort
    decay_per_week: float          # k, in 1/week
    w0_lb: float                   # weight at t=0 (the fit's anchor)
    t0: datetime                   # the timestamp of t=0
    r_squared: float
    n_points: int

    def predict(self, when: datetime) -> float:
        t_weeks = (when - self.t0).total_seconds() / SECONDS_PER_WEEK
        return self.asymptote_lb + (self.w0_lb - self.asymptote_lb) * math.exp(
            -self.decay_per_week * t_weeks,
        )

    def date_for(self, target_lb: float) -> datetime | None:
        """Return the datetime when `predict()` equals `target_lb`, or None
        if the asymptote sits at or above the target (you would plateau
        before reaching it at current effort)."""
        # Solve: target = W_inf + (W_0 - W_inf) * exp(-k * t_weeks)
        #   ⇒  t_weeks = -ln((target - W_inf) / (W_0 - W_inf)) / k
        denom = self.w0_lb - self.asymptote_lb
        numer = target_lb - self.asymptote_lb
        if denom == 0 or self.decay_per_week <= 0:
            return None
        ratio = numer / denom
        # ratio must be in (0, 1] — strictly positive for ln to be real,
        # and ≤1 because target should be between asymptote and start.
        # Treat "within 0.5 lb of asymptote" as effectively-unreachable;
        # otherwise tiny floating-point gaps produce huge spurious ETAs.
        if ratio <= 0 or numer < 0.5:
            return None
        if ratio >= 1:
            # target is at/above the fit's starting weight → already there
            return self.t0
        t_weeks = -math.log(ratio) / self.decay_per_week
        return self.t0 + timedelta(seconds=t_weeks * SECONDS_PER_WEEK)


def _fit_linear_for_asymptote(
    pts: list[tuple[float, float]], asymptote: float,
) -> tuple[float, float, float] | None:
    """Given a candidate asymptote, fit `ln(W - asymptote) = a - k*t` via
    plain linear regression. Returns (k, intercept, sse) or None if any
    (W - asymptote) is non-positive (asymptote sits above some observed
    weight — invalid). `intercept` is `ln(W_0_fit - asymptote)`; the
    model's t=0 prediction is `asymptote + exp(intercept)`.
    """
    xs = []
    ys = []
    for t_weeks, w in pts:
        residual = w - asymptote
        if residual <= 0:
            return None  # asymptote candidate violates the data
        xs.append(t_weeks)
        ys.append(math.log(residual))
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None
    slope = num / den  # = -k
    intercept = mean_y - slope * mean_x
    sse = sum(
        (y - (slope * x + intercept)) ** 2
        for x, y in zip(xs, ys, strict=True)
    )
    return -slope, intercept, sse


def fit_decay(
    points: list[tuple[datetime, float]],
    *,
    min_days: int = MIN_DAYS_FOR_FIT,
) -> DecayFit | None:
    """Fit `W(t) = W_inf + (W_0 - W_inf) * exp(-k*t)` to `points`.

    `points` is a list of `(timestamp, weight_lb)` tuples; need not be
    sorted. Returns None if there's insufficient data span or if no valid
    asymptote can be found.
    """
    if len(points) < 3:
        return None
    pts_sorted = sorted(points, key=lambda p: p[0])
    t0 = pts_sorted[0][0]
    t_last = pts_sorted[-1][0]
    span_days = (t_last - t0).total_seconds() / 86_400
    if span_days < min_days:
        return None

    # Recast as (t_weeks_from_t0, weight_lb).
    series = [
        ((p[0] - t0).total_seconds() / SECONDS_PER_WEEK, p[1])
        for p in pts_sorted
    ]
    weights = [p[1] for p in series]
    min_w = min(weights)

    # Search for asymptote in a physically-plausible band below current min.
    # Tight bounds matter: a 3-parameter exponential is poorly identifiable —
    # a "lower asymptote + slower decay" can fit noisy data nearly as well
    # as the true parameters. Empirically, clamping the lower bound to
    # min_w − 15 lb prevents the worst overfitting without losing real cases
    # (someone with goal 220 weighing 245 is well within 15 lb of any
    # reasonable asymptote between those values).
    lo = min_w - 15.0
    hi = min_w - 0.1

    # Golden-section search over candidate asymptote.
    phi = (math.sqrt(5) - 1) / 2  # 0.6180
    a, b = lo, hi

    def sse_at(asymptote: float) -> float:
        res = _fit_linear_for_asymptote(series, asymptote)
        return res[2] if res is not None else float("inf")

    # 60 iterations brings the bracket below 1e-12 lb — overkill but cheap.
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc = sse_at(c)
    fd = sse_at(d)
    for _ in range(60):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = sse_at(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = sse_at(d)
    asymptote = (a + b) / 2
    fit = _fit_linear_for_asymptote(series, asymptote)
    if fit is None:
        return None
    k, intercept, _sse = fit
    if k <= 0:
        # No decay → either flat or gaining. Caller should treat as "no
        # projection" rather than producing a nonsense answer.
        return None

    # The model's t=0 prediction is asymptote + exp(intercept). Anchoring
    # `w0_lb` here (not at weights[0]) makes the curve consistent — the
    # log-space linear regression has its own intercept, separate from
    # whatever the first noisy observation happens to be.
    w0_fit = asymptote + math.exp(intercept)
    predicted = [
        asymptote + (w0_fit - asymptote) * math.exp(-k * t)
        for t, _ in series
    ]
    mean_w = sum(weights) / len(weights)
    ss_res = sum((w - p) ** 2 for w, p in zip(weights, predicted, strict=True))
    ss_tot = sum((w - mean_w) ** 2 for w in weights)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return DecayFit(
        asymptote_lb=asymptote,
        decay_per_week=k,
        w0_lb=w0_fit,
        t0=t0 if t0.tzinfo else t0.replace(tzinfo=UTC),
        r_squared=r_squared,
        n_points=len(pts_sorted),
    )
