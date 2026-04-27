#!/usr/bin/env python3
"""Recommend daily calorie + protein targets, then optionally write them
to /profile/targets so the coach uses them.

The math: Mifflin-St Jeor BMR (the equation everyone serious uses since
1990 — slightly more accurate than Harris-Benedict for adults), then a
TDEE multiplier from a self-reported activity tier, then a deficit
based on the goal weekly weight change. Protein recommendation tracks
ISSN/ACSM cutting guidance: ~0.8–1.0 g per lb of *target* body weight
preserves lean mass through a sustained deficit.

Inputs that change the math:
  --age 44 --sex male --height-in 77 --weight-lb 250
  --activity moderate            (sedentary | light | moderate | very | athlete)
  --goal lose-1lb-week           (maintain | lose-0.5lb | lose-1lb-week | lose-1.5lb-week)
  --target-weight-lb 195         (used for protein math; defaults to 'healthy BMI midpoint')

Latest weight can be auto-pulled from /metrics/summary (latest Garmin
scale reading) so you only have to type it once. Pass --pull-weight to
opt in.

Usage:
  recommend                      print the recommendation
  apply --yes                    recommend AND write to /profile/targets
                                 (skip the y/n confirm with --yes)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from _client import client

# ---- conversions ------------------------------------------------------------

KG_PER_LB = 0.45359237
CM_PER_IN = 2.54


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def in_to_cm(inches: float) -> float:
    return inches * CM_PER_IN


# ---- activity multipliers ---------------------------------------------------
# Standard Katch-McArdle / NSCA tiers. The numbers are from the literature;
# not opinions. "athlete" is for people doing heavy training >1h/day.
ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,    # desk job, no deliberate exercise
    "light":     1.375,  # 1–3 light sessions / week, mostly walking
    "moderate":  1.55,   # 3–5 sessions / week, some lifting or runs
    "very":      1.725,  # 6–7 sessions / week, structured training
    "athlete":   1.9,    # 2-a-days, high training volume
}

# Weekly weight change → daily kcal deficit. 1 lb of fat ≈ 3500 kcal so
# 1 lb / week ≈ 500 kcal / day. The lookup is named for clarity in the CLI.
GOAL_WEEKLY_DEFICIT_KCAL: dict[str, float] = {
    "maintain":          0.0,
    "lose-0.5lb-week":   250.0,
    "lose-1lb-week":     500.0,
    "lose-1.5lb-week":   750.0,  # aggressive — flag in the output
}


@dataclass
class Recommendation:
    bmr: int
    tdee: int
    deficit: int
    recommended_calories: int
    recommended_protein_g: int
    target_weight_lb: int
    notes: list[str]


def mifflin_st_jeor_bmr(*, weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Mifflin-St Jeor (1990). Validated as the most accurate widely-used
    BMR equation for non-obese adults. For obese adults use of LBM-based
    Katch-McArdle is technically better but requires a body-fat-% input;
    we'd rather be slightly low than ask for something the user may not
    know."""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return base + (5.0 if sex == "male" else -161.0)


def healthy_bmi_target_weight_lb(height_cm: float) -> int:
    """Mid-point of the "healthy BMI" band (BMI 22). Standard nutrition-
    counselor heuristic for "what should this person aim for". Intentionally
    conservative; many lifters carry more lean mass and look great at 24-25."""
    height_m = height_cm / 100.0
    bmi_target = 22.0
    kg = bmi_target * (height_m ** 2)
    return round(kg / KG_PER_LB)


def recommend(
    *, age: int, sex: str, height_in: float, weight_lb: float,
    activity: str, goal: str, target_weight_lb: int | None,
) -> Recommendation:
    height_cm = in_to_cm(height_in)
    weight_kg = lb_to_kg(weight_lb)
    bmr = mifflin_st_jeor_bmr(
        weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex,
    )
    factor = ACTIVITY_FACTORS[activity]
    tdee = bmr * factor
    deficit = GOAL_WEEKLY_DEFICIT_KCAL[goal]
    rec_cal = tdee - deficit

    if target_weight_lb is None:
        target_weight_lb = healthy_bmi_target_weight_lb(height_cm)

    # Protein: 0.9 g / lb of target body weight is the sweet spot for a
    # sustained deficit. Round to nearest 5 for ergonomics.
    rec_protein = int(round(target_weight_lb * 0.9 / 5.0) * 5)

    notes: list[str] = []
    if rec_cal < 1800 and sex == "male":
        notes.append(
            "WARNING: recommended kcal under 1,800 for an adult male — "
            "this is crash-cut territory and unsustainable past 4–6 weeks. "
            "Consider easing the goal (e.g. lose-1lb-week) or eating back "
            "exercise calories."
        )
    if goal == "lose-1.5lb-week":
        notes.append(
            "1.5 lb/week is aggressive. Plan to step up to lose-1lb-week "
            "after 8–12 weeks to protect lean mass and HRV."
        )
    if activity == "athlete" and goal != "maintain":
        notes.append(
            "'athlete' multiplier + a deficit is a hard combo. Recovery "
            "tanks fast. Monitor HRV and sleep score weekly; consider a "
            "smaller deficit if either drops >10%."
        )

    return Recommendation(
        bmr=int(round(bmr)),
        tdee=int(round(tdee)),
        deficit=int(deficit),
        recommended_calories=int(round(rec_cal)),
        recommended_protein_g=rec_protein,
        target_weight_lb=target_weight_lb,
        notes=notes,
    )


