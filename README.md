# 🔬 Research MCP Server

A free, open-source MCP (Model Context Protocol) server that connects AI assistants like Claude to scientific literature databases — with no paywalls, no API keys required.

## Features

- **4 data sources** searched in parallel: PubMed, Semantic Scholar, OpenAlex, Europe PMC
- **Legal full-text access** via Unpaywall — finds free, legitimate versions of papers
- **9 tools** covering search, article details, related papers, and open-access lookup
- **No required API keys** — all sources are free and open
- **One-click deploy** to Render.com free tier

---

## Tools

| Tool | Description |
|---|---|
| `search_pubmed` | PubMed search with MeSH filters, article type, and free full-text filtering |
| `get_paper_details` | Full details for any article by PMID or DOI — abstract, MeSH terms, PMC link |
| `find_related_articles` | Similar articles from a seed PMID using PubMed's similarity algorithm |
| `search_semantic_scholar` | Semantic search across 200M+ papers |
| `search_openalex` | Advanced filters across 250M+ works — study type, open access, year |
| `search_europe_pmc` | Full-text and systematic review search |
| `research_all_sources` | Simultaneous search across all 4 sources |
| `find_free_fulltext` | Best free, legal link for any DOI via Unpaywall |
| `find_free_fulltext_batch` | Batch free-access check for up to 10 DOIs |

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
4. Click **Deploy** — done in ~2 minutes
5. Copy your public URL (e.g. `https://research-mcp.onrender.com`)

### 3. Connect to Claude.ai

1. Go to [claude.ai](https://claude.ai) → **Settings → Integrations → Add Integration**
2. Enter your URL: `https://research-mcp.onrender.com/mcp`
3. Save — all 9 tools are now available in your Claude chats

---

## Optional environment variables

All are optional. The server works without any configuration.

| Variable | Where to get | Effect |
|---|---|---|
| `PUBMED_API_KEY` | [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/) | Increases PubMed rate limit from 3 to 10 req/s |
| `PUBMED_EMAIL` | Your email address | Best practice required by NCBI |

---

## Run locally

```bash
pip install -r requirements.txt
python server.py
# Server running at http://localhost:8000
```

To connect a local instance to Claude.ai, expose it with [ngrok](https://ngrok.com):
```bash
ngrok http 8000
# Use the generated https URL + /mcp in Claude.ai integrations
```

---

## Example usage in Claude

```
Search all sources for evidence on dupilumab in atopic dermatitis, 
reviews only, from 2020 onwards
```

```
Get full details for PMID 35123456
```

```
Find free full text for these DOIs: 10.1016/j.jaad.2023.01.001, 10.1001/jama.2022.1234
```

---

## Data sources

- [PubMed](https://pubmed.ncbi.nlm.nih.gov/) — NLM/NIH official medical database
- [Semantic Scholar](https://www.semanticscholar.org/) — AI-powered search, 200M+ papers
- [OpenAlex](https://openalex.org/) — Open catalog of 250M+ scholarly works
- [Europe PMC](https://europepmc.org/) — Full-text biomedical literature
- [Unpaywall](https://unpaywall.org/) — Legal open-access versions of paywalled articles

---

## Notes

- Render free tier hibernates after 15 min of inactivity. First request after sleep takes ~30s.
- To keep the server awake, use [UptimeRobot](https://uptimerobot.com) (free) to ping `/mcp` every 10 minutes.
- All data sources are free and open. No subscriptions required.

---

## License

MIT
