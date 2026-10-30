from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db import get_session
from app.models import ImportedHoldingSnapshot, Instrument, Portfolio, PortfolioImport, PortfolioTransaction, User
from app.schemas.portfolio_import import ImportConfirmInput, ImportHistoryItem
from app.services import mutual_fund_service
from app.services import stock_service
from app.services.statement_import_service import (
    MAX_IMPORT_BYTES,
    IncorrectPdfPassword,
    ImportParseError,
    PasswordRequired,
    file_digest,
    parse_statement,
)

router = APIRouter(prefix="/portfolios/{portfolio_id}/imports", tags=["portfolio imports"])


def _normal(value: object | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _scheme_terms(value: object | None) -> tuple[str, ...]:
    ignored = {
        "fund", "plan", "option", "direct", "regular", "growth", "idcw",
        "dividend", "payout", "reinvestment", "reinvest",
    }
    return tuple(token for token in _normal(value).split() if token not in ignored)


def _scheme_plan(name: object | None, plan_type: object | None = None) -> str | None:
    value = _normal(plan_type or name)
    if "direct" in value.split():
        return "direct"
    if "regular" in value.split():
        return "regular"
    return None


def _scheme_option(name: object | None, option_type: object | None = None) -> str | None:
    value = _normal(option_type or name)
    tokens = set(value.split())
    if tokens & {"idcw", "dividend", "payout", "reinvestment", "reinvest"}:
        return "idcw"
    if "growth" in tokens:
        return "growth"
    return None


def _amc_key(value: object | None) -> str:
    ignored = {"mutual", "fund", "funds", "asset", "management", "company", "limited", "ltd", "amc", "the"}
    return " ".join(token for token in _normal(value).split() if token not in ignored)


def _normal_amc(value: object | None) -> str:
    return _amc_key(value)


def _scheme_identity_matches(statement_name: object, candidate: dict) -> bool:
    if _scheme_terms(statement_name) != _scheme_terms(candidate.get("scheme_name")):
        return False
    statement_plan = _scheme_plan(statement_name)
    candidate_plan = _scheme_plan(candidate.get("scheme_name"), candidate.get("plan_type"))
    if statement_plan and statement_plan != candidate_plan:
        return False
    statement_option = _scheme_option(statement_name)
    candidate_option = _scheme_option(candidate.get("scheme_name"), candidate.get("option_type"))
    if statement_option and statement_option != candidate_option:
        return False
    return True


def _scheme_matches(statement_name: object, statement_amc: object, candidate: dict) -> bool:
    return (
        _scheme_identity_matches(statement_name, candidate)
        and bool(_amc_key(statement_amc))
        and _amc_key(statement_amc) == _amc_key(candidate.get("fund_house") or candidate.get("amc_name"))
    )


def _scheme_search_queries(name: str) -> list[str]:
    raw = " ".join(_normal(name).split())
    ignored = {"fund", "plan", "option", "direct", "regular", "growth", "idcw", "dividend", "payout", "reinvestment", "reinvest"}
    base = " ".join(token for token in _normal(name).split() if token not in ignored)
    queries = [raw]
    if len(base) >= 3 and base != raw:
        queries.append(base)
    return list(dict.fromkeys(query for query in queries if len(query) >= 2))


def _folio_key(value: str | None) -> tuple[str, str | None]:
    normalized = re.sub(r"\s+", "", value or "").casefold()
    if not normalized:
        return "no-folio", None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), normalized[-4:]


