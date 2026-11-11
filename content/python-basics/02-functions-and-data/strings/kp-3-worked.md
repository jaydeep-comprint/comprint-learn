## Worked example: string methods

```python
name = "  Asha Rao  "
clean = name.strip()           # "Asha Rao"     spaces removed from both ends
print(clean.upper())           # ASHA RAO
print(clean.lower())           # asha rao
print(clean.replace("a", "@")) # Ash@ R@o       every "a" replaced
print(clean.find("R"))         # 5              index of the first "R"
print(clean.find("z"))         # -1             not found
parts = clean.split()          # ["Asha", "Rao"]
print(len(parts))              # 2
print(parts[1])                # Rao
print(name)                    # "  Asha Rao  " unchanged!
```

- A method gives back a **new** string; the old one doesn't change. Write `name = name.strip()` to keep it.
- `find` gives the index of the first match, or `-1` if there is none.
- `split()` cuts at spaces; `split(",")` cuts at commas. It gives back a **list** of the parts: use
  `len(parts)` for how many, and `parts[0]`, `parts[1]` … to read them.
