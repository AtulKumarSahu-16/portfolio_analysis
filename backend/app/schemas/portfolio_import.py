from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ImportRecordInput(BaseModel):
    asset_type: Literal["stock", "mutual_fund"] = "mutual_fund"
    record_type: Literal["transaction", "holding"]
    scheme_name: str = Field(min_length=1, max_length=240)
    symbol: str | None = Field(default=None, max_length=40)
    exchange: str | None = Field(default=None, max_length=12)
    amc_name: str | None = Field(default=None, max_length=180)
    category: str | None = Field(default=None, max_length=120)
    sub_category: str | None = Field(default=None, max_length=160)
    folio_number: str | None = Field(default=None, max_length=80)
    isin: str | None = Field(default=None, min_length=12, max_length=12, pattern=r"^[A-Za-z0-9]{12}$")
    scheme_code: int | None = Field(default=None, gt=0)
    scheme_match_status: Literal["exact", "selected", "unverified", "manual"] | None = None
    identity_status: Literal["verified", "provided", "unverified"] = "unverified"
    transaction_date: date | None = None
    transaction_type: Literal["BUY", "SELL", "DIVIDEND", "FEE"] | None = None
    units: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=10)
    nav: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    average_cost: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    field_sources: dict[str, str] = Field(default_factory=dict)
    current_price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    current_value: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    returns_value: Decimal | None = Field(default=None, max_digits=20, decimal_places=2)
    xirr_pct: Decimal | None = Field(default=None, max_digits=9, decimal_places=4)
    snapshot_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("scheme_name", "amc_name", "category", "sub_category", "folio_number", "notes")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def validate_record(self):
        if not self.scheme_name:
            raise ValueError("Scheme name is required.")
        if self.asset_type == "stock" and self.record_type != "holding":
            raise ValueError("Stock statement rows must be current holdings.")
        if self.record_type == "transaction" and self.asset_type == "mutual_fund" and not self.scheme_code and not self.isin:
            raise ValueError("A scheme code or ISIN is required to identify the fund.")
        if self.record_type == "holding":
            if self.units is None or self.snapshot_date is None:
                raise ValueError("A holding needs units and a statement as-of date.")
            if self.snapshot_date > date.today():
                raise ValueError("Statement as-of date cannot be in the future.")
            if self.transaction_type or self.transaction_date:
                raise ValueError("A current holding cannot also contain transaction fields.")
        else:
            if self.transaction_type in ("BUY", "SELL"):
                if self.transaction_date is None or self.units is None:
                    raise ValueError("A purchase/redemption needs a date and units.")
                if self.transaction_date > date.today():
                    raise ValueError("Transaction date cannot be in the future.")
                if self.nav is None and (self.amount is None or self.units == 0):
                    raise ValueError("A purchase/redemption needs NAV or an amount from which unit price can be derived.")
            elif self.transaction_type in ("DIVIDEND", "FEE"):
                if self.transaction_date is None or self.amount is None:
                    raise ValueError("A dividend/fee needs a date and amount.")
            else:
                raise ValueError("Select a recognized transaction type.")
        return self


class ImportConfirmInput(BaseModel):
    import_id: int = Field(gt=0)
    records: list[ImportRecordInput] = Field(min_length=1, max_length=10000)


class ImportHistoryItem(BaseModel):
    id: int
    file_type: str
    status: str
    total_rows: int
    imported_rows: int
    skipped_duplicates: int
    created_at: str
    confirmed_at: str | None
