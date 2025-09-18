import numpy as np
import numpy_financial as npf

from .models import CashFlowInputs, CashFlowAnalysis
from general.utils import chg_nonnum


def payback(cash_flow: np.ndarray) -> float | None:
    """Returns the year (first element is year 0) that the cash flow accumulates
    to zero. If the cumulative cash flow in the last year is less than 0, returns None. If the
    cumulative cash flow is never negative, returns 0.0. Interpolation is used to return
    fractional year values.

    For calculating simple payback, pass the unmodified cash flow. To calculate discounted
    payback, pass the discounted cash flow.
    """
    cum_cash = cash_flow.cumsum()
    if cum_cash.min() > 0.0:
        # cumulative cash is never negative
        return 0.0

    if cum_cash[-1] < 0.0:
        # never reaches 0
        return None

    # create an array of the year values associated with the cash flow
    yrs = np.array(range(len(cash_flow)))

    # use numpy interpolate to determine zero crossing
    return np.interp(0.0, cum_cash, yrs)


def analyze_cash_flow(inp: CashFlowInputs) -> CashFlowAnalysis:
    # Dictionary of results
    results = {}

    # Cash Flow table, starting with a column for the Year
    table = {"Year": list(range(inp.duration + 1))}
    net_cash = None  # array containing total of cash flows.
    for flow in inp.cash_flow_items:
        cash_array = flow.cash_flow(inp.duration)
        table[flow.label] = list(cash_array)
        if net_cash is not None:
            net_cash += cash_array
        else:
            net_cash = cash_array

    table["Net Cash"] = list(net_cash)
    results["cash_flow_table"] = table

    # internal rate of return, converted to None if can't be calculated
    irr = chg_nonnum(npf.irr(net_cash), None)
    results["irr"] = irr

    if inp.discount_rate is not None:
        # Calculate net present value
        npv = npf.npv(inp.discount_rate, net_cash)

        # determine discounted payback
        # create a discounted cash flow
        disc_mult = np.ones(inp.duration) / (1.0 + inp.discount_rate)
        disc_mult = np.insert(disc_mult.cumprod(), 0, 1.0)
        disc_cash = disc_mult * net_cash
        discounted_payback = payback(disc_cash)

        # Calculate benefit cost ratio
        if net_cash[0] >= 0.0:
            # no cost in year 0, not possible to calc B/C
            bc_ratio = None
        else:
            cost = -net_cash[0]
            npv_benefits = npv + cost
            bc_ratio = npv_benefits / cost

    else:
        # these items cannot be calculated withouut a discount rate
        npv = None
        discounted_payback = None
        bc_ratio = None

    results["npv"] = npv
    results["discounted_payback"] = discounted_payback
    results["bc_ratio"] = bc_ratio

    # simple payback
    results["simple_payback"] = payback(net_cash)

    return CashFlowAnalysis(**results)
