## Worked example: linear search

Find the index of a value, or −1 if it is not in the list:

```python
def find_index(items, target):
    for i in range(len(items)):    # i = 0, 1, 2, ...
        if items[i] == target:
            return i               # found: stop at once
    return -1                      # after the loop: not found

runs = [12, 45, 30, 45]
print(find_index(runs, 45))        # 1
print(find_index(runs, 99))        # -1
```

| i | items[i] | == 45? |
|---|---|---|
| 0 | 12 | no |
| 1 | 45 | yes → return 1 |

- `return` ends the function at once, so you get the **first** match (index 1, not 3).
- `return -1` goes **after** the loop, not in an `else`: you only know a value is missing when you
  have checked every item.
- −1 can't be a real index from this loop, so it safely means "not found".
- Outside a function, `break` does the same job as `return`: it ends the loop at once when the item is found.