async def _match_schemes(request: Request, settings: Settings, record: dict) -> dict:
    name = record.get("scheme_name")
    amc = record.get("amc_name")
    record.update(scheme_candidates=[], scheme_match_status="unverified")
    if not name:
        record["scheme_match_message"] = "Scheme name is needed for automatic scheme matching. You can still import this holding as unverified."
        return record
    try:
        candidate_by_code = {}
        successful_search = False
        for query in _scheme_search_queries(name):
            try:
                result = await mutual_fund_service.search_funds(request.app.state.http, settings, query, 1, 250)
                successful_search = True
            except HTTPException:
                continue
            for fund in result.get("results", []):
                if not isinstance(fund, dict) or not fund.get("scheme_code") or not fund.get("scheme_name"):
                    continue
                code = str(fund["scheme_code"])
                candidate_by_code[code] = {
                    "scheme_code": fund["scheme_code"],
                    "scheme_name": fund["scheme_name"],
                    "fund_house": fund.get("fund_house") or fund.get("amc_name"),
                    "isin": fund.get("isin"),
                    "plan_type": fund.get("plan_type"),
                    "option_type": fund.get("option_type"),
                    "category": fund.get("category"),
                    "sub_category": fund.get("sub_category"),
                }
            if amc and any(_scheme_matches(name, amc, candidate) for candidate in candidate_by_code.values()):
                break
        if not successful_search:
            raise HTTPException(status_code=502, detail="MFNAV lookup failed.")
        candidates = list(candidate_by_code.values())
    except HTTPException:
        record["scheme_match_message"] = "MFNAV scheme lookup is unavailable. You can still import this holding as unverified."
        return record
    exact = [candidate for candidate in candidates if _scheme_matches(name, amc, candidate)]
    if len(exact) == 1:
        selected = exact[0]
        record.update(
            scheme_code=selected["scheme_code"], isin=selected["isin"], scheme_match_status="exact",
            identity_status="verified", category=record.get("category") or selected.get("category"),
            sub_category=record.get("sub_category") or selected.get("sub_category"),
        )
        try:
            details = await mutual_fund_service.fund_details(request.app.state.http, settings, int(selected["scheme_code"]))
            nav = details.get("latest_nav")
            if record.get("nav") is None and isinstance(nav, (int, float)) and not isinstance(nav, bool) and nav > 0:
                record["nav"] = str(nav)
                if record.get("current_price") is None:
                    record["current_price"] = str(nav)
                    record.setdefault("field_sources", {})["current_price"] = "MFNAV"
                record["nav_date"] = details.get("latest_nav_date")
            record["isin"] = details.get("isin") or selected["isin"]
        except (HTTPException, TypeError, ValueError):
            pass
        record["scheme_match_message"] = "Exact scheme name and AMC match found in MFNAV."
        record["scheme_candidates"] = [selected]
    elif len(exact) > 1:
        record["scheme_candidates"] = exact[:20]
        record["scheme_match_status"] = "multiple"
        record["scheme_match_message"] = "Several exact matches were returned; select the correct scheme or leave this holding unverified."
    else:
        record["scheme_candidates"] = [candidate for candidate in candidates if _scheme_identity_matches(name, candidate)][:20]
        record["scheme_match_status"] = "multiple" if record["scheme_candidates"] else "unverified"
        record["scheme_match_message"] = "No exact name and AMC match. Review the candidate's fund house before selecting it, or import as unverified." if amc else "AMC was not present in the statement. Choose the matching MFNAV result to confirm its fund house, or import as unverified."
    return record


