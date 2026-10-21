## Worked example: elif chains

```python
marks = 81
if marks >= 90:
    grade = "A"
elif marks >= 75:
    grade = "B"
elif marks >= 50:
    grade = "C"
else:
    grade = "D"
print(grade)
```

Python checks the conditions **top to bottom** and runs only the **first** one that is `True`:

1. `81 >= 90` is False → skip.
2. `81 >= 75` is True → grade = "B", and the rest of the chain is skipped,
   even though `81 >= 50` is also True.

So the order of the conditions matters: put the strictest test first.
