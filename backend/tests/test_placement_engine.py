"""The placement engine (spec 012): evidence, the decided rule, next-concept choice, item choice,
stopping and the final classification. Pure, no DB."""

import random
import uuid

import pytest
from app.services.placement_engine import Ev, RangeGraph

from app.services import placement_engine as eng


def ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i + 1) for i in range(n)]


def chain(n: int, w: float = 1.0) -> tuple[RangeGraph, list[uuid.UUID]]:
    """c0 <- c1 <- ... (c0 is the most basic; each concept's prerequisite is the one before)."""
    c = ids(n)
    edges = [(c[i + 1], c[i], w) for i in range(n - 1)]
    return RangeGraph.build(c, edges), c


def diamond() -> tuple[RangeGraph, list[uuid.UUID]]:
    """a <- b, a <- c, b <- d, c <- d (d needs b and c, both need a)."""
    a, b, c, d = ids(4)
    edges = [(b, a, 0.5), (c, a, 0.8), (d, b, 0.5), (d, c, 0.5)]
    return RangeGraph.build([a, b, c, d], edges), [a, b, c, d]


def test_ancestor_weight_is_the_largest_path_product() -> None:
    g, (a, b, c, d) = diamond()
    w = eng.ancestor_weights(g, d)
    assert w[b] == pytest.approx(0.5)
    assert w[c] == pytest.approx(0.5)
    assert w[a] == pytest.approx(0.4)  # d->c->a = 0.5*0.8 beats d->b->a = 0.25
    assert d not in w


def test_correct_answer_credits_ancestors_by_weight() -> None:
    g, (a, b, c, d) = diamond()
    ev = eng.apply_answer(g, eng.initial(g, set()), d, correct=True)
    assert ev[d] == Ev(1.0, 1, 0)
    assert ev[b].e == pytest.approx(0.5)
    assert ev[a].e == pytest.approx(0.4)
    assert ev[a].asked == 0


def test_wrong_answer_debits_every_descendant() -> None:
    g, (a, b, c, d) = diamond()
    ev = eng.apply_answer(g, eng.initial(g, set()), a, correct=False)
    assert ev[a] == Ev(-1.0, 1, 1)
    assert ev[b].e == ev[c].e == ev[d].e == -1.0
    assert ev[d].wrong == 0  # only direct answers count as wrong


def test_decided_rule() -> None:
    assert eng.decided(Ev(2.0, 1, 0))
    assert eng.decided(Ev(-1.0, 1, 1))
    assert eng.decided(Ev(0.0, 2, 1))  # the 2-question cap
    assert not eng.decided(Ev(1.9, 1, 0))
    assert not eng.decided(Ev(-0.5, 0, 0))


def test_learned_concepts_start_with_a_prior() -> None:
    g, (a, b, *_rest) = chain(3)
    ev = eng.initial(g, {a})
    assert ev[a] == Ev(1.0, 0, 0)
    assert ev[b] == Ev(0.0, 0, 0)


def test_first_pick_on_a_chain_is_mid_graph() -> None:
    g, c = chain(7)
    first = eng.next_concept(g, eng.initial(g, set()), set(c))
    assert first == c[4]  # balanced: correct moves 5 concepts halfway, wrong decides 3


def test_first_pick_on_a_full_weight_diamond_is_mid_graph() -> None:
    a, b, c, d = ids(4)
    g = RangeGraph.build([a, b, c, d], [(b, a, 1), (c, a, 1), (d, b, 1), (d, c, 1)])
    assert eng.next_concept(g, eng.initial(g, set()), {a, b, c, d}) == b


def test_low_weights_favour_asking_the_top_concept() -> None:
    """A correct answer on d says little about a, b and c, but a wrong one only decides d, so
    the top concept's worse outcome is still the best."""
    g, (a, b, c, d) = diamond()
    assert eng.next_concept(g, eng.initial(g, set()), {a, b, c, d}) == d


def test_next_concept_skips_decided_and_unaskable() -> None:
    g, c = chain(3)
    ev = eng.initial(g, set())
    ev[c[1]] = Ev(2.0, 1, 0)
    assert eng.next_concept(g, ev, {c[1]}) is None
    assert eng.next_concept(g, ev, {c[0], c[1]}) == c[0]


def test_ties_go_to_the_middle_then_lowest_id() -> None:
    c = ids(3)
    g = RangeGraph.build(c, [])  # three unrelated concepts score the same
    assert eng.next_concept(g, eng.initial(g, set()), set(c)) == c[1]
    assert eng.next_concept(g, eng.initial(g, set()), {c[0], c[2]}) == c[0]


