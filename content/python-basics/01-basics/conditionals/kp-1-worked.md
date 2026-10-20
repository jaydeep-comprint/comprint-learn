## Worked example: comparisons and booleans

```python
age = 15
print(age >= 13)                 # True
print(age >= 13 and age <= 19)   # True: both sides are True
print(age < 10 or age > 60)      # False: neither side is True
print(not age == 15)             # False
```

- `and` is `True` only when **both** sides are `True`.
- `or` is `True` when **at least one** side is `True`.
- `not` flips `True` and `False`.

Booleans behave like numbers in arithmetic: `int(True)` is 1 and `int(False)` is 0.
