import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type {
  Food, MealEntry, MealSlot, MealTemplate, MealTemplateItem,
  UsualAugmentSuggestion, UsualNewSuggestion, UsualSuggestion,
} from "../api/types";
import { todayLocalISO } from "../lib/tz";

const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];
const SLOT_LABEL: Record<MealSlot, string> = {
  breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner",
  snack: "Snack", supplement: "Supplement",
};

interface DraftItem extends MealTemplateItem {
  food_name: string;
}

interface Draft {
  id?: string;
  name: string;
  default_slot: MealSlot;
  items: DraftItem[];
}

export function UsualsPage() {
  const qc = useQueryClient();
  const templates = useQuery({
    queryKey: ["meals.templates"],
    queryFn: api.listTemplates,
  });
  const suggestions = useQuery({
    queryKey: ["meals.suggest"],
    queryFn: api.suggestUsuals,
    // LLM call — don't auto-refetch
    staleTime: Infinity,
    retry: false,
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  const [buildFromDayOpen, setBuildFromDayOpen] = useState(false);

  const deleteTemplate = useMutation({
    mutationFn: (id: string) => api.deleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meals.templates"] }),
  });

  const saveTemplate = useMutation({
    mutationFn: (t: Draft) =>
      api.createTemplate({
        name: t.name.trim(),
        default_slot: t.default_slot,
        items: t.items.map(i => ({ food_id: i.food_id, quantity_g: i.quantity_g })),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["meals.templates"] });
      setDraft(null);
    },
  });

  const dismissSuggestion = useMutation({
    mutationFn: (signature: string) => api.dismissUsualSuggestion(signature),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meals.suggest"] }),
  });

  const refreshSuggestions = useMutation({
    mutationFn: api.suggestUsuals,
    onSuccess: (data) => qc.setQueryData(["meals.suggest"], data),
  });

  const onSaveNewSuggestion = (s: UsualNewSuggestion) => {
    saveTemplate.mutate({
      name: s.name,
      default_slot: s.slot,
      items: s.items.map(it => ({
        food_id: it.food_id, quantity_g: it.quantity_g,
        food_name: it.food_name,
      })),
    });
  };

  const onSaveAugmentSuggestion = (s: UsualAugmentSuggestion) => {
    // Look up the existing template, then upsert by same name with the
    // merged items list (existing items + new ones at their suggested qty).
    const existing = templates.data?.find(t => t.id === s.template_id);
    if (!existing) return;
    const existingIds = new Set(existing.items.map(i => i.food_id));
    const additions = s.items
      .filter(it => s.add_food_ids.includes(it.food_id) && !existingIds.has(it.food_id))
      .map(it => ({ food_id: it.food_id, quantity_g: it.quantity_g }));
    saveTemplate.mutate({
      name: existing.name,
      default_slot: existing.default_slot,
      items: [
        ...existing.items.map(i => ({ food_id: i.food_id, quantity_g: i.quantity_g })),
        ...additions,
      ].map((i): DraftItem => ({ ...i, food_name: "" })),
    });
  };

  const onTweakSuggestion = (s: UsualSuggestion) => {
    if (s.kind === "augment") {
      const existing = templates.data?.find(t => t.id === s.template_id);
      const baseItems: DraftItem[] = existing
        ? existing.items.map(i => ({
            food_id: i.food_id, quantity_g: i.quantity_g, food_name: "",
          }))
        : [];
      const additions: DraftItem[] = s.items
        .filter(it => s.add_food_ids.includes(it.food_id))
        .map(it => ({
          food_id: it.food_id, quantity_g: it.quantity_g,
          food_name: it.food_name,
        }));
      setDraft({
        id: existing?.id,
        name: existing?.name ?? s.template_name,
        default_slot: s.slot,
        items: [...baseItems, ...additions],
      });
      return;
    }
    const items: DraftItem[] = s.items.map(it => ({
      food_id: it.food_id, quantity_g: it.quantity_g, food_name: it.food_name,
    }));
    setDraft({ name: s.name, default_slot: s.slot, items });
  };

  const grouped = useMemo(() => {
    const out = new Map<MealSlot, MealTemplate[]>();
    for (const s of SLOTS) out.set(s, []);
    for (const t of templates.data ?? []) {
      out.get(t.default_slot)?.push(t);
    }
    return out;
  }, [templates.data]);

  return (
    <div className="max-w-3xl mx-auto px-3 sm:px-4 py-4 sm:py-8 space-y-6 pb-12">
      <header className="flex items-center justify-between">
        <div>
          <Link to="/more" className="text-xs text-neutral-500 active:text-neutral-200">
            ← More
          </Link>
          <h1 className="text-2xl font-semibold mt-1">Usuals</h1>
          <p className="text-sm text-neutral-500">
            One-tap meal bundles. Manage rarely; log daily.
          </p>
        </div>
        <button
          onClick={() => setDraft({ name: "", default_slot: "snack", items: [] })}
          className="px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 text-white text-sm min-h-[44px]"
        >
          + New
        </button>
      </header>

      <SuggestionsSection
        loading={suggestions.isFetching || refreshSuggestions.isPending}
        error={
          suggestions.error
            ? (suggestions.error instanceof Error ? suggestions.error.message : String(suggestions.error))
            : suggestions.data?.error ?? null
        }
        newSuggestions={suggestions.data?.new ?? []}
        augmentSuggestions={suggestions.data?.augment ?? []}
        onSaveNew={onSaveNewSuggestion}
        onSaveAugment={onSaveAugmentSuggestion}
        onTweak={onTweakSuggestion}
        onDismiss={(sig) => { dismissSuggestion.mutate(sig); }}
        onRefresh={() => { refreshSuggestions.mutate(); }}
        saving={saveTemplate.isPending}
      />

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm uppercase tracking-wide text-neutral-400">
            My usuals
          </h2>
          <span className="text-xs text-neutral-600 tabular-nums">
            {templates.data?.length ?? 0}
          </span>
        </div>
        {!templates.data?.length && (
          <div className="text-sm text-neutral-500 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            No usuals yet. The suggestions above can build your first few in
            one tap — or use <b>+ New</b> to start from scratch.
          </div>
        )}
        {SLOTS.map(slot => {
          const list = grouped.get(slot) ?? [];
          if (list.length === 0) return null;
          return (
            <div key={slot}>
              <div className="text-xs uppercase tracking-wide text-neutral-500 mb-1">
                {SLOT_LABEL[slot]}
              </div>
              <ul className="divide-y divide-neutral-800 rounded-lg border border-neutral-800 bg-neutral-900">
                {list.map(t => (
                  <UsualRow
                    key={t.id}
                    template={t}
                    onEdit={() => {
                      setDraft({
                        id: t.id,
                        name: t.name,
                        default_slot: t.default_slot,
                        items: t.items.map(i => ({
                          food_id: i.food_id, quantity_g: i.quantity_g,
                          food_name: "",
                        })),
                      });
                    }}
                    onDelete={() => {
                      if (confirm(`Delete usual "${t.name}"?`)) {
                        deleteTemplate.mutate(t.id);
                      }
                    }}
                    busy={deleteTemplate.isPending}
                  />
                ))}
              </ul>
            </div>
          );
        })}
      </section>

      <section>
        <button
          onClick={() => setBuildFromDayOpen(true)}
          className="text-sm text-neutral-400 active:text-emerald-300"
        >
          + Build from a recent day
        </button>
      </section>

      {draft && (
        <UsualEditor
          draft={draft}
          onChange={setDraft}
          onCancel={() => setDraft(null)}
          onSave={() => {
            if (!draft.name.trim() || draft.items.length === 0) return;
            saveTemplate.mutate(draft);
          }}
          saving={saveTemplate.isPending}
        />
      )}

      {buildFromDayOpen && (
        <BuildFromDay
          onClose={() => setBuildFromDayOpen(false)}
          onPick={(entries) => {
            const seen = new Set<string>();
            const items: DraftItem[] = [];
            for (const e of entries) {
              if (e.food_name === "Water" || e.food_name === "Vitamins") continue;
              const key = `${e.food_id}:${e.quantity_g}`;
              if (seen.has(key)) continue;
              seen.add(key);
              items.push({
                food_id: e.food_id,
                quantity_g: e.quantity_g,
                food_name: e.food_name,
              });
            }
            const firstSlot = entries[0]?.slot ?? "snack";
            setDraft({ name: "", default_slot: firstSlot, items });
            setBuildFromDayOpen(false);
          }}
        />
      )}
    </div>
  );
}

function UsualRow({ template, onEdit, onDelete, busy }: {
  template: MealTemplate;
  onEdit: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  return (
    <li className="flex items-center justify-between gap-3 p-3">
      <button
        onClick={onEdit}
        className="flex-1 min-w-0 text-left active:bg-neutral-800/40 -m-2 p-2 rounded"
      >
        <div className="font-medium truncate">{template.name}</div>
        <div className="text-xs text-neutral-500">
          {template.items.length} item{template.items.length === 1 ? "" : "s"}
        </div>
      </button>
      <button
        onClick={onDelete}
        disabled={busy}
        aria-label={`delete ${template.name}`}
        className="text-neutral-500 active:text-red-400 px-3 py-2 min-h-[44px] min-w-[44px] disabled:opacity-50"
      >
        ✕
      </button>
    </li>
  );
}

function SuggestionsSection({
  loading, error, newSuggestions, augmentSuggestions,
  onSaveNew, onSaveAugment, onTweak, onDismiss, onRefresh, saving,
}: {
  loading: boolean;
  error: string | null;
  newSuggestions: UsualNewSuggestion[];
  augmentSuggestions: UsualAugmentSuggestion[];
  onSaveNew: (s: UsualNewSuggestion) => void;
  onSaveAugment: (s: UsualAugmentSuggestion) => void;
  onTweak: (s: UsualSuggestion) => void;
  onDismiss: (sig: string) => void;
  onRefresh: () => void;
  saving: boolean;
}) {
  const total = newSuggestions.length + augmentSuggestions.length;
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wide text-neutral-400">
          Suggested usuals
        </h2>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-xs text-neutral-500 active:text-neutral-200 disabled:opacity-40"
        >
          {loading ? "scanning…" : "refresh"}
        </button>
      </div>
      {error && (
        <div className="text-xs text-amber-300">
          Suggester error: {error}
        </div>
      )}
      {loading && total === 0 && (
        <div className="text-sm text-neutral-500 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          Looking at the last 30 days…
        </div>
      )}
      {!loading && total === 0 && !error && (
        <div className="text-sm text-neutral-500 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          No new patterns spotted. Try again in a few days, or build one manually.
        </div>
      )}
      {augmentSuggestions.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-amber-400/70 mb-1">
            tweaks to existing usuals
          </div>
          <ul className="space-y-2">
            {augmentSuggestions.map(s => (
              <SuggestionCard
                key={s.signature}
                title={`Add ${s.add_food_names.join(", ")} to ${s.template_name}`}
                subline={`${SLOT_LABEL[s.slot]} · adds ${s.add_food_names.length} item${s.add_food_names.length === 1 ? "" : "s"}`}
                rationale={s.rationale}
                accent="amber"
                onSave={() => onSaveAugment(s)}
                onTweak={() => onTweak(s)}
                onDismiss={() => onDismiss(s.signature)}
                saving={saving}
              />
            ))}
          </ul>
        </div>
      )}
      {newSuggestions.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-emerald-400/70 mb-1">
            new usuals
          </div>
          <ul className="space-y-2">
            {newSuggestions.map(s => (
              <SuggestionCard
                key={s.signature}
                title={s.name}
                subline={`${SLOT_LABEL[s.slot]} · ${s.items.length} items`}
                rationale={s.rationale}
                accent="emerald"
                onSave={() => onSaveNew(s)}
                onTweak={() => onTweak(s)}
                onDismiss={() => onDismiss(s.signature)}
                saving={saving}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function SuggestionCard({ title, subline, rationale, accent, onSave, onTweak, onDismiss, saving }: {
  title: string;
  subline: string;
  rationale: string;
  accent: "emerald" | "amber";
  onSave: () => void;
  onTweak: () => void;
  onDismiss: () => void;
  saving: boolean;
}) {
  const ring = accent === "amber"
    ? "border-amber-800/40 bg-amber-950/20"
    : "border-emerald-800/40 bg-emerald-950/20";
  const cta = accent === "amber"
    ? "bg-amber-700 active:bg-amber-800"
    : "bg-emerald-700 active:bg-emerald-800";
  return (
    <li className={`rounded-lg border p-3 space-y-2 ${ring}`}>
      <div className="min-w-0">
        <div className="font-medium">{title}</div>
        <div className="text-xs text-neutral-500">{subline}</div>
      </div>
      {rationale && (
        <div className="text-xs text-neutral-400 italic">{rationale}</div>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={onSave}
          disabled={saving}
          className={`px-3 py-2 rounded text-white text-sm min-h-[44px] disabled:opacity-50 ${cta}`}
        >
          Save
        </button>
        <button
          onClick={onTweak}
          className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 text-sm min-h-[44px]"
        >
          Tweak
        </button>
        <button
          onClick={onDismiss}
          className="px-3 py-2 rounded text-neutral-500 active:text-neutral-200 text-sm min-h-[44px]"
        >
          Dismiss
        </button>
      </div>
    </li>
  );
}

function UsualEditor({ draft, onChange, onCancel, onSave, saving }: {
  draft: Draft;
  onChange: (d: Draft) => void;
  onCancel: () => void;
  onSave: () => void;
  saving: boolean;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Food[]>([]);

  // Resolve any item food_names we don't have yet (e.g., from suggestions)
  useEffect(() => {
    const missing = draft.items.filter(i => !i.food_name);
    if (missing.length === 0) return;
    let cancelled = false;
    void (async () => {
      const resolved = await Promise.all(missing.map(async i => {
        try {
          const food = await api.foodById(i.food_id);
          return { food_id: i.food_id, name: food.name };
        } catch {
          return { food_id: i.food_id, name: `food ${i.food_id.slice(-4)}` };
        }
      }));
      if (cancelled) return;
      onChange({
        ...draft,
        items: draft.items.map(i => {
          const r = resolved.find(x => x.food_id === i.food_id);
          return r && !i.food_name ? { ...i, food_name: r.name } : i;
        }),
      });
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const search = async (v: string) => {
    setQ(v);
    if (v.length < 2) { setHits([]); return; }
    try { setHits(await api.searchFoods(v, 8)); }
    catch { setHits([]); }
  };

  const addFood = (f: Food) => {
    onChange({
      ...draft,
      items: [...draft.items, {
        food_id: f.id, quantity_g: f.serving_g || 100, food_name: f.name,
      }],
    });
    setQ(""); setHits([]);
  };

  const removeAt = (idx: number) => {
    onChange({ ...draft, items: draft.items.filter((_, i) => i !== idx) });
  };

  const setQty = (idx: number, qty: number) => {
    onChange({
      ...draft,
      items: draft.items.map((it, i) => i === idx ? { ...it, quantity_g: qty } : it),
    });
  };

  return (
    <div className="fixed inset-0 z-40 bg-black/70 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="w-full max-w-lg max-h-[92vh] overflow-auto bg-neutral-950 border border-neutral-800 sm:rounded-xl rounded-t-xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">
            {draft.id ? "Edit usual" : "New usual"}
          </h3>
          <button
            onClick={onCancel}
            className="text-neutral-400 active:text-neutral-100 px-2 py-1"
            aria-label="close"
          >
            ✕
          </button>
        </div>

        <label className="block space-y-1">
          <span className="text-xs text-neutral-500">name</span>
          <input
            value={draft.name}
            onChange={e => onChange({ ...draft, name: e.target.value })}
            placeholder="e.g. Yogurt Breakfast"
            className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
            autoFocus={!draft.id}
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs text-neutral-500">default slot</span>
          <select
            value={draft.default_slot}
            onChange={e => onChange({ ...draft, default_slot: e.target.value as MealSlot })}
            className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
          >
            {SLOTS.map(s => <option key={s} value={s}>{SLOT_LABEL[s]}</option>)}
          </select>
        </label>

        <div className="space-y-2">
          <div className="text-xs text-neutral-500">items</div>
          {draft.items.length === 0 && (
            <div className="text-sm text-neutral-500 italic">No foods yet — add one below.</div>
          )}
          <ul className="divide-y divide-neutral-800 rounded border border-neutral-800 bg-neutral-900">
            {draft.items.map((it, idx) => (
              <li key={`${it.food_id}-${idx}`} className="flex items-center gap-2 p-2">
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">
                    {it.food_name || `food ${it.food_id.slice(-4)}`}
                  </div>
                </div>
                <input
                  type="number" inputMode="decimal" step="1"
                  value={it.quantity_g}
                  onChange={e => setQty(idx, parseFloat(e.target.value) || 0)}
                  className="w-20 px-2 py-2 rounded bg-neutral-800 border border-neutral-700 text-sm tabular-nums"
                  aria-label="grams"
                />
                <span className="text-xs text-neutral-500">g</span>
                <button
                  onClick={() => removeAt(idx)}
                  className="text-neutral-500 active:text-red-400 px-2 py-2 min-h-[44px]"
                  aria-label="remove"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-neutral-500">add food</div>
          <input
            value={q}
            onChange={e => { void search(e.target.value); }}
            placeholder="search food name"
            className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
            autoCapitalize="none"
          />
          {hits.length > 0 && (
            <ul className="rounded border border-neutral-800 bg-neutral-900 max-h-48 overflow-auto">
              {hits.map(f => (
                <li key={f.id}>
                  <button
                    onClick={() => addFood(f)}
                    className="w-full text-left px-3 py-3 active:bg-neutral-700 text-sm min-h-[44px]"
                  >
                    <div className="font-medium truncate">{f.name}</div>
                    <div className="text-xs text-neutral-500">
                      {f.brand ? `${f.brand} · ` : ""}{f.serving_g}g serving
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex gap-2 pt-1">
          <button
            onClick={onSave}
            disabled={saving || !draft.name.trim() || draft.items.length === 0}
            className="flex-1 px-3 py-3 rounded bg-emerald-700 active:bg-emerald-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
          >
            {saving ? "saving…" : draft.id ? "save changes" : "save usual"}
          </button>
          <button
            onClick={onCancel}
            className="px-4 py-3 rounded bg-neutral-800 active:bg-neutral-700 text-sm min-h-[44px]"
          >
            cancel
          </button>
        </div>
      </div>
    </div>
  );
}

const BUILD_SLOT_ORDER: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];

function shiftDay(iso: string, deltaDays: number): string {
  // iso is local-tz YYYY-MM-DD — keep it as a local date so shifts don't
  // jump tz boundaries.
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, (m ?? 1) - 1, d ?? 1);
  dt.setDate(dt.getDate() + deltaDays);
  const yy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

function prettyDayLabel(iso: string): string {
  const today = todayLocalISO();
  if (iso === today) return "Today";
  if (iso === shiftDay(today, -1)) return "Yesterday";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, (m ?? 1) - 1, d ?? 1);
  return dt.toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

function BuildFromDay({ onClose, onPick }: {
  onClose: () => void;
  onPick: (entries: MealEntry[]) => void;
}) {
  const [day, setDay] = useState<string>(shiftDay(todayLocalISO(), -1));
  const dayEntries = useQuery({
    queryKey: ["meals.entries", day],
    queryFn: () => api.todayEntries(day),
  });
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setPicked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const list = (dayEntries.data ?? []).filter(
    e => e.food_name !== "Water" && e.food_name !== "Vitamins",
  );

  const grouped = useMemo(() => {
    const out = new Map<MealSlot, MealEntry[]>();
    for (const s of BUILD_SLOT_ORDER) out.set(s, []);
    for (const e of list) out.get(e.slot)?.push(e);
    return out;
  }, [list]);

  const setDayAndReset = (next: string) => {
    setDay(next);
    setPicked(new Set());
  };
  const onPrev = () => setDayAndReset(shiftDay(day, -1));
  const onNext = () => {
    const today = todayLocalISO();
    if (day < today) setDayAndReset(shiftDay(day, 1));
  };
  const onPickWholeSlot = (slot: MealSlot) => {
    const slotIds = (grouped.get(slot) ?? []).map(e => e.id);
    setPicked(prev => {
      const next = new Set(prev);
      const allOn = slotIds.every(id => next.has(id));
      if (allOn) slotIds.forEach(id => next.delete(id));
      else slotIds.forEach(id => next.add(id));
      return next;
    });
  };

  const atToday = day >= todayLocalISO();

  return (
    <div className="fixed inset-0 z-40 bg-black/70 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="w-full max-w-lg max-h-[92vh] overflow-auto bg-neutral-950 border border-neutral-800 sm:rounded-xl rounded-t-xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">Build from a day</h3>
          <button
            onClick={onClose}
            className="text-neutral-400 active:text-neutral-100 px-2 py-1"
            aria-label="close"
          >
            ✕
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onPrev}
            className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 min-h-[44px] min-w-[44px] text-base"
            aria-label="previous day"
          >
            ‹
          </button>
          <div className="flex-1 flex flex-col items-center">
            <input
              type="date" value={day}
              max={todayLocalISO()}
              onChange={e => setDayAndReset(e.target.value)}
              className="bg-transparent text-center text-base px-2 py-1 rounded"
              aria-label="day"
            />
            <div className="text-xs text-neutral-500 -mt-1">{prettyDayLabel(day)}</div>
          </div>
          <button
            onClick={onNext}
            disabled={atToday}
            className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 min-h-[44px] min-w-[44px] text-base disabled:opacity-30"
            aria-label="next day"
          >
            ›
          </button>
        </div>

        {list.length === 0 ? (
          <div className="text-sm text-neutral-500">Nothing loggable on this day.</div>
        ) : (
          <div className="space-y-3">
            {BUILD_SLOT_ORDER.map(slot => {
              const slotList = grouped.get(slot) ?? [];
              if (slotList.length === 0) return null;
              const slotIds = slotList.map(e => e.id);
              const allOn = slotIds.every(id => picked.has(id));
              return (
                <section key={slot}>
                  <div className="flex items-baseline justify-between mb-1">
                    <div className="text-xs uppercase tracking-wide text-neutral-500">
                      {SLOT_LABEL[slot]}
                    </div>
                    <button
                      onClick={() => onPickWholeSlot(slot)}
                      className="text-[11px] text-neutral-500 active:text-emerald-300 px-1"
                    >
                      {allOn ? "clear" : "select all"}
                    </button>
                  </div>
                  <ul className="divide-y divide-neutral-800 rounded border border-neutral-800 bg-neutral-900">
                    {slotList.map(e => {
                      const on = picked.has(e.id);
                      return (
                        <li key={e.id}>
                          <button
                            onClick={() => toggle(e.id)}
                            className={`w-full text-left px-3 py-3 text-sm min-h-[44px] ${on ? "bg-emerald-900/30" : "active:bg-neutral-800/60"}`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <div className="font-medium truncate">{e.food_name}</div>
                                <div className="text-xs text-neutral-500">
                                  {Math.round(e.quantity_g)}g
                                </div>
                              </div>
                              <span className={`text-lg ${on ? "text-emerald-300" : "text-neutral-600"}`}>
                                {on ? "✓" : "○"}
                              </span>
                            </div>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
        <div className="flex gap-2 sticky bottom-0 pt-2 bg-neutral-950">
          <button
            onClick={() => onPick(list.filter(e => picked.has(e.id)))}
            disabled={picked.size === 0}
            className="flex-1 px-3 py-3 rounded bg-emerald-700 active:bg-emerald-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
          >
            use {picked.size} selected
          </button>
          <button
            onClick={onClose}
            className="px-4 py-3 rounded bg-neutral-800 active:bg-neutral-700 text-sm min-h-[44px]"
          >
            cancel
          </button>
        </div>
      </div>
    </div>
  );
}
