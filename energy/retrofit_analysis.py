"""The main function "analyze_retrofit" determines the impact and economics of
doing an energy retrofit on a building. This module uses the energy_model.model_building()
function to model the pre- and post-retrofit energy use.
"""

import numpy_financial as npf

from .models import (
    RetrofitAnalysisInputs,
    RetrofitAnalysisResults,
)
from .energy_model import (
    model_building,
)
import econ.econ
from econ.models import InitialAmount, EscalatingFlow, PatternFlow, CashFlowInputs
from library.models import Fuel_id
from general.dict2d import Dict2d


def convert_co2_to_miles_driven(co2_saved: float) -> float:
    """Converts CO2 emissions to a mileage driven
    equivalent for vehicles in the U.S. using EPA
    calculator:  https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator
    """

    return 1396.0 / 1208.0 * co2_saved

def analyze_retrofit(inp: RetrofitAnalysisInputs) -> RetrofitAnalysisResults:
    """Performs a performance and economic analysis of installing a Heat Pump."""

    # Start the main results dictionary
    res = {}

    # shortcuts to some of the input structures
    pre_bldg = inp.pre_bldg
    post_bldg = inp.post_bldg
    inp_cost = inp.retrofit_cost
    inp_econ = inp.economic_inputs

    # Run the base case with no heat pump and record energy results.
    en_base = model_building(pre_bldg)
    res["base_case_detail"] = en_base

    # Run the model with the heat pump and record energy results
    en_post = model_building(post_bldg)
    res["with_retrofit_detail"] = en_post

    # Calculate Misc Retrofit results, which are just CO2 savings at the
    # moment.
    misc_res = {}
    misc_res["co2_lbs_saved"] = en_base.annual_results.co2_lbs - en_post.annual_results.co2_lbs
    misc_res["co2_driving_miles_saved"] = convert_co2_to_miles_driven(
        misc_res["co2_lbs_saved"]
    )
    res['misc'] = misc_res

    # Calculate changes in fuel use by fuel, both in terms of fuel units and $.
    # First, fuel units, which come in a two-level dictionary keyed on fuel ID, then end use.
    # collapse to 1-level dicts keyed on Fuel ID
    base_units = Dict2d(en_base.annual_results.fuel_use_units).sum_key1()
    retrofit_units = Dict2d(en_post.annual_results.fuel_use_units).sum_key1()
    # determine all the fuels in use, including pre- and post-retrofit.
    all_fuels = set(base_units.keys()) | set(retrofit_units.keys())
    fuel_change_units = {}
    for fuel_id in all_fuels:
        fuel_change_units[fuel_id] = retrofit_units.get(fuel_id, 0.0) - base_units.get(fuel_id, 0.0)
    # now fuel cost, which comes in a 1-level dictionary by fuel type
    fuel_change_cost = {}
    for fuel_id in all_fuels:
        fuel_change_cost[fuel_id] = en_post.annual_results.fuel_cost.get(fuel_id, 0.0) - \
            en_base.annual_results.fuel_cost.get(fuel_id, 0.0)
    res['fuel_change'] = {
        'units': fuel_change_units,
        'cost': fuel_change_cost
    }

    # ---------------- Cash Flow Analysis

    # List of cash flow items
    cash_flow_items = []

    # Initial year impacts
    loan_amount = inp_cost.loan_amount
    capital_cost = inp_cost.capital_cost
    if loan_amount > 0.0:
        # Loan is being used. 
        cash_flow_items.append(
            InitialAmount(
                label="Retrofit Downpayment", amount=-(capital_cost - loan_amount)
            )
        )
        # loan payment
        loan_pmt = npf.pmt(inp_cost.loan_interest, inp_cost.loan_term, loan_amount)
        # above function produces negative number already
        cash_flow_items.append(
            EscalatingFlow(
                label="Loan Payment",
                amount=loan_pmt,
                escalation_rate=0.0,
                end_year=inp_cost.loan_term,
            )
        )
    else:
        cash_flow_items.append(InitialAmount(label="Retrofit Cost", amount=-capital_cost))

    if inp_cost.rebate_amount > 0.0:
        cash_flow_items.append(
            InitialAmount(label="Rebate", amount=inp_cost.rebate_amount)
        )

    # Electricity cost impacts
    # Determine the change in electricity cost
    elec_cost_chg = en_post.annual_results.fuel_cost[Fuel_id.elec] - \
        en_base.annual_results.fuel_cost[Fuel_id.elec]
    # determine whether and escalation rate or pattern was provided
    if type(inp_econ.elec_rate_forecast) == float:
        # escalation rate
        cash_flow_items.append(
            EscalatingFlow(
                label="Electricity Cost",
                amount=-elec_cost_chg,
                escalation_rate=inp_econ.elec_rate_forecast,
            )
        )
    else:
        # A price pattern was provided, but the provided pattern starts at Year 1.
        # Add a Year 0 value.
        cash_flow_items.append(
            PatternFlow(
                label="Electricity Cost",
                amount=-elec_cost_chg,
                pattern=[0.0] + inp_econ.elec_rate_forecast,
            )
        )

    # Fuel cost impacts (not counting electricity), if present (may be electric heat)
    # Determine fuel cost change by netting out electricity cost change
    # from total fuel cost change.
    fuel_cost_chg = en_post.annual_results.fuel_total_cost - \
        en_base.annual_results.fuel_total_cost - elec_cost_chg
    if fuel_cost_chg != 0.0:
        # determine whether and escalation rate or pattern was provided
        if type(inp_econ.fuel_price_forecast) == float:
            # escalation rate
            cash_flow_items.append(
                EscalatingFlow(
                    label="Fuel Cost",
                    amount=-fuel_cost_chg,
                    escalation_rate=inp_econ.fuel_price_forecast,
                )
            )
        else:
            # A price pattern was provided, but the provided pattern starts at Year 1.
            # Add a Year 0 value.
            cash_flow_items.append(
                PatternFlow(
                    label="Fuel Cost",
                    amount=-fuel_cost_chg,
                    pattern=[0.0] + inp_econ.fuel_price_forecast,
                )
            )

    # include the operating cost change
    cash_flow_items.append(
        EscalatingFlow(
            label="Operating Cost Change",
            amount=-inp_cost.op_cost_chg,
            escalation_rate=inp_econ.inflation_rate,
        )
    )

    # Analyze the cash flows
    econ_inp = CashFlowInputs(
        duration=inp_cost.retrofit_life,
        discount_rate=inp_econ.discount_rate,
        cash_flow_items=cash_flow_items,
    )
    res["financial"] = econ.econ.analyze_cash_flow(econ_inp)

    return RetrofitAnalysisResults(**res)
