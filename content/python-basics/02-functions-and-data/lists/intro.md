# Lists

A **list** keeps many values in one variable, in order.

```python
marks = [72, 85, 64]      # a list of 3 numbers
print(marks[0])           # 72: the first item is at index 0
print(len(marks))         # 3
```

- Items are numbered from **0**: in a list of `n` items the last one is at index `n − 1` (or `-1`).
- A list can **change**: you can add, insert and remove items.
- A `for` loop visits every item, so you can add them up or build a new list.
- A **slice** like `marks[0:2]` takes part of a list; `in` checks whether a value is in it.
