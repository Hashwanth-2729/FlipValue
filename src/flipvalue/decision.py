"""Repair-versus-sell arithmetic. Transparent sums only: no forecasting, no time value, no guarantee.

net proceeds (sell as-is)        = as-is value - selling fees - fixed selling costs
net proceeds (repair, then sell) = after-repair value - repair cost - selling fees - fixed selling costs
advantage of repairing first     = net (repair, then sell) - net (sell as-is)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from flipvalue.schemas import Money


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(pattern=r"^(INR|USD)$")
    as_is_value: Money | None = Field(default=None, ge=0, le=10_000_000)
    after_repair_value: Money | None = Field(default=None, ge=0, le=10_000_000)
    repair_cost: Money | None = Field(default=None, ge=0, le=10_000_000)
    repair_cost_basis: Literal["user_supplied", "estimated", "verified_quote"] = "user_supplied"
    selling_fee_pct: Money = Field(default=Decimal("0"), ge=0, le=50)
    selling_fixed_cost: Money = Field(default=Decimal("0"), ge=0, le=1_000_000)
    replacement_price: Money | None = Field(default=None, ge=0, le=10_000_000)


class Scenario(BaseModel):
    key: str
    title: str
    available: bool
    missing: list[str]
    gross: Money | None = None
    selling_fees: Money | None = None
    other_costs: Money | None = None
    net: Money | None = None
    explanation: str


class DecisionResult(BaseModel):
    currency: str
    scenarios: list[Scenario]
    repair_first_advantage: Money | None
    assumptions: list[str]


def _r(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decide(d: DecisionInput) -> DecisionResult:
    fee_rate = d.selling_fee_pct / Decimal(100)

    def sale(gross: Decimal, extra: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        fees = _r(gross * fee_rate)
        costs = _r(d.selling_fixed_cost + extra)
        return fees, costs, _r(gross - fees - costs)

    scenarios: list[Scenario] = []
    if d.as_is_value is not None:
        fees, costs, net = sale(d.as_is_value, Decimal(0))
        scenarios.append(Scenario(key="sell_as_is", title="Sell as-is", available=True, missing=[],
                                  gross=_r(d.as_is_value), selling_fees=fees, other_costs=costs, net=net,
                                  explanation="As-is value minus selling fees and fixed selling costs."))
    else:
        scenarios.append(Scenario(key="sell_as_is", title="Sell as-is", available=False,
                                  missing=["as-is value"], explanation="No as-is value is available."))

    missing = [n for n, v in (("after-repair value", d.after_repair_value), ("repair cost", d.repair_cost))
               if v is None]
    if not missing:
        assert d.after_repair_value is not None and d.repair_cost is not None
        fees, costs, net = sale(d.after_repair_value, d.repair_cost)
        scenarios.append(Scenario(key="repair_then_sell", title="Repair, then sell", available=True, missing=[],
                                  gross=_r(d.after_repair_value), selling_fees=fees, other_costs=costs, net=net,
                                  explanation="After-repair value minus repair cost, selling fees and fixed "
                                              "selling costs."))
    else:
        scenarios.append(Scenario(key="repair_then_sell", title="Repair, then sell", available=False,
                                  missing=missing, explanation="Needs " + " and ".join(missing) + "."))

    if d.repair_cost is not None:
        scenarios.append(Scenario(key="repair_and_keep", title="Repair and keep", available=True, missing=[],
                                  other_costs=_r(d.repair_cost), net=_r(-d.repair_cost),
                                  explanation="You pay the repair cost and keep using the phone."))
    else:
        scenarios.append(Scenario(key="repair_and_keep", title="Repair and keep", available=False,
                                  missing=["repair cost"], explanation="Needs a repair cost."))

    if d.replacement_price is not None and d.as_is_value is not None:
        _, _, as_is_net = sale(d.as_is_value, Decimal(0))
        scenarios.append(Scenario(key="sell_and_replace", title="Sell as-is and buy a replacement", available=True,
                                  missing=[], gross=_r(d.as_is_value), other_costs=_r(d.replacement_price),
                                  net=_r(as_is_net - d.replacement_price),
                                  explanation="Net sale proceeds minus the replacement phone's price."))
    else:
        need = [n for n, v in (("replacement price", d.replacement_price), ("as-is value", d.as_is_value))
                if v is None]
        scenarios.append(Scenario(key="sell_and_replace", title="Sell as-is and buy a replacement",
                                  available=False, missing=need, explanation="Needs " + " and ".join(need) + "."))

    by_key = {s.key: s for s in scenarios}
    a, b = by_key["sell_as_is"], by_key["repair_then_sell"]
    advantage = _r(b.net - a.net) if a.net is not None and b.net is not None else None

    basis_label = {"user_supplied": "entered by you", "estimated": "an estimate",
                   "verified_quote": "a verified quote"}[d.repair_cost_basis]
    assumptions = [
        "Resale values are gross expected sale prices before selling fees.",
        f"Selling fees: {d.selling_fee_pct}% of the sale price, plus fixed costs of {d.selling_fixed_cost} "
        f"{d.currency}.",
        "No allowance for time, risk that a repair fails, or price changes while you wait.",
        "A repair does not necessarily raise the resale value by the repair cost.",
    ]
    if d.repair_cost is not None:
        assumptions.insert(2, f"Repair cost is {basis_label}.")
    return DecisionResult(currency=d.currency, scenarios=scenarios, repair_first_advantage=advantage,
                          assumptions=assumptions)
