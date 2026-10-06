"""
Site lists for evidence research — EDIT THIS FILE to change which sites Grey
trusts, searches, or treats as discovery-only. No logic lives here.

Each entry is a domain. A domain also covers its subdomains:
"springer.com" matches "link.springer.com".

How the lists are used:
  - classification.py decides a source's type and tier (blueprint §11) from them.
  - The research plan (Release 0.4, Step 4) uses some of them to aim searches,
    e.g. "discover startups" only on STARTUP_DIRECTORIES.

Tier reminder:
  A — primary: official company/startup sites, government, peer-reviewed research, official datasets
  B — strong secondary: reputable news, preprints, university news, community datasets, open source
  C — discovery only: directories, accelerator profiles, blogs, forums, social media
"""

# ── Discovery (Tier C) ────────────────────────────────────────────────────────

# Startup / company directories and accelerator lists. Great for FINDING startups;
# the startup's own website (found in the second search hop) is the Tier A evidence.

# Directories with one page per startup, titled with its name
# ("Finic: The AI fraud hunter | Y Combinator"). "Discovering startups" searches these.
STARTUP_PROFILE_SITES = [
    "ycombinator.com",
    "producthunt.com",
    "f6s.com",
    "crunchbase.com",
    "dealroom.co",
    "wellfound.com",
    "tracxn.com",
]

# Sites that mostly publish lists and market maps ("90 startups making noise…").
# No startup name can be read from such a title, so they are not searched for
# discovery (live run, 2026-10-06) — but they still count as Tier C if found.
STARTUP_LIST_SITES = [
    "cbinsights.com",
    "startupblink.com",
    "eu-startups.com",
]

STARTUP_DIRECTORIES = STARTUP_PROFILE_SITES + STARTUP_LIST_SITES

# Blogs, forums and social media: leads only.
DISCUSSION_SITES = [
    "medium.com",
    "substack.com",
    "reddit.com",
    "quora.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "youtube.com",
]

# ── News (Tier B when listed here; other news sites are Tier C) ───────────────

NEWS_OUTLETS = [
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "ft.com",
    "bloomberg.com",
    "wsj.com",
    "nytimes.com",
    "theguardian.com",
    "economist.com",
    "cnbc.com",
    "aljazeera.com",
    "techcrunch.com",
    "wired.com",
    "theverge.com",
    "venturebeat.com",
    "technologyreview.com",
    "arstechnica.com",
    "zdnet.com",
    "sifted.eu",
    "restofworld.org",
    "defensenews.com",
    "dawn.com",
]

# ── Research ──────────────────────────────────────────────────────────────────

# Peer-reviewed publishers and indexes (Tier A).
PEER_REVIEWED_PUBLISHERS = [
    "doi.org",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "sciencedirect.com",
    "springer.com",
    "nature.com",
    "mdpi.com",
    "wiley.com",
    "tandfonline.com",
    "sagepub.com",
    "plos.org",
    "frontiersin.org",
    "ncbi.nlm.nih.gov",
    "jmlr.org",
    "aclanthology.org",
    "proceedings.neurips.cc",
    "proceedings.mlr.press",
]

# Preprints and paper hosts that aren't peer-reviewed (Tier B).
PREPRINT_SERVERS = [
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "researchgate.net",
    "openreview.net",
    "semanticscholar.org",
]

# ── Government and official bodies (Tier A) ───────────────────────────────────

# Endings that mark a government website anywhere in the world.
# ".gov.<country>" (e.g. gov.uk, gov.pk) is recognised automatically too.
GOVERNMENT_SUFFIXES = [
    ".gov",
    ".mil",
    ".gc.ca",
    ".gouv.fr",
    ".govt.nz",
    ".go.jp",
    ".go.kr",
    ".gob.mx",
    ".gob.es",
    ".bund.de",
]

# International public bodies, treated like government sources.
INTERNATIONAL_BODIES = [
    "europa.eu",
    "un.org",
    "who.int",
    "worldbank.org",
    "oecd.org",
    "nato.int",
    "imo.org",
    "itu.int",
    "imf.org",
    "wto.org",
]

# Where the government step searches (Release 0.4.1). Without a limit, Google
# returned an insurance marketplace and law-firm blogs for "government AI".
# "gov" covers every *.gov site; ".gov.<country>" sites must be listed here.
GOVERNMENT_SEARCH_SITES = [
    "gov",
    "mil",
    "gov.uk",
    "gov.au",
    "gov.in",
    "gov.pk",
    "gov.sg",
    "gc.ca",
    "europa.eu",
    "who.int",
    "worldbank.org",
    "oecd.org",
    "un.org",
]

# ── Datasets ──────────────────────────────────────────────────────────────────

# Official, curated data portals (Tier A).
OFFICIAL_DATA_PORTALS = [
    "data.gov",
    "data.gov.uk",
    "data.europa.eu",
    "data.worldbank.org",
    "data.un.org",
    "zenodo.org",
    "archive.ics.uci.edu",
]

# Community dataset platforms (Tier B).
COMMUNITY_DATASET_SITES = [
    "kaggle.com",
    "huggingface.co",
    "paperswithcode.com",
]

# Open-source code hosts (Tier B).
OPEN_SOURCE_SITES = [
    "github.com",
    "gitlab.com",
]


def host_in(host: str, domains: list[str]) -> bool:
    """True if `host` is one of `domains` or a subdomain of one ("link.springer.com" is in ["springer.com"])."""
    host = host.lower().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in domains)
