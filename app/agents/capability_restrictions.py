"""Generic capability restriction mechanism for GoalOS.

Users can constrain GoalOS autonomous capability resolution with explicit
plain-language restrictions. Restrictions are parsed deterministically
from the requirement text and applied AFTER autonomous matching
(deterministic keyword matching plus any LLM refinement), so an explicit
user restriction always wins over any capability the keyword matcher or
the LLM would otherwise add.

Supported forms:

- Whitelist: "use only X", "ONLY the X capability", "only these
  capabilities: X, Y", "restrict/limit to X", ...
- Blacklist: "do not use X", "never use X", "without X", "except X",
  "avoid X", "excluding X", ...

Capability references are resolved against the known capability catalog
(names and their deterministic keywords) using flexible word-boundary
comparison, so "web_research", "web research", "WooCommerce" and
"analytics" all resolve to their registered capability names.

The mechanism is generic: it takes the known ``(name, keywords)`` pairs
from any capability source (the persistent registry or the static
catalog) and filters matched capability names. It is not special-cased to
any one integration or business use case.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityRestrictions:
    """Explicit capability restrictions parsed from a requirement.

    Attributes:
        whitelist: Capability names the user explicitly allowed
            ("use ONLY ..."). When non-empty, only these capabilities may
            survive resolution.
        blacklist: Capability names the user explicitly prohibited
            ("do not use ..."). These are always removed.
    """

    whitelist: frozenset[str] = frozenset()
    blacklist: frozenset[str] = frozenset()

    @property
    def active(self) -> bool:
        """Whether any restriction was detected."""
        return bool(self.whitelist or self.blacklist)

    def describe(self) -> str:
        """Human-readable restriction summary for LLM prompts."""
        parts: list[str] = []
        if self.whitelist:
            parts.append(
                "ONLY these capabilities may be used: "
                + ", ".join(sorted(self.whitelist))
            )
        if self.blacklist:
            parts.append(
                "these capabilities are prohibited: "
                + ", ".join(sorted(self.blacklist))
            )
        return "; ".join(parts)


#: Whitelist phrases. Each captures the capability list that follows the
#: marker, up to the end of the sentence.
_WHITELIST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:use|using)\s+only\s+(?:the\s+|on\s+)?([^.!?\n]+)"),
    re.compile(r"\bonly\s+use\s+(?:the\s+)?([^.!?\n]+)"),
    re.compile(r"\bonly\s+(?:these|the\s+following)\s+capabilit(?:y|ies)\s*[:=]\s*([^.!?\n]+)"),
    re.compile(r"\bonly\s+(?:the\s+)?([a-z0-9_]+(?:\s*[,/]\s*[a-z0-9_]+)*)\s+capabilit"),
    re.compile(r"\b(?:restrict(?:ed|ing)?|limit(?:ed|ing)?)\s+to\s+([^.!?\n]+)"),
)

#: Blacklist phrases. Each captures the prohibited capability list that
#: follows the marker, up to the end of the sentence.
_BLACKLIST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:do not use|don'?t use|never use|must not use|should not use|not use)\s+([^.!?\n]+)"),
    re.compile(r"\bwithout\s+([^.!?\n]+)"),
    re.compile(r"\bexcept\s+([^.!?\n]+)"),
    re.compile(r"\bavoid\s+([^.!?\n]+)"),
    re.compile(r"\bexclud(?:e|ing)\s+([^.!?\n]+)"),
)

#: Words that end a restriction list and start the actual task description.
#: A restriction phrase is truncated at the first stop word (after the
#: first token), so "use only web_research to search the web" captures just
#: ``web_research`` and "do not use gmail for this task" captures ``gmail``.
_STOP_WORDS: tuple[str, ...] = (
    " to ",
    " for ",
    " in ",
    " on ",
    " with ",
    " using ",
    " please ",
    " then ",
    " and then ",
    " so ",
    " because ",
    " when ",
    " while ",
    " after ",
    " before ",
    " now ",
    " instead ",
    " you ",
    " that ",
    " thanks ",
)


def _bounded_phrase(phrase: str) -> str:
    """Truncate a restriction phrase at the first list-ending word.

    The first token is never truncated away ("without using X" must keep
    ``using X``).
    """
    lowered = phrase.casefold()
    positions = [lowered.find(word) for word in _STOP_WORDS]
    positions = [position for position in positions if position > 0]
    if positions:
        return phrase[: min(positions)]
    return phrase


def _flexible_pattern(token: str) -> re.Pattern[str]:
    """Build a word-boundary regex that tolerates space/underscore separators.

    ``web_research``, ``web research`` and ``web  research`` all match
    ``web_research``; underscores count as word characters so a name is
    never matched as a substring of a larger token (``website`` does not
    match inside ``website_analysis``).
    """
    parts = re.split(r"[\s_]+", re.escape(token))
    return re.compile(r"\b" + r"[\s_]+".join(parts) + r"\b", re.IGNORECASE)


def _resolve_names(
    phrase: str,
    patterns: Sequence[tuple[re.Pattern[str], str]],
) -> set[str]:
    """Return registered capability names referenced in ``phrase``."""
    found: set[str] = set()
    for pattern, name in patterns:
        if pattern.search(phrase):
            found.add(name)
    return found


def parse_capability_restrictions(
    requirement: str,
    known: Iterable[tuple[str, Iterable[str]]],
) -> CapabilityRestrictions:
    """Parse explicit capability restrictions from ``requirement``.

    Args:
        requirement: The user's goal text.
        known: Registered capabilities as ``(name, keywords)`` pairs. The
            parser resolves capability references in restriction phrases
            against these names and keywords.

    Returns:
        The parsed restrictions (both sets empty when none are detected).
    """
    patterns: list[tuple[re.Pattern[str], str]] = []
    for name, keywords in known:
        patterns.append((_flexible_pattern(name), name))
        for keyword in keywords:
            patterns.append((_flexible_pattern(keyword), name))

    # Marker matching is case-insensitive ("Use ONLY", "Do not use").
    text = requirement.casefold()
    whitelist: set[str] = set()
    blacklist: set[str] = set()
    for pattern in _WHITELIST_PATTERNS:
        for match in pattern.finditer(text):
            whitelist.update(_resolve_names(_bounded_phrase(match.group(1)), patterns))
    for pattern in _BLACKLIST_PATTERNS:
        for match in pattern.finditer(text):
            blacklist.update(_resolve_names(_bounded_phrase(match.group(1)), patterns))
    return CapabilityRestrictions(
        whitelist=frozenset(whitelist),
        blacklist=frozenset(blacklist),
    )


def apply_capability_restrictions(
    matched: Sequence[Any],
    restrictions: CapabilityRestrictions | None,
    resolve: Callable[[str], Iterable[str]] | None = None,
) -> list[Any]:
    """Filter matched capabilities by explicit restrictions (last word wins).

    When a whitelist is present only capabilities related to it survive;
    blacklisted capabilities (and anything related to them) are always
    removed. ``resolve`` may map a capability name to its related
    capability names (its execution capability and the integration
    capabilities it requires), so prohibiting an integration also removes
    capabilities that require it. Unrestricted requirements pass through
    untouched.

    Args:
        matched: Matched capabilities as names or objects with a ``name``.
        restrictions: Parsed restrictions; ``None``/inactive returns input.
        resolve: Optional ``name -> related names`` resolver.

    Returns:
        The filtered capabilities, preserving order.
    """
    if restrictions is None or not restrictions.active:
        return list(matched)
    whitelist = restrictions.whitelist
    blacklist = restrictions.blacklist
    filtered: list[Any] = []
    for result in matched:
        name = result.name if hasattr(result, "name") else str(result)
        related = {name}
        if resolve is not None:
            related.update(resolve(name) or ())
        if whitelist and not (related & whitelist):
            continue
        if related & blacklist:
            continue
        filtered.append(result)
    return filtered