# ---- CLI plumbing -----------------------------------------------------------

def _pull_latest_weight_lb() -> float | None:
    try:
        with client() as c:
            r = c.get("/metrics/summary")
            r.raise_for_status()
            data = r.json()
        kg = (data.get("weight") or {}).get("kg")
        if kg is None:
            return None
        return kg / KG_PER_LB
    except Exception as e:
        sys.stderr.write(f"warning: couldn't pull latest weight ({e}); pass --weight-lb\n")
        return None


def _print(rec: Recommendation, args: argparse.Namespace) -> None:
    print(f"=== inputs ===")
    print(f"  age={args.age}  sex={args.sex}  height={args.height_in}\"  weight={args.weight_lb} lb")
    print(f"  activity={args.activity}  goal={args.goal}")
    print(f"  target_weight_lb={rec.target_weight_lb}")
    print(f"\n=== math ===")
    print(f"  BMR (Mifflin-St Jeor):     {rec.bmr:>5} kcal/day")
    print(f"  TDEE @ {args.activity:<10} {rec.tdee:>5} kcal/day  (BMR × {ACTIVITY_FACTORS[args.activity]})")
    print(f"  deficit:                   {rec.deficit:>5} kcal/day  ({args.goal})")
    print(f"\n=== recommendation ===")
    print(f"  daily calories:  {rec.recommended_calories:>5} kcal")
    print(f"  daily protein:   {rec.recommended_protein_g:>5} g    (≈0.9 g/lb of target weight)")
    if rec.notes:
        print("\n=== notes ===")
        for n in rec.notes:
            print(f"  • {n}")


def cmd_recommend(args: argparse.Namespace) -> int:
    rec = _build(args)
    _print(rec, args)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    rec = _build(args)
    _print(rec, args)
    if not args.yes:
        confirm = input(
            f"\nWrite calories={rec.recommended_calories}, "
            f"protein={rec.recommended_protein_g} to /profile/targets? [y/N] ",
        ).strip().lower()
        if confirm != "y":
            print("aborted (no write)")
            return 1
    body = {
        "daily_calories": rec.recommended_calories,
        "daily_protein_g": rec.recommended_protein_g,
    }
    if args.step_goal:
        body["step_goal_override"] = args.step_goal
    with client() as c:
        r = c.put("/profile/targets", json=body)
        r.raise_for_status()
    print("\nwrote targets:")
    for k, v in r.json().items():
        print(f"  {k}: {v}")
    return 0


def _build(args: argparse.Namespace) -> Recommendation:
    if args.weight_lb is None:
        if args.pull_weight:
            pulled = _pull_latest_weight_lb()
            if pulled is None:
                sys.stderr.write("error: --pull-weight set but no weight in /metrics/summary\n")
                sys.exit(2)
            args.weight_lb = round(pulled, 1)
            print(f"(pulled latest weight from API: {args.weight_lb} lb)\n")
        else:
            sys.stderr.write("error: --weight-lb required (or pass --pull-weight)\n")
            sys.exit(2)
    return recommend(
        age=args.age, sex=args.sex, height_in=args.height_in,
        weight_lb=args.weight_lb, activity=args.activity, goal=args.goal,
        target_weight_lb=args.target_weight_lb,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--age", type=int, required=True)
        sp.add_argument("--sex", choices=["male", "female"], default="male")
        sp.add_argument("--height-in", type=float, required=True,
                        help="height in inches (e.g. 77 for 6'5\")")
        sp.add_argument("--weight-lb", type=float,
                        help="current weight in lb (or use --pull-weight)")
        sp.add_argument("--pull-weight", action="store_true",
                        help="auto-pull latest weight from /metrics/summary")
        sp.add_argument("--activity", choices=list(ACTIVITY_FACTORS), default="moderate")
        sp.add_argument("--goal", choices=list(GOAL_WEEKLY_DEFICIT_KCAL),
                        default="lose-1lb-week")
        sp.add_argument("--target-weight-lb", type=int,
                        help="goal weight in lb (default: BMI 22 midpoint)")

    sp = sub.add_parser("recommend", help="print the recommendation")
    add_common(sp)
    sp.set_defaults(func=cmd_recommend)

    sp = sub.add_parser("apply", help="recommend AND write to /profile/targets")
    add_common(sp)
    sp.add_argument("--step-goal", type=int, help="also set step_goal_override")
    sp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_apply)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
