from app.api.routes.portfolio_import import _scheme_matches, _scheme_search_queries


def test_scheme_name_match_normalizes_spaces_case_and_direct_plan_wording():
    candidate = {
        "scheme_name": "SBI Gold Fund - Direct Plan - Growth",
        "fund_house": "SBI Mutual Fund",
        "plan_type": "Direct",
        "option_type": "Growth",
    }
    assert _scheme_matches("  sbi   gold DIRECT Plan Growth ", "SBI Mutual Fund", candidate)


def test_scheme_name_match_handles_icici_prudential_without_collapsing_plan_or_option():
    candidate = {
        "scheme_name": "ICICI Prudential Large Cap Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "plan_type": "Direct",
        "option_type": "Growth",
    }
    assert _scheme_matches("ICICI Prudential Large Cap Fund Direct Growth", "ICICI Prudential", candidate)
    assert not _scheme_matches(
        "ICICI Prudential Large Cap Fund Direct Growth",
        "ICICI Prudential",
        {**candidate, "plan_type": "Regular", "scheme_name": "ICICI Prudential Large Cap Fund Regular Plan Growth"},
    )
    assert not _scheme_matches(
        "ICICI Prudential Large Cap Fund Direct Growth",
        "ICICI Prudential",
        {**candidate, "option_type": "IDCW", "scheme_name": "ICICI Prudential Large Cap Fund Direct Plan IDCW"},
    )


def test_scheme_lookup_retries_with_base_fund_name():
    assert _scheme_search_queries("SBI Gold Direct Plan Growth") == ["sbi gold direct plan growth", "sbi gold"]
