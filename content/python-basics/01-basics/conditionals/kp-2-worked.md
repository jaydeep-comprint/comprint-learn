## Worked example: if / else

Is a number even or odd?

```python
n = 14
if n % 2 == 0:
    print(n // 2)
else:
    print(3 * n + 1)
```

1. `n % 2` is the remainder after dividing by 2: 14 % 2 = 0.
2. `0 == 0` is `True`, so the `if` block runs and prints 14 // 2 = **7**.
3. The `else` block is skipped. `else` runs only when the condition is `False`.

Indentation (4 spaces) tells Python which lines belong to each block.
