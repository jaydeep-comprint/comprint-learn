# List algorithms

An **algorithm** is a step-by-step recipe. Many useful ones just walk through a list with a `for` loop
and an `if`, and keep track of something as they go.

```python
def count_passes(marks):
    count = 0                 # set up BEFORE the loop
    for m in marks:
        if m >= 33:
            count = count + 1
    return count

print(count_passes([45, 20, 33, 78]))   # 3
```

- **Search**: find where a value is (its index), or −1 if it isn't there.
- **Biggest / smallest**: keep the best value seen so far, starting from the first item.
- **Filter and count**: keep or count only the items that pass a test.
- **Nested loops**: a loop inside a loop, to look at pairs of items or at a grid (a list of lists).
