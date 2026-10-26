from fcrag.generation.citations import check_citations, format_locator


def test_valid_invalid_and_uncited() -> None:
    answer = (
        "The maximum coolant outlet temperature is 85 °C [S2]. "
        "Version 1 stated 90 °C [S2][S5]. "
        "The stack has 440 cells. "
        "Membranes dry at high load [S1]."
    )
    report = check_citations(answer, n_sources=3)
    assert report.cited == [2, 1]
    assert report.invalid == [5]
    assert not report.ok
    assert report.uncited_sentences == ["The stack has 440 cells."]


def test_locators() -> None:
    assert format_locator({"page": 12, "bbox": [1, 2, 3, 4]}) == "p. 12"
    assert format_locator({"page": 4, "pages": [4, 5]}) == "pp. 4-5"
    assert format_locator({"sheet": "Limits", "cells": "B4:F9"}) == "sheet Limits!B4:F9"
    assert format_locator({"page": 3, "row": 2}) == "p. 3, table row 2"
    assert format_locator({"req_id": "REQ-0142"}) == "REQ-0142"
    assert format_locator({"part_id": "BPP-02"}) == "part BPP-02"
    assert format_locator({}) == ""


def test_fullwidth_citations_are_normalised() -> None:
    from fcrag.generation.citations import normalise_citations

    answer = "It is 85 °C【S1】【S2】 and［S3］, see [ S4 ]."
    assert normalise_citations(answer) == "It is 85 °C[S1][S2] and[S3], see [S4]."
    assert check_citations(answer, n_sources=3).cited == [1, 2, 3]
    assert check_citations(answer, n_sources=3).invalid == [4]