def test_two_question_cap() -> None:
    g, (a,) = chain(1)
    ev = eng.initial(g, set())
    ev = eng.apply_answer(g, ev, a, correct=True)  # e = 1
    assert not eng.decided(ev[a])
    ev = eng.apply_answer(g, ev, a, correct=False)  # e = 0, asked = 2
    assert eng.decided(ev[a])
    assert eng.next_concept(g, ev, {a}) is None


def test_stops_at_25_and_when_nothing_askable_is_undecided() -> None:
    g, c = chain(3)
    ev = eng.initial(g, set())
    assert not eng.finished(0, ev, set(c))
    assert eng.finished(eng.MAX_QUESTIONS, ev, set(c))
    assert eng.finished(0, ev, set())


def test_a_full_run_all_correct_places_everything() -> None:
    g, c = chain(6)
    ev = eng.initial(g, set())
    answered = 0
    while not eng.finished(answered, ev, set(c)):
        nxt = eng.next_concept(g, ev, set(c))
        assert nxt is not None
        ev = eng.apply_answer(g, ev, nxt, correct=True)
        answered += 1
    res = eng.classify(g, ev, learned=set(), conditional=set())
    assert set(res.learned) | set(res.conditional) == set(c)
    assert answered <= len(c)  # never more than one question per concept on a chain


def test_classification_table() -> None:
    a, b, c, d, e = ids(5)
    g = RangeGraph.build([a, b, c, d, e], [])
    ev = {
        a: Ev(2.0, 1, 0),  # not learned -> learned
        b: Ev(1.0, 1, 0),  # not learned -> conditional
        c: Ev(-1.0, 1, 1),  # learned + direct wrong -> demoted
        d: Ev(-1.0, 0, 0),  # learned, no direct wrong -> unchanged
        e: Ev(1.5, 1, 0),  # learned -> unchanged
    }
    res = eng.classify(g, ev, learned={c, d, e}, conditional=set())
    assert res.learned == [a]
    assert res.conditional == [b]
    assert res.demoted == [c]
    assert res.confirmed == []


def test_placed_concepts_imply_their_ancestors_conditionally() -> None:
    g, (a, b, c) = chain(3, w=0.1)
    ev = {a: Ev(0.1, 0, 0), b: Ev(0.1, 0, 0), c: Ev(2.0, 2, 0)}
    res = eng.classify(g, ev, learned={a}, conditional=set())
    assert res.learned == [c]
    assert res.conditional == [b]  # implied; a is already learned


def test_a_later_strong_result_confirms_a_conditional_concept() -> None:
    a, b = ids(2)
    g = RangeGraph.build([a, b], [])
    ev = {a: Ev(2.0, 1, 0), b: Ev(1.0, 1, 0)}
    res = eng.classify(g, ev, learned={a, b}, conditional={a, b})
    assert res.confirmed == [a]
    assert res.learned == res.conditional == res.demoted == []


def test_topo_puts_prerequisites_first() -> None:
    g, (a, b, c, d) = diamond()
    order = eng.topo(g, [d, c, b, a])
    assert order.index(a) < order.index(b) < order.index(d)
    assert order.index(c) < order.index(d)


def test_item_choice_last_kp_first_then_a_different_kp() -> None:
    k1, k2, k3 = [uuid.uuid4() for _ in range(2)], [uuid.uuid4()], [uuid.uuid4()]
    rng = random.Random(1)
    first = eng.pick_item([k1, k2, k3], served=set(), rng=rng)
    assert first in k3
    second = eng.pick_item([k1, k2, k3], served={first}, rng=rng)
    assert second is not None and second not in k3
    # Only the last KP's items remain: fall back to them, never a served one.
    fallback = eng.pick_item(
        [k1, k2, [k3[0], uuid.UUID(int=99)]], served={first, *k1, *k2}, rng=rng
    )
    assert fallback == uuid.UUID(int=99)
    assert eng.pick_item([k3], served=set(k3), rng=rng) is None


def test_deterministic_with_a_fixed_rng() -> None:
    kps = [[uuid.UUID(int=i) for i in range(10)], [uuid.UUID(int=i) for i in range(10, 20)]]
    one = eng.pick_item(kps, served=set(), rng=random.Random(7))
    two = eng.pick_item(kps, served=set(), rng=random.Random(7))
    assert one == two


def test_evidence_round_trips_through_json() -> None:
    g, c = chain(2)
    ev = eng.apply_answer(g, eng.initial(g, {c[0]}), c[1], correct=True)
    assert eng.load_evidence(eng.dump_evidence(ev)) == ev
