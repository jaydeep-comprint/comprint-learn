## Worked example: indexing a string

```python
pin = "4719"
print(pin[0])                     # 4
print(pin[-1])                    # 9
print(int(pin[1]) + int(pin[-2])) # 7 + 1 = 8
```

| Character | 4 | 7 | 1 | 9 |
|---|---|---|---|---|
| Index | 0 | 1 | 2 | 3 |
| Negative index | −4 | −3 | −2 | −1 |

- The first character is `pin[0]`, not `pin[1]`. `pin` has 4 characters, so `pin[4]` is an **IndexError**.
- `pin[-k]` is the same character as `pin[len(pin) - k]`: `pin[-2]` is `pin[2]`.
- Each character is itself a string: `pin[1]` is `"7"`, so use `int(pin[1])` to do maths with it.
