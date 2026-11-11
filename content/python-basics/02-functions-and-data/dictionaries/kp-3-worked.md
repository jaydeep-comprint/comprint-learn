## Worked example: looping over a dictionary

Add up a bill, and make a new price list with ₹5 off:

```python
bill = {"rice": 60, "dal": 45, "oil": 120}
total = 0
cheaper = {}
for item, price in bill.items():
    total = total + price
    cheaper[item] = price - 5
print(total)        # 225
print(cheaper)      # {'rice': 55, 'dal': 40, 'oil': 115}
```

| Pass | item | price | total after |
|---|---|---|---|
| 1 | "rice" | 60 | 60 |
| 2 | "dal" | 45 | 105 |
| 3 | "oil" | 120 | 225 |

- `bill.items()` gives each pair; `for item, price in ...` puts the key in `item` and the value in `price`.
- `for item in bill:` gives only the **keys**. Use `bill[item]` to get each value.
- `bill.values()` gives only the values, in the same order the pairs were added.
