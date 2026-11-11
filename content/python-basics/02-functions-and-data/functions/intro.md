# Functions

A **function** is a named block of code. You write it once with `def`, then **call** it as many times as you like.

```python
def area(length, width):      # define: nothing runs yet
    return length * width     # send a value back to the caller

a = area(5, 3)                # call: length = 5, width = 3, so a = 15
print(a + area(2, 2))         # 15 + 4 = 19
```

- The body runs only when the function is **called**, not when it is defined.
- **Parameters** (`length`, `width`) take the values you pass in, in order.
- `return` gives a value back to the caller. `print` only shows it on the screen.
- Variables made inside a function are **local**: they don't exist outside it.
