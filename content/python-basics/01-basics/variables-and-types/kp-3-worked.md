## Worked example: arithmetic operators

| Operator | Meaning | `17 ? 5` |
|---|---|---|
| `+` `-` `*` | add, subtract, multiply | 22, 12, 85 |
| `/` | division (always a float) | 3.4 |
| `//` | floor division (whole part) | 3 |
| `%` | remainder | 2 |
| `**` | power | 1419857 |

Example: 200 minutes in hours and minutes:

```python
minutes = 200
print(minutes // 60)   # 3 hours
print(minutes % 60)    # 20 minutes left over
```

`**` happens before `*` and `/`, which happen before `+` and `-`. Use brackets to be clear.
