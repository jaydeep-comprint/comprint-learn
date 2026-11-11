# Strings

A **string** is text: a sequence of characters, each with its own index, starting at **0**.

```python
city = "MUMBAI"
print(city[0])          # M: the first character is at index 0
print(city[-1])         # I: negative indexes count from the end
print(city[1:4])        # UMB: a slice stops just before index 4
print(city.lower())     # mumbai: a new string; city itself is still "MUMBAI"
print(len(city))        # 6
print("ab" * 3)         # ababab: * repeats a string
```

- A string of `n` characters has indexes `0` to `n − 1`, or `-n` to `-1` from the end.
- A **slice** `s[a:b]` takes characters `a` up to, but not including, `b`.
- Strings **can't be changed**. Methods like `upper()`, `strip()` and `replace()` give back a new string.
- A `for` loop visits every character, so you can count letters or build a new string.
