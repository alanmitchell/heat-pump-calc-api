"""Utility functions."""

import math
import numbers
import simplejson
from typing import List

import pandas as pd
from pydantic import BaseModel


def chg_nonnum(val, sub_val):
    """Changes a nan or anything that is not a number to 'sub_val'.
    Otherwise returns val.
    """
    if isinstance(val, numbers.Number):
        if math.isnan(val):
            return sub_val
        else:
            return val
    else:
        return sub_val


def to_float(val, sub_val):
    """Try to convert 'val' to a float.  If it fails, return 'sub_val' instead.
    Remove any commas before trying to convert.
    """
    try:
        if isinstance(val, str):
            # remove any commas before converting.
            val = val.replace(",", "")
        return float(val)
    except:
        return sub_val


def is_null(val):
    """Returns True if 'val' is None, NaN, or a blank string.
    Returns False otherwise.
    """
    if val is None:
        return True

    if isinstance(val, float) and math.isnan(val):
        return True

    if isinstance(val, str) and len(val.strip()) == 0:
        return True

    return False


def nan_to_none(obj):
    """Converts the NaN values found in an object 'obj' into None values. Only
    works objects that can be serialized to JSON.
    """
    return simplejson.loads(simplejson.dumps(obj, ignore_nan=True))


def models_to_dataframe(model_list: List[BaseModel]) -> pd.DataFrame:
    """Converts a list of Pydantic model objects into a Pandas Dataframe."""
    dict_list = [o.model_dump() for o in model_list]
    return pd.DataFrame(dict_list)


def dataframe_to_models(
    df: pd.DataFrame, model: BaseModel, convert_nans: bool = False
) -> List[BaseModel]:
    """Converts a Pandas DataFrame into a List of Pydantic model objects.
    Optionally convert NaN values in the DataFrame to None values in the Pydantic
    objects.
    """
    return [
        model(**(rec if not convert_nans else nan_to_none(rec)))
        for rec in df.to_dict(orient="records")
    ]

def sum_dicts(dict_list):
    """
    Given a list of dictionaries with numeric values,
    return a dictionary where like keys are summed.
    Missing keys are treated as 0.
    """
    result = {}
    for d in dict_list:
        for key, value in d.items():
            result[key] = result.get(key, 0) + value
    return result
