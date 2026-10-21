## Worked example: while loops

How many times can you take 3 away from 10 before it reaches 0 or less?

```python
n = 10
steps = 0
while n > 0:
    n = n - 3
    steps = steps + 1
print(steps)
```

| Check `n > 0` | n after | steps |
|---|---|---|
| 10 > 0 ✓ | 7 | 1 |
| 7 > 0 ✓ | 4 | 2 |
| 4 > 0 ✓ | 1 | 3 |
| 1 > 0 ✓ | −2 | 4 |
| −2 > 0 ✗ | stop | |

It prints **4**. The loop must change `n`; without `n = n - 3` the condition stays True forever.
