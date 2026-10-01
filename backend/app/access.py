"""Knowledge-base access policy: which roles may read which documents.

Single source of truth for the RAG access tiers.

The policy is enforced in the backend as a Qdrant payload filter at
retrieval time (app/retriever.py), so a restricted chunk is never
retrieved, never enters the LLM prompt, and can never be cited as a
source. The prompt is not trusted to enforce any of this.
"""

from pathlib import Path

PUBLIC = "public"
STAFF = "staff"

# Access tier per knowledge-base document, keyed by file name.
DOCUMENT_ACCESS = {
    # Visiting hours, visitor limits, emergency services, location.
    "hospital_info.pdf": PUBLIC,
    # Appointment, identification, privacy, ICU visitors, safety, children.
    "hospital_policy.pdf": PUBLIC,
    # Employee handbook: leave, WFH, probation, notice, reimbursement,
    # code of conduct, exit.
    "hr_policy.txt": STAFF,
}

# Documents that are not listed above are treated as public. Adding a
# file to knowledge_base/ therefore cannot silently restrict or leak it;
# change DOCUMENT_ACCESS explicitly for anything sensitive.
DEFAULT_ACCESS = PUBLIC

# Tiers each role may read. Patients see public documents only.
ROLE_ACCESS = {
    "patient": {PUBLIC},
    "doctor": {PUBLIC, STAFF},
    "employee": {PUBLIC, STAFF},
    "hr": {PUBLIC, STAFF},
    "admin": {PUBLIC, STAFF},
}


def access_for_source(source: str) -> str:
    """Tier for a document path, e.g. 'knowledge_base\\hr_policy.txt'.

    Keyed on the file name because metadata stores the path with the
    platform separator.
    """
    return DOCUMENT_ACCESS.get(Path(source).name, DEFAULT_ACCESS)


def tiers_for_role(role: str | None) -> set[str]:
    """Tiers readable by a role.

    `None` means an anonymous caller (no token), which is the most
    restricted case: public documents only. An unrecognised role is
    likewise restricted to public rather than being granted everything.
    """
    if role is None:
        return {PUBLIC}

    return ROLE_ACCESS.get(role, {PUBLIC})
