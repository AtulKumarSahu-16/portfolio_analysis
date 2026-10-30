from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db import get_session
from app.models import FundAllocationSnapshot, ImportedHoldingSnapshot, Instrument, InstrumentMarketDataSnapshot, MarketDataRefreshRun, Portfolio, PortfolioTransaction, SIPSchedule, User
from app.schemas.portfolio import (
    FundAllocationInput,
    FundAllocationResponse,
    InstrumentResponse,
    PortfolioCreate,
    PortfolioResponse,
    SIPResponse,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from app.services import market_data_service

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


async def _owned_portfolio(session: AsyncSession, portfolio_id: int, user_id: int, *, lock: bool = False) -> Portfolio:
    query = select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.owner_id == user_id)
    if lock:
        query = query.with_for_update()
    portfolio = await session.scalar(query)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found.")
    return portfolio


def _ensure_nonnegative_position(transactions: list[PortfolioTransaction]) -> None:
    units = Decimal("0")
    for transaction in sorted(transactions, key=lambda item: (item.trade_date, item.id if item.id is not None else float("inf"))):
        quantity = transaction.quantity or Decimal("0")
        units += quantity if transaction.side == "BUY" else -quantity
        if units < 0:
            raise HTTPException(status_code=422, detail="A sale cannot exceed the units held on that date.")


@router.get("", response_model=list[PortfolioResponse])
async def list_portfolios(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Portfolio).where(Portfolio.owner_id == user.id).order_by(Portfolio.created_at, Portfolio.id))
    return list(result.all())


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(data: PortfolioCreate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    portfolio = Portfolio(owner_id=user.id, name=data.name, currency="INR")
    session.add(portfolio)
    await session.commit()
    await session.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}/transactions", response_model=list[TransactionResponse])
