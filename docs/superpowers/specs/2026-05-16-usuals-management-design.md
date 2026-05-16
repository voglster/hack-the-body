# Usuals Management — Design

**Date:** 2026-05-16
**Status:** Approved, ready for implementation plan

## Problem

Logging common multi-item meals (yogurt breakfast = protein powder + granola
+ yogurt + chia; "protein coffee" = water + protein drink; almond-milk latte;
protein-bar snack) is currently 3–4 separate food searches every time. The
data model and API for `meal_templates` already support one-click logging of
multi-item bundles, and `UsualsBar` in `TodayMeals.tsx` renders templates as
log buttons — but there is no real UI to **create or manage** templates, so
in practice only one trivial template exists. Today's data shows the yogurt
breakfast logged as 4 separate entries on 10 mornings (40 manual log actions
that should have been 10 taps).

## Goals

- A discoverable, non-cramped surface for creating, editing, and deleting
  meal templates ("usuals").
- Bootstrap the cold-start problem: LLM suggests usuals from the last 30
  days of food log history so the user doesn't have to think about which
  combos to build.
- Keep the daily surfaces (Today, Food tab) unchanged in weight — management
  lives in **More**.

## Non-goals (v1)

- Per-log quantity overrides (long-press tweak then log).
- Compound side-effect templates (a template that also bumps
  `/water/log` or `/vitamins/log`). Water-as-food already covers the
  "protein coffee" case — Water is logged as a food entry today.
- Sharing or syncing usuals across users.

## Placement

- **Entry point:** new row in the **More** tab — `🍱 Usuals` → navigates
  to `/usuals`.
- No new bottom-nav tab. No icon on the daily `UsualsBar`. Management is
  monthly-ish; the daily log surface stays uncluttered.
- `UsualsBar` (one-tap log buttons on the Food tab) is unchanged.

## `/usuals` page layout

Three stacked sections, top to bottom:

### 1. Suggestions (LLM-powered)

- Header "Suggested usuals" + a small **Refresh** button.
- Auto-loads on page open if no cached suggestion exists for today; otherwise
  shows the cached set with a "regenerate" affordance.
- Each suggestion card:
  - Suggested name (LLM-generated, editable inline before save)
  - Slot (LLM-inferred from when the foods are usually logged)
  - Item list (food name · quantity)
  - One-line rationale ("logged together 8 of last 14 breakfasts")
  - Actions: **Save** (creates the template), **Tweak** (opens editor
    pre-filled), **Dismiss** (hides this suggestion for 7 days)
- Empty state when no suggestions: "No new patterns found in the last
  30 days."

### 2. My usuals (CRUD list)

- Grouped by slot (Breakfast / Lunch / Dinner / Snack / Supplement).
- Row: name · item count · macro summary (cal/P/C/F at default quantities).
- Tap row → edit screen.
- Swipe-left or long-press → delete (with confirm).
- Empty state: "No usuals yet. The Suggestions above can build your first
  few in one tap — or start from scratch below."

### 3. New usual (manual creator)

- "+ Build from scratch" button → opens the editor blank.
- "+ Build from a recent day" button → opens a sub-flow:
  - Day picker (default: yesterday)
  - List of that day's `meal_entries` with checkboxes
  - "Save as usual" → opens the editor pre-populated with the selected
    entries' foods + quantities
  - This replaces the buried "save selected as usual" affordance currently
    inside `TodayMeals.tsx`.

## Editor screen

A simple form (its own route or a full-screen modal — implementation choice):

- **Name** (required)
- **Default slot** (dropdown: breakfast / lunch / dinner / snack / supplement)
- **Items** list: each row = food name + quantity input (grams, with a
  servings hint), plus a remove button
- **+ Add food** button opens a sheet with the existing food pickers:
  - search (`/foods/search`)
  - paste-food parser (existing `PasteFood` component)
  - barcode (existing `BarcodeScanner`)
- **Live macro preview** at the bottom — sum of items at current quantities
- **Save** / **Cancel** in a sticky bottom bar

