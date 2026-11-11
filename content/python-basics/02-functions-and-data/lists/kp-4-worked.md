## Worked example: slices and `in`

```python
days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
print(days[1:3])      # ['Tue', 'Wed']
print(days[:2])       # ['Mon', 'Tue']
print(days[3:])       # ['Thu', 'Fri']
print(days[1:-1])     # ['Tue', 'Wed', 'Thu']
print("Wed" in days)  # True
print("Sun" in days)  # False
```

- `days[a:b]` starts at index `a` and stops **before** index `b`, so it has `b − a` items.
- Leave out `a` to start at the beginning, or `b` to go to the end.
- A slice is a **new** list; `days` itself doesn't change.
- `x in days` is `True` when `x` is one of the items.
