"""The main function "analyze_heat_pump" determines the impact and economics of
installing a heat pump in a building. This module uses the space heating model
(model_space_heat()) found in the "home_heat_model" module.
"""
import numpy as np
import numpy_financial as npf

from .models import HeatPumpAnalysisInputs, HeatPumpAnalysisResults
from .home_heat_model import model_space_heat, ELECTRIC_ID, determine_ua_true_up
import econ.econ
from econ.elec_cost import ElecCostCalc
from econ.models import InitialAmount, EscalatingFlow, PatternFlow, CashFlowInputs
import library.library as lib
from general.utils import is_null, chg_nonnum, models_to_dataframe

# --------- Some Constants

# The days in each month
DAYS_IN_MONTH = np.array([
    31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31
])

# The pattern of Lights and appliances other than DHW, Clothes Drying & Cooking.
# This is average power in the month divided average annual power.
LIGHTS_OTHER_PAT = np.array([
    1.13, 1.075, 1.0, 0.925, 0.87, 0.85, 0.87, 0.925, 1.0, 1.075, 1.13, 1.15
])

def convert_co2_to_miles_driven(co2_saved: float) -> float:
    """Converts CO2 emissions to a mileage driven
    equivalent for vehicles in the U.S. using EPA
    methodology:  https://www.epa.gov/energy/greenhouse-gases-equivalencies-calculator-calculations-and-references#miles
    """
    pounds_in_metric_ton = 2204.62
    tons_co2_per_gallon = 0.0089
    avg_gas_mileage_us_fleet = 22
    mileage_equivalent = co2_saved / pounds_in_metric_ton / tons_co2_per_gallon * avg_gas_mileage_us_fleet
    
    return mileage_equivalent