The food-picker bits currently embedded in `TodayMeals.tsx` are refactored
out into a reusable component so both the daily entry flow and this editor
share one picker.

## LLM suggestion service

**Endpoint:** `POST /meals/templates/suggest`

- Auth: `require_api_key` (consistent with other routes)
- No body. Implicit window = last 30 days.
- Response: `{ suggestions: [{ name, slot, items: [{food_id, quantity_g}],
  rationale, source_entry_ids: [...] }], generated_at }`

**Pipeline:**

1. Load all `meal_entries` from the last 30 days.
2. Load all existing `meal_templates`.
3. Pre-filter: keep only foods that appear **≥3 times** in the window.
   Drop one-offs to keep tokens down and noise out.
4. Build a compact prompt for the LLM:
   - The filtered entry list (food name, slot, hour, date) — not the full
     entries.
   - The existing template list (name + items) so the LLM knows what's
     already covered.
   - System instruction: "Identify groups of foods consistently logged
     together at the same slot and similar hour that are NOT already a
     saved usual. Also flag a saved usual that is missing an item the user
     consistently logs alongside it. Return JSON: array of suggestions
     with `name`, `slot`, `items`, `rationale`. Max 5 suggestions. Each
     item's `quantity_g` should be the median quantity from the user's
     history."
5. Call Ollama with `settings.ollama_model` (`glm-4.7-flash:latest`) —
   fast, good results on this kind of structured task. If quality drifts
   later, easy swap to `weekly_ollama_model` (`gpt-oss:120b`).
6. Parse the JSON. Validate every `food_id` exists in `foods`. Cap at 5
   suggestions. Return.

**Caching:** cache the response in `kv_cache` keyed by
`usuals_suggest:{date}` for the rest of the day. The Refresh button busts
the cache.

**Dismissals:** when the user dismisses a suggestion, store the suggestion
signature (sorted list of food_ids + slot) in a `usuals_suggest_dismissed`
collection with a `dismissed_until` timestamp 7 days out. The endpoint
filters these on the way out.

## What changes — file-level

**FE:**
- New `services/web/src/pages/Usuals.tsx`
- New `services/web/src/components/UsualEditor.tsx`
- New `services/web/src/components/UsualSuggestions.tsx`
- New `services/web/src/components/FoodPicker.tsx` (refactored out of
  `TodayMeals.tsx`)
- `services/web/src/components/TodayMeals.tsx` — drop the inline
  save-as-usual UI; keep `UsualsBar` for one-tap logging only. Use the new
  `FoodPicker`.
- `services/web/src/pages/Dashboard.tsx` — add `🍱 Usuals` row in
  `MoreTab` linking to `/usuals`.
- `services/web/src/router.tsx` — register `/usuals`.
- `services/web/src/api/client.ts` — add `suggestTemplates()`,
  `dismissSuggestion(signature)`.

**API:**
- New `services/api/app/routers/meals_suggest.py` (or extend
  `routers/meals.py`) — `POST /meals/templates/suggest`,
  `POST /meals/templates/suggest/dismiss`.
- New `services/api/app/services/usuals_suggest.py` — prompt assembly,
  Ollama call, JSON parse + validation.
- New collection: `usuals_suggest_dismissed` (no schema migration; mongo).

## Testing

- API: unit test for the pre-filter (drops <3-count foods), prompt
  assembly (deterministic given input), JSON parse + validation
  (rejects unknown food_ids), dismissal filter.
- FE: render tests for `Usuals.tsx` empty / populated / suggestion-card
  states; editor save round-trip; "build from recent day" flow.
- No need to test the LLM itself — mock the Ollama HTTP call.

## Open follow-ups (future specs)

- Per-log quantity overrides on the `UsualsBar` (long-press → tweak).
- Templates with cross-domain side-effects (also log water mL / vitamins).
- Suggestion quality: if `glm-4.7-flash` produces noisy groupings, switch
  to `gpt-oss:120b` and benchmark.
