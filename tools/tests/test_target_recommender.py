"""Math-only tests for the recommender. No HTTP, no API."""
import sys
from pathlib import Path

# Make the script directory importable so we can import the function under test.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_recommender import (  # noqa: E402
    MIN_AUTO_DAYS,
    healthy_bmi_target_weight_lb,
    in_to_cm,
    lb_to_kg,
    mifflin_st_jeor_bmr,
    observed_tdee_from_history,
    recommend,
)


def test_unit_conversions():
    assert abs(lb_to_kg(250) - 113.4) < 0.1
    assert abs(in_to_cm(77) - 195.6) < 0.1


def test_bmr_male_known_value():
    """44yo male, 6'5", 250 lb → ~2141 kcal BMR (verified against several
    public Mifflin-St Jeor calculators)."""
    bmr = mifflin_st_jeor_bmr(weight_kg=113.4, height_cm=195.6, age=44, sex="male")
    assert 2135 <= bmr <= 2150


def test_bmr_female_uses_minus_161():
    """Same body, female sex offset is -161 vs +5 = 166 kcal lower."""
    male = mifflin_st_jeor_bmr(weight_kg=113.4, height_cm=195.6, age=44, sex="male")
    female = mifflin_st_jeor_bmr(weight_kg=113.4, height_cm=195.6, age=44, sex="female")
    assert abs((male - female) - 166) < 0.01


def test_recommendation_for_known_user():
    """The motivating case — 44yo male, 6'5", 250 lb, lightly active,
    1 lb/week loss. Should land near 2,400-2,500 cal."""
    rec = recommend(
        age=44, sex="male", height_in=77, weight_lb=250,
        activity="light", goal="lose-1lb-week", target_weight_lb=None,
    )
    assert 2400 <= rec.recommended_calories <= 2500
    assert rec.bmr in range(2135, 2150)
    assert rec.target_weight_lb in range(180, 195)  # BMI 22 mid for 6'5"


def test_aggressive_cut_emits_warning_note():
    rec = recommend(
        age=44, sex="male", height_in=77, weight_lb=250,
        activity="sedentary", goal="lose-1.5lb-week", target_weight_lb=None,
    )
    assert any("aggressive" in n.lower() for n in rec.notes)


def test_too_low_kcal_emits_warning_note():
    """Small sedentary male wanting 1.5 lb/week could land under 1800."""
    rec = recommend(
        age=70, sex="male", height_in=64, weight_lb=140,
        activity="sedentary", goal="lose-1.5lb-week", target_weight_lb=None,
    )
    assert any("crash" in n.lower() or "1,800" in n for n in rec.notes)


def test_protein_uses_target_weight_not_current():
    """A 250 lb user trying to reach 190 lb should get protein math
    based on 190, not 250 — that's the cutting-protocol convention."""
    rec_default = recommend(
        age=44, sex="male", height_in=77, weight_lb=250,
        activity="light", goal="lose-1lb-week", target_weight_lb=None,
    )
    rec_explicit = recommend(
        age=44, sex="male", height_in=77, weight_lb=250,
        activity="light", goal="lose-1lb-week", target_weight_lb=190,
    )
    # Default is BMI 22 = ~186; explicit is 190. Protein scales with target.
    assert rec_explicit.recommended_protein_g >= rec_default.recommended_protein_g


def test_observed_tdee_uses_median_and_filters_partial_days():
    rows = [
        {"total_kcal": 2500},
        {"total_kcal": 2600},
        {"total_kcal": 2700},
        {"total_kcal": 100},   # off-wrist day, must be filtered
        {"total_kcal": None},  # missing data, must be filtered
    ]
    median, days = observed_tdee_from_history(rows)
    # 3 valid days → median of [2500, 2600, 2700] = 2600
    assert median == 2600
    assert days == 3


def test_observed_tdee_returns_zero_when_no_data():
    median, days = observed_tdee_from_history([])
    assert median == 0
    assert days == 0


def test_auto_uses_observed_when_enough_days():
    """The motivating use case — formula says ~2,944 (light), but
    observed is 2,533 (the user's actual Garmin median). Auto must
    pick observed since the formula systematically over-predicts for
    beginners."""
    rows = [{"total_kcal": v} for v in [
        2337, 2493, 2533, 2489, 2643, 2730, 2882, 2627, 2468, 2538, 2523,
    ]]
    rec = recommend(
        age=44, sex="male", height_in=77, weight_lb=253.4,
        activity="auto", goal="lose-1lb-week", target_weight_lb=None,
        history_rows=rows,
    )
    assert rec.tdee_source == "observed"
    assert rec.observed_days >= MIN_AUTO_DAYS
    # Median of those values is ~2,533. Recommendation = 2,533 - 500 = ~2,033.
    assert 2000 <= rec.recommended_calories <= 2100
    # Way different from what formula 'light' would have given (~2,440)
    assert rec.recommended_calories < 2400


def test_auto_falls_back_to_formula_with_thin_history():
    rows = [{"total_kcal": 2500}, {"total_kcal": 2600}]  # only 2 days
    rec = recommend(
        age=44, sex="male", height_in=77, weight_lb=253.4,
        activity="auto", goal="lose-1lb-week", target_weight_lb=None,
        history_rows=rows,
    )
    assert rec.tdee_source == "formula"
    assert any("falling back" in n.lower() for n in rec.notes)


def test_auto_warns_when_observed_below_bmr():
    """Wearable off-wrist a lot can produce observed TDEE < BMR. Don't
    silently swallow that — flag it."""
    rows = [{"total_kcal": 1500}] * 7  # implausibly low for the test profile
    rec = recommend(
        age=44, sex="male", height_in=77, weight_lb=253.4,
        activity="auto", goal="lose-1lb-week", target_weight_lb=None,
        history_rows=rows,
    )
    assert rec.tdee_source == "observed"
    assert any("off-wrist" in n.lower() or "below predicted bmr" in n.lower()
               for n in rec.notes)


def test_healthy_bmi_target_weight_for_6ft5():
    """6'5" → BMI 22 ≈ 186 lb. Slot for the canonical case."""
    cm = in_to_cm(77)
    target = healthy_bmi_target_weight_lb(cm)
    assert 182 <= target <= 190
