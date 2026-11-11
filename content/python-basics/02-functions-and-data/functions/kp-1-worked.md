## Worked example: defining and calling a function

```python
def add_delivery(price):          # 1. define (the body does not run yet)
    return price + 18

print("Start")               # 2. runs first
bill = add_delivery(100)          # 3. call: price = 100, gives back 118
print(add_delivery(bill))         # 4. call again: price = 118, prints 136
```

| Step | What happens | Printed |
|---|---|---|
| 1 | Python remembers `add_delivery` | (nothing) |
| 2 | `print("Start")` | Start |
| 3 | `add_delivery(100)` returns 118, stored in `bill` | (nothing) |
| 4 | `add_delivery(118)` returns 136 | 136 |

- `def name(...):` plus an indented body **defines** the function. Nothing inside runs yet.
- `name(...)` **calls** it: the body runs now, once per call.
- A function that is defined but never called never runs.
- A returned number is still a number: `"Bill: " + add_delivery(100)` is a TypeError. Use `str(...)`.
