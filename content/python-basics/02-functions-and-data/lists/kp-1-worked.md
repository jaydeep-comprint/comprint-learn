## Worked example: reading items by index

```python
runs = [34, 12, 57, 8]
print(runs[0])            # 34
print(runs[2])            # 57
print(runs[-1])           # 8
print(runs[1] + runs[3])  # 12 + 8 = 20
```

| Index | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Item | 34 | 12 | 57 | 8 |
| Negative index | −4 | −3 | −2 | −1 |

- The first item is `runs[0]`, not `runs[1]`.
- `runs` has 4 items, so the last index is 3. `runs[4]` is an **IndexError**.
- Negative indexes count from the end: `runs[-1]` is always the last item.
