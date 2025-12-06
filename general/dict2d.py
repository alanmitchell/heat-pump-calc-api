"""Class that tracks floating point values indexed with two keys.  New values
can be added to existing values located at the same key pair. The data structure
can be "sparse", meaning not all possible key pairs need to have values. If a
key does not exist, it's current value is assumed to be 0.0.
Values are stored in nested dictionaries; The outer dictionary is keyed on key1
and the inner dictionary is keyed on key2 and holds the floating point values.
"""
import copy
from typing import Hashable, Self


class Dict2d:

    def __init__(self, initial_values: dict[Hashable, dict[Hashable, float]] | None = None):
        if initial_values:
            self.store = initial_values
        else:
            self.store = {}

    def add(self, key1: Hashable, key2: Hashable, value: float) -> float:
        """Add 'value' to the existing value at the (key1, key2) location.
        Return the new value.
        """
        inner = self.store.get(key1, {})
        existing_val = inner.get(key2, 0.0)
        new_value = existing_val + value
        inner[key2] = new_value
        self.store[key1] = inner
        return new_value

    def get(self, key1: Hashable, key2: Hashable) -> float:
        """Return the value at the (key1, key2) location.
        """
        inner = self.store.get(key1, {})
        existing_val = inner.get(key2, 0.0)
        return existing_val
    
    def get_all(self) -> dict[Hashable, dict[Hashable, float]]:
        """Return a copy of the underlying dictionary storing the values.
        """
        return copy.deepcopy(self.store)

    def sum_key1(self) -> dict[Hashable, float]:
        """Return a dictionary keyed on key1 that sums all the values in the
        inner dictionary associated with each key.
        """
        result = {}
        for k, inner in self.store.items():
            result[k] = sum(inner.values())
        return result

    def sum_key2(self) -> dict[Hashable, float]:
        """Return a dictionary keyed on key2 that sums all the values
        for that key across all the inner dictionaries.
        """
        result = {}
        for inner in self.store.values():
            for k, v in inner.items():
                result[k] = result.get(k, 0.0) + v
        return result
    
    def add_object(self, obj: Self) -> Self:
        """Adds the values from the Dict2d object 'obj' to this one, returning
        this new updated object.
        """
        for k1, d in obj.get_all().items():
            for k2, val in d.items():
                self.add(k1, k2, val)
        return self

    def copy(self) -> Self:
        """Returns a copy of this object.
        """
        return Dict2d(copy.deepcopy(self.store))


if __name__ == "__main__":
    st = Dict2d()
    st.add('propane', 'space', 55.4)
    st.add('propane', 'cooking', 14.3)
    st.add('oil1', 'space', 44.3)
    st.add('oil1', 'dhw', 8.1)
    print(st.get_all())
    print(st.get('oil1', 'space'))
    print(st.sum_key1())
    print(st.sum_key2())
