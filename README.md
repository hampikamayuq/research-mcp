# 🔬 Research MCP Server

A free, open-source MCP (Model Context Protocol) server that connects AI assistants like Claude to scientific literature databases — with no paywalls, no API keys required.

## Features

- **6 data sources** in parallel: PubMed, Semantic Scholar, OpenAlex, Europe PMC, ClinicalTrials.gov, bioRxiv/medRxiv
- **Legal full-text access** via Unpaywall
- **AI-powered synthesis** via Claude (PICO, summarization, query translation, paper comparison)
- **Evidence ranking** with composite scoring (study design + citations + journal impact)
- **Export** to RIS (Zotero/Mendeley/EndNote) and CSV (Rayyan/Excel)
- **In-memory cache** with 1hr TTL — repeated queries return instantly
- **25 tools** covering the full research workflow
- **No required API keys** — all sources are free and open
- **One-click deploy** to Render.com free tier

---

## Tools (25)

### 🔍 Search
| Tool | Description |
|---|---|
| `search_pubmed` | PubMed with MeSH filters, article type, free full-text |
| `search_semantic_scholar` | Semantic search across 200M+ papers |
| `search_openalex` | Advanced filters across 250M+ works |
| `search_europe_pmc` | Full-text and systematic review search |
| `search_preprints` | bioRxiv + medRxiv preprints |
| `search_clinical_trials` | ClinicalTrials.gov — recruiting and completed trials |
| `search_high_impact_papers` | Filter by citation count with impact badges |
| `research_all_sources` | Simultaneous search across all 4 main sources |

### 📄 Article Details
| Tool | Description |
|---|---|
| `get_paper_details` | Full details by PMID or DOI — abstract, MeSH, PMC link |
| `find_related_articles` | Similar articles from a seed PMID |
| `get_references` | Full reference list via CrossRef |
| `check_retraction` | Retraction/correction check via CrossRef |

### 🔓 Full-Text Access
| Tool | Description |
|---|---|
| `find_free_fulltext` | Best free, legal link for any DOI via Unpaywall |
| `find_free_fulltext_batch` | Batch free-access check for up to 10 DOIs |

### 📊 Metrics
| Tool | Description |
|---|---|
| `get_journal_impact` | Impact Factor (2yr), h-index, quartile, OA status |
| `get_author_profile` | h-index, citations, affiliations, top topics |
| `rank_evidence` | Rank articles by evidence strength (design + citations + IF) |

### 🤖 AI-Powered Analysis
| Tool | Description |
|---|---|
| `extract_pico` | Extract Population, Intervention, Comparison, Outcome |
| `summarize_papers` | Synthesize multiple abstracts into evidence summary |
| `compare_papers` | Structured comparison table across multiple papers |
| `translate_query` | Convert clinical question to optimized PubMed query |
| `get_mesh_terms` | Suggest MeSH terms and search strategy |

### 📦 Export
| Tool | Description |
|---|---|
| `generate_bibliography` | Format references in Vancouver, APA, or ABNT |
| `export_to_ris` | RIS format for Zotero, Mendeley, EndNote |
| `export_to_csv` | CSV for Rayyan, Excel, systematic review tools |

---

## Deploy (Render.com free tier)

### 1. Fork or clone this repository
```bash
git clone https://github.com/YOUR_USERNAME/research-mcp
cd research-mcp
```

### 2. Deploy to Render
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

Or manually:
1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repository
3. Render auto-detects `render.yaml`
4. Click **Deploy** (~2 min)
5. Copy your public URL (e.g. `https://research-mcp.onrender.com`)

### 3. Connect to Claude.ai
1. Go to [claude.ai](https://claude.ai) → **Settings → Integrations → Add Integration**
2. Enter your URL: `https://research-mcp.onrender.com/mcp`
3. Save — all 25 tools are now available

---

## Optional environment variables

| Variable | Where to get | Effect |
|---|---|---|
| `PUBMED_API_KEY` | [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/) | PubMed rate limit 3→10 req/s |
| `PUBMED_EMAIL` | Your email | Best practice required by NCBI |

---

## Run locally

```bash
pip install -r requirements.txt
python server.py
# Server at http://localhost:8000/mcp
```

Expose with [ngrok](https://ngrok.com):
```bash
ngrok http 8000
```

---

## Example workflows

**Full literature review:**
```
translate_query("Does dupilumab improve QoL in atopic dermatitis?")
→ research_all_sources("dupilumab atopic dermatitis", year_from=2018)
→ rank_evidence([pmid1, pmid2, pmid3])
→ compare_papers([pmid1, pmid2, pmid3], comparison_focus="efficacy and safety")
→ find_free_fulltext_batch([doi1, doi2])
→ check_retraction(doi)
→ summarize_papers([abstract1, abstract2])
→ generate_bibliography([doi1, doi2], style="vancouver")
→ export_to_ris([doi1, doi2])
```

**Quick clinical question:**
```
search_high_impact_papers("vismodegib basal cell carcinoma", min_citations=100)
→ get_journal_impact("JAMA Dermatology")
→ extract_pico(abstract)
```

**Stay current:**
```
search_preprints("melanoma immunotherapy", days_back=90)
→ search_clinical_trials("melanoma pembrolizumab", status="RECRUITING", phase="PHASE3")
```

**Systematic review export:**
```
export_to_csv("atopic dermatitis biologic therapy", max_results=50, year_from=2018)
→ export_to_ris([doi1, doi2, ...])
```

---

## Data sources

- [PubMed](https://pubmed.ncbi.nlm.nih.gov/) — NLM/NIH medical database
- [Semantic Scholar](https://www.semanticscholar.org/) — AI-powered, 200M+ papers
- [OpenAlex](https://openalex.org/) — 250M+ scholarly works
- [Europe PMC](https://europepmc.org/) — Full-text biomedical literature
- [ClinicalTrials.gov](https://clinicaltrials.gov/) — Clinical trials registry
- [bioRxiv](https://biorxiv.org/) / [medRxiv](https://medrxiv.org/) — Preprints
- [Unpaywall](https://unpaywall.org/) — Legal open-access versions
- [CrossRef](https://crossref.org/) — Metadata, references, retraction data

---

## Notes

- Render free tier hibernates after 15 min. Use [UptimeRobot](https://uptimerobot.com) (free) to ping `/mcp` every 10 min.
- AI tools (`extract_pico`, `summarize_papers`, `compare_papers`, `translate_query`) use the Claude API — work automatically via Claude.ai with no setup.
- Results are cached in memory for 1 hour — repeated identical queries return instantly.

---

## License

MIT
