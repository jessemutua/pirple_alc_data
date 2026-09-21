# drinks/drink_types.py
"""
One vocabulary for what a drink is, shared by the ledger and the log.

A product's category and a logged drink's type use the same words, so a
valid scan logs its drink straight from the ledger with no mapping, and the
two can never drift apart.

"spirits" stays valid for drinks logged before the finer types existed and
for products the ledger has not yet categorised further. The app no longer
offers it as a choice.
"""

DRINK_TYPES = (
    "beer",
    "cider",
    "wine",
    "whisky",
    "vodka",
    "gin",
    "brandy",
    "rum",
    "liqueur",
    "rtd",
    "spirits",
    "other",
)

FALLBACK_DRINK_TYPE = "other"


def normalise_drink_type(value) -> str:
    """Any stored, ledger or legacy value, reduced to a known type."""
    cleaned = str(value or "").strip().lower()
    return cleaned if cleaned in DRINK_TYPES else FALLBACK_DRINK_TYPE