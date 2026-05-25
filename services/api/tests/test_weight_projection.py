"""Unit tests for the exponential-decay weight projection."""
import math
from datetime import UTC, datetime, timedelta

import pytest

from app.services.weight_projection import (
    MIN_DAYS_FOR_FIT,
    DecayFit,
    fit_decay,
)


def _synthetic_points(
    w0: float,
    w_inf: float,
    k_per_week: float,
    *,
    n: int = 30,
    noise_lb: float = 0.0,
    start: datetime = datetime(2026, 4, 26, 13, 0, tzinfo=UTC),
) -> list[tuple[datetime, float]]:
    """Generate clean (or noisy) points following W(t) = W_inf + (W0-W_inf)*exp(-k*t)."""
    import random
    random.seed(42)
    pts = []
    for i in range(n):
        t = start + timedelta(days=i)
        t_weeks = i / 7
        w = w_inf + (w0 - w_inf) * math.exp(-k_per_week * t_weeks)
        if noise_lb > 0:
            w += random.gauss(0, noise_lb)
        pts.append((t, w))
    return pts


def test_fit_recovers_clean_parameters():
    # 90 days of clean data — the regime once a user is a few months in.
    # With <30 days the asymptote is fundamentally underdetermined (the
    # data hasn't approached W_inf closely enough), so a tighter check
    # only makes sense once we have a meaningful tail.
    pts = _synthetic_points(w0=253.0, w_inf=220.0, k_per_week=0.10, n=90)
    fit = fit_decay(pts)
    assert fit is not None
    assert fit.asymptote_lb == pytest.approx(220.0, abs=0.5)
    assert fit.decay_per_week == pytest.approx(0.10, abs=0.005)
    assert fit.r_squared > 0.99


def test_fit_returns_none_below_min_days():
    pts = _synthetic_points(w0=250.0, w_inf=210.0, k_per_week=0.1, n=10)
    assert fit_decay(pts) is None


def test_fit_returns_none_for_too_few_points():
    assert fit_decay([]) is None
    assert fit_decay([(datetime.now(UTC), 250.0)]) is None


def test_fit_returns_none_when_not_losing():
    """Flat or gaining weight: no decay, no projection."""
    pts = [
        (datetime(2026, 4, 26, tzinfo=UTC) + timedelta(days=i), 250.0 + i * 0.1)
        for i in range(30)
    ]
    assert fit_decay(pts) is None


def test_date_for_returns_extrapolated_eta():
    pts = _synthetic_points(w0=253.0, w_inf=220.0, k_per_week=0.10, n=90)
    fit = fit_decay(pts)
    assert fit is not None
    # In the synthetic world, weight crosses 230 at:
    #   230 = 220 + 33 * exp(-0.1 * t)
    #   ⇒ exp(-0.1 t) = 10/33  ⇒  t ≈ 11.94 weeks from start
    target_eta = fit.date_for(230.0)
    assert target_eta is not None
    expected = pts[0][0] + timedelta(weeks=11.94)
    assert abs((target_eta - expected).total_seconds()) < 86_400 * 3  # within 3 days


def test_date_for_returns_none_when_target_at_or_below_asymptote():
    pts = _synthetic_points(w0=253.0, w_inf=225.0, k_per_week=0.10, n=90)
    fit = fit_decay(pts)
    assert fit is not None
    # Asymptote is ~225 — can't reach 220 at this effort.
    assert fit.date_for(220.0) is None
    assert fit.date_for(225.0) is None


def test_date_for_target_above_starting_weight():
    """Target weight higher than start (silly case) returns the start time."""
    pts = _synthetic_points(w0=253.0, w_inf=220.0, k_per_week=0.10, n=90)
    fit = fit_decay(pts)
    assert fit is not None
    assert fit.date_for(260.0) == fit.t0


def test_fit_robust_to_modest_noise():
    """Real Garmin data has ±0.5 lb day-to-day jitter (hydration, gut, etc.)."""
    pts = _synthetic_points(
        w0=253.0, w_inf=220.0, k_per_week=0.10, n=40, noise_lb=0.6,
    )
    fit = fit_decay(pts)
    assert fit is not None
    # 3-parameter exponential fits are poorly identifiable under noise:
    # "lower asymptote + slower decay" fits nearly as well as the truth.
    # The clamp on the asymptote search keeps it within 15 lb of the
    # observed minimum, which is the relevant property for the dashboard.
    assert fit.r_squared > 0.97
    assert 215.0 <= fit.asymptote_lb <= 226.0
    assert fit.decay_per_week > 0


def test_predict_at_t0_is_w0():
    pts = _synthetic_points(w0=253.0, w_inf=220.0, k_per_week=0.10, n=90)
    fit = fit_decay(pts)
    assert fit is not None
    assert fit.predict(fit.t0) == pytest.approx(fit.w0_lb, abs=0.01)


def test_min_days_constant_is_sane():
    """If MIN_DAYS_FOR_FIT changes, downstream UX breaks; document the choice."""
    assert MIN_DAYS_FOR_FIT == 21
