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
}

const EMPTY: FormState = {
  daily_calories: "",
  daily_protein_g: "",
  daily_fat_g: "",
  daily_carbs_g: "",
  daily_water_oz: "",
  step_goal_override: "",
};

function fromServer(t: UserTargets | undefined): FormState {
  if (!t) return EMPTY;
  return {
    daily_calories: t.daily_calories?.toString() ?? "",
    daily_protein_g: t.daily_protein_g?.toString() ?? "",
    daily_fat_g: t.daily_fat_g?.toString() ?? "",
    daily_carbs_g: t.daily_carbs_g?.toString() ?? "",
    daily_water_oz: t.daily_water_oz?.toString() ?? "",
    step_goal_override: t.step_goal_override?.toString() ?? "",
  };
}

function toServer(f: FormState): Partial<UserTargets> {
  const num = (s: string): number | null => {
    const t = s.trim();
    if (t === "") return null;
    const n = parseInt(t, 10);
    return Number.isFinite(n) ? n : null;
  };
  return {
    daily_calories: num(f.daily_calories),
    daily_protein_g: num(f.daily_protein_g),
    daily_fat_g: num(f.daily_fat_g),
    daily_carbs_g: num(f.daily_carbs_g),
    daily_water_oz: num(f.daily_water_oz),
    step_goal_override: num(f.step_goal_override),
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

function Field({ label, value, onChange, placeholder, suffix }: {
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  suffix?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-neutral-500">{label}</span>
      <div className="relative">
        <input
          type="number"
          inputMode="numeric"
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
