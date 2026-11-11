## Worked example: local variables and default arguments

```python
total = 100

def add_bonus(marks, bonus=5):   # bonus has a default value
    total = marks + bonus        # a new, local total
    return total

print(add_bonus(60))             # bonus = 5: prints 65
print(add_bonus(60, 10))         # bonus = 10: prints 70
print(total)                     # the outside total: still 100
```

| Call | marks | bonus | Returns |
|---|---|---|---|
| `add_bonus(60)` | 60 | 5 (default) | 65 |
| `add_bonus(60, 10)` | 60 | 10 | 70 |

- `bonus=5` is a **default**: it is used when the caller leaves that argument out.
- A variable given a value inside a function is **local**. It is a different variable from one with the same
  name outside, and it disappears when the function ends.
- So the outside `total` stays 100. Using a local name outside its function is a `NameError`.
- Changing a parameter inside the function doesn't change the caller's variable.
