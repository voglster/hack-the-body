"""Food, meal entry, and meal template models.

Design notes:
- A `Food` is a canonical, normalized record. Macros are stored per 100g for
  packaged foods (matching Open Food Facts) so we can compute totals at any
  serving size. For ingredients with no natural weight (1 multivitamin), use
  `serving_g=1` and set `serving_label="1 capsule"`.
- A `MealEntry` is a logged consumption: foreign-keys a food + a quantity in
  grams, plus a meal slot (breakfast / lunch / dinner / snack / supplement).
- A `MealTemplate` is a named bundle: list of (food_id, qty_g) pairs the user
  routinely eats together. One-click logging creates N MealEntry rows.
- Supplements live in `foods` with `category="supplement"`. Same data model;
  the dashboard groups them separately.
"""
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FoodCategory = Literal["food", "supplement", "drink"]
MealSlot = Literal["breakfast", "lunch", "dinner", "snack", "supplement"]


class Macros(BaseModel):
    """Macros per 100g (or per-serving for supplements where serving_g=1)."""
    model_config = ConfigDict(extra="forbid")
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    sugar_g: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)


class Food(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None)  # mongo _id, set by repo
    name: str = Field(min_length=1)
    brand: str | None = None
    barcode: str | None = None
    category: FoodCategory = "food"
    serving_g: float = Field(default=100.0, gt=0)
    serving_label: str | None = None  # "1 cup", "1 capsule", "1 scoop"
    per_serving: Macros = Field(default_factory=Macros)
    micros: dict[str, float] = Field(default_factory=dict)  # vitamin/mineral name -> amount in unit
    source: str = "manual"  # "off" (open food facts), "manual", "import"
    source_ref: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MealEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None)
    ts: datetime
    food_id: str
    food_name: str  # denormalized for display without join
    food_category: FoodCategory = "food"
    quantity_g: float = Field(gt=0)
    servings: float | None = None  # convenience: quantity_g / food.serving_g at log time
    slot: MealSlot
    template_id: str | None = None  # if logged from a template
    note: str | None = None
    # Snapshot of macros at log time so historical totals don't shift if the
    # food record is later edited.
    macros: Macros = Field(default_factory=Macros)


class MealTemplateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    food_id: str
    quantity_g: float = Field(gt=0)


class MealTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None)
    name: str = Field(min_length=1)
    description: str | None = None
    default_slot: MealSlot = "snack"
    items: list[MealTemplateItem] = Field(default_factory=list, min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
