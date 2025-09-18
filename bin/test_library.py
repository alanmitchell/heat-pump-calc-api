# This now can be run from the 'bin' directory since it inserts the parent
# directory in the path.

# Old method of running:
# from the root project directory, run this script via the following command:
#
#     python -m bin.test_library
#
# This is needed for test_library to find the modules it needs to import.
import sys

sys.path.insert(0, "../")

from library.library import (
    cities,
    city_from_id,
    fuels,
    fuel_from_id,
    fuel_price,
    utilities,
    util_from_id,
    tmys,
    tmy_from_id,
)

print("Testing cities...")
for choice in cities():
    try:
        city = city_from_id(choice.id)
        # print(city.Name, city.Oil1Price)
    except:
        print(f"Problem with city: {choice.id}, {choice.label}")

print("Testing fuels...")
for choice in fuels():
    try:
        fuel = fuel_from_id(choice.id)
    except:
        print(f"Error with Fuel: {choice.id}, {choice.label}")


print("Testing fuel prices...")
for fuel_id in range(1, 12):
    try:
        fuel_price(fuel_id, 1)
    except:
        print(f"Error for fuel {fuel_id}")

print("Testing utilities...")
for choice in utilities():
    try:
        util = util_from_id(choice.id)
    except:
        print(f"Error for Utility: {choice.id}, {choice.label}")

print("TMY sites")
for tmy_meta in tmys():
    try:
        tmy = tmy_from_id(tmy_meta.tmy_id)
    except:
        print(f"Error for TMY site: {tmy_meta.tmy_id}, {tmy_meta.city}")
