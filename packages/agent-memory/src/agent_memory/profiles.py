"""Domain profiles: domain behaviour on top of the universal core (architecture revision 3, section 8).

The four trees, the cross-tree layer and the preservation classes are the
same for every project. A profile adds what one kind of work needs:

| Profile | Adds |
|---|---|
| `generic` (always on) | versions and metadata for any artifact; the core knowledge and state kinds; a plain folder walk for reconciliation |
| `software` | the code dependency graph, git-accelerated reconciliation and attribution, verification records |

`documents` arrives in Stage 2.7. Creative, research, business and ADAM
profiles come later, on demand (decision D13).

A store remembers its profiles. Opening it with an explicit list changes
them, and the change applies from then on; history is never rewritten.
"""
from __future__ import annotations

PROFILES = {
    "generic": "versions and metadata for any artifact, the core knowledge and state kinds, a folder walk",
    "software": "code dependency graph, git-accelerated reconciliation, verification records",
}
DEFAULT = ("generic", "software")


class ProfileError(ValueError):
    """A feature was used that belongs to a profile this store doesn't have."""


def normalize(names) -> tuple[str, ...]:
    chosen = {"generic", *names}
    unknown = sorted(chosen - set(PROFILES))
    if unknown:
        raise ProfileError(f"unknown profile(s) {unknown}; available: {sorted(PROFILES)}")
    return tuple(p for p in PROFILES if p in chosen)
