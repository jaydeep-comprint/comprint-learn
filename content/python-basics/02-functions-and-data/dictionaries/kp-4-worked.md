## Worked example: counting with a dictionary

Count the letters of a word:

```python
word = "noon"
counts = {}                              # before the loop
for ch in word:
    counts[ch] = counts.get(ch, 0) + 1   # 0 the first time we see ch
print(counts)                            # {'n': 2, 'o': 2}
print(len(counts))                       # 2 different letters
```

| Pass | ch | counts after |
|---|---|---|
| 1 | "n" | {'n': 1} |
| 2 | "o" | {'n': 1, 'o': 1} |
| 3 | "o" | {'n': 1, 'o': 2} |
| 4 | "n" | {'n': 2, 'o': 2} |

- Make the empty dictionary **before** the loop, or it is emptied again on every pass.
- `counts.get(ch, 0) + 1` works for new and old keys. The longer way is
  `if ch in counts: counts[ch] = counts[ch] + 1` / `else: counts[ch] = 1`.
- `len(counts)` is the number of **different** things counted.
- `"noon" * 3` repeats a string: `"noonnoonnoon"`, so every count is 3 times bigger.
  To count words, loop over `text.split()` instead of the letters.
