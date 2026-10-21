## Worked example: adding up in a loop

Find 1 + 2 + … + 5:

```python
total = 0                  # start the total BEFORE the loop
for i in range(1, 6):      # 1, 2, 3, 4, 5
    total = total + i
print(total)
```

| Pass | i | total after |
|---|---|---|
| 1 | 1 | 1 |
| 2 | 2 | 3 |
| 3 | 3 | 6 |
| 4 | 4 | 10 |
| 5 | 5 | 15 |

It prints **15**. If `total = 0` were inside the loop, it would be reset on every pass and print 5.
To count instead of add, use `count = count + 1` inside an `if`.
