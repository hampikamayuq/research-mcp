"""
Research MCP Server
Fontes: Semantic Scholar, OpenAlex, Europe PMC
Deploy: Render.com (free tier)
"""

from mcp.server.fastmcp import FastMCP
import httpx
import asyncio
import json
from typing import Optional

mcp = FastMCP("research-mcp")

# ─────────────────────────────────────────
# 1. SEMANTIC SCHOLAR
# ─────────────────────────────────────────

@mcp.tool()
async def search_semantic_scholar(
    query: str,
    max_results: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    open_access_only: bool = False
) -> str:
    """
    Busca papers no Semantic Scholar (200M+ artigos).
    Retorna título, autores, ano, abstract, citações, DOI e link PDF se disponível.
    
    Args:
        query: Pergunta ou termos de pesquisa (inglês recomendado)
        max_results: Número de resultados (máx 100)
        year_from: Filtrar a partir deste ano
        year_to: Filtrar até este ano
        open_access_only: Retornar apenas artigos com PDF gratuito
    """
    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": "title,year,abstract,authors,citationCount,openAccessPdf,externalIds,journal"
    }
    
    if year_from and year_to:
        params["year"] = f"{year_from}-{year_to}"
    elif year_from:
        params["year"] = f"{year_from}-"
    elif year_to:
        params["year"] = f"-{year_to}"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params
        )
        r.raise_for_status()
        data = r.json()

    papers = data.get("data", [])
    
    if open_access_only:
        papers = [p for p in papers if p.get("openAccessPdf")]

    results = []
    for p in papers:
        authors = ", ".join(
            a.get("name", "") for a in (p.get("authors") or [])[:3]
        )
        if len(p.get("authors") or []) > 3:
            authors += " et al."
        
        doi = (p.get("externalIds") or {}).get("DOI", "")
        pdf = (p.get("openAccessPdf") or {}).get("url", "")
        journal = (p.get("journal") or {}).get("name", "")

        results.append({
            "title": p.get("title", ""),
            "authors": authors,
            "year": p.get("year", ""),
            "journal": journal,
            "citations": p.get("citationCount", 0),
            "abstract": (p.get("abstract") or "")[:400] + ("..." if len(p.get("abstract") or "") > 400 else ""),
            "doi": doi,
            "pdf_url": pdf,
        })

    if not results:
        return "Nenhum resultado encontrado para esta busca."

    output = f"## Semantic Scholar — {len(results)} resultados para: '{query}'\n\n"
    for i, p in enumerate(results, 1):
        output += f"### {i}. {p['title']} ({p['year']})\n"
        output += f"**Autores:** {p['authors']}\n"
        if p['journal']:
            output += f"**Journal:** {p['journal']}\n"
        output += f"**Citações:** {p['citations']}\n"
        if p['doi']:
            output += f"**DOI:** https://doi.org/{p['doi']}\n"
        if p['pdf_url']:
            output += f"**PDF:** {p['pdf_url']}\n"
        if p['abstract']:
            output += f"**Abstract:** {p['abstract']}\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 2. OPENALEX
# ─────────────────────────────────────────

@mcp.tool()
async def search_openalex(
    query: str,
    max_results: int = 10,
    year_from: Optional[int] = None,
    study_type: Optional[str] = None,
    open_access_only: bool = False
) -> str:
    """
    Busca papers no OpenAlex (250M+ works). 
    Excelente para filtros avançados e acesso aberto.
    
    Args:
        query: Termos de pesquisa
        max_results: Número de resultados (máx 50)
        year_from: Filtrar a partir deste ano (ex: 2020)
        study_type: Tipo de estudo — 'journal-article', 'review', 'book-chapter'
        open_access_only: Apenas artigos open access
    """
    params = {
        "search": query,
        "per-page": min(max_results, 50),
        "select": "title,publication_year,authorships,primary_location,cited_by_count,doi,open_access,abstract_inverted_index,type",
        "sort": "cited_by_count:desc",
        "mailto": "research@qara.com.br"
    }

    filters = []
    if year_from:
        filters.append(f"publication_year:>{year_from - 1}")
    if study_type:
        filters.append(f"type:{study_type}")
    if open_access_only:
        filters.append("open_access.is_oa:true")
    if filters:
        params["filter"] = ",".join(filters)

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.openalex.org/works",
            params=params
        )
        r.raise_for_status()
        data = r.json()

    works = data.get("results", [])

    def reconstruct_abstract(inverted_index):
        if not inverted_index:
            return ""
        words = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word
        text = " ".join(words[k] for k in sorted(words))
        return text[:400] + ("..." if len(text) > 400 else "")

    results = []
    for w in works:
        authors = []
        for a in (w.get("authorships") or [])[:3]:
            name = (a.get("author") or {}).get("display_name", "")
            if name:
                authors.append(name)
        if len(w.get("authorships") or []) > 3:
            authors.append("et al.")

        location = w.get("primary_location") or {}
        source = (location.get("source") or {}).get("display_name", "")
        oa = (w.get("open_access") or {}).get("oa_url", "")
        
        results.append({
            "title": w.get("title", ""),
            "authors": ", ".join(authors),
            "year": w.get("publication_year", ""),
            "journal": source,
            "citations": w.get("cited_by_count", 0),
            "doi": w.get("doi", ""),
            "oa_url": oa,
            "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
            "type": w.get("type", ""),
        })

    if not results:
        return "Nenhum resultado encontrado no OpenAlex."

    output = f"## OpenAlex — {len(results)} resultados para: '{query}'\n\n"
    for i, p in enumerate(results, 1):
        output += f"### {i}. {p['title']} ({p['year']})\n"
        output += f"**Autores:** {p['authors']}\n"
        if p['journal']:
            output += f"**Journal:** {p['journal']}\n"
        if p['type']:
            output += f"**Tipo:** {p['type']}\n"
        output += f"**Citações:** {p['citations']}\n"
        if p['doi']:
            output += f"**DOI:** {p['doi']}\n"
        if p['oa_url']:
            output += f"**PDF OA:** {p['oa_url']}\n"
        if p['abstract']:
            output += f"**Abstract:** {p['abstract']}\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 3. EUROPE PMC
