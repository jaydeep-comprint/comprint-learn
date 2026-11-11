## Worked example: creating a dictionary and looking up a key

```python
marks = {"Asha": 72, "Ravi": 85, "Meera": 64}
print(marks["Ravi"])              # 85
print(marks.get("Meera", 0))      # 64: "Meera" is a key
print(marks.get("Kabir", 0))      # 0: no key "Kabir", so the default
print("Kabir" in marks)           # False
print(marks["Kabir"])             # KeyError: 'Kabir'
```

| Key | "Asha" | "Ravi" | "Meera" |
|---|---|---|---|
| Value | 72 | 85 | 64 |

- You look up by **key**: `marks["Ravi"]`. `marks[85]` is a KeyError, because 85 is a value, not a key.
- A dictionary has no positions: `marks[0]` is a KeyError too (there is no key `0`).
- `d.get(key, default)` never raises an error: it gives the default when the key is missing
  (`None` if you leave the default out). `key in d` checks the **keys**.
- Keys can be numbers too: in `{1: 1, 2: 4, 3: 9}`, `d[2]` is 4 (the value for key 2).
- If you write the same key twice, like `{"Asha": 72, "Asha": 90}`, only the **last** value is kept.
