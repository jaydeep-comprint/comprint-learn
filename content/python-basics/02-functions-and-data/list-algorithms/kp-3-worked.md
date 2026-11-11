## Worked example: filtering and counting

Keep the marks that pass (33 or more), and count them:

```python
def passes(marks):
    result = []                 # BEFORE the loop
    for m in marks:
        if m >= 33:
            result.append(m)    # keep only the matches
    return result

good = passes([45, 20, 33, 12])
print(good)          # [45, 33]
print(len(good))     # 2
```

| m | m >= 33? | result after |
|---|---|---|
| 45 | yes | [45] |
| 20 | no | [45] |
| 33 | yes | [45, 33] |
| 12 | no | [45, 33] |

- To **count** without keeping the items, use `count = count + 1` inside the `if`.
- The test can be anything true or false: `x % 2 == 0` (even), `x >= lo and x <= hi` (between, ends included).
- Set `result = []` or `count = 0` once, before the loop. The function must `return` it, not `print` it.
