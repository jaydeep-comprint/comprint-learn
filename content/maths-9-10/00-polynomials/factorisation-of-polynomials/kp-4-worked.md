## Worked example: factorising a cubic

Factorise $p(x) = x^3 - 2x^2 - 5x + 6$.

1. **Find one zero by trial.** An integer zero must divide the constant term 6, so try $\pm 1, \pm 2, \pm 3, \pm 6$.
   $p(1) = 1 - 2 - 5 + 6 = 0$, so by the factor theorem $x - 1$ is a factor.
2. **Find the other factor.** Write $p(x) = (x - 1)(x^2 + bx + c)$ and compare coefficients
   (or divide $p(x)$ by $x - 1$):
   - $x^2$ terms: $b - 1 = -2$, so $b = -1$.
   - constants: $-c = 6$, so $c = -6$.

   So $p(x) = (x - 1)(x^2 - x - 6)$.
3. **Factorise the quadratic** by splitting the middle term: product $-6$, sum $-1$ gives $-3$ and $2$, so
   $x^2 - x - 6 = (x - 3)(x + 2)$.
4. **Answer**: $p(x) = (x - 1)(x - 3)(x + 2)$. The zeros are $1$, $3$ and $-2$.

Check one: $p(-2) = -8 - 8 + 10 + 6 = 0$. ✓
