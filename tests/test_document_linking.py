"""Connecting an uploaded datasheet to the catalogue row it describes.

Extraction has always produced typed facts with page-level evidence, and
those facts have never reached a product record — the gap the README calls
the largest open one. The link is the part number: a datasheet that names
one is talking about a specific row, and a datasheet that names none is
talking about nothing this catalogue holds.

Matching is exact, on purpose. A fuzzy match that attaches a 2-inch
valve's specifications to a 1/2-inch valve is worse than no match at all,
because the result looks verified.
"""

import unittest

from backend.specledger.document_linking import (
    find_matching_rows, proposals_from_facts, normalize_part_number,
)
from backend.specledger.extraction import ExtractedFact


def _fact(name: str, value: str, page: int = 1) -> ExtractedFact:
    return ExtractedFact(name, value, page, f"{name}: {value}")


CATALOGUE = [
    {"batch_id": "b1", "row_number": 1, "part_number": "70-104-01"},
    {"batch_id": "b1", "row_number": 2, "part_number": "R02D215P1RW"},
    {"batch_id": "b1", "row_number": 3, "part_number": "DCG413B"},
]


class PartNumberNormalizationTests(unittest.TestCase):
    def test_case_and_padding_are_ignored(self) -> None:
        assert normalize_part_number("  r02d215p1rw ") == normalize_part_number("R02D215P1RW")

    def test_separators_are_ignored(self) -> None:
        assert normalize_part_number("70-104-01") == normalize_part_number("7010401")

    def test_distinct_parts_stay_distinct(self) -> None:
        assert normalize_part_number("70-104-01") != normalize_part_number("70-108-01")


class MatchingTests(unittest.TestCase):
    def test_exact_part_number_matches_its_row(self) -> None:
        links = find_matching_rows([_fact("part_number", "70-104-01")], CATALOGUE)
        assert [(l.batch_id, l.row_number) for l in links] == [("b1", 1)]
        assert links[0].match_type == "exact"

    def test_case_insensitive_match_is_still_exact(self) -> None:
        links = find_matching_rows([_fact("part_number", "r02d215p1rw")], CATALOGUE)
        assert links[0].row_number == 2

    def test_separator_difference_is_reported_as_normalized(self) -> None:
        links = find_matching_rows([_fact("part_number", "7010401")], CATALOGUE)
        assert links[0].row_number == 1
        assert links[0].match_type == "normalized"

    def test_a_part_number_not_in_the_catalogue_matches_nothing(self) -> None:
        assert find_matching_rows([_fact("part_number", "NOT-A-REAL-PART")], CATALOGUE) == []

    def test_a_datasheet_with_no_part_number_matches_nothing(self) -> None:
        assert find_matching_rows([_fact("material", "Bronze")], CATALOGUE) == []

    def test_a_near_miss_does_not_match(self) -> None:
        # 70-104-02 is a different product from 70-104-01.
        assert find_matching_rows([_fact("part_number", "70-104-02")], CATALOGUE) == []

    def test_several_part_numbers_link_several_rows(self) -> None:
        links = find_matching_rows(
            [_fact("part_number", "70-104-01"), _fact("part_number", "DCG413B", page=2)], CATALOGUE)
        assert sorted(l.row_number for l in links) == [1, 3]

    def test_the_same_row_is_not_linked_twice(self) -> None:
        links = find_matching_rows(
            [_fact("part_number", "70-104-01"), _fact("part_number", "70-104-01", page=2)], CATALOGUE)
        assert len(links) == 1


class ProposalTests(unittest.TestCase):
    def test_specifications_become_proposals(self) -> None:
        facts = [_fact("part_number", "70-104-01"), _fact("material", "Bronze ASTM B584"),
                 _fact("pressure_rating", "600 WOG")]
        names = {p["name"] for p in proposals_from_facts(facts)}
        assert names == {"material", "pressure_rating"}

    def test_the_part_number_is_the_key_not_a_proposal(self) -> None:
        # It identifies the row; proposing it back onto the row it selected
        # would be circular.
        facts = [_fact("part_number", "70-104-01")]
        assert proposals_from_facts(facts) == []

    def test_a_proposal_carries_its_evidence(self) -> None:
        proposals = proposals_from_facts([_fact("material", "Bronze ASTM B584", page=3)])
        assert proposals[0]["page"] == 3
        assert "Bronze ASTM B584" in proposals[0]["evidence"]

    def test_a_proposal_is_never_pre_applied(self) -> None:
        proposals = proposals_from_facts([_fact("material", "Bronze")])
        assert proposals[0]["state"] == "proposed"


if __name__ == "__main__":
    unittest.main()
