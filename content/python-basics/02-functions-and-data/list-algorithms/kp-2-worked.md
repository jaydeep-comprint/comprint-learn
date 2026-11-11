## Worked example: the biggest and smallest by hand

```python
def biggest(nums):
    best = nums[0]          # start with the first item, not 0
    for x in nums:
        if x > best:
            best = x        # a new biggest so far
    return best

print(biggest([-7, -2, -9]))   # -2
```

| x | x > best? | best after |
|---|---|---|
| −7 | no | −7 |
| −2 | yes | −2 |
| −9 | no | −2 |

- Start with `nums[0]`. If `best` started at 0, an all-negative list would wrongly give 0.
- For the smallest, use `x < best` instead.
- To find **where** the biggest is, keep an index: `if nums[i] > nums[best_i]: best_i = i`.
- An empty list has no `nums[0]`, so check `len(nums) == 0` first (and, say, `return None`).
