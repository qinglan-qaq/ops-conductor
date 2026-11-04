"""Parameterized execution of the 28 MVP Golden Tasks (spec section 9.1)."""

from collections import Counter

import pytest
from cases import CATEGORY_COUNTS, GOLDEN_CASES, KNOWN_GAP_REASONS
from harness import assert_case, assert_case_table, run_case

CASE_PARAMS = [
    pytest.param(
        case,
        id=case.id,
        marks=pytest.mark.slow if case.slow else (),
    )
    for case in GOLDEN_CASES
]


def test_case_table_matches_spec():
    assert len(GOLDEN_CASES) == 28
    assert_case_table()
    counts = Counter(case.category for case in GOLDEN_CASES)
    assert dict(counts) == CATEGORY_COUNTS
    assert [case.id for case in GOLDEN_CASES] == [
        f"GT-{index:02d}" for index in range(1, 29)
    ]


def test_known_gaps_are_explicit_and_limited():
    assert set(KNOWN_GAP_REASONS) == {
        "GT-08",
        "GT-09",
        "GT-12",
        "GT-17",
        "GT-26",
    }
    assert all(KNOWN_GAP_REASONS.values())


@pytest.mark.parametrize("case", CASE_PARAMS)
@pytest.mark.asyncio
async def test_golden_task(case, seeded_db, monkeypatch):
    run = await run_case(case, monkeypatch)
    await assert_case(case, run)
