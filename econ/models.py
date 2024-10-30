"""Models associated with economic anlaysis of cash flows.
"""
from typing import List

from pydantic import BaseModel

class FutureChange(BaseModel):
    """Describes how an first-year amount changes over time. 
    Either the 'pattern' or the 'escalation_rate' should be provided. If both
    are provided, the 'pattern' has precedence and is used.
    Defaults to no change over the future.
    """
    pattern: List[float] | None = None

    # a rate per year of change, expressed as fraction, e.g. 0.04 for 4%/year
    escalation_rate: float = 0.0      

class CashFlowItem(BaseModel):
    """One cash flow stream starting in year 1 and proceeding with a particular
    pattern of change.
    """
    year_1_amount: float
    future_change: FutureChange

class CashFlow(BaseModel):
    """A full investment cash flow, including initial year 0 impacts and ongoing
    cash flow items.  Positve values are benefits and negative values are costs.
    """
    duration: int           # duration of cash flow in years

    # an initial year 0 amount, or a list of year 0 amounts that will be added together.
    initial_amount: float | List[float]

    # A cash flow stream spanning year 1 through the end of the cash flow duration.
    # Or, a list of such streams. If a 'pattern' is used to describe the future change
    # of the cash flow, the last value of the pattern is extended if needed to cover
    # the duration of the cash flow. 
    recurring: CashFlowItem | List[CashFlowItem]


class Test1(BaseModel):
    a: int
    b: str

class Test2(BaseModel):
    c: str
    d: float

