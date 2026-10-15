"""Choosing which question type each question gets (done in code, not by the LLM).

Small local models tend to produce the same type again and again, so the type mix is decided
here from the weights in config/question_types.yaml and only then handed to the model.
"""
from __future__ import annotations

import random

from .config import QuestionTypeSpec


def assign_types(count: int, specs: list[QuestionTypeSpec], seed: int | None = None, jitter: float = 0.35) -> list[str]:
    """Return ``count`` type keys, mixed according to the weights of ``specs``.

    Step 1 - quotas: each type gets ``count * weight / total_weight`` questions. The integer part
    is assigned directly; the remaining slots go to the types with the largest fractional parts.
    A little random jitter breaks ties so short surveys do not always get the same types.
    Step 2 - ordering: types are interleaved greedily (always pick the type with the most
    questions left that differs from the previous one) so identical types do not cluster.
    """
    if count <= 0:
        return []
    if not specs:
        raise ValueError("No question types are enabled.")

    rng = random.Random(seed)
    total_weight = sum(max(s.weight, 0) for s in specs)
    weights = [max(s.weight, 0) if total_weight > 0 else 1.0 for s in specs]
    total_weight = sum(weights)

    quotas = [count * w / total_weight for w in weights]
    base = [int(q) for q in quotas]
    remaining = count - sum(base)
    ranked = sorted(range(len(specs)), key=lambda i: (quotas[i] - base[i]) + rng.uniform(0, jitter), reverse=True)
    for index in ranked[:remaining]:
        base[index] += 1

    left = {specs[i].key: base[i] for i in range(len(specs)) if base[i] > 0}
    ordered: list[str] = []
    previous: str | None = None
    while len(ordered) < count:
        candidates = [k for k, n in left.items() if n > 0 and k != previous]
        if not candidates:  # only the previous type is left, repetition is unavoidable
            candidates = [k for k, n in left.items() if n > 0]
        top = max(left[k] for k in candidates)
        choice = rng.choice([k for k in candidates if left[k] == top])
        ordered.append(choice)
        left[choice] -= 1
        previous = choice
    return ordered