async def _match_stock(request: Request, settings: Settings, record: dict, lookup_cache: dict | None = None) -> dict:
    label = record.get("symbol") or record.get("scheme_name")
    record.update(identity_status="unverified", stock_match_status="unverified")
    if not label:
        record["stock_match_message"] = "A stock name or symbol is needed. You can still import this holding unverified."
        return record
    cache_key = _normal(label)
    cached = lookup_cache.get(cache_key) if lookup_cache is not None else None
    if cached is None:
        try:
            cached = {"market_data": (await stock_service.get_price(request.app.state.http, settings, label)).get("market_data")}
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "IndianAPI lookup failed."
            cached = {"error": detail}
        if lookup_cache is not None:
            lookup_cache[cache_key] = cached
    if cached.get("error"):
        record["stock_match_message"] = f"IndianAPI could not verify this stock ({cached['error']}). The holding can still be imported unverified."
        return record
    market = cached.get("market_data")
    if not isinstance(market, dict):
        record["stock_match_message"] = "IndianAPI returned an unexpected stock response. The holding can still be imported unverified."
        return record
    ticker = str(market.get("tickerId") or "").strip().upper()
    requested_symbol = str(record.get("symbol") or "").strip().upper()
    if ticker and requested_symbol and ticker != requested_symbol:
        record["stock_match_message"] = f"IndianAPI returned {ticker}, which differs from the supplied symbol. Review the symbol or import unverified."
        return record
    if not ticker:
        record["stock_match_message"] = "IndianAPI returned company data without a ticker identifier. Review the symbol or import unverified."
        return record
    record.update(
        symbol=ticker,
        matched_name=market.get("companyName"),
        identity_status="verified",
        stock_match_status="exact",
        stock_match_message=f"IndianAPI identified {market.get('companyName') or ticker} ({ticker}).",
    )
    prices = market.get("currentPrice")
    if record.get("current_price") is None:
        price = market.get("ltp")
        if isinstance(prices, dict):
            price = prices.get(record.get("exchange") or "NSE") or prices.get("NSE") or prices.get("BSE") or price
        try:
            if price is not None and Decimal(str(price)) > 0:
                record["current_price"] = str(price)
                record.setdefault("field_sources", {})["current_price"] = "IndianAPI"
        except Exception:
            pass
    if record.get("current_value") is None and record.get("current_price") and record.get("units"):
        record["current_value"] = str(Decimal(record["current_price"]) * Decimal(record["units"]))
        record.setdefault("field_sources", {})["current_value"] = "calculated"
    return record


async def _owned_portfolio(session: AsyncSession, portfolio_id: int, user_id: int, *, lock: bool = False) -> Portfolio:
    query = select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.owner_id == user_id)
    if lock:
        query = query.with_for_update()
    portfolio = await session.scalar(query)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found.")
    return portfolio


async def _read_bounded(file: UploadFile) -> bytes:
    content = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds the 15 MB upload limit.")
    return bytes(content)