async def list_transactions(
    portfolio_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    result = await session.scalars(
        select(PortfolioTransaction)
        .options(selectinload(PortfolioTransaction.instrument))
        .where(PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(PortfolioTransaction.trade_date.desc(), PortfolioTransaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.all())


@router.post("/{portfolio_id}/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    portfolio_id: int,
    data: TransactionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id, lock=True)
    asset = data.instrument
    provider = "IndianAPI" if asset.asset_type == "stock" else "MFNAV"
    provider_id = asset.symbol.strip().upper() if asset.asset_type == "stock" else str(asset.scheme_code)
    instrument = await session.scalar(
        select(Instrument).where(Instrument.provider == provider, Instrument.provider_instrument_id == provider_id)
    )
    if instrument is None:
        instrument = Instrument(
            asset_type=asset.asset_type,
            display_name=asset.display_name,
            symbol=asset.symbol.strip().upper() if asset.symbol else None,
            exchange=asset.exchange,
            scheme_code=str(asset.scheme_code) if asset.scheme_code else None,
            isin=asset.isin.upper() if asset.isin else None,
            provider=provider,
            provider_instrument_id=provider_id,
        )
        session.add(instrument)
        await session.flush()
    elif instrument.asset_type != asset.asset_type:
        raise HTTPException(status_code=409, detail="The provider instrument identifier is already assigned to another asset type.")

    existing = list((await session.scalars(
        select(PortfolioTransaction)
        .where(PortfolioTransaction.portfolio_id == portfolio_id, PortfolioTransaction.instrument_id == instrument.id)
        .order_by(PortfolioTransaction.trade_date, PortfolioTransaction.id)
    )).all())
    transaction = PortfolioTransaction(
        portfolio_id=portfolio_id,
        instrument_id=instrument.id,
        side=data.side,
        trade_date=data.trade_date,
        quantity=data.quantity,
        price_per_unit=data.price_per_unit,
        fees=data.fees,
        notes=data.notes.strip() if data.notes else None,
    )
    _ensure_nonnegative_position([*existing, transaction])
    session.add(transaction)
    if data.sip_schedule:
        schedule = SIPSchedule(
            portfolio_id=portfolio_id,
            instrument_id=instrument.id,
            amount=data.sip_schedule.amount,
            frequency=data.sip_schedule.frequency,
            start_date=data.sip_schedule.start_date,
            end_date=data.sip_schedule.end_date,
            is_active=True,
        )
        session.add(schedule)
    await session.commit()
    await session.refresh(transaction, attribute_names=["instrument"])
    return transaction


@router.put("/{portfolio_id}/transactions/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    portfolio_id: int,
    transaction_id: int,
    data: TransactionUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id, lock=True)
    transaction = await session.scalar(
        select(PortfolioTransaction)
        .options(selectinload(PortfolioTransaction.instrument))
        .where(PortfolioTransaction.id == transaction_id, PortfolioTransaction.portfolio_id == portfolio_id)
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    previous = list((await session.scalars(
        select(PortfolioTransaction).where(
            PortfolioTransaction.portfolio_id == portfolio_id,
            PortfolioTransaction.instrument_id == transaction.instrument_id,
            PortfolioTransaction.id != transaction_id,
        )
    )).all())
    candidate = PortfolioTransaction(
        id=transaction.id,
        trade_date=data.trade_date,
        side=data.side,
        quantity=data.quantity,
    )
    _ensure_nonnegative_position([*previous, candidate])
    transaction.side = data.side
    transaction.trade_date = data.trade_date
    transaction.quantity = data.quantity
    transaction.price_per_unit = data.price_per_unit
    transaction.fees = data.fees
    transaction.notes = data.notes.strip() if data.notes else None
    await session.commit()
    await session.refresh(transaction, attribute_names=["instrument"])
    return transaction


@router.delete("/{portfolio_id}/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    portfolio_id: int,
    transaction_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id, lock=True)
    transaction = await session.scalar(
        select(PortfolioTransaction).where(PortfolioTransaction.id == transaction_id, PortfolioTransaction.portfolio_id == portfolio_id)
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    await session.delete(transaction)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{portfolio_id}/sip-schedules", response_model=list[SIPResponse])
async def list_sip_schedules(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    result = await session.scalars(
        select(SIPSchedule)
        .options(selectinload(SIPSchedule.instrument))
        .where(SIPSchedule.portfolio_id == portfolio_id)
        .order_by(SIPSchedule.start_date.desc(), SIPSchedule.id.desc())
    )
    return list(result.all())


async def _current_quote(request: Request, settings: Settings, session: AsyncSession, instrument: Instrument) -> dict:
    snapshot = await session.get(InstrumentMarketDataSnapshot, instrument.id)
    if snapshot is None:
        snapshot = await market_data_service.refresh_instrument_snapshot(session, request.app.state.http, settings, instrument)
        await session.commit()
    return {**market_data_service.snapshot_payload(snapshot), "price": Decimal(str(snapshot.price))}


@router.get("/{portfolio_id}/holdings")
async def get_holdings(
    portfolio_id: int,
    request: Request,
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    result = await session.scalars(
        select(PortfolioTransaction)
        .options(selectinload(PortfolioTransaction.instrument))
        .where(PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(PortfolioTransaction.trade_date, PortfolioTransaction.id)
    )
    grouped = defaultdict(list)
    for transaction in result.all():
        grouped[(transaction.instrument_id, transaction.folio_reference or "no-folio")].append(transaction)

    snapshot_result = await session.scalars(
        select(ImportedHoldingSnapshot)
        .options(selectinload(ImportedHoldingSnapshot.instrument))
        .where(ImportedHoldingSnapshot.portfolio_id == portfolio_id)
        .order_by(ImportedHoldingSnapshot.instrument_id, ImportedHoldingSnapshot.snapshot_date.desc(), ImportedHoldingSnapshot.id.desc())
    )
    latest_snapshots = {}
    for snapshot in snapshot_result.all():
        latest_snapshots.setdefault((snapshot.instrument_id, snapshot.folio_reference or "no-folio"), snapshot)
    latest_snapshot_date_by_instrument = {}
    for snapshot in latest_snapshots.values():
        latest_snapshot_date_by_instrument[snapshot.instrument_id] = max(
            latest_snapshot_date_by_instrument.get(snapshot.instrument_id, snapshot.snapshot_date),
            snapshot.snapshot_date,
        )

    items = []
    total_cost_basis = Decimal("0")
    total_cost_basis_complete = True
    total_current_value = Decimal("0")
    valuation_complete = True
    latest_market_date = None
    position_keys = set(grouped) | set(latest_snapshots)
    for instrument_id, folio_reference in sorted(position_keys):
        transactions = grouped.get((instrument_id, folio_reference), [])
        snapshot = latest_snapshots.get((instrument_id, folio_reference))
        if snapshot is None and folio_reference == "no-folio":
            baseline_date = latest_snapshot_date_by_instrument.get(instrument_id)
            if baseline_date:
                transactions = [transaction for transaction in transactions if transaction.trade_date > baseline_date]
        instrument = snapshot.instrument if snapshot else transactions[0].instrument
        units = snapshot.quantity if snapshot else Decimal("0")
        cost_basis = snapshot.invested_amount if snapshot and snapshot.invested_amount is not None else Decimal("0")
        cost_basis_known = snapshot is None or snapshot.invested_amount is not None
        for transaction in transactions:
            if snapshot and transaction.trade_date <= snapshot.snapshot_date:
                continue
            quantity = transaction.quantity or Decimal("0")
            price = transaction.price_per_unit or Decimal("0")
            if transaction.side == "BUY":
                cost_basis += quantity * price + transaction.fees
                units += quantity
            elif transaction.side == "SELL" and units > 0:
                if cost_basis_known:
                    average_cost = cost_basis / units
                    cost_basis = max(Decimal("0"), cost_basis - average_cost * quantity)
                units -= quantity
        if units <= 0:
            continue
        if cost_basis_known:
            total_cost_basis += cost_basis
        else:
            total_cost_basis_complete = False
        quote = None
        quote_error = None
        try:
            quote = await _current_quote(request, settings, session, instrument)
        except HTTPException as exc:
            quote_error = "identity_unverified" if (instrument.asset_type == "mutual_fund" and not instrument.scheme_code) or (instrument.asset_type == "stock" and not instrument.symbol) else "not_configured" if exc.status_code == 503 else "rate_limited" if exc.status_code == 429 else "unavailable"
        current_value = units * quote["price"] if quote else None
        if quote is None:
            valuation_complete = False
        else:
            total_current_value += current_value
            latest_market_date = max(latest_market_date, quote["price_date"]) if latest_market_date else quote["price_date"]
        profit_loss = current_value - cost_basis if current_value is not None and cost_basis_known else None
        return_pct = (profit_loss / cost_basis * Decimal("100")) if profit_loss is not None and cost_basis > 0 else None
        items.append({
            "instrument": {
                "id": instrument.id,
                "asset_type": instrument.asset_type,
                "display_name": instrument.display_name,
                "symbol": instrument.symbol,
                "exchange": instrument.exchange,
                "scheme_code": instrument.scheme_code,
                "isin": instrument.isin,
                "amc_name": instrument.amc_name,
                "category": instrument.category,
                "sub_category": instrument.sub_category,
                "identity_status": instrument.identity_status,
            },
            "quantity": str(units),
            "cost_basis": str(cost_basis) if cost_basis_known else None,
            "current_price": str(quote["price"]) if quote else None,
            "average_buy_price": str(snapshot.average_buy_price) if snapshot and snapshot.average_buy_price is not None else (str(cost_basis / units) if cost_basis_known and units > 0 else None),
            "current_value": str(current_value) if current_value is not None else None,
            "profit_loss": str(profit_loss) if profit_loss is not None else None,
            "return_pct": str(return_pct) if return_pct is not None else None,
            "price_date": quote["price_date"] if quote else None,
            "price_timestamp": quote.get("price_timestamp") if quote else None,
            "queried_at": quote.get("queried_at") if quote else None,
            "source": quote["source"] if quote else None,
            "data_status": quote.get("data_status") if quote else "unavailable",
            "valuation_status": "available" if quote else quote_error,
            "statement_as_of_date": snapshot.snapshot_date.isoformat() if snapshot else None,
            "folio_last4": snapshot.folio_last4 if snapshot else None,
            "returns_value": str(snapshot.returns_value) if snapshot and snapshot.returns_value is not None else None,
            "xirr_pct": str(snapshot.xirr_pct) if snapshot and snapshot.xirr_pct is not None else None,
            "position_key": f"{instrument.id}:{folio_reference}",
            "valuation_source": "previous_close" if quote and instrument.asset_type == "stock" else "latest_nav" if quote else None,
        })
    total_profit_loss = total_current_value - total_cost_basis if valuation_complete and total_cost_basis_complete else None
    total_return_pct = (total_profit_loss / total_cost_basis * Decimal("100")) if total_profit_loss is not None and total_cost_basis > 0 else None
    last_refresh = await session.scalar(
        select(MarketDataRefreshRun)
        .where(MarketDataRefreshRun.status == "completed", MarketDataRefreshRun.finished_at.is_not(None))
        .order_by(MarketDataRefreshRun.finished_at.desc(), MarketDataRefreshRun.id.desc())
        .limit(1)
    )
    last_refresh_at = last_refresh.finished_at if last_refresh else None
    if last_refresh_at is not None and last_refresh_at.tzinfo is None:
        from datetime import timezone
        last_refresh_at = last_refresh_at.replace(tzinfo=timezone.utc)
    return {
        "items": items,
        "total_cost_basis": str(total_cost_basis) if total_cost_basis_complete else None,
        "cost_basis_complete": total_cost_basis_complete,
        "current_value": str(total_current_value) if valuation_complete else None,
        "valuation_complete": valuation_complete,
        "profit_loss": str(total_profit_loss) if total_profit_loss is not None else None,
        "return_pct": str(total_return_pct) if total_return_pct is not None else None,
        "data_status": "unavailable" if not valuation_complete else "delayed" if any(item["data_status"] == "delayed" for item in items) else "updated",
        "latest_market_data_date": latest_market_date,
        "last_successful_refresh_at": last_refresh_at.isoformat() if last_refresh_at else None,
    }


async def _portfolio_fund_instruments(session: AsyncSession, portfolio_id: int) -> list[Instrument]:
    result = await session.scalars(
        select(Instrument)
        .join(PortfolioTransaction, PortfolioTransaction.instrument_id == Instrument.id)
        .where(PortfolioTransaction.portfolio_id == portfolio_id, Instrument.asset_type == "mutual_fund")
        .distinct()
        .order_by(Instrument.display_name)
    )
    return list(result.all())


async def _latest_fund_allocations(session: AsyncSession, portfolio_id: int) -> list[FundAllocationSnapshot]:
    result = await session.scalars(
        select(FundAllocationSnapshot)
        .options(selectinload(FundAllocationSnapshot.instrument))
        .where(FundAllocationSnapshot.portfolio_id == portfolio_id)
        .order_by(FundAllocationSnapshot.instrument_id, FundAllocationSnapshot.snapshot_date.desc(), FundAllocationSnapshot.id.desc())
    )
    latest: dict[int, FundAllocationSnapshot] = {}
    for row in result.all():
        latest.setdefault(row.instrument_id, row)
    return list(latest.values())


@router.get("/{portfolio_id}/fund-allocations")
async def list_fund_allocations(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    instruments = await _portfolio_fund_instruments(session, portfolio_id)
    latest = {row.instrument_id: row for row in await _latest_fund_allocations(session, portfolio_id)}
    return {
        "funds": [
            {
                "instrument": InstrumentResponse.model_validate(instrument).model_dump(mode="json"),
                "allocation": FundAllocationResponse.model_validate(latest[instrument.id]).model_dump(mode="json")
                if instrument.id in latest else None,
            }
            for instrument in instruments
        ]
    }


@router.post("/{portfolio_id}/fund-allocations", response_model=FundAllocationResponse, status_code=status.HTTP_201_CREATED)
async def save_fund_allocation(
    portfolio_id: int,
    data: FundAllocationInput,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id, lock=True)
    instrument = await session.scalar(
        select(Instrument)
        .join(PortfolioTransaction, PortfolioTransaction.instrument_id == Instrument.id)
        .where(
            PortfolioTransaction.portfolio_id == portfolio_id,
            Instrument.id == data.instrument_id,
            Instrument.asset_type == "mutual_fund",
        )
    )
    if instrument is None:
        raise HTTPException(status_code=404, detail="Mutual fund not found in this portfolio.")

    snapshot = await session.scalar(
        select(FundAllocationSnapshot).where(
            FundAllocationSnapshot.portfolio_id == portfolio_id,
            FundAllocationSnapshot.instrument_id == instrument.id,
            FundAllocationSnapshot.snapshot_date == data.snapshot_date,
        )
    )
    values = {
        "source_label": data.source_label,
        "source_url": str(data.source_url) if data.source_url else None,
        "large_cap_pct": data.large_cap_pct,
        "mid_cap_pct": data.mid_cap_pct,
        "small_cap_pct": data.small_cap_pct,
        "commodities_pct": data.commodities_pct,
    }
    if snapshot is None:
        snapshot = FundAllocationSnapshot(
            portfolio_id=portfolio_id,
            instrument_id=instrument.id,
            snapshot_date=data.snapshot_date,
            **values,
        )
        session.add(snapshot)
    else:
        for key, value in values.items():
            setattr(snapshot, key, value)
    await session.commit()
    result = await session.scalar(
        select(FundAllocationSnapshot)
        .options(selectinload(FundAllocationSnapshot.instrument))
        .where(FundAllocationSnapshot.id == snapshot.id)
    )
    return result


@router.get("/{portfolio_id}/fund-allocations/overlap")
async def get_fund_allocation_overlap(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    instruments = await _portfolio_fund_instruments(session, portfolio_id)
    latest = {row.instrument_id: row for row in await _latest_fund_allocations(session, portfolio_id)}
    allocations = [
        {
            "instrument_id": instrument.id,
            "scheme_code": instrument.scheme_code,
            "scheme_name": instrument.display_name,
            "allocation": latest.get(instrument.id),
        }
        for instrument in instruments
    ]
    categories = ("large_cap_pct", "mid_cap_pct", "small_cap_pct", "commodities_pct")
    pairs = []
    for index, left in enumerate(allocations):
        for right in allocations[index + 1:]:
            a = left["allocation"]
            b = right["allocation"]
            comparable = a is not None and b is not None and a.snapshot_date == b.snapshot_date
            overlap = {}
            for category in categories:
                a_value = getattr(a, category, None) if a is not None else None
                b_value = getattr(b, category, None) if b is not None else None
                overlap[category] = str(min(a_value, b_value)) if comparable and a_value is not None and b_value is not None else None
            pairs.append({
                "fund_a": {"instrument_id": left["instrument_id"], "scheme_name": left["scheme_name"], "snapshot_date": a.snapshot_date.isoformat() if a else None},
                "fund_b": {"instrument_id": right["instrument_id"], "scheme_name": right["scheme_name"], "snapshot_date": b.snapshot_date.isoformat() if b else None},
                "comparable": comparable,
                "overlap_pct": overlap,
            })
    return {
        "funds": [
            {
                "instrument_id": item["instrument_id"],
                "scheme_code": item["scheme_code"],
                "scheme_name": item["scheme_name"],
                "allocation": FundAllocationResponse.model_validate(item["allocation"]).model_dump(mode="json") if item["allocation"] else None,
            }
            for item in allocations
        ],
        "pairs": pairs,
        "method": "For each category, shared allocation is min(fund A percentage, fund B percentage); this is allocation similarity, not security-level holdings overlap.",
    }