# ─────────────────────────────────────────

@mcp.tool()
async def search_europe_pmc(
    query: str,
    max_results: int = 10,
    has_full_text: bool = False,
    is_review: bool = False
) -> str:
    """
    Busca no Europe PMC — excelente para full-text e revisões sistemáticas.
    Inclui artigos do PubMed com metadados extras.
    
    Args:
        query: Termos de pesquisa
        max_results: Número de resultados
        has_full_text: Apenas artigos com full-text disponível
        is_review: Apenas revisões (review articles)
    """
    search_query = query
    if has_full_text:
        search_query += " AND HAS_FT:y"
    if is_review:
        search_query += " AND PUB_TYPE:Review"

    params = {
        "query": search_query,
        "format": "json",
        "pageSize": min(max_results, 100),
        "resultType": "core",
        "sort_cited": "y"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params=params
        )
        r.raise_for_status()
        data = r.json()

    articles = data.get("resultList", {}).get("result", [])

    if not articles:
        return "Nenhum resultado encontrado no Europe PMC."

    output = f"## Europe PMC — {len(articles)} resultados para: '{query}'\n\n"
    for i, a in enumerate(articles, 1):
        pmid = a.get("pmid", "")
        doi = a.get("doi", "")
        full_text = a.get("hasTextMinedTerms", "N") == "Y" or a.get("hasPDF", "N") == "Y"
        
        output += f"### {i}. {a.get('title', '')} ({a.get('pubYear', '')})\n"
        output += f"**Autores:** {a.get('authorString', '')[:100]}\n"
        if a.get('journalTitle'):
            output += f"**Journal:** {a.get('journalTitle')}\n"
        if a.get('citedByCount'):
            output += f"**Citações:** {a.get('citedByCount')}\n"
        if pmid:
            output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n"
        if doi:
            output += f"**DOI:** https://doi.org/{doi}\n"
        if full_text:
            output += f"**Full text:** https://europepmc.org/article/MED/{pmid}\n"
        if a.get('abstractText'):
            abstract = a['abstractText'][:400]
            output += f"**Abstract:** {abstract}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 4. BUSCA COMBINADA (todas as fontes)
# ─────────────────────────────────────────

@mcp.tool()
async def research_all_sources(
    query: str,
    max_per_source: int = 5,
    year_from: Optional[int] = None,
    open_access_only: bool = False
) -> str:
    """
    Busca simultaneamente no Semantic Scholar, OpenAlex e Europe PMC.
    Ideal para revisão abrangente de literatura.
    
    Args:
        query: Pergunta de pesquisa
        max_per_source: Resultados por fonte (total = 3x)
        year_from: Filtrar a partir deste ano
        open_access_only: Apenas artigos com acesso gratuito
    """
    tasks = [
        search_semantic_scholar(query, max_per_source, year_from=year_from, open_access_only=open_access_only),
        search_openalex(query, max_per_source, year_from=year_from, open_access_only=open_access_only),
        search_europe_pmc(query, max_per_source),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = f"# Pesquisa Combinada: '{query}'\n"
    output += f"*Fontes: Semantic Scholar + OpenAlex + Europe PMC*\n\n"
    output += "---\n\n"
    
    labels = ["Semantic Scholar", "OpenAlex", "Europe PMC"]
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            output += f"## {label}\n⚠️ Erro: {str(result)}\n\n"
        else:
            output += result + "\n---\n\n"

    return output


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
