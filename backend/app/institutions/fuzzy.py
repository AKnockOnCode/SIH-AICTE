"""String similarity in the style of RapidFuzz (RapidFuzz itself was not installable here).

`ratio` is the normalised Indel similarity used by `rapidfuzz.fuzz.ratio`:
100 * 2 * LCS(a, b) / (len(a) + len(b)). LCS is computed with the bit-parallel algorithm
of Hyyrö (2004) on Python integers, so it is fast enough for interactive matching.
`partial_ratio`, `token_sort_ratio` and `token_set_ratio` follow the RapidFuzz definitions.
"""

from __future__ import annotations


def lcs_length(a: str, b: str) -> int:
    if not a or not b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    masks: dict[str, int] = {}
    for i, ch in enumerate(a):
        masks[ch] = masks.get(ch, 0) | (1 << i)
    full = (1 << len(a)) - 1
    v = full
    for ch in b:
        u = v & masks.get(ch, 0)
        v = ((v + u) | (v - u)) & full
    return len(a) - bin(v).count("1")


def ratio(a: str, b: str) -> float:
    if not a and not b:
        return 100.0
    if not a or not b:
        return 0.0
    return 100.0 * 2 * lcs_length(a, b) / (len(a) + len(b))


def partial_ratio(a: str, b: str) -> float:
    """Best ratio of the shorter string against equal-length windows of the longer one."""
    if not a or not b:
        return 0.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    n, m = len(short), len(long_)
    if n == m:
        return ratio(short, long_)
    best = 0.0
    for start in range(0, m - n + 1):
        r = ratio(short, long_[start:start + n])
        if r > best:
            best = r
            if best == 100.0:
                break
    return best


def token_sort_ratio(a: str, b: str) -> float:
    return ratio(" ".join(sorted(a.split())), " ".join(sorted(b.split())))


def token_set_ratio(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = " ".join(sorted(ta & tb))
    diff_ab = " ".join(sorted(ta - tb))
    diff_ba = " ".join(sorted(tb - ta))
    if inter and (not diff_ab or not diff_ba):
        return 100.0
    sect_ab = f"{inter} {diff_ab}".strip()
    sect_ba = f"{inter} {diff_ba}".strip()
    scores = [ratio(sect_ab, sect_ba)]
    if inter:
        scores += [ratio(inter, sect_ab), ratio(inter, sect_ba)]
    return max(scores)