async def _resolve_instrument(
    session: AsyncSession,
    request: Request,
    settings: Settings,
    record,
) -> Instrument:
    if record.asset_type == "stock":
        symbol = (record.symbol or "").strip().upper() or None
        exchange = (record.exchange or "").strip().upper() or None
        if symbol:
            provider = "IndianAPI"
            provider_id = symbol
            instrument = await session.scalar(select(Instrument).where(Instrument.provider == provider, Instrument.provider_instrument_id == provider_id))
        else:
            provider = "StatementImport"
            stock_key = f"{exchange or ''}|{_normal(record.scheme_name)}"
            provider_id = f"stock:{hashlib.sha256(stock_key.encode()).hexdigest()}"
            instrument = await session.scalar(select(Instrument).where(Instrument.provider == provider, Instrument.provider_instrument_id == provider_id))
        if instrument is None:
            instrument = Instrument(
                asset_type="stock", display_name=record.scheme_name, symbol=symbol, exchange=exchange,
                isin=record.isin.upper() if record.isin else None,
                identity_status="verified" if symbol and record.identity_status == "verified" else "unverified",
                provider=provider, provider_instrument_id=provider_id,
            )
            session.add(instrument)
            await session.flush()
        else:
            instrument.display_name = record.scheme_name
            instrument.symbol = instrument.symbol or symbol
            instrument.exchange = instrument.exchange or exchange
            instrument.isin = instrument.isin or (record.isin.upper() if record.isin else None)
            if record.identity_status == "verified":
                instrument.identity_status = "verified"
        return instrument

    scheme_code = record.scheme_code
    details = None
    if not scheme_code and record.isin:
        try:
            details = await mutual_fund_service.fund_details_by_isin(request.app.state.http, settings, record.isin)
            scheme_code = int(details["scheme_code"])
        except HTTPException as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Could not resolve {record.scheme_name} from its ISIN. Correct the ISIN or enter the MFNAV scheme code in the review table.",
            ) from exc

    if scheme_code:
        if record.record_type == "holding" and record.scheme_match_status in ("exact", "selected"):
            try:
                details = await mutual_fund_service.fund_details(request.app.state.http, settings, int(scheme_code))
            except HTTPException as exc:
                raise HTTPException(status_code=422, detail=f"MFNAV could not verify the selected scheme for {record.scheme_name}.") from exc
            if not _scheme_matches(record.scheme_name, record.amc_name, details):
                raise HTTPException(status_code=422, detail=f"Selected MFNAV scheme does not exactly match {record.scheme_name} and its AMC. Clear the selection to import as unverified.")
        provider_id = str(scheme_code)
        instrument = await session.scalar(
            select(Instrument).where(Instrument.provider == "MFNAV", Instrument.provider_instrument_id == provider_id)
        )
        if instrument is None and record.isin:
            instrument = await session.scalar(
                select(Instrument).where(Instrument.asset_type == "mutual_fund", Instrument.isin == record.isin.upper())
            )
        if instrument is None:
            instrument = Instrument(
                asset_type="mutual_fund",
                display_name=(details or {}).get("scheme_name") or record.scheme_name,
                scheme_code=provider_id,
                isin=record.isin.upper() if record.isin else (details or {}).get("isin"),
                provider="MFNAV",
                provider_instrument_id=provider_id,
                amc_name=record.amc_name or (details or {}).get("fund_house"),
                category=record.category,
                sub_category=record.sub_category,
                identity_status="verified" if record.scheme_match_status in ("exact", "selected") else "provided",
            )
            session.add(instrument)
            await session.flush()
        else:
            instrument.amc_name = instrument.amc_name or record.amc_name or (details or {}).get("fund_house")
            instrument.category = instrument.category or record.category
            instrument.sub_category = instrument.sub_category or record.sub_category
            instrument.identity_status = "verified" if record.scheme_match_status in ("exact", "selected") else instrument.identity_status
        return instrument

    if record.record_type == "holding":
        label = f"statement:{hashlib.sha256(f'{_normal_amc(record.amc_name)}|{_normal(record.scheme_name)}'.encode()).hexdigest()}"
        instrument = await session.scalar(select(Instrument).where(Instrument.provider == "StatementImport", Instrument.provider_instrument_id == label))
        if instrument is None:
            instrument = Instrument(
                asset_type="mutual_fund", display_name=record.scheme_name,
                amc_name=record.amc_name, category=record.category, sub_category=record.sub_category,
                identity_status="unverified", provider="StatementImport", provider_instrument_id=label,
            )
            session.add(instrument)
            await session.flush()
        return instrument

    # Transactions need an identifier because their ledger must be tied to a specific scheme.
    raise HTTPException(status_code=422, detail=f"Add an MFNAV scheme code or valid ISIN for {record.scheme_name}.")


