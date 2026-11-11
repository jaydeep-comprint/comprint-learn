## Worked example: slicing a string

```python
word = "BENGALURU"          # 9 characters, indexes 0 to 8
print(word[0:4])            # BENG    indexes 0, 1, 2, 3
print(word[4:7])            # ALU     indexes 4, 5, 6
print(len(word[2:6]))       # 4       6 − 2 = 4 characters
print(word[:3])             # BEN     no start: from the beginning
print(word[6:])             # URU     no end: to the end
print(word[-3:])            # URU     the last 3 characters
```

- `s[a:b]` starts at index `a` and stops **before** index `b`, so it has `b − a` characters.
- Leave out the start to begin at 0; leave out the end to go to the last character.
- `s[:k]` and `s[k:]` split `s` into two parts that meet at index `k`.
- A slice of a number's string works too: `int(str(2026)[2:])` is `26`.
