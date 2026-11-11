# Dictionaries

A **dictionary** stores pairs: each **key** points to a **value**. You look a value up by its key, not by a
position.

```python
stock = {"pen": 40, "book": 12}   # key "pen" → value 40
print(stock["pen"])               # 40
stock["eraser"] = 25              # add a new pair
print(len(stock))                 # 3 pairs
```

- Keys are **unique**: one key can't appear twice. Values can repeat.
- `stock["ruler"]` is a **KeyError** (no such key); `stock.get("ruler", 0)` gives 0 instead.
- `for item, count in stock.items():` visits every pair.
- A dictionary is great for **counting**: one key per thing, its value is the count.