@router.post("/preview")
async def preview_statement(
    portfolio_id: int,
    request: Request,
    settings: Settings = Depends(get_settings),
    file: UploadFile = File(...),
    password: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    content = await _read_bounded(file)
    digest = file_digest(content)
    try:
        file_type, records = await run_in_threadpool(parse_statement, content, file.filename or "", password)
    except PasswordRequired as exc:
        return {"requires_password": True, "message": str(exc)}
    except IncorrectPdfPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        # Clear the request-local reference; the PDF password is never persisted or logged.
        password = None
        content = b""
    if len(records) > 10000:
        raise HTTPException(status_code=422, detail="The statement contains more than 10,000 rows. Split it into smaller files and retry.")

    scheme_cache = {}
    stock_cache = {}
    for record in records:
        if record.get("asset_type") == "stock":
            matched_stock = await _match_stock(request, settings, record, stock_cache)
            record.update({key: matched_stock.get(key) for key in ("identity_status", "stock_match_status", "stock_match_message", "symbol", "matched_name", "current_price", "current_value", "field_sources") if matched_stock.get(key) is not None})
            if matched_stock.get("stock_match_status") != "exact":
                record.setdefault("warnings", []).append(matched_stock.get("stock_match_message", "Stock identity is unverified."))
            continue
        if record.get("asset_type") != "mutual_fund" or record.get("record_type") != "holding" or record.get("scheme_code"):
            continue
        cache_key = (_normal(record.get("scheme_name")), _normal_amc(record.get("amc_name")))
        if cache_key not in scheme_cache:
            if len(scheme_cache) >= 30:
                record.update(
                    scheme_candidates=[],
                    scheme_match_status="unverified",
                    scheme_match_message="Automatic lookup is limited to 30 distinct schemes per upload. This holding can still be imported unverified.",
                )
                continue
            scheme_cache[cache_key] = await _match_schemes(request, settings, record.copy())
        matched = scheme_cache[cache_key]
        for key in ("scheme_candidates", "scheme_match_status", "scheme_match_message", "identity_status"):
            if key in matched:
                record[key] = matched[key]
        for key in ("nav", "nav_date", "category", "sub_category", "current_price"):
            if matched.get(key) is not None and record.get(key) is None:
                record[key] = matched[key]
        if record.get("field_sources") is None and matched.get("field_sources") is not None:
            record["field_sources"] = matched["field_sources"]
        elif matched.get("field_sources") and record.get("current_price") == matched.get("current_price"):
            record.setdefault("field_sources", {}).update(matched["field_sources"])
        if matched.get("scheme_match_status") == "exact":
            record["scheme_code"] = matched.get("scheme_code")
            record["isin"] = matched.get("isin")

    for record in records:
        record["name"] = record.get("scheme_name")
        record["quantity"] = record.get("units")
        record["invested_value"] = record.get("amount")
        record["profit_loss"] = record.get("returns_value")
        record["as_of_date"] = record.get("snapshot_date")
        record["source_file"] = file.filename
        record["match_status"] = record.get("stock_match_status") or record.get("scheme_match_status") or record.get("identity_status") or "unverified"

    previous = await session.scalar(
        select(PortfolioImport).where(PortfolioImport.portfolio_id == portfolio_id, PortfolioImport.file_sha256 == digest)
    )
    if previous:
        state = "already imported" if previous.status == "confirmed" else "already has a pending preview"
        raise HTTPException(status_code=409, detail=f"This exact statement {state}. Cancel the pending preview or check Import History.")

    batch = PortfolioImport(
        portfolio_id=portfolio_id,
        file_sha256=digest,
        file_type=file_type,
        status="previewed",
        total_rows=len(records),
    )
    session.add(batch)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This statement has already been previewed or imported.") from exc
    await session.refresh(batch)
    return {
        "import_id": batch.id,
        "file_type": file_type,
        "total_rows": len(records),
        "records": records,
        "message": "Review every row before confirming. No investment records have been saved yet.",
    }


@router.post("/confirm")
async def confirm_statement(
    portfolio_id: int,
    data: ImportConfirmInput,
    request: Request,
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id, lock=True)
    batch = await session.scalar(
        select(PortfolioImport).where(PortfolioImport.id == data.import_id, PortfolioImport.portfolio_id == portfolio_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Import preview not found. Upload the statement again.")
    if batch.status != "previewed":
        raise HTTPException(status_code=409, detail="This statement preview has already been confirmed or cancelled.")

    inserted_transactions = 0
    inserted_holding_rows = 0
    skipped_duplicates = 0
    holding_groups: dict[tuple[int, object, str], list] = defaultdict(list)
    in_file_transactions = set()

    for record in data.records:
        # Reconcile only missing holding values. Decimal keeps statement precision and
        # every supplied statement/API value remains authoritative.
        if record.record_type == "holding" and record.units and record.units > 0:
            sources = record.field_sources or {}
            if (record.average_cost is None or sources.get("average_cost") == "calculated") and record.amount is not None:
                record.average_cost = record.amount / record.units
            if (record.amount is None or sources.get("invested_value") == "calculated") and record.average_cost is not None:
                record.amount = record.average_cost * record.units
            if sources.get("current_price") == "calculated" and record.current_value is not None:
                unit_price = record.current_value / record.units
                record.current_price = unit_price
            unit_price = record.current_price or (record.nav if record.asset_type == "mutual_fund" else None)
            if record.current_price is None and record.current_value is not None:
                unit_price = record.current_value / record.units
                record.current_price = unit_price
            if (record.current_value is None or sources.get("current_value") == "calculated") and unit_price is not None:
                record.current_value = unit_price * record.units
            if (record.returns_value is None or sources.get("profit_loss") == "calculated") and record.current_value is not None and record.amount is not None:
                record.returns_value = record.current_value - record.amount
        instrument = await _resolve_instrument(session, request, settings, record)
        if record.record_type == "holding":
            folio_reference, folio_last4 = _folio_key(record.folio_number)
            holding_groups[(instrument.id, record.snapshot_date, folio_reference)].append((record, instrument, folio_last4))
            continue

        if record.transaction_type in ("BUY", "SELL"):
            quantity = record.units
            unit_price = record.nav or (record.amount / quantity if record.amount is not None and quantity else None)
            if quantity is None or unit_price is None:
                raise HTTPException(status_code=422, detail=f"{record.scheme_name} needs transaction units and a reliable NAV or unit price.")
            duplicate_key = (instrument.id, record.transaction_type, record.transaction_date, quantity, unit_price)
            if duplicate_key in in_file_transactions:
                skipped_duplicates += 1
                continue
            in_file_transactions.add(duplicate_key)
            existing = await session.scalar(
                select(PortfolioTransaction.id).where(
                    PortfolioTransaction.portfolio_id == portfolio_id,
                    PortfolioTransaction.instrument_id == instrument.id,
                    PortfolioTransaction.side == record.transaction_type,
                    PortfolioTransaction.trade_date == record.transaction_date,
                    PortfolioTransaction.quantity == quantity,
                    PortfolioTransaction.price_per_unit == unit_price,
                ).limit(1)
            )
            if existing:
                skipped_duplicates += 1
                continue
            session.add(PortfolioTransaction(
                portfolio_id=portfolio_id,
                instrument_id=instrument.id,
                import_id=batch.id,
                side=record.transaction_type,
                trade_date=record.transaction_date,
                quantity=quantity,
                price_per_unit=unit_price,
                fees=Decimal("0"),
                notes="Imported from user-reviewed statement.",
            ))
            inserted_transactions += 1
        else:
            duplicate_key = (instrument.id, record.transaction_type, record.transaction_date, record.amount)
            if duplicate_key in in_file_transactions:
                skipped_duplicates += 1
                continue
            in_file_transactions.add(duplicate_key)
            existing = await session.scalar(
                select(PortfolioTransaction.id).where(
                    PortfolioTransaction.portfolio_id == portfolio_id,
                    PortfolioTransaction.instrument_id == instrument.id,
                    PortfolioTransaction.side == record.transaction_type,
                    PortfolioTransaction.trade_date == record.transaction_date,
                    PortfolioTransaction.cash_amount == record.amount,
                ).limit(1)
            )
            if existing:
                skipped_duplicates += 1
                continue
            session.add(PortfolioTransaction(
                portfolio_id=portfolio_id,
                instrument_id=instrument.id,
                import_id=batch.id,
                side=record.transaction_type,
                trade_date=record.transaction_date,
                quantity=None,
                price_per_unit=None,
                cash_amount=record.amount,
                fees=Decimal("0"),
                notes="Imported from user-reviewed statement.",
            ))
            inserted_transactions += 1

    await session.flush()
    for (instrument_id, snapshot_date, folio_reference), entries in holding_groups.items():
        existing_snapshot = await session.scalar(
            select(ImportedHoldingSnapshot.id).where(
                ImportedHoldingSnapshot.portfolio_id == portfolio_id,
                ImportedHoldingSnapshot.instrument_id == instrument_id,
                ImportedHoldingSnapshot.snapshot_date == snapshot_date,
                ImportedHoldingSnapshot.folio_reference == folio_reference,
            )
        )
        if existing_snapshot:
            skipped_duplicates += len(entries)
            continue
        quantity = sum((entry[0].units for entry in entries), Decimal("0"))
        invested_values = [entry[0].amount for entry in entries]
        invested_amount = sum(invested_values, Decimal("0")) if all(value is not None for value in invested_values) else None
        returns_values = [entry[0].returns_value for entry in entries]
        returns_value = sum(returns_values, Decimal("0")) if all(value is not None for value in returns_values) else None
        xirr_values = [entry[0].xirr_pct for entry in entries if entry[0].xirr_pct is not None]
        xirr_pct = xirr_values[0] if xirr_values and all(value == xirr_values[0] for value in xirr_values) else None
        current_values = [entry[0].current_value if entry[0].current_value is not None else (entry[0].units * (entry[0].current_price or entry[0].nav) if (entry[0].current_price or entry[0].nav) is not None else None) for entry in entries]
        current_value = sum(current_values, Decimal("0")) if all(value is not None for value in current_values) else None
        nav = None
        average_buy_price = None
        statement_prices = [
            entry[0].current_price if entry[1].asset_type == "stock" else (entry[0].current_price or entry[0].nav)
            for entry in entries
        ]
        average_prices = [entry[0].average_cost or (entry[0].nav if entry[1].asset_type == "stock" else None) for entry in entries]
        if any(price is not None for price in average_prices):
            average_buy_price = sum((entry[0].units * price for entry, price in zip(entries, average_prices) if price is not None), Decimal("0")) / sum((entry[0].units for entry, price in zip(entries, average_prices) if price is not None), Decimal("0"))
        if all(price is not None for price in statement_prices):
            nav = sum((entry[0].units * price for entry, price in zip(entries, statement_prices)), Decimal("0")) / quantity
        elif current_value is not None and quantity:
            nav = current_value / quantity
        statement_current_price = None
        if all(price is not None for price in statement_prices):
            statement_current_price = sum((entry[0].units * price for entry, price in zip(entries, statement_prices)), Decimal("0")) / quantity
        elif current_value is not None and quantity:
            statement_current_price = current_value / quantity
        session.add(ImportedHoldingSnapshot(
            portfolio_id=portfolio_id,
            instrument_id=instrument_id,
            import_id=batch.id,
            snapshot_date=snapshot_date,
            folio_reference=folio_reference,
            folio_last4=entries[0][2],
            quantity=quantity,
            nav=nav,
            average_buy_price=average_buy_price,
            current_price=statement_current_price,
            current_value=current_value,
            invested_amount=invested_amount,
            returns_value=returns_value,
            xirr_pct=xirr_pct,
        ))
        inserted_holding_rows += 1

    batch.status = "confirmed"
    batch.imported_rows = inserted_transactions + inserted_holding_rows
    batch.skipped_duplicates = skipped_duplicates
    batch.total_rows = len(data.records)
    batch.confirmed_at = datetime.now(timezone.utc)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Some imported rows conflict with existing records. Refresh the preview and check for duplicates.") from exc
    return {
        "import_id": batch.id,
        "status": batch.status,
        "transaction_rows_imported": inserted_transactions,
        "holding_snapshots_imported": inserted_holding_rows,
        "skipped_duplicates": skipped_duplicates,
        "message": "Statement records were imported. Current holdings snapshots remain distinct from dated transactions.",
    }


@router.get("")
async def import_history(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    result = await session.scalars(
        select(PortfolioImport)
        .where(PortfolioImport.portfolio_id == portfolio_id)
        .order_by(PortfolioImport.created_at.desc(), PortfolioImport.id.desc())
    )
    return [
        ImportHistoryItem(
            id=item.id,
            file_type=item.file_type,
            status=item.status,
            total_rows=item.total_rows,
            imported_rows=item.imported_rows,
            skipped_duplicates=item.skipped_duplicates,
            created_at=item.created_at.isoformat(),
            confirmed_at=item.confirmed_at.isoformat() if item.confirmed_at else None,
        ).model_dump(mode="json")
        for item in result.all()
    ]


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_import_preview(
    portfolio_id: int,
    import_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned_portfolio(session, portfolio_id, user.id)
    batch = await session.scalar(
        select(PortfolioImport).where(PortfolioImport.id == import_id, PortfolioImport.portfolio_id == portfolio_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Import preview not found.")
    if batch.status != "previewed":
        raise HTTPException(status_code=409, detail="Only an unconfirmed preview can be cancelled.")
    await session.delete(batch)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
