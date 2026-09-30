"""PubMed literature search tool.

Searches PubMed through NCBI Entrez and returns the top papers for a query.
NCBI policy requires an email address with every request - set NCBI_EMAIL
in the environment (see .env.example). No API key needed.

Run directly to smoke-test:
    python -m tools.pubmed_tool "metformin lactic acidosis"
"""


from __future__ import annotations
import config  # noqa: F401  (loads .env)

import os
import re
import sys
from dataclasses import asdict, dataclass, field

try:
    from Bio import Entrez
except ImportError:
    raise SystemExit("Missing library. Run:  pip install biopython")

DEFAULT_MAX_RESULTS = 5

# Filler words the planner loves but PubMed text-matches literally (and then
# finds nothing): stripped from the free-text part of a query.
_STOPWORDS = {
    "recent", "recently", "latest", "newest", "new", "novel", "current",
    "currently", "past", "last", "years", "year", "literature", "studies",
    "study", "evidence", "papers", "paper", "research", "findings", "and",
    "or", "the", "of", "in", "on", "for", "from", "between", "to", "about",
    "events", "event",
}
_YEAR_RANGE = re.compile(r"(19|20)\d{2}\s*\.\.\s*((?:19|20)\d{2})")
_BARE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b(?!\s*\[)")


def _normalize_query(query: str) -> tuple[str, str]:
    """Turn planner date-speak into valid Entrez syntax.

    Returns (free_text, date_clause): "metformin adverse events recent
    2022..2024" -> ("metformin adverse", "(2022:2024[dp])"). Bare year lists
    ("2023 2024 2025") become "(2023[dp] OR 2024[dp] OR 2025[dp])".
    """
    text = query
    date_clause = ""

    match = _YEAR_RANGE.search(text)
    if match:
        date_clause = f"({match.group(0).split('..')[0].strip()}:{match.group(2)}[dp])"
        text = _YEAR_RANGE.sub(" ", text)
    else:
        years = _BARE_YEAR.findall(text)
        if years:
            date_clause = "(" + " OR ".join(f"{y}[dp]" for y in years[:4]) + ")"
            text = _BARE_YEAR.sub(" ", text)

    words = [w for w in text.split() if w.lower().strip(",.;:") not in _STOPWORDS]
    return " ".join(words), date_clause


@dataclass
class Paper:
    """One PubMed record, flattened to what the agent needs."""

    pmid: str
    title: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    pub_date: str = ""
    link: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _require_email() -> str:
    email = os.environ.get("NCBI_EMAIL", "").strip()
    if not email:
        raise ValueError(
            "NCBI_EMAIL is not set. NCBI requires an email address with every "
            "Entrez request - add it to your .env (see .env.example)."
        )
    return email


def _parse_article(article: dict) -> Paper:
    """Flatten one PubmedArticle record from the Entrez XML parser."""
    citation = article["MedlineCitation"]
    pmid = str(citation["PMID"])
    art = citation["Article"]

    title = str(art.get("ArticleTitle", "")).strip()

    abstract_parts = art.get("Abstract", {}).get("AbstractText", [])
    abstract = " ".join(str(part) for part in abstract_parts).strip()

    authors = []
    for author in art.get("AuthorList", []):
        last = author.get("LastName")
        fore = author.get("ForeName")
        if last:
            authors.append(f"{last} {fore}" if fore else str(last))

    pub_date = ""
    pub_date_data = art.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
    if pub_date_data:
        pub_date = " ".join(
            str(pub_date_data[key]) for key in ("Year", "Month", "Day") if key in pub_date_data
        )

    return Paper(
        pmid=pmid,
        title=title,
        abstract=abstract,
        authors=authors,
        pub_date=pub_date,
        link=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )


def search_pubmed(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[Paper]:
    """Return the top PubMed papers for a free-text query, most relevant first.

    Planner-proof: date-speak (2022..2024, "recent 2023 2024") is rewritten
    into Entrez [dp] syntax and filler words are stripped BEFORE searching.
    If a dated query comes back empty, retries once without the date
    constraint instead of reporting nothing.
    """
    Entrez.email = _require_email()

    free_text, date_clause = _normalize_query(query)
    terms = [f"{free_text} AND {date_clause}"] if date_clause else []
    terms.append(free_text)  # relaxed fallback (or the only term when no dates)

    ids: list[str] = []
    for term in terms:
        if not term.strip():
            continue
        with Entrez.esearch(db="pubmed", term=term, retmax=max_results, sort="relevance") as handle:
            ids = Entrez.read(handle)["IdList"]
        if ids:
            break
    if not ids:
        return []

    with Entrez.efetch(db="pubmed", id=ids, rettype="abstract", retmode="xml") as handle:
        records = Entrez.read(handle)

    return [_parse_article(article) for article in records["PubmedArticle"]]


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "metformin lactic acidosis"
    print(f"PubMed query: {query}\n")
    for i, paper in enumerate(search_pubmed(query), start=1):
        print(f"[{i}] {paper.title}")
        print(f"    {paper.pub_date} | {', '.join(paper.authors[:3])}")
        print(f"    {paper.link}")
        print(f"    {paper.abstract[:300]}{'...' if len(paper.abstract) > 300 else ''}\n")
