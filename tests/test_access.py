"""The knowledge-base access policy (app/access.py).

These are the rules the retrieval filter enforces, so they are tested
directly rather than through the LLM.
"""

import pytest

from app.access import (
    DEFAULT_ACCESS,
    DOCUMENT_ACCESS,
    PUBLIC,
    ROLE_ACCESS,
    STAFF,
    access_for_source,
    tiers_for_role,
)

# Every role the application defines. Kept explicit so a new role added to
# app.schema.Role without a decision here fails the coverage test below.
ALL_ROLES = ["admin", "hr", "employee", "doctor", "patient"]


def test_hospital_information_is_public():
    assert access_for_source("knowledge_base/hospital_info.pdf") == PUBLIC
    assert access_for_source("knowledge_base\\hospital_info.pdf") == PUBLIC


def test_hospital_policy_is_public():
    assert access_for_source("knowledge_base/hospital_policy.pdf") == PUBLIC


def test_hr_policy_is_staff_only():
    assert access_for_source("knowledge_base/hr_policy.txt") == STAFF


def test_unlisted_document_falls_back_to_public():
    assert access_for_source("knowledge_base/brand_new_leaflet.pdf") == DEFAULT_ACCESS


def test_patient_reads_public_documents_only():
    assert tiers_for_role("patient") == {PUBLIC}


@pytest.mark.parametrize("role", ["doctor", "employee", "hr", "admin"])
def test_staff_roles_read_both_tiers(role):
    assert tiers_for_role(role) == {PUBLIC, STAFF}


def test_anonymous_is_restricted_to_public():
    """No token must never mean 'no restrictions'."""
    assert tiers_for_role(None) == {PUBLIC}


def test_unknown_role_fails_closed_to_public():
    assert tiers_for_role("superuser") == {PUBLIC}


def test_hr_policy_is_never_reachable_without_a_staff_role():
    """The tier holding hr_policy.txt is excluded for every non-staff role."""
    for role in ALL_ROLES + [None, "unknown"]:
        if role in ("doctor", "employee", "hr", "admin"):
            continue

        assert STAFF not in tiers_for_role(role), role


def test_every_application_role_has_an_explicit_policy():
    assert set(ROLE_ACCESS) == set(ALL_ROLES)


def test_staff_tier_actually_governs_a_document():
    """Documents and roles must agree — a staff role that gates nothing, or
    a staff document no role can read, is a configuration mistake."""
    assert STAFF in DOCUMENT_ACCESS.values()

    readable = {tier for role in ALL_ROLES for tier in tiers_for_role(role)}
    assert set(DOCUMENT_ACCESS.values()) <= readable
