## Worked example: looping over a list

Add up the prices, and build a list of prices with ₹10 delivery added:

```python
prices = [120, 45, 80]
total = 0                     # before the loop
with_delivery = []            # an empty list to fill
for p in prices:
    total = total + p
    with_delivery.append(p + 10)
print(total)                  # 245
print(with_delivery)          # [130, 55, 90]
```

| Pass | p | total after | with_delivery after |
|---|---|---|---|
| 1 | 120 | 120 | [130] |
| 2 | 45 | 165 | [130, 55] |
| 3 | 80 | 245 | [130, 55, 90] |

`for p in prices` gives the **items** one by one. The average is `total / len(prices)`.
