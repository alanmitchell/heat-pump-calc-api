"""Models associated with economic anlaysis of cash flows.
"""
from typing import List, Dict

from pydantic import BaseModel
import numpy as np

# --------------- Cash Flow Item models
# Each model represents one item of cash flow. These all subclass CashFlowItem.
# If new classes are added make sure the Pydantic field collection is unique for
# each class.

class CashFlowItem(BaseModel):

    label: str = 'Cash Flow Item'      # Label for this cash flow item
    
    # Base amount used to generate a cash flow. Could be an initial year 0 amount,
    # or a first year amount, depending on the subclass.
    amount: float

    def cash_flow(self, duration: int) -> np.ndarray:
        # Returns a numpy array containing the cash flow.  The first element of the 
        # array is the year 0 amount, followed by 'duration' additional elements spanning
        # the remaining years of the cash flow.
        # This method should be overridden by the subclass.
        return np.zeros(duration + 1)

class InitialAmount(CashFlowItem):
    """An amount that occurs in year 0.
    """
    def cash_flow(self, duration: int) -> np.ndarray:
        result = np.zeros(duration + 1)
        result[0] = self.amount
        return result

class EscalatingFlow(CashFlowItem):
    """Represents an escalating (can be 0 escalation) amount starting in year 1 and 
    continuing through the duration of the cash flow, or through "end_year" if
    'end_year' is not None.
    """
    escalation_rate: float   # yearly escalation as a fraction, e.g. 0.04 means 4% / year.
    end_year: int | None = None    # last year of cash flow

    def cash_flow(self, duration: int) -> np.ndarray:
        pat = np.ones(duration - 1) * (1 + self.escalation_rate)
        result = np.insert(pat.cumprod(), 0, [0.0, 1.0]) * self.amount
        # blank out last elements if there is an end year
        if self.end_year is not None:
            result[self.end_year + 1:] = 0.0

        return result

class PatternFlow(CashFlowItem):
    """An amount that is adjusted by a 'pattern' array, which multiplies the 'amount' to
    determine the cash flow.
    """
    # A list of multipliers to apply to the scalar 'amount' to generate a cash flow. The first
    # multiplier in 'pattern' is for year 0, followed by multipliers for subsequent years. If 
    # the 'pattern' list is shorter than the cash flow duration, the last pattern value is extended
    # through the end of the cash flow. If the 'pattern' is longer than the cash flow duration,
    # excess values are ignored.
    pattern: List[float]

    def cash_flow(self, duration: int) -> np.ndarray:
        pat = np.array(self.pattern)
        if len(pat) < duration + 1:
            # need to extend the pattern
            pat = np.concatenate([pat, np.full(duration + 1 - len(pat), pat[-1])])
        elif len(pat) > duration + 1:
            # need to truncate the pattern
            pat = pat[:duration + 1]

        return self.amount * pat
        
class PeriodicAmount(CashFlowItem):
    """An amount that occurs at equally spaced periods in time, for example every 5 years,
    possible with escalation between the recurrences. The first occurence is year 'interval',
    not year 0. This class is useful for modeling replacement costs.
    """
    
    # Spacing in years between recurring amounts
    interval: int
    
    # Escalation rate between occurences. The first occurrence *does* receive escalation
    # measured from year 0. The escalation rate is expressed as a fraction, e.g. 0.02 means
    # 2%/year.
    escalation_rate: float = 0.0  
        
    def cash_flow(self, duration: int) -> np.ndarray:
        result = np.zeros(duration + 1)
        for yr in range(self.interval, duration + 1, self.interval):
            result[yr] = self.amount * (1 + self.escalation_rate) ** yr
        return result
        
# -----------------------------------------

class CashFlowInputs(BaseModel):
    """Describes a complete cash flow consisting of multiple CashFlowItem's, a duration
    of the cash flow, and a economic discount rate.
    """
    # Number of years that the cash flow spans. Year 0 + 1 through duration will be
    # included.
    duration: int

    # The discount rate to use when calculating net present value amounts
    discount_rate: float | None
    
    # A list of the CashFlowItem's
    cash_flow_items: List[InitialAmount | EscalatingFlow | PatternFlow | PeriodicAmount]

class CashFlowAnalysis(BaseModel):
    """The results of a cash flow analysis.
    """
    
    # A cash flow table in dictionary form. Keys are column headings and values are
    # a list of the cash flows for each year starting with Year 0. The table also
    # includes a "Year" key, which lists the years starting with 0.
    cash_flow_table: Dict[str, List[float | int]]

    # Internal rate of return of the cash flow. None if it can't be calculated.
    irr: float | None

    # Net present value of cash flow. None if no discount rate provided
    npv: float | None 

    # The number of years before the net present value of the cash flow is zero or greater.
    # None if no discount rate is provided or if the cash flow never accumulates zero or positive NPV.
    discounted_payback: float | None

    # The number of years before the cumulative sum of the cash flow (not discounted) is zero or greater.
    # None if the cash flow never accumulates to zero or positive.
    simple_payback: float | None

    # Benefit / Cost ratio of the cash flow, considering the Year 0 negative amount as the cost and
    # all flows in Year 1 and beyond as the benefits. Calculated on a net present value basis.
    bc_ratio: float | None

