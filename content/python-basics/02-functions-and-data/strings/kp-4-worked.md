## Worked example: looping over a string

Count the vowels in a city name:

```python
city = "BENGALURU"
count = 0
for ch in city:
    if ch in "AEIOU":
        count = count + 1
print(count)
```

| ch | B | E | N | G | A | L | U | R | U |
|---|---|---|---|---|---|---|---|---|---|
| count after | 0 | 1 | 1 | 1 | 2 | 2 | 3 | 3 | 4 |

It prints **4**. To build a new string, start with `""` and add to it:

```python
out = ""
for ch in "GOA":
    out = ch + out      # "G", then "OG", then "AOG"
print(out)              # AOG: the word reversed
```

- `for ch in s` gives each character in turn, from index 0.
- `for i in range(len(s))` gives each **index**; use `s[i]` for the character.
- Set `count = 0` or `out = ""` **before** the loop, not inside it.
