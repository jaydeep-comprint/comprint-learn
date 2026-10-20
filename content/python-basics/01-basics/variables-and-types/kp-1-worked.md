## Worked example: following a variable

```python
apples = 4
apples = apples + 3
apples = apples * 2
print(apples)
```

Track the value line by line:

1. `apples = 4` → apples is 4.
2. `apples = apples + 3` → the right side is worked out first: 4 + 3 = 7, then stored. apples is 7.
3. `apples = apples * 2` → 7 × 2 = 14. apples is 14.
4. `print(apples)` prints **14**.

`=` means "store the right side in the name on the left". `apples += 3` is a short way to write `apples = apples + 3`.
