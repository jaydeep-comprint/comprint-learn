## Worked example: nested loops

A loop inside a loop: the inner loop runs **completely** on every pass of the outer one.

```python
count = 0
for i in range(3):
    for j in range(i + 1, 3):     # only j bigger than i
        print(i, j)               # 0 1, 0 2, 1 2
        count = count + 1
print(count)                      # 3 pairs
```

A **grid** is a list of lists. `grid[r][c]` is row `r`, column `c`:

```python
grid = [[4, 1, 6],
        [2, 8, 3]]
totals = []
for row in grid:          # row is [4, 1, 6], then [2, 8, 3]
    t = 0                 # reset for each row
    for x in row:
        t = t + x
    totals.append(t)
print(totals)             # [11, 13]
print(grid[1][0])         # 2
```

- `range(n)` inside `range(m)` runs the inner body `m × n` times.
- Starting the inner loop at `i + 1` gives each pair once: n items have n × (n − 1) ÷ 2 pairs.
- Rows and columns both start at index 0.