def analyze_heat_pump(inp: HeatPumpAnalysisInputs) -> HeatPumpAnalysisResults:
    """Performs a performance and economic analysis of installing a Heat Pump.
    """
    # Start results dictionary
    res = {}

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
    fuel_other_uses = inp_bldg.exist_heat_system.serves_dhw * 4.23e6 / fuel.dhw_effic     # per occupant value
    fuel_other_uses += inp_bldg.exist_heat_system.serves_clothes_drying * (0.86e6 if is_electric_heat else 2.15e6)
    fuel_other_uses += inp_bldg.exist_heat_system.serves_cooking * (0.64e6 if is_electric_heat else 0.8e6)
    # assume 3 occupants if no value is provided.
    fuel_other_uses *= chg_nonnum(inp_bldg.exist_heat_system.occupant_count, 3.0) / fuel.btus

    # For elecric heat we also need to account for lights and other applicances not
    # itemized above.
    if is_electric_heat:
        # Use the AkWarm Medium Lights/Appliances formula but take 25% off
        # due to efficiency improvements since then.
        lights_other_elec = 2086. + 1.20 * inp_bldg.bldg_floor_area   # kWh in the year
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
        space_fuel_use = sum(inp_actual.electric_use_by_month) - fuel_other_uses - lights_other_elec
        ua_true_up = determine_ua_true_up(inp_bldg, space_fuel_use)

    else:
        ua_true_up = 1.0
        
    # Set the UA true up value into the model and also add it to results.
    inp_bldg.ua_true_up = ua_true_up
    res['ua_true_up'] = ua_true_up

    # Run the base case with no heat pump and record energy results.
    # This model only models the space heating end use.
    bldg_no_hp = inp_bldg.model_copy()
    bldg_no_hp.heat_pump = None
    en_base = model_space_heat(bldg_no_hp)

    # Run the model with the heat pump and record energy results
    en_hp = model_space_heat(inp_bldg)

    # record design heat load and temperature
    res['design_heat_load'] = en_hp.design_heat_load
    res['design_heat_temp'] = en_hp.design_heat_temp
    
    # Calculate some summary measures
    res['annual_cop'] = en_hp.annual_results.cop
    res['hp_max_out_5F'] = inp_bldg.heat_pump.max_out_5f
    res['max_hp_reached'] = (en_hp.annual_results.hp_capacity_used_max == 1.0)
    
    # CO2 savings. If secondary fuel is electric, fuel.co2 is None, so protect against that.
    co2_base = en_base.annual_results.total_kwh * elec_util.CO2 + en_base.annual_results.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)
    co2_hp = en_hp.annual_results.total_kwh * elec_util.CO2 + en_hp.annual_results.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)
    res['co2_lbs_saved'] = co2_base - co2_hp
    res['co2_driving_miles_saved'] = convert_co2_to_miles_driven(res['co2_lbs_saved'])

    # Determine fraction of space heating load served by heat pump.
    res['hp_load_frac'] = en_hp.annual_results.hp_load_mmbtu / (en_hp.annual_results.hp_load_mmbtu + en_hp.annual_results.secondary_load_mmbtu)

    # -------- Monthly cash flow analysis - Determine Base Electric Use

    # Make dataframes of monthly space heating results
    df_mo_en_base = models_to_dataframe(en_base.monthly_results)
    df_mo_en_hp = models_to_dataframe(en_hp.monthly_results)

    # start some cash flow dataframes, with just the 'period' (month) column initially
    dfb = df_mo_en_base[['period']].copy()
    dfh = df_mo_en_base[['period']].copy()

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
            dfb['elec_kwh'] = inp_actual.electric_use_by_month.copy()
        else:
            dfb['elec_kwh'] =  city.avg_elec_usage.copy()

        # rough estimate of a base demand: not super critical, as the demand rate 
        # structure does not have blocks.  Assume a load factor of 0.4
        dfb['elec_kw'] = dfb.elec_kwh / (DAYS_IN_MONTH * 24.0) / 0.4

    else:
        # Electric Heat Case
        if inp_actual.electric_use_by_month:
            # actual use by month was provided
            dfb['elec_kwh'] = inp_actual.electric_use_by_month.copy()

        else:

            # No monthly electric use provided.  But, an annual electric use figure
            # might be provided.
            if inp_actual.secondary_fuel_units:
                if inp_actual.annual_electric_is_just_space_heat:
                    # the provided value is just electric space heat. First spread it out according
                    # to the modeled electric space heat.
                    scaler = inp_actual.secondary_fuel_units / df_mo_en_base.total_kwh.sum()
                    elec_kwh = scaler * df_mo_en_base.total_kwh.values

                    # add in any DHW, Clothes Drying and Cooking provided by electricity.
                    elec_kwh += fuel_other_uses / 8760.0 * DAYS_IN_MONTH * 24.0

                    # add in lights and other misc. appliances, with some monthly variation.
                    elec_kwh += lights_other_elec / 8760.0 * LIGHTS_OTHER_PAT * DAYS_IN_MONTH * 24.0

                else:
                    # provided value is total electric kWh.  Scale modeled values of space heat, 
                    # other big uses, and misc. lights and appliances to match.
                    # NOTE: the .copy() method is *important*, otherwise elec_kwh is just a
                    # reference to the underlying numpy array of the original Dataframe, and 
                    # subsequent changes to elec_kwh change the original Dataframe!!
                    elec_kwh = df_mo_en_base.total_kwh.values.copy()

                    # add in any DHW, Clothes Drying and Cooking provided by electricity.
                    elec_kwh += fuel_other_uses / 8760.0 * DAYS_IN_MONTH * 24.0

                    # add in lights and other misc. appliances, with some monthly variation.
                    elec_kwh += lights_other_elec / 8760.0 * LIGHTS_OTHER_PAT * DAYS_IN_MONTH * 24.0

                    # scale to provided annual total
                    scaler = inp_actual.secondary_fuel_units / elec_kwh.sum()
                    elec_kwh *= scaler

            else:
                # No annual value provided. Build up electric use from space heat and
                # other electric uses.

                # Space heating kWh
                elec_kwh = df_mo_en_base.total_kwh.values.copy()

                # DHW, Clothes Drying and Cooking.  Assume flat use through year.
                # This is a numpy array because DAYS_IN_MONTH is an array.
                elec_kwh += fuel_other_uses / 8760.0 * DAYS_IN_MONTH * 24.0

                # Now lights and other misc. appliances. Some monthly variation, given
                # by LIGHTS_OTHER_PAT.
                elec_kwh += lights_other_elec / 8760.0 * LIGHTS_OTHER_PAT * DAYS_IN_MONTH * 24.0

            # store results
            dfb['elec_kwh'] =  elec_kwh

        # Monthly load factor is pretty high for electric heat, about 0.63 in winter 
        # months.
        dfb['elec_kw'] =  dfb['elec_kwh'] / (DAYS_IN_MONTH * 24.0) / 0.63

    #---------- Calculate Monthly Electric and Fuel Costs

    # Make an object to calculate electric utility costs
    sales_tax = chg_nonnum(
        inp_econ.sales_tax_override, 
        chg_nonnum(city.MunicipalSalesTax, 0.0) + chg_nonnum(city.BoroughSalesTax, 0.0)
        )
    elec_cost_calc = ElecCostCalc(elec_util, sales_tax=sales_tax, pce_limit=inp_econ.pce_limit)
    # cost function that will be applied to each row of the cost DataFrame
    cost_func = lambda r: elec_cost_calc.monthly_cost(r.elec_kwh, r.elec_kw)

    dfb['elec_dol'] = dfb.apply(cost_func, axis=1)

    if not is_electric_heat:
        # Now fuel use by month.  Remember that the home heat model only looked at
        # space heating, so we need to add in the fuel use from the other end uses
        # that use this fuel.
        fuel_price = chg_nonnum(
            inp_econ.fuel_price_override, 
            lib.fuel_price(inp_bldg.exist_heat_system.heat_fuel_id, city.id).price
            )
        dfb['secondary_fuel_units'] = df_mo_en_base.secondary_fuel_units + \
            fuel_other_uses / 12.0
        dfb['secondary_fuel_dol'] = dfb.secondary_fuel_units * fuel_price * (1. + sales_tax)

    else:
        # Electric Heat, so no secondary fuel
        dfb['secondary_fuel_units'] = 0.0
        dfb['secondary_fuel_dol'] = 0.0

    # Total Electric + space heat
    dfb['total_dol'] =  dfb.elec_dol + dfb.secondary_fuel_dol

    # Now with the heat pump
    # determine extra kWh used in the heat pump scenario. Note, this will
    # be negative numbers if the base case used electric heat.
    extra_kwh = (df_mo_en_hp.total_kwh - df_mo_en_base.total_kwh).values
    dfh['elec_kwh'] = dfb['elec_kwh'] + extra_kwh
    extra_kw = (df_mo_en_hp.total_kw_max - df_mo_en_base.total_kw_max).values
    dfh['elec_kw'] =  dfb['elec_kw'] + extra_kw
    dfh['elec_dol'] = dfh.apply(cost_func, axis=1)

    # Now fuel, including other end uses using the heating fuel
    if not is_electric_heat:
        dfh['secondary_fuel_units'] = df_mo_en_hp.secondary_fuel_units + \
            fuel_other_uses / 12.0
        dfh['secondary_fuel_dol'] = dfh.secondary_fuel_units * fuel_price * (1. + sales_tax)

    else:
        # Electric Heat, so no secondary fuel
        dfh['secondary_fuel_units'] = 0.0
        dfh['secondary_fuel_dol'] = 0.0

    # Total Electric + space heat
    dfh['total_dol'] =  dfh.elec_dol + dfh.secondary_fuel_dol

    # ---------------- Cash Flow Analysis

    # determine the changes caused by the heat pump on an annual basis.
    # First calculate annual totals for base case and heat pump case and
    # then calculate the change.
    numeric_cols = dfb.select_dtypes(include='number').columns
    ann_base = dfb[numeric_cols].sum()
    ann_hp = dfh[numeric_cols].sum()
    ann_chg = ann_hp - ann_base

    # List of cash flow items
    cash_flow_items = []

    # Initial year impacts
    frac_fin = inp_hpc.frac_financed
    hp_cost = inp_hpc.capital_cost
    if frac_fin > 0.0:
        # Loan is being used. Fraction financed applies to full heat pump cost.
        cash_flow_items.append(
            InitialAmount(label='Heat Pump Downpayment', amount=-(1.- frac_fin) * hp_cost)
        )
        # loan payment
        loan_pmt = npf.pmt(inp_hpc.loan_interest, inp_hpc.loan_term, hp_cost * frac_fin)
        # above function produces negative number already
        cash_flow_items.append(
            EscalatingFlow(label='Loan Payment', amount=loan_pmt, 
                           escalation_rate=0.0, end_year=inp_hpc.loan_term)
        )
    else:
        cash_flow_items.append(
            InitialAmount(label='Heat Pump Cost', amount=-hp_cost)
        )
    if inp_hpc.rebate_amount > 0.0:
        cash_flow_items.append(
            InitialAmount(label='Rebate', amount=inp_hpc.rebate_amount)
        )

    # Electricity cost impacts
    # determine whether and escalation rate or pattern was provided
    if type(inp_econ.elec_rate_forecast) == float:
        # escalation rate
        cash_flow_items.append(
            EscalatingFlow(label='Electricity Cost', amount=-ann_chg.elec_dol,
                escalation_rate=inp_econ.elec_rate_forecast)
        )
    else:
        # A price pattern was provided, but the provided pattern starts at Year 1.
        # Add a Year 0 value.
        cash_flow_items.append(
            PatternFlow(label='Electricity Cost', amount=-ann_chg.elec_dol,
                pattern=[0.0] + inp_econ.elec_rate_forecast)
        )
  
    # Fuel cost impacts, if present (may be electric heat)
    if ann_chg.secondary_fuel_dol != 0.0:
        # determine whether and escalation rate or pattern was provided
        if type(inp_econ.fuel_price_forecast) == float:
            # escalation rate
            cash_flow_items.append(
                EscalatingFlow(label='Fuel Cost', amount=-ann_chg.secondary_fuel_dol,
                    escalation_rate=inp_econ.fuel_price_forecast)
            )
        else:
            # A price pattern was provided, but the provided pattern starts at Year 1.
            # Add a Year 0 value.
            cash_flow_items.append(
                PatternFlow(label='Fuel Cost', amount=-ann_chg.secondary_fuel_dol,
                    pattern=[0.0] + inp_econ.fuel_price_forecast)
            )

    # include the operating cost change
    cash_flow_items.append(
        EscalatingFlow(label='Operating Cost Change', amount=-inp_hpc.op_cost_chg,
                       escalation_rate=inp_econ.inflation_rate)
    )

    # Analyze the cash flows
    econ_inp = CashFlowInputs(
        duration=inp_hpc.heat_pump_life,
        discount_rate=inp_econ.discount_rate,
        cash_flow_items=cash_flow_items
    )
    res['econ'] = econ.econ.analyze_cash_flow(econ_inp)

    return HeatPumpAnalysisResults(**res)
