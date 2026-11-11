## Worked example: parameters and return values

```python
def bigger(a, b):
    if a > b:
        return a             # return ends the function here
    return b

def double(x):
    return 2 * x

print(bigger(4, 9))          # a = 4, b = 9, prints 9
print(double(bigger(7, 3)))  # inner call first: bigger(7, 3) = 7, then double(7) = 14
```

| Call | Parameters | Returns |
|---|---|---|
| `bigger(4, 9)` | a = 4, b = 9 | 9 |
| `bigger(7, 3)` | a = 7, b = 3 | 7 |
| `double(7)` | x = 7 | 14 |

- Arguments go to parameters **by position**: the first value to the first parameter, and so on.
- In `double(bigger(7, 3))` the inner call runs first and its return value is passed on.
- `return` stops the function at once. Lines after it in the same block never run.
- `/` always gives a float: a function returning `n / 2` gives `4.5` for 9.
