## Worked example: return versus print

```python
def show_square(n):
    print(n * n)             # shows a value, gives nothing back

def get_square(n):
    return n * n             # gives the value back

a = show_square(4)           # prints 16; a is None
b = get_square(4)            # prints nothing; b is 16
print(b + 1)                 # 17
print(a)                     # None
```

| Line | Printed | Value stored |
|---|---|---|
| `a = show_square(4)` | 16 | a = None |
| `b = get_square(4)` | (nothing) | b = 16 |
| `print(b + 1)` | 17 | |
| `print(a)` | None | |

- `print` shows a value on the screen. The caller **does not get it**.
- `return` hands the value back, so the caller can store it, add to it or pass it on.
- A function with no `return` gives back `None`. `a + 1` here would be a TypeError.
- A function can do both: print something and then return something else.
