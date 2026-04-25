# 🔬 Research MCP Server

The most complete open-source MCP server for scientific literature research.
Connects AI assistants (Claude, etc.) to 10+ data sources with 43 tools covering
the full research workflow — from search to synthesis, meta-analysis, and export.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![Tools: 43](https://img.shields.io/badge/tools-43-green.svg)]()

---

## Features

- **10 data sources:** PubMed, Semantic Scholar, OpenAlex, Europe PMC, Cochrane, arXiv, CORE, ClinicalTrials.gov, bioRxiv/medRxiv, FDA, NIH RePORTER, WHO, OMIM
- **Legal full-text access** with 7-source fallback chain (Unpaywall → PMC → CORE → OpenAIRE → S2 → arXiv)
- **Evidence appraisal:** RoB 2 / ROBINS-I, GRADE, meta-analysis data extraction
- **Statistical calculator:** OR, RR, ARR, NNT/NNH, CI 95%
- **Citation network analysis** — who cited this, what it cites, influential papers
- **Research gap analysis** — identify unexplored areas in a field
- **Literature monitoring** — persistent topic alerts with SQLite
- **Export:** RIS (Zotero/Mendeley/EndNote), CSV (Rayyan/Covidence), Bibliography (Vancouver/APA)
- **No required API keys** — all core sources are free and open
- **In-memory cache** (1hr TTL) — repeated queries return instantly
- **One-click deploy** to Render.com free tier

---

## Tools (43)

### 🔍 Search
| Tool | Source | Description |
|---|---|---|
| `search_pubmed` | PubMed/NCBI | MeSH filters, article type, free full-text |
| `search_semantic_scholar` | Semantic Scholar | Semantic search, 200M+ papers |
| `search_openalex` | OpenAlex | 250M+ works, advanced filters |
| `search_europe_pmc` | Europe PMC | Full-text, systematic reviews |
| `search_preprints` | bioRxiv+medRxiv | Recent preprints |
| `search_arxiv` | arXiv | AI/ML in medicine, bioinformatics |
| `search_core` | CORE.ac.uk | 200M+ OA institutional repository articles |
| `search_clinical_trials` | ClinicalTrials.gov | Ongoing and completed trials |
| `search_cochrane` | Cochrane Library | Highest-quality systematic reviews |
| `search_high_impact_papers` | Semantic Scholar | Filter by citation count + impact badges |
| `search_nih_reporter` | NIH RePORTER | Active research grants by topic |
| `search_fda_approvals` | openFDA | Drug approvals, labels, adverse events, recalls |
| `search_omim` | OMIM | Genetic diseases, genes, phenotypes |
| `search_who_guidelines` | WHO IRIS | International guidelines and reports |
| `research_all_sources` | All | Simultaneous search across 4 main sources |

### 📄 Article Details & Access
| Tool | Description |
|---|---|
| `get_paper_details` | Full details by PMID or DOI (abstract, MeSH, PMC link) |
| `find_related_articles` | Similar articles from a seed PMID |
| `get_references` | Full reference list via CrossRef |
| `check_retraction` | Retraction/correction check |
| `find_free_fulltext` | Best free legal link for any DOI (Unpaywall) |
| `find_free_fulltext_batch` | Batch free-access check (up to 10 DOIs) |
| `download_paper` | 7-source fallback PDF retrieval (Unpaywall→PMC→CORE→OpenAIRE→S2→arXiv) |

### 📊 Metrics & Impact
| Tool | Description |
|---|---|
| `get_journal_impact` | IF (2yr), h-index, quartile estimate, OA status |
| `get_author_profile` | h-index, citations, affiliations, research topics |
| `rank_evidence` | Composite evidence ranking (design + citations + IF) |
| `get_citation_network` | Citation graph — who cited this + what it cites |
| `find_expert_reviewers` | Suggest peer reviewers by expertise and h-index |

### 🧪 Evidence Appraisal & Statistics
| Tool | Description |
|---|---|
| `assess_risk_of_bias` | RoB 2 (RCTs) or ROBINS-I (observational) via Claude |
| `grade_evidence_body` | Full GRADE assessment for a body of evidence |
| `extract_meta_analysis_data` | Extract 2×2 table data / continuous data for meta-analysis |
| `calculate_statistics` | OR, RR, ARR, NNT/NNH, CI 95% from a 2×2 table |

### 🤖 AI-Powered Synthesis
| Tool | Description |
|---|---|
| `extract_pico` | Extract Population, Intervention, Comparison, Outcome |
| `summarize_papers` | Evidence synthesis across multiple abstracts |
| `compare_papers` | Structured comparative table across papers |
| `translate_query` | Clinical question → optimized PubMed query |
| `get_mesh_terms` | MeSH terms and search strategy |
| `find_research_gaps` | Identify unexplored areas and controversies |
| `translate_abstract` | Medical-grade translation preserving terminology |

### 📦 Export & Productivity
| Tool | Description |
|---|---|
| `generate_bibliography` | Vancouver, APA, or ABNT formatting |
| `export_to_ris` | RIS for Zotero, Mendeley, EndNote |
| `export_to_csv` | CSV with citations for Rayyan, Covidence, Excel |
| `detect_duplicates` | Find exact and near-duplicate papers in a list |
| `monitor_topic` | Persistent literature alerts (SQLite-backed) |

---

## Deploy (Render.com free tier)

### 1. Fork or clone
```bash
git clone https://github.com/YOUR_USERNAME/research-mcp
cd research-mcp
```

### 2. Deploy to Render
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

Or manually: **New → Web Service** → connect repo → Deploy (~2 min)

### 3. Connect to Claude.ai
**Settings → Integrations → Add Integration**
URL: `https://your-service.onrender.com/mcp`

---

## Optional environment variables

| Variable | Effect |
|---|---|
| `PUBMED_API_KEY` | PubMed rate limit 3→10 req/s ([get free key](https://www.ncbi.nlm.nih.gov/account/)) |
| `PUBMED_EMAIL` | Required by NCBI best practices |

---

## Run locally

```bash
pip install -r requirements.txt
python server.py
# Server at http://localhost:8000/mcp
```

---

## Example workflows

**Full systematic review:**
```
translate_query → research_all_sources → rank_evidence
→ search_cochrane → assess_risk_of_bias → grade_evidence_body
→ extract_meta_analysis_data → calculate_statistics
→ compare_papers → export_to_ris → export_to_csv
```

**Rapid clinical appraisal:**
```
search_high_impact_papers(min_citations=100) → rank_evidence
→ extract_pico → check_retraction → download_paper
```

**Research strategy:**
```
find_research_gaps → search_clinical_trials(status=RECRUITING)
→ search_nih_reporter → search_arxiv
```

**Drug/regulatory intelligence:**
```
search_fda_approvals(search_type='label') → search_fda_approvals(search_type='adverse_events')
→ search_clinical_trials → search_pubmed
```

**Genetic dermatology:**
```
search_omim("epidermolysis bullosa") → get_citation_network
→ find_expert_reviewers → search_pubmed
```

---

## Data sources

PubMed · Semantic Scholar · OpenAlex · Europe PMC · Cochrane · arXiv · CORE ·
ClinicalTrials.gov · bioRxiv · medRxiv · Unpaywall · CrossRef · openFDA ·
NIH RePORTER · WHO IRIS · OMIM

---

## Notes
- Render free tier hibernates after 15 min. Use [UptimeRobot](https://uptimerobot.com) to ping `/mcp` every 10 min.
- AI tools (RoB, GRADE, PICO, etc.) call the Claude API automatically when used via Claude.ai — no setup needed.
- Results cached in memory for 1 hour.

---

## License
MIT
