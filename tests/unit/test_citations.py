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
    drawing = {"page": 1, "drawing_no": "DWG-A-0001", "revision": "B"}
    assert format_locator(drawing) == "DWG-A-0001 rev B, p. 1"
    assert format_locator({**drawing, "source": "vision_model"}) == (
        "DWG-A-0001 rev B, p. 1, vision model description"
    )
    assert format_locator({}) == ""


def test_fullwidth_citations_are_normalised() -> None:
    from fcrag.generation.citations import normalise_citations

    answer = "It is 85 °C【S1】【S2】 and［S3］, see [ S4 ]."
    assert normalise_citations(answer) == "It is 85 °C[S1][S2] and[S3], see [S4]."
    assert check_citations(answer, n_sources=3).cited == [1, 2, 3]
    assert check_citations(answer, n_sources=3).invalid == [4]


def test_line_span_citations_and_typography() -> None:
    from fcrag.generation.citations import normalise_citations

    answer = "REQ\u2011A\u20110013 refines it\u00a0【S2†L1-L3】【S4†L1】."
    assert normalise_citations(answer) == "REQ-A-0013 refines it [S2][S4]."


def test_bare_labels_in_a_reference_parenthesis_are_citations() -> None:
    from fcrag.generation.citations import normalise_citations

    answer = "Er beträgt 40 kPa (vgl. S2, S6, REQ-B-0026 in S4) bzw. 0,4 bar (vgl. S8)."
    assert normalise_citations(answer) == (
        "Er beträgt 40 kPa (vgl. [S2], [S6], REQ-B-0026 in [S4]) bzw. 0,4 bar (vgl. [S8])."
    )
    assert check_citations(answer, n_sources=8).cited == [2, 6, 4, 8]
    # outside such a parenthesis a bare S2 is text (a part or sensor name), not a citation
    assert normalise_citations("Sensor S2 reads 80 °C (S2 is the outlet).") == (
        "Sensor S2 reads 80 °C (S2 is the outlet)."
    )
    assert normalise_citations("It is 80 °C (see [S1], S3).") == "It is 80 °C (see [S1], [S3])."
