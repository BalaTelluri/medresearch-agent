"""openFDA client: drug labels and FAERS adverse-event reports.

Both endpoints are free and work without a key. A free key from
https://open.fda.gov/apis/authentication/ raises the rate limit - set
OPENFDA_API_KEY in the environment if you have one.

Note: the FAERS database load into SQLite (weekend 2) replaces the live
event API with local text-to-SQL. This client stays as the label lookup
and as a way to explore the data before loading it.

Run directly to smoke-test:
    python -m tools.openfda_tool metformin
"""


from __future__ import annotations
import config  # noqa: F401  (loads .env)

import os
import sys
from typing import Any

try:
    import requests
except ImportError:
    raise SystemExit("Missing library. Run:  pip install requests")

BASE_URL = "https://api.fda.gov/drug"
TIMEOUT_SECONDS = 20


def _params(extra: dict[str, Any]) -> dict[str, Any]:
    """Attach the optional API key to every request."""
    key = os.environ.get("OPENFDA_API_KEY", "").strip()
    if key:
        extra["api_key"] = key
    return extra


def get_drug_label(drug_name: str) -> dict[str, Any]:
    """Return key safety sections of the drug label for a brand or generic name.

    Raises LookupError if openFDA has no label for the name.
    """
    search = f'openfda.brand_name:"{drug_name}"+openfda.generic_name:"{drug_name}"'
    response = requests.get(
        f"{BASE_URL}/label.json",
        params=_params({"search": search, "limit": 1}),
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        raise LookupError(f"No openFDA label found for {drug_name!r}.")
    response.raise_for_status()

    label = response.json()["results"][0]
    sections = {}
    for field in (
        "boxed_warning",
        "warnings_and_cautions",
        "adverse_reactions",
        "indications_and_usage",
        "contraindications",
    ):
        if field in label:
            # openFDA returns each section as a one-element list of text.
            sections[field] = label[field][0]
    return {
        "drug": drug_name,
        "brand_names": label.get("openfda", {}).get("brand_name", []),
        "generic_names": label.get("openfda", {}).get("generic_name", []),
        "sections": sections,
    }


def query_adverse_events(drug_name: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return the most-reported adverse reactions for a drug, with counts.

    Uses the FAERS count aggregation - one request, no pagination.
    """
    search = f'patient.drug.medicinalproduct:"{drug_name}"'
    response = requests.get(
        f"{BASE_URL}/event.json",
        params=_params(
            {
                "search": search,
                "count": "patient.reaction.reactionmeddrapt.exact",
                "limit": limit,
            }
        ),
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()

    return [
        {"reaction": bucket["term"], "report_count": bucket["count"]}
        for bucket in response.json()["results"]
    ]


if __name__ == "__main__":
    drug = sys.argv[1] if len(sys.argv) > 1 else "metformin"
    print(f"Top reported reactions for {drug}:\n")
    for row in query_adverse_events(drug):
        print(f"  {row['report_count']:>8,}  {row['reaction']}")
    print()
    label = get_drug_label(drug)
    print(f"Label sections found: {', '.join(label['sections']) or 'none'}")
