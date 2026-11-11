# Variables and types

A **variable** is a name that points to a value. You create or change one with `=`:

```python
score = 10
score = score + 5   # now 15
```

Every value has a **type**. The four you will use most are:

| Type | Example | Meaning |
|---|---|---|
| `int` | `42` | whole number |
| `float` | `3.5` | number with a decimal point |
| `str` | `"hello"` | text |
| `bool` | `True` | true or false |

Python works out each step from top to bottom, so the order of your lines matters.

**How code tasks work.** A code task gives you a starting line like `def to_hours(minutes):`. Write your
lines under it, indented, and finish with `return` and the answer, e.g. `return minutes // 60`. To give back
two values, return them in square brackets: `return [hours, mins]`. You'll learn more about `def` and
`return` in the Functions lesson.
