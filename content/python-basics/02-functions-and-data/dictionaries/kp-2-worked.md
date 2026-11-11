## Worked example: adding, updating and deleting pairs

```python
stock = {"pen": 40, "book": 12}
stock["bag"] = 5                  # new key: adds a pair     {'pen': 40, 'book': 12, 'bag': 5}
stock["pen"] = stock["pen"] + 10  # old key: updates value   {'pen': 50, 'book': 12, 'bag': 5}
stock["book"] = 20                # old key: replaces value  {'pen': 50, 'book': 20, 'bag': 5}
del stock["bag"]                  # deletes the pair         {'pen': 50, 'book': 20}
n = stock.pop("book")             # n = 20                   {'pen': 50}
print(len(stock))                 # 1
```

- `d[key] = value` **adds** a pair if the key is new, and **replaces** the value if the key is already there.
  The number of pairs only grows for a new key.
- `del d[key]` deletes a pair; `d.pop(key)` deletes it **and gives back** its value.
- Both need the **key**: deleting a key that isn't there is a KeyError.
