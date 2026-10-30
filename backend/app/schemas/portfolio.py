from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Portfolio name is required.")
        return value


class PortfolioResponse(BaseModel):
    id: int
    name: str
    currency: str
    model_config = ConfigDict(from_attributes=True)


class InstrumentInput(BaseModel):
    asset_type: Literal["stock", "mutual_fund"]
    display_name: str = Field(min_length=1, max_length=240)
    symbol: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9.&-]*$")
    exchange: Literal["NSE", "BSE"] | None = None
    scheme_code: int | None = Field(default=None, gt=0)
    isin: str | None = Field(default=None, min_length=12, max_length=12, pattern=r"^[A-Za-z0-9]{12}$")

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Instrument name is required.")
        return value

    @model_validator(mode="after")
    def require_identifier(self):
        if self.asset_type == "stock" and not self.symbol:
            raise ValueError("A stock symbol is required.")
        if self.asset_type == "mutual_fund" and not self.scheme_code:
            raise ValueError("A mutual-fund scheme code is required.")
        return self


class SIPInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    frequency: Literal["WEEKLY", "MONTHLY", "QUARTERLY"] = "MONTHLY"
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("SIP end date must be on or after its start date.")
        return self


class TransactionCreate(BaseModel):
    instrument: InstrumentInput
    side: Literal["BUY", "SELL"] = "BUY"
    trade_date: date
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=10)
    price_per_unit: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    fees: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    sip_schedule: SIPInput | None = None

    @model_validator(mode="after")
    def validate_trade(self):
        if self.trade_date > date.today():
            raise ValueError("Trade date cannot be in the future.")
        if self.sip_schedule and (self.side != "BUY" or self.instrument.asset_type != "mutual_fund"):
            raise ValueError("A SIP schedule can only be added to a mutual-fund purchase.")
        return self


class TransactionUpdate(BaseModel):
    side: Literal["BUY", "SELL"]
    trade_date: date
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=10)
    price_per_unit: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    fees: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("trade_date")
    @classmethod
    def reject_future_trade(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Trade date cannot be in the future.")
        return value


class InstrumentResponse(BaseModel):
    id: int
    asset_type: str
    display_name: str
    symbol: str | None
    exchange: str | None
    scheme_code: str | None
    isin: str | None
    model_config = ConfigDict(from_attributes=True)


class TransactionResponse(BaseModel):
    id: int
    portfolio_id: int
    side: str
    trade_date: date
    quantity: Decimal | None
    price_per_unit: Decimal | None
    cash_amount: Decimal | None
    fees: Decimal
    notes: str | None
    instrument: InstrumentResponse


class SIPResponse(BaseModel):
    id: int
    portfolio_id: int
    instrument_id: int
    amount: Decimal
    frequency: str
    start_date: date
    end_date: date | None
    is_active: bool
    instrument: InstrumentResponse

    model_config = ConfigDict(from_attributes=True)


class FundAllocationInput(BaseModel):
    instrument_id: int = Field(gt=0)
    snapshot_date: date
    source_label: str = Field(min_length=3, max_length=180)
    source_url: AnyHttpUrl | None = None
    large_cap_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    mid_cap_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    small_cap_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    commodities_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)

    @field_validator("source_label")
    @classmethod
    def trim_source_label(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Source name must contain at least 3 characters.")
        return value

    @model_validator(mode="after")
    def require_allocation_value(self):
        allocations = (self.large_cap_pct, self.mid_cap_pct, self.small_cap_pct, self.commodities_pct)
        if all(value is None for value in allocations):
            raise ValueError("Enter at least one disclosed allocation percentage.")
        if sum((value or Decimal("0") for value in allocations), Decimal("0")) > Decimal("100"):
            raise ValueError("The entered categories cannot total more than 100%.")
        if self.snapshot_date > date.today():
            raise ValueError("Snapshot date cannot be in the future.")
        return self


class FundAllocationResponse(BaseModel):
    id: int
    portfolio_id: int
    instrument_id: int
    snapshot_date: date
    source_label: str
    source_url: str | None
    large_cap_pct: Decimal | None
    mid_cap_pct: Decimal | None
    small_cap_pct: Decimal | None
    commodities_pct: Decimal | None
    instrument: InstrumentResponse

    model_config = ConfigDict(from_attributes=True)
