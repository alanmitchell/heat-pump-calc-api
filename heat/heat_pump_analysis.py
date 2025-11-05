"""The main function "analyze_heat_pump" determines the impact and economics of
installing a heat pump in a building. This module uses the space heating model
(model_space_heat()) found in the "home_heat_model" module.
"""

import numpy as np
import numpy_financial as npf

from .models import (
    HeatPumpAnalysisInputs,
    HeatPumpAnalysisResults,
    TimePeriodResults,
    DetailedModelResults,
    MiscHeatPumpResults,
)
from .home_heat_model import (
    model_space_heat,
    ELECTRIC_ID,
    determine_ua_true_up,
    monthly_to_annual_results,
)
import econ.econ
from econ.elec_cost import ElecCostCalc
from econ.models import InitialAmount, EscalatingFlow, PatternFlow, CashFlowInputs
import library.library as lib
from general.utils import (
    is_null,
    chg_nonnum,
    models_to_dataframe,
    dataframe_to_models,
    nan_to_none,
)

# --------- Some Constants

# The days in each month
DAYS_IN_MONTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

# The pattern of Lights and appliances other than DHW, Clothes Drying & Cooking.
# This is average power in the month divided average annual power.
LIGHTS_OTHER_PAT = np.array(
    [1.13, 1.075, 1.0, 0.925, 0.87, 0.85, 0.87, 0.925, 1.0, 1.075, 1.13, 1.15]
)


def convert_co2_to_miles_driven(co2_saved: float) -> float:
    """Converts CO2 emissions to a mileage driven
    equivalent for vehicles in the U.S. using EPA
    methodology:  https://www.epa.gov/energy/greenhouse-gases-equivalencies-calculator-calculations-and-references#miles
    """
    pounds_in_metric_ton = 2204.62
    tons_co2_per_gallon = 0.0089
    avg_gas_mileage_us_fleet = 22
    mileage_equivalent = (
        co2_saved
        / pounds_in_metric_ton
        / tons_co2_per_gallon
        * avg_gas_mileage_us_fleet
    )

    return mileage_equivalent


