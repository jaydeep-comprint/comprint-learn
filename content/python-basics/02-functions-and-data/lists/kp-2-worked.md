## Worked example: changing a list

```python
nums = [5, 9]
nums.append(4)        # [5, 9, 4]     add at the end
nums.insert(0, 7)     # [7, 5, 9, 4]  put 7 at index 0
nums.remove(9)        # [7, 5, 4]     delete the first 9
last = nums.pop()     # last = 4, nums = [7, 5]
first = nums.pop(0)   # first = 7, nums = [5]
print(len(nums))      # 1
```

- `append`, `insert` and `remove` change the list **in place** and give back `None`.
  So write `nums.append(4)`, never `nums = nums.append(4)` (that sets `nums` to `None`).
- `pop()` removes the last item **and gives it back**; `pop(i)` does the same for index `i`.
- `remove(x)` deletes only the **first** copy of `x`.
- `len(nums)` is the number of items.
