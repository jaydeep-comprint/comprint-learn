## Worked example: for loops and range

`range` makes a sequence of whole numbers. The **stop value is never included**.

| Call | Values |
|---|---|
| `range(4)` | 0, 1, 2, 3 |
| `range(2, 6)` | 2, 3, 4, 5 |
| `range(1, 10, 3)` | 1, 4, 7 |

```python
for i in range(2, 6):
    print(i * i)
```

The loop runs 6 − 2 = **4** times and prints 4, 9, 16, 25. In general `range(a, b)` gives `b - a` values.
