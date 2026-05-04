/**
 * Editor for the user's daily targets. Lives in the More tab.
 *
 * The coach reads these and judges progress against them — without
 * targets it has no anchor and tends to invent baselines (e.g. "TDEE
 * = 3000") and call routine numbers a crisis. Leave a field blank to
 * tell the coach "don't judge me on this."
 *
 * Storage is one row in `user_profile` keyed `_id="targets"` server-side.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { UserTargets } from "../api/types";

interface FormState {
  daily_calories: string;
  daily_protein_g: string;
  daily_fat_g: string;
  daily_carbs_g: string;
  daily_water_oz: string;
  step_goal_override: string;
  goal_weight_lb: string;
  weekly_loss_rate_min_lb: string;
  weekly_loss_rate_max_lb: string;
}

const EMPTY: FormState = {
  daily_calories: "",
  daily_protein_g: "",
  daily_fat_g: "",
  daily_carbs_g: "",
  daily_water_oz: "",
  step_goal_override: "",
  goal_weight_lb: "",
  weekly_loss_rate_min_lb: "",
  weekly_loss_rate_max_lb: "",
};

const FIELDS: (keyof FormState)[] = [
  "daily_calories", "daily_protein_g", "daily_fat_g", "daily_carbs_g",
  "daily_water_oz", "step_goal_override",
  "goal_weight_lb", "weekly_loss_rate_min_lb", "weekly_loss_rate_max_lb",
];

function fromServer(t: UserTargets | undefined): FormState {
  if (!t) return EMPTY;
  const out = { ...EMPTY };
  for (const k of FIELDS) {
    const v = (t as unknown as Record<string, number | null | undefined>)[k];
    out[k] = v == null ? "" : String(v);
  }
  return out;
}

function toServer(f: FormState): Partial<UserTargets> {
  const intNum = (s: string): number | null => {
    const t = s.trim();
    if (t === "") return null;
    const n = parseInt(t, 10);
    return Number.isFinite(n) ? n : null;
  };
  const floatNum = (s: string): number | null => {
    const t = s.trim();
    if (t === "") return null;
    const n = parseFloat(t);
    return Number.isFinite(n) ? n : null;
  };
  return {
    daily_calories: intNum(f.daily_calories),
    daily_protein_g: intNum(f.daily_protein_g),
    daily_fat_g: intNum(f.daily_fat_g),
    daily_carbs_g: intNum(f.daily_carbs_g),
    daily_water_oz: intNum(f.daily_water_oz),
    step_goal_override: intNum(f.step_goal_override),
    goal_weight_lb: floatNum(f.goal_weight_lb),
    weekly_loss_rate_min_lb: floatNum(f.weekly_loss_rate_min_lb),
    weekly_loss_rate_max_lb: floatNum(f.weekly_loss_rate_max_lb),
  };
}

export function TargetsCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["profile.targets"],
    queryFn: api.getTargets,
  });
  const [form, setForm] = useState<FormState>(EMPTY);
  const [savedFlash, setSavedFlash] = useState(false);

  // Hydrate the form once the server data lands. We only sync once so
  // typing isn't clobbered by a background refetch.
  useEffect(() => {
    if (data) setForm(fromServer(data));
  }, [data]);

  const save = useMutation({
    mutationFn: () => api.putTargets(toServer(form)),
    onSuccess: () => {
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1800);
      void qc.invalidateQueries({ queryKey: ["profile.targets"] });
      // Coach reads targets on next ask, so no need to invalidate there.
    },
  });

  const onField = (k: keyof FormState) =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm(s => ({ ...s, [k]: e.target.value }));

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-neutral-400">Daily targets</div>
          <div className="text-[11px] text-neutral-500">
            Coach uses these as the anchor — leave a field blank to tell it
            “don’t judge me on this metric.”
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="text-sm text-neutral-500">loading…</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Field
              label="calories"
              value={form.daily_calories}
              onChange={onField("daily_calories")}
              placeholder="e.g. 2200"
              suffix="kcal"
            />
            <Field
              label="protein"
              value={form.daily_protein_g}
              onChange={onField("daily_protein_g")}
              placeholder="e.g. 180"
              suffix="g"
            />
            <Field
              label="fat"
              value={form.daily_fat_g}
              onChange={onField("daily_fat_g")}
              placeholder="e.g. 70"
              suffix="g"
            />
            <Field
              label="carbs"
              value={form.daily_carbs_g}
              onChange={onField("daily_carbs_g")}
              placeholder="e.g. 220"
              suffix="g"
            />
            <Field
              label="water"
              value={form.daily_water_oz}
              onChange={onField("daily_water_oz")}
              placeholder="e.g. 128"
              suffix="oz"
            />
            <Field
              label="step goal override"
              value={form.step_goal_override}
              onChange={onField("step_goal_override")}
              placeholder="(blank = use Garmin)"
              suffix="steps"
            />
          </div>
          <div className="text-[11px] text-neutral-500 pt-1">Weight goal</div>
          <div className="grid grid-cols-3 gap-3">
            <Field
              label="goal weight"
              value={form.goal_weight_lb}
              onChange={onField("goal_weight_lb")}
              placeholder="e.g. 220"
              suffix="lb"
              step="0.5"
            />
            <Field
              label="loss rate min"
              value={form.weekly_loss_rate_min_lb}
              onChange={onField("weekly_loss_rate_min_lb")}
              placeholder="e.g. 1"
              suffix="lb/wk"
              step="0.25"
            />
            <Field
              label="loss rate max"
              value={form.weekly_loss_rate_max_lb}
              onChange={onField("weekly_loss_rate_max_lb")}
              placeholder="e.g. 1.5"
              suffix="lb/wk"
              step="0.25"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50 text-sm min-h-[44px]"
            >
              {save.isPending ? "saving…" : "save targets"}
            </button>
            {savedFlash && <span className="text-emerald-300 text-xs">saved ✓</span>}
            {save.error && (
              <span className="text-red-400 text-xs">save failed: {save.error.message}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder, suffix, step }: {
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  suffix?: string;
  step?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-neutral-500">{label}</span>
      <div className="relative">
        <input
          type="number"
          inputMode={step ? "decimal" : "numeric"}
          step={step}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          className="w-full px-3 py-3 pr-12 rounded bg-neutral-800 border border-neutral-700 text-base tabular-nums"
        />
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-neutral-500">
            {suffix}
          </span>
        )}
      </div>
    </label>
  );
}