def analyze_heat_pump(inp: HeatPumpAnalysisInputs) -> HeatPumpAnalysisResults:
    """Performs a performance and economic analysis of installing a Heat Pump."""
    # Start the main results dictionary
    res = {}

    # Start the miscellaneous results dictionary
    misc_res = {}

    # shortcuts to some of the input structures
    inp_bldg = inp.bldg_model_inputs
    inp_hpc = inp.heat_pump_cost
    inp_econ = inp.economic_inputs
    inp_actual = inp.actual_fuel_use

    # acquire some key objects
    city = lib.city_from_id(inp.bldg_model_inputs.city_id)
    fuel = lib.fuel_from_id(inp.bldg_model_inputs.exist_heat_system.heat_fuel_id)
    elec_util = lib.util_from_id(inp_econ.utility_id)

    # Some of the fields in the electric utility object may be overridden.
    # Adjust the object now.
    if inp_econ.elec_rate_override is not None:
        # overwrite the block structure with one block
        elec_util.Blocks = [(None, inp_econ.elec_rate_override)]
        # zero out the demand charge as that is included in the overridden electric rate.
        elec_util.DemandCharge = 0.0
    if inp_econ.pce_rate_override is not None:
        elec_util.PCE = inp_econ.pce_rate_override
    if inp_econ.customer_charge_override is not None:
        elec_util.CustomerChg = inp_econ.customer_charge_override
    if inp_econ.co2_lbs_per_kwh_override is not None:
        elec_util.CO2 = inp_econ.co2_lbs_per_kwh_override

    # If other end uses use the heating fuel, make an estimate of their annual
    # consumption of that fuel.  This figure is expressed in the physical unit
    # for the fuel type, e.g. gallons of oil.
    # See Evernote notes on values (AkWarm for DHW and Michael Bluejay for Drying
    # and Cooking).
    is_electric_heat = (fuel.id == ELECTRIC_ID)  # True if Electric
    fuel_other_uses = (
        (fuel.id == inp_bldg.dhw_fuel_id) * 4.23e6 / fuel.dhw_effic
    )  # per occupant value
    fuel_other_uses += (fuel.id == inp_bldg.clothes_drying_fuel_id) * (
        0.86e6 if is_electric_heat else 2.15e6
    )
    fuel_other_uses += (fuel.id == inp_bldg.cooking_fuel_id) * (
        0.64e6 if is_electric_heat else 0.8e6
    )
    # convert from per occupant to total
    fuel_other_uses *= inp_bldg.occupant_count
    # convert to fuel units
    fuel_other_uses /= fuel.btus

    # For elecric heat we also need to account for lights and other applicances not
    # itemized above.
    if is_electric_heat:
        # Use the AkWarm Medium Lights/Appliances formula but take 25% off
        # due to efficiency improvements since then.
        lights_other_elec = 2086.0 + 1.20 * inp_bldg.bldg_floor_area  # kWh in the year
    else:
        lights_other_elec = 0.0

    # Match the existing space heating use if it is provided.  Do so by using
    # the UA true up factor.
    if inp_actual.secondary_fuel_units is not None:
        # Remove the energy use from the other end uses that use the fuel, unless
        # this is electric heat and the user indicated that the entered value is
        # just space heating.
        if is_electric_heat and inp.actual_fuel_use.annual_electric_is_just_space_heat:
            # user explicitly indicated that the entered annual usage value is
            # just space heating.
            space_fuel_use = inp.actual_fuel_use.secondary_fuel_units
        else:
            space_fuel_use = inp.actual_fuel_use.secondary_fuel_units - fuel_other_uses
            if is_electric_heat:
                # if electric heat, also need to subtract out other lights and appliances
                space_fuel_use -= lights_other_elec

        ua_true_up = determine_ua_true_up(inp_bldg, space_fuel_use)

    elif inp_actual.electric_use_by_month and is_electric_heat:
        # it's electric heat and there are monthly actuals. Use these to true-up.
        space_fuel_use = (
            sum(inp_actual.electric_use_by_month) - fuel_other_uses - lights_other_elec
        )
        ua_true_up = determine_ua_true_up(inp_bldg, space_fuel_use)

    else:
        ua_true_up = 1.0

    # Set the UA true up value into the model and also add it to the miscellaneous results.
    inp_bldg.ua_true_up = ua_true_up
    misc_res["ua_true_up"] = ua_true_up

    # Run the base case with no heat pump and record energy results.
    # This model only models the space heating end use.
    bldg_no_hp = inp_bldg.model_copy()
    bldg_no_hp.heat_pump = None
    en_base = model_space_heat(bldg_no_hp)
    res["base_case_detail"] = en_base

    # Run the model with the heat pump and record energy results
    en_hp = model_space_heat(inp_bldg)
    res["with_heat_pump_detail"] = en_hp

    # Calculate some summary measures

    # CO2 savings. If secondary fuel is electric, fuel.co2 is None, so protect against that.
    co2_base = (
        en_base.annual_results.space_heat_kwh * elec_util.CO2
        + en_base.annual_results.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)
    )
    co2_hp = (
        en_hp.annual_results.space_heat_kwh * elec_util.CO2
        + en_hp.annual_results.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)
    )
    misc_res["co2_lbs_saved"] = co2_base - co2_hp
    misc_res["co2_driving_miles_saved"] = convert_co2_to_miles_driven(
        misc_res["co2_lbs_saved"]
    )

    # -------- Monthly cash flow analysis - Determine Base Electric Use

    # Make dataframes of monthly space heating results. Economic columns will
    # be added to these.
    dfb = models_to_dataframe(en_base.monthly_results)
    dfh = models_to_dataframe(en_hp.monthly_results)

    # Determine the base electric use by month.  Approach is different
    # if there is electric heat. This is only important for dealing with
    # block rate structures and PCE. The actual kWh and kW deltas determined
    # from the space heating modeling will be added to this base electric use
    # to determine the impact of the heat pump.
    if not is_electric_heat:
        # Fuel-based space heat.
        # Either the User supplies a full 12-month array of electric use, which
        # should be used outright, or they supply no array of use. In the no data
        # case, use the default values provided in the City record.
        if inp_actual.electric_use_by_month:
            dfb["all_kwh"] = inp_actual.electric_use_by_month.copy()
        else:
            dfb["all_kwh"] = city.avg_elec_usage.copy()

        # rough estimate of a base demand: not super critical, as the demand rate
        # structure does not have blocks.  Assume a load factor of 0.4
        dfb["all_kw_max"] = dfb.all_kwh / (DAYS_IN_MONTH * 24.0) / 0.4

    else:
        # Electric Heat Case
        if inp_actual.electric_use_by_month:
            # actual use by month was provided
            dfb["all_kwh"] = inp_actual.electric_use_by_month.copy()

        else:
            # No monthly electric use provided.  But, an annual electric use figure
            # might be provided.
            if inp_actual.secondary_fuel_units:
                if inp_actual.annual_electric_is_just_space_heat:
                    # the provided value is just electric space heat. First spread it out according
                    # to the modeled electric space heat.
                    scaler = inp_actual.secondary_fuel_units / dfb.space_heat_kwh.sum()
                    all_kwh = scaler * dfb.space_heat_kwh.values

                    # add in any DHW, Clothes Drying and Cooking provided by electricity.
                    all_kwh += fuel_other_uses / 8760.0 * DAYS_IN_MONTH * 24.0

                    # add in lights and other misc. appliances, with some monthly variation.
                    all_kwh += (
                        lights_other_elec
                        / 8760.0
                        * LIGHTS_OTHER_PAT
                        * DAYS_IN_MONTH
                        * 24.0
                    )

                else:
                    # provided value is total electric kWh.  Scale modeled values of space heat,
                    # other big uses, and misc. lights and appliances to match.
                    # NOTE: the .copy() method is *important*, otherwise all_kwh is just a
                    # reference to the underlying numpy array of the original Dataframe, and
                    # subsequent changes to all_kwh change the original Dataframe!!
                    all_kwh = dfb.space_heat_kwh.values.copy()

                    # add in any DHW, Clothes Drying and Cooking provided by electricity.
                    all_kwh += fuel_other_uses / 8760.0 * DAYS_IN_MONTH * 24.0

                    # add in lights and other misc. appliances, with some monthly variation.
                    all_kwh += (
                        lights_other_elec
                        / 8760.0
                        * LIGHTS_OTHER_PAT
                        * DAYS_IN_MONTH
                        * 24.0
                    )

                    # scale to provided annual total
                    scaler = inp_actual.secondary_fuel_units / all_kwh.sum()
                    all_kwh *= scaler

            else:
                # No annual value provided. Build up electric use from space heat and
                # other electric uses.

                # Space heating kWh
                all_kwh = dfb.space_heat_kwh.values.copy()

                # DHW, Clothes Drying and Cooking.  Assume flat use through year.
                # This is a numpy array because DAYS_IN_MONTH is an array.
                all_kwh += fuel_other_uses / 8760.0 * DAYS_IN_MONTH * 24.0

                # Now lights and other misc. appliances. Some monthly variation, given
                # by LIGHTS_OTHER_PAT.
                all_kwh += (
                    lights_other_elec / 8760.0 * LIGHTS_OTHER_PAT * DAYS_IN_MONTH * 24.0
                )

            # store results
            dfb["all_kwh"] = all_kwh

        # Monthly load factor is pretty high for electric heat, about 0.63 in winter
        # months.
        dfb["all_kw_max"] = dfb["all_kwh"] / (DAYS_IN_MONTH * 24.0) / 0.63

    # ---------- Calculate Monthly Electric and Fuel Costs

    # Make an object to calculate electric utility costs
    sales_tax = chg_nonnum(
        inp_econ.sales_tax_override,
        chg_nonnum(city.MunicipalSalesTax, 0.0) + chg_nonnum(city.BoroughSalesTax, 0.0),
    )
    elec_cost_calc = ElecCostCalc(
        elec_util, sales_tax=sales_tax, pce_limit=inp_econ.pce_limit
    )
    # cost function that will be applied to each row of the cost DataFrame
    cost_func = lambda r: elec_cost_calc.monthly_cost(r.all_kwh, r.all_kw_max)

    dfb["all_elec_dol"] = dfb.apply(cost_func, axis=1)

    if not is_electric_heat:
        # Now fuel use by month.  Remember that the home heat model only looked at
        # space heating, so we need to add in the fuel use from the other end uses
        # that use this fuel.
        fuel_price = chg_nonnum(
            inp_econ.fuel_price_override,
            lib.fuel_price(inp_bldg.exist_heat_system.heat_fuel_id, city.id).price,
        )
        dfb["fuel_units"] = dfb.secondary_fuel_units + fuel_other_uses / 12.0
        dfb["fuel_dol"] = dfb.fuel_units * fuel_price * (1.0 + sales_tax)

    else:
        # Electric Heat, so no secondary fuel
        dfb["fuel_units"] = 0.0
        dfb["fuel_dol"] = 0.0

    # Total Electric + space heat
    dfb["total_dol"] = dfb.all_elec_dol + dfb.fuel_dol

    # Now with the heat pump
    # determine extra kWh used in the heat pump scenario. Note, this will
    # be negative numbers if the base case used electric heat.
    extra_kwh = (dfh.space_heat_kwh - dfb.space_heat_kwh).values
    dfh["all_kwh"] = dfb["all_kwh"] + extra_kwh
    extra_kw = (dfh.space_heat_kw_max - dfb.space_heat_kw_max).values
    dfh["all_kw_max"] = dfb["all_kw_max"] + extra_kw
    dfh["all_elec_dol"] = dfh.apply(cost_func, axis=1)

    # Now fuel, including other end uses using the heating fuel
    if not is_electric_heat:
        dfh["fuel_units"] = dfh.secondary_fuel_units + fuel_other_uses / 12.0
        dfh["fuel_dol"] = dfh.fuel_units * fuel_price * (1.0 + sales_tax)

    else:
        # Electric Heat, so no secondary fuel
        dfh["fuel_units"] = 0.0
        dfh["fuel_dol"] = 0.0

    # Total Electric + space heat
    dfh["total_dol"] = dfh.all_elec_dol + dfh.fuel_dol

    # Aggregate monthly data into annual data for both the base case and the
    # with heat pump case
    ann_base = monthly_to_annual_results(dfb)
    ann_hp = monthly_to_annual_results(dfh)

    # determine the change from the base case to the heat pump case
    # Get a list of numeric columms by removing the 'period' column.
    numeric_cols = list(dfh.columns)
    numeric_cols.remove("period")
    df_mo_chg = dfh[numeric_cols] - dfb[numeric_cols]
    df_mo_chg["period"] = dfh["period"].values
    ann_chg = ann_hp[numeric_cols] - ann_base[numeric_cols]
    ann_chg["period"] = ann_base["period"]

    # Create the detailed modeling results object to return.
    # First, design load info from before
    design_t = en_base.design_heat_temp
    design_load = en_base.design_heat_load

    res["base_case_detail"] = DetailedModelResults(
        monthly_results=dataframe_to_models(dfb, TimePeriodResults, True),
        annual_results=nan_to_none(ann_base.to_dict()),
        design_heat_temp=design_t,
        design_heat_load=design_load,
    )
    res["with_heat_pump_detail"] = DetailedModelResults(
        monthly_results=dataframe_to_models(dfh, TimePeriodResults, True),
        annual_results=nan_to_none(ann_hp.to_dict()),
        design_heat_temp=design_t,
        design_heat_load=design_load,
    )
    res["change_detail"] = DetailedModelResults(
        monthly_results=dataframe_to_models(df_mo_chg, TimePeriodResults, True),
        annual_results=nan_to_none(ann_chg.to_dict()),
        design_heat_temp=0.0,  # no change in design heat temperature or load
        design_heat_load=0.0,
    )

    # Calculate and include incremental fuel and electricity prices
    if ann_chg.fuel_units != 0.0:
        misc_res["fuel_price_incremental"] = ann_chg.fuel_dol / ann_chg.fuel_units
    else:
        misc_res["fuel_price_incremental"] = None

    if ann_chg.all_kwh != 0.0:
        misc_res["elec_rate_incremental"] = ann_chg.all_elec_dol / ann_chg.all_kwh
    else:
        misc_res["elec_rate_incremental"] = None

    # ---------------- Cash Flow Analysis

    # List of cash flow items
    cash_flow_items = []

    # Initial year impacts
    frac_fin = inp_hpc.frac_financed
    hp_cost = inp_hpc.capital_cost
    if frac_fin > 0.0:
        # Loan is being used. Fraction financed applies to full heat pump cost.
        cash_flow_items.append(
            InitialAmount(
                label="Heat Pump Downpayment", amount=-(1.0 - frac_fin) * hp_cost
            )
        )
        # loan payment
        loan_pmt = npf.pmt(inp_hpc.loan_interest, inp_hpc.loan_term, hp_cost * frac_fin)
        # above function produces negative number already
        cash_flow_items.append(
            EscalatingFlow(
                label="Loan Payment",
                amount=loan_pmt,
                escalation_rate=0.0,
                end_year=inp_hpc.loan_term,
            )
        )
    else:
        cash_flow_items.append(InitialAmount(label="Heat Pump Cost", amount=-hp_cost))
    if inp_hpc.rebate_amount > 0.0:
        cash_flow_items.append(
            InitialAmount(label="Rebate", amount=inp_hpc.rebate_amount)
        )

    # Electricity cost impacts
    # determine whether and escalation rate or pattern was provided
    if type(inp_econ.elec_rate_forecast) == float:
        # escalation rate
        cash_flow_items.append(
            EscalatingFlow(
                label="Electricity Cost",
                amount=-ann_chg.all_elec_dol,
                escalation_rate=inp_econ.elec_rate_forecast,
            )
        )
    else:
        # A price pattern was provided, but the provided pattern starts at Year 1.
        # Add a Year 0 value.
        cash_flow_items.append(
            PatternFlow(
                label="Electricity Cost",
                amount=-ann_chg.all_elec_dol,
                pattern=[0.0] + inp_econ.elec_rate_forecast,
            )
        )

    # Fuel cost impacts, if present (may be electric heat)
    if ann_chg.fuel_dol != 0.0:
        # determine whether and escalation rate or pattern was provided
        if type(inp_econ.fuel_price_forecast) == float:
            # escalation rate
            cash_flow_items.append(
                EscalatingFlow(
                    label="Fuel Cost",
                    amount=-ann_chg.fuel_dol,
                    escalation_rate=inp_econ.fuel_price_forecast,
                )
            )
        else:
            # A price pattern was provided, but the provided pattern starts at Year 1.
            # Add a Year 0 value.
            cash_flow_items.append(
                PatternFlow(
                    label="Fuel Cost",
                    amount=-ann_chg.fuel_dol,
                    pattern=[0.0] + inp_econ.fuel_price_forecast,
                )
            )

    # include the operating cost change
    cash_flow_items.append(
        EscalatingFlow(
            label="Operating Cost Change",
            amount=-inp_hpc.op_cost_chg,
            escalation_rate=inp_econ.inflation_rate,
        )
    )

    # Analyze the cash flows
    econ_inp = CashFlowInputs(
        duration=inp_hpc.heat_pump_life,
        discount_rate=inp_econ.discount_rate,
        cash_flow_items=cash_flow_items,
    )
    res["financial"] = econ.econ.analyze_cash_flow(econ_inp)

    # add in the miscellaneous results
    res["misc"] = MiscHeatPumpResults(**misc_res)

    return HeatPumpAnalysisResults(**res)
