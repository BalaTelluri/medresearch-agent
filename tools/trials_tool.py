"""ClinicalTrials.gov API v2 client.

Free, no key, no registration. API docs:
https://clinicaltrials.gov/data-api/api

Run directly to smoke-test:
    python -m tools.trials_tool "metformin lactic acidosis"
"""


from __future__ import annotations
import config  # noqa: F401  (loads .env)

import sys
from dataclasses import asdict, dataclass, field

try:
    import requests
except ImportError:
    raise SystemExit("Missing library. Run:  pip install requests")

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT_SECONDS = 20
DEFAULT_MAX_RESULTS = 5

FIELDS = ",".join(
    [
        "NCTId",
        "BriefTitle",
        "OverallStatus",
        "Phase",
        "Condition",
        "LeadSponsorName",
        "StartDate",
        "BriefSummary",
    ]
)


@dataclass
class Trial:
    """One clinical trial record, flattened to what the agent needs."""

    nct_id: str
    title: str
    status: str
    phase: str = ""
    conditions: list[str] = field(default_factory=list)
    sponsor: str = ""
    start_date: str = ""
    summary: str = ""
    link: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_study(study: dict) -> Trial:
    protocol = study["protocolSection"]
    ident = protocol["identificationModule"]
    status_mod = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    conditions = protocol.get("conditionsModule", {})
    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
    description = protocol.get("descriptionModule", {})

    nct_id = ident["nctId"]
    return Trial(
        nct_id=nct_id,
        title=ident.get("briefTitle", ""),
        status=status_mod.get("overallStatus", ""),
        phase=", ".join(design.get("phases", [])),
        conditions=conditions.get("conditions", []),
        sponsor=sponsor_mod.get("leadSponsor", {}).get("name", ""),
        start_date=status_mod.get("startDateStruct", {}).get("date", ""),
        summary=description.get("briefSummary", ""),
        link=f"https://clinicaltrials.gov/study/{nct_id}",
    )


def search_trials(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    recruiting_only: bool = False,
) -> list[Trial]:
    """Return clinical trials matching a free-text query."""
    params: dict = {
        "query.term": query,
        "pageSize": max_results,
        "fields": FIELDS,
    }
    if recruiting_only:
        params["filter.overallStatus"] = "RECRUITING"

    response = requests.get(BASE_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    return [_parse_study(study) for study in response.json().get("studies", [])]


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "metformin lactic acidosis"
    print(f"ClinicalTrials.gov query: {query}\n")
    for trial in search_trials(query):
        print(f"[{trial.nct_id}] {trial.title}")
        print(f"    {trial.status} | {trial.phase or 'no phase'} | {trial.sponsor}")
        print(f"    {trial.link}\n")
