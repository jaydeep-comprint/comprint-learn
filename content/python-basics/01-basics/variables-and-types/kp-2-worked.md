## Worked example: types and conversion

```python
age = "15"        # a str: text, even though it looks like a number
next_year = int(age) + 1
print(next_year)          # 16
print(type(next_year))    # <class 'int'>
print("Age: " + str(next_year))
```

- `int("15")` turns the text `"15"` into the number 15.
- `int(7.9)` gives **7**: it cuts off the decimal part, it does not round.
- `str(16)` turns the number into text so it can be joined with `+` to another string.
- `"15" + 1` is an error (TypeError): Python won't add text and a number.
