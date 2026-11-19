"""Dated per-tool prices and once-per-account monthly adjustments."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from studio_collector.models import Amount, Identifier, UsageRow


class Price(BaseModel):
    """One immutable price revision, in USD per thousand tool calls."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    effective_from: AwareDatetime
    default: Amount | None = None
    tools: dict[Identifier, Amount | None] = Field(default_factory=dict)
    monthly_fee: Amount = Decimal(0)
    included_calls: Amount = Decimal(0)
    monthly_credit: Amount = Decimal(0)


class Account(BaseModel):
    """One provider billing account; quotas are shared across its tools and callers."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    server: Identifier
    billing_account: Identifier
    billing_timezone: str = "UTC"
    billing_day: int = Field(default=1, ge=1, le=28)
    # True only when the configured gateway covers this account's entire usage.
    complete_account_usage: bool = False
    # Only tools qualified as one provider billing unit per native tool call.
    verified_call_units: list[Identifier] = Field(default_factory=list)
    prices: list[Price] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered(self) -> Account:
        """Reject ambiguous schedules instead of silently changing historic rates."""
        ZoneInfo(self.billing_timezone)
        instants = [price.effective_from for price in self.prices]
        if instants != sorted(set(instants)):
            raise ValueError("Prices must have unique, increasing effective dates")  # noqa: TRY003
        return self

    def at(self, instant: datetime) -> Price | None:
        """Resolve the revision effective at usage time."""
        return next((p for p in reversed(self.prices) if p.effective_from <= instant), None)


class Catalogue(BaseModel):
    """Client-owned price configuration; absent pricing is never inferred as free."""

    model_config = ConfigDict(extra="forbid")
    accounts: list[Account] = Field(default_factory=list, max_length=200)
    default_rate: Amount | None = None

    @model_validator(mode="after")
    def unique(self) -> Catalogue:
        """Each collected server maps to exactly one billing account."""
        if len({a.server for a in self.accounts}) != len(self.accounts):
            raise ValueError("Duplicate pricing server")  # noqa: TRY003
        if len({a.billing_account for a in self.accounts}) != len(self.accounts):
            raise ValueError("Duplicate billing account")  # noqa: TRY003
        return self

    def apply(self, row: UsageRow, instant: datetime) -> UsageRow:
        """Snapshot the selected rate, preserving an explicit unknown tool override."""
        account = next((a for a in self.accounts if a.server == row.dimensions.server), None)
        if account is None:
            rate = self.default_rate
            return row.model_copy(
                update={
                    "rate": rate,
                    "cost_usd": row.requests * rate / 1000 if rate is not None else Decimal(0),
                    "cost_known": row.requests if rate is not None else Decimal(0),
                }
            )
        if (price := account.at(instant)) is None:
            return row
        rate = price.tools.get(row.dimensions.tool or "", price.default)
        revision = hashlib.sha256(price.model_dump_json().encode()).hexdigest()
        return row.model_copy(
            update={
                "rate": rate,
                "price_revision": revision,
                "billing_account": account.billing_account,
                "cost_usd": row.requests * rate / 1000 if rate is not None else Decimal(0),
                "cost_known": row.requests if rate is not None else Decimal(0),
            }
        )

    def at(self, instant: datetime) -> Catalogue:
        """Keep effective prices or the first future price to prevent free fallback."""
        return Catalogue(
            default_rate=self.default_rate,
            accounts=[
                account.model_copy(update={"prices": [account.at(instant) or account.prices[0]]})
                for account in self.accounts
            ],
        )


def monthly_cost(price: Price, calls: Decimal, gross_cost: Decimal) -> Decimal:
    """Apply one shared allowance, credit and fee without negative usage charges."""
    # Included calls are allocated proportionally across tools at their actual rates.
    included_fraction = min(Decimal(1), price.included_calls / calls) if calls else Decimal(0)
    usage = gross_cost * (1 - included_fraction)
    return price.monthly_fee + max(Decimal(0), usage - price.monthly_credit)


def billing_period(account: Account, day: date) -> tuple[datetime, datetime]:
    """Find the account's calendar billing cycle containing the supplied date."""
    from studio_collector.calendar import midnight

    first = day.replace(day=account.billing_day)
    if day < first:
        first = (
            first.replace(year=first.year - 1, month=12)
            if first.month == 1
            else (first.replace(month=first.month - 1))
        )
    after = (
        first.replace(year=first.year + 1, month=1)
        if first.month == 12
        else (first.replace(month=first.month + 1))
    )
    timezone = ZoneInfo(account.billing_timezone)
    return midnight(first, timezone), midnight(after, timezone)


class ProviderEstimate(BaseModel):
    """Gross tool costs and adjusted account estimate are alternative views."""

    billing_account: str
    server: str
    period_start: datetime
    period_end: datetime
    gross_usage_usd: Decimal
    adjusted_estimate_usd: Decimal | None
    complete: bool
    estimated: bool = True
