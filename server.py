"""
Research MCP Server v3
43 tools | 10+ data sources | Full research workflow
Sources: PubMed, Semantic Scholar, OpenAlex, Europe PMC, Cochrane,
         arXiv, CORE, ClinicalTrials.gov, bioRxiv/medRxiv,
         FDA, NIH RePORTER, WHO, OMIM, Unpaywall, CrossRef
Deploy: Render.com (free tier) — see README.md
"""

from mcp.server.fastmcp import FastMCP
import httpx
import asyncio
import csv
import difflib
import hashlib
import io
import json
import math
import os
import sqlite3
import time as _time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from functools import wraps
from math import sqrt, log, exp
from typing import Optional

_port = int(os.environ.get("PORT", 8000))
mcp = FastMCP("research-mcp", host="0.0.0.0", port=_port)

PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "")
PUBMED_EMAIL   = os.environ.get("PUBMED_EMAIL", "research@qara.com.br")


# ─────────────────────────────────────────
# 1. PUBMED (NCBI E-utilities)
# ─────────────────────────────────────────

@mcp.tool()
async def search_pubmed(
    query: str,
    max_results: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    article_type: Optional[str] = None,
    free_full_text: bool = False
) -> str:
    """
    Busca no PubMed via NCBI E-utilities. Base médica oficial da NLM/NIH.
    Retorna PMID, título, autores, journal, abstract e links.

    Args:
        query: Termos MeSH ou linguagem natural (ex: 'basal cell carcinoma treatment RCT')
        max_results: Número de resultados (max 50)
        year_from: Ano inicial (ex: 2018)
        year_to: Ano final (ex: 2024)
        article_type: 'Clinical Trial', 'Review', 'Systematic Review', 'Meta-Analysis', 'Case Reports'
        free_full_text: Apenas artigos com full text gratuito
    """
    search_query = query
    if year_from or year_to:
        y_from = year_from or 1900
        y_to   = year_to   or 2099
        search_query += f" AND {y_from}:{y_to}[dp]"
    if article_type:
        search_query += f" AND {article_type}[pt]"
    if free_full_text:
        search_query += " AND free full text[sb]"

    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY:
        base_params["api_key"] = PUBMED_API_KEY

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={**base_params, "db": "pubmed", "term": search_query,
                    "retmax": min(max_results, 50), "retmode": "json", "sort": "relevance"}
        )
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])

        if not ids:
            return f"Nenhum resultado no PubMed para: '{query}'"

        r2 = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={**base_params, "db": "pubmed", "id": ",".join(ids),
                    "retmode": "xml", "rettype": "abstract"}
        )
        r2.raise_for_status()

    root = ET.fromstring(r2.text)
    output = f"## PubMed — resultados para: '{query}'\n\n"

    for i, article in enumerate(root.findall(".//PubmedArticle"), 1):
        pmid  = article.findtext(".//PMID", "")
        title = article.findtext(".//ArticleTitle", "").strip()

        authors = []
        for a in article.findall(".//Author")[:3]:
            last  = a.findtext("LastName", "")
            first = a.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {first}".strip())
        if len(article.findall(".//Author")) > 3:
            authors.append("et al.")

        journal = (article.findtext(".//Journal/Title", "") or
                   article.findtext(".//Journal/ISOAbbreviation", ""))
        year    = (article.findtext(".//PubDate/Year", "") or
                   (article.findtext(".//PubDate/MedlineDate", "") or "")[:4])
        volume  = article.findtext(".//Volume", "")
        issue   = article.findtext(".//Issue", "")
        pages   = article.findtext(".//MedlinePgn", "")

        abstract_parts = article.findall(".//AbstractText")
        abstract = " ".join(
            (f"[{p.get('Label')}] " if p.get('Label') else "") + (p.text or "")
            for p in abstract_parts
        )
        abstract = abstract[:500] + ("..." if len(abstract) > 500 else "")

        doi = ""
        for eid in article.findall(".//ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""

        pub_types = [pt.text for pt in article.findall(".//PublicationType") if pt.text]
        relevant_types = [pt for pt in pub_types if pt in (
            "Clinical Trial", "Randomized Controlled Trial", "Review",
            "Systematic Review", "Meta-Analysis", "Case Reports", "Guideline"
        )]

        output += f"### {i}. {title} ({year})\n"
        output += f"**Autores:** {', '.join(authors)}\n"
        if journal:
            vol_info = f" {volume}({issue}):{pages}" if volume else ""
            output += f"**Journal:** {journal}{vol_info}\n"
        if relevant_types:
            output += f"**Tipo:** {', '.join(relevant_types)}\n"
        output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n"
        if doi:
            output += f"**DOI:** https://doi.org/{doi}\n"
        if abstract:
            output += f"**Abstract:** {abstract}\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 2. BUSCAR ARTIGO POR PMID OU DOI
# ─────────────────────────────────────────

@mcp.tool()
async def get_paper_details(identifier: str) -> str:
    """
    Busca detalhes completos de um artigo pelo PMID ou DOI.
    Retorna abstract completo, autores, journal, MeSH terms e links.

    Args:
        identifier: PMID numérico (ex: '35123456') ou DOI (ex: '10.1016/j.jaad.2023.01.001')
    """
    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY:
        base_params["api_key"] = PUBMED_API_KEY

    pmid = None

    async with httpx.AsyncClient(timeout=30) as client:
        if identifier.startswith("10."):
            r = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={**base_params, "db": "pubmed",
                        "term": f"{identifier}[doi]", "retmode": "json"}
            )
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                r2 = await client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/DOI:{identifier}",
                    params={"fields": "title,year,abstract,authors,citationCount,journal"}
                )
                if r2.status_code == 200:
                    d = r2.json()
                    authors = ", ".join(a.get("name","") for a in (d.get("authors") or [])[:5])
                    journal = (d.get("journal") or {}).get("name","")
                    out  = f"# {d.get('title','')}\n\n"
                    out += f"**Autores:** {authors}\n"
                    if journal: out += f"**Journal:** {journal} ({d.get('year','')})\n"
                    out += f"**Citações:** {d.get('citationCount',0)}\n"
                    if d.get('abstract'): out += f"\n## Abstract\n{d['abstract']}\n"
                    return out
                return f"Artigo não encontrado para DOI: {identifier}"
            pmid = ids[0]
        else:
            pmid = identifier.strip()

        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={**base_params, "db": "pubmed", "id": pmid,
                    "retmode": "xml", "rettype": "full"}
        )
        r.raise_for_status()

    root    = ET.fromstring(r.text)
    article = root.find(".//PubmedArticle")
    if not article:
        return f"PMID {pmid} não encontrado."

    title   = article.findtext(".//ArticleTitle", "").strip()
    journal = article.findtext(".//Journal/Title", "")
    year    = article.findtext(".//PubDate/Year", "")
    volume  = article.findtext(".//Volume", "")
    issue   = article.findtext(".//Issue", "")
    pages   = article.findtext(".//MedlinePgn", "")

    authors = []
    for a in article.findall(".//Author"):
        last  = a.findtext("LastName", "")
        first = a.findtext("ForeName", "")
        if last:
            authors.append(f"{last} {first}".strip())

    abstract_parts = article.findall(".//AbstractText")
    abstract = "\n".join(
        (f"**{p.get('Label')}:** " if p.get('Label') else "") + (p.text or "")
        for p in abstract_parts
    )

    mesh_terms = [m.findtext("DescriptorName","") for m in article.findall(".//MeshHeading")]

    doi = pmc = ""
    for eid in article.findall(".//ArticleId"):
        if eid.get("IdType") == "doi": doi = eid.text or ""
        if eid.get("IdType") == "pmc": pmc = eid.text or ""

    pub_types = [pt.text for pt in article.findall(".//PublicationType") if pt.text]

    output  = f"# {title}\n\n"
    output += f"**Autores:** {'; '.join(authors[:6])}\n"
    if len(authors) > 6:
        output += f"*(+{len(authors)-6} autores)*\n"
    output += f"**Journal:** {journal}"
    if volume: output += f" {volume}({issue}):{pages}"
    output += f" ({year})\n"
    if pub_types:
        output += f"**Tipos:** {', '.join(pub_types)}\n"
    output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n"
    if doi: output += f"**DOI:** https://doi.org/{doi}\n"
    if pmc: output += f"**PMC Full Text:** https://pmc.ncbi.nlm.nih.gov/articles/{pmc}/\n"
    if abstract:
        output += f"\n## Abstract\n{abstract}\n"
    if mesh_terms:
        output += f"\n## MeSH Terms\n{', '.join(t for t in mesh_terms if t)}\n"

    return output


# ─────────────────────────────────────────
# 3. ARTIGOS RELACIONADOS
# ─────────────────────────────────────────

@mcp.tool()
async def find_related_articles(pmid: str, max_results: int = 10) -> str:
    """
    Encontra artigos relacionados a um PMID pelo algoritmo de similaridade do PubMed.
    Útil para expandir a revisão a partir de um artigo-chave.

    Args:
        pmid: PMID do artigo de referência
        max_results: Número de artigos relacionados (max 20)
    """
    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY:
        base_params["api_key"] = PUBMED_API_KEY

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
            params={**base_params, "dbfrom": "pubmed", "db": "pubmed",
                    "id": pmid, "cmd": "neighbor_score", "retmode": "json"}
        )
        r.raise_for_status()
        data = r.json()

    try:
        links = data["linksets"][0]["linksetdbs"][0]["links"][:max_results]
    except (KeyError, IndexError):
        return f"Nenhum artigo relacionado encontrado para PMID {pmid}."

    return await search_pubmed(
        query=" OR ".join(f"{lid}[uid]" for lid in links),
        max_results=max_results
    )


# ─────────────────────────────────────────
# 4. SEMANTIC SCHOLAR
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
    Busca no Semantic Scholar (200M+ artigos) com busca semântica.

    Args:
        query: Termos de pesquisa (inglês recomendado)
        max_results: Número de resultados (max 100)
        year_from: Filtrar a partir deste ano
        year_to: Filtrar até este ano
        open_access_only: Apenas artigos com PDF gratuito
    """
    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": "title,year,abstract,authors,citationCount,openAccessPdf,externalIds,journal"
    }
    if year_from and year_to: params["year"] = f"{year_from}-{year_to}"
    elif year_from:            params["year"] = f"{year_from}-"
    elif year_to:              params["year"] = f"-{year_to}"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params
        )
        r.raise_for_status()
        papers = r.json().get("data", [])

    if open_access_only:
        papers = [p for p in papers if p.get("openAccessPdf")]

    if not papers:
        return "Nenhum resultado no Semantic Scholar."

    output = f"## Semantic Scholar — {len(papers)} resultados para: '{query}'\n\n"
    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.get("name","") for a in (p.get("authors") or [])[:3])
        if len(p.get("authors") or []) > 3: authors += " et al."
        doi     = (p.get("externalIds") or {}).get("DOI","")
        pdf     = (p.get("openAccessPdf") or {}).get("url","")
        journal = (p.get("journal") or {}).get("name","")
        abstract = (p.get("abstract") or "")[:400]
        output += f"### {i}. {p.get('title','')} ({p.get('year','')})\n"
        output += f"**Autores:** {authors}\n"
        if journal:  output += f"**Journal:** {journal}\n"
        output += f"**Citações:** {p.get('citationCount',0)}\n"
        if doi:      output += f"**DOI:** https://doi.org/{doi}\n"
        if pdf:      output += f"**PDF:** {pdf}\n"
        if abstract: output += f"**Abstract:** {abstract}...\n"
        output += "\n"
    return output


# ─────────────────────────────────────────
# 5. OPENALEX
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
    Busca no OpenAlex (250M+ works). Ótimo para filtros avançados e acesso aberto.

    Args:
        query: Termos de pesquisa
        max_results: Número de resultados (max 50)
        year_from: Filtrar a partir deste ano
        study_type: 'journal-article', 'review', 'book-chapter'
        open_access_only: Apenas artigos open access
    """
    params = {
        "search": query,
        "per-page": min(max_results, 50),
        "select": "title,publication_year,authorships,primary_location,cited_by_count,doi,open_access,abstract_inverted_index,type",
        "sort": "cited_by_count:desc",
        "mailto": PUBMED_EMAIL
    }
    filters = []
    if year_from:        filters.append(f"publication_year:>{year_from-1}")
    if study_type:       filters.append(f"type:{study_type}")
    if open_access_only: filters.append("open_access.is_oa:true")
    if filters:          params["filter"] = ",".join(filters)

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://api.openalex.org/works", params=params)
        r.raise_for_status()
        works = r.json().get("results", [])

    def reconstruct_abstract(inv):
        if not inv: return ""
        words = {}
        for w, positions in inv.items():
            for pos in positions: words[pos] = w
        text = " ".join(words[k] for k in sorted(words))
        return text[:400] + ("..." if len(text) > 400 else "")

    if not works: return "Nenhum resultado no OpenAlex."

    output = f"## OpenAlex — {len(works)} resultados para: '{query}'\n\n"
    for i, w in enumerate(works, 1):
        authors = [
            (a.get("author") or {}).get("display_name","")
            for a in (w.get("authorships") or [])[:3]
        ]
        if len(w.get("authorships") or []) > 3: authors.append("et al.")
        loc    = w.get("primary_location") or {}
        source = (loc.get("source") or {}).get("display_name","")
        oa_url = (w.get("open_access") or {}).get("oa_url","")
        output += f"### {i}. {w.get('title','')} ({w.get('publication_year','')})\n"
        output += f"**Autores:** {', '.join(a for a in authors if a)}\n"
        if source:         output += f"**Journal:** {source}\n"
        if w.get('type'): output += f"**Tipo:** {w['type']}\n"
        output += f"**Citações:** {w.get('cited_by_count',0)}\n"
        if w.get('doi'): output += f"**DOI:** {w['doi']}\n"
        if oa_url:       output += f"**PDF OA:** {oa_url}\n"
        ab = reconstruct_abstract(w.get("abstract_inverted_index"))
        if ab: output += f"**Abstract:** {ab}\n"
        output += "\n"
    return output


# ─────────────────────────────────────────
# 6. EUROPE PMC
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

    Args:
        query: Termos de pesquisa
        max_results: Número de resultados
        has_full_text: Apenas artigos com full-text disponível
        is_review: Apenas revisões
    """
    q = query
    if has_full_text: q += " AND HAS_FT:y"
    if is_review:     q += " AND PUB_TYPE:Review"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": q, "format": "json",
                    "pageSize": min(max_results, 100),
                    "resultType": "core", "sort_cited": "y"}
        )
        r.raise_for_status()
        articles = r.json().get("resultList", {}).get("result", [])

    if not articles: return "Nenhum resultado no Europe PMC."

    output = f"## Europe PMC — {len(articles)} resultados para: '{query}'\n\n"
    for i, a in enumerate(articles, 1):
        pmid = a.get("pmid","")
        doi  = a.get("doi","")
        has_ft = a.get("hasTextMinedTerms","N") == "Y" or a.get("hasPDF","N") == "Y"
        output += f"### {i}. {a.get('title','')} ({a.get('pubYear','')})\n"
        output += f"**Autores:** {a.get('authorString','')[:100]}\n"
        if a.get('journalTitle'): output += f"**Journal:** {a['journalTitle']}\n"
        if a.get('citedByCount'): output += f"**Citações:** {a['citedByCount']}\n"
        if pmid: output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n"
        if doi:  output += f"**DOI:** https://doi.org/{doi}\n"
        if has_ft and pmid:
            output += f"**Full text:** https://europepmc.org/article/MED/{pmid}\n"
        if a.get('abstractText'):
            output += f"**Abstract:** {a['abstractText'][:400]}...\n"
        output += "\n"
    return output


# ─────────────────────────────────────────
# 7. BUSCA COMBINADA (4 fontes)
# ─────────────────────────────────────────

@mcp.tool()
async def research_all_sources(
    query: str,
    max_per_source: int = 5,
    year_from: Optional[int] = None,
    open_access_only: bool = False,
    reviews_only: bool = False
) -> str:
    """
    Busca simultânea em PubMed + Semantic Scholar + OpenAlex + Europe PMC.
    Ideal para revisão abrangente. Retorna até 20 resultados no total.

    Args:
        query: Pergunta de pesquisa
        max_per_source: Resultados por fonte (recomendado: 5)
        year_from: Filtrar a partir deste ano
        open_access_only: Apenas artigos com acesso gratuito
        reviews_only: Priorizar revisões e meta-análises
    """
    pubmed_query = query
    if reviews_only:
        pubmed_query += " AND (Review[pt] OR Meta-Analysis[pt] OR Systematic Review[pt])"

    tasks = [
        search_pubmed(pubmed_query, max_per_source, year_from=year_from,
                      free_full_text=open_access_only),
        search_semantic_scholar(query, max_per_source, year_from=year_from,
                                open_access_only=open_access_only),
        search_openalex(query, max_per_source, year_from=year_from,
                        open_access_only=open_access_only,
                        study_type="review" if reviews_only else None),
        search_europe_pmc(query, max_per_source, is_review=reviews_only),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    output  = f"# Pesquisa Combinada: '{query}'\n"
    output += "*Fontes: PubMed + Semantic Scholar + OpenAlex + Europe PMC*\n\n---\n\n"

    labels = ["PubMed", "Semantic Scholar", "OpenAlex", "Europe PMC"]
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            output += f"## {label}\n⚠️ Erro: {str(result)}\n\n"
        else:
            output += result + "\n---\n\n"

    return output


# ─────────────────────────────────────────
# 8. UNPAYWALL — full-text legal e gratuito
# ─────────────────────────────────────────

@mcp.tool()
async def find_free_fulltext(doi: str) -> str:
    """
    Encontra a melhor versão gratuita e legal de um artigo pelo DOI via Unpaywall.
    Cobre ~50% dos artigos recentes — repositórios institucionais, preprints, versões do autor.

    Args:
        doi: DOI do artigo (ex: '10.1016/j.jaad.2023.01.001')
    """
    doi = doi.strip().lstrip("https://doi.org/")

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": PUBMED_EMAIL}
        )
        if r.status_code == 404:
            return f"DOI não encontrado no Unpaywall: {doi}"
        r.raise_for_status()
        data = r.json()

    title      = data.get("title", "")
    year       = data.get("year", "")
    journal    = data.get("journal_name", "")
    is_oa      = data.get("is_oa", False)
    oa_status  = data.get("oa_status", "")  # gold, green, hybrid, bronze, closed
    best_oa    = data.get("best_oa_location") or {}
    locations  = data.get("oa_locations") or []

    if not is_oa:
        return (
            f"## {title} ({year})\n"
            f"**Journal:** {journal}\n"
            f"**DOI:** https://doi.org/{doi}\n\n"
            f"❌ Nenhuma versão gratuita encontrada no Unpaywall.\n\n"
            f"**Alternativas:**\n"
            f"- Solicitar ao autor via ResearchGate ou email\n"
            f"- Verificar se a instituição tem acesso\n"
            f"- Buscar preprint em bioRxiv/medRxiv: https://biorxiv.org/search/{doi}\n"
        )

    # Ordena localizações por qualidade: publisher > repository
    oa_labels = {
        "gold":   "🥇 Gold OA (publisher)",
        "green":  "🟢 Green OA (repositório)",
        "hybrid": "🔵 Hybrid OA",
        "bronze": "🟤 Bronze OA (gratuito sem licença formal)",
    }

    output  = f"## {title} ({year})\n"
    output += f"**Journal:** {journal}\n"
    output += f"**DOI:** https://doi.org/{doi}\n"
    output += f"**Status OA:** {oa_labels.get(oa_status, oa_status)}\n\n"

    # Melhor link
    best_url     = best_oa.get("url", "")
    best_version = best_oa.get("version", "")  # publishedVersion, acceptedVersion, submittedVersion
    best_host    = best_oa.get("host_type", "")

    version_labels = {
        "publishedVersion": "versão publicada",
        "acceptedVersion":  "versão aceita (post-print)",
        "submittedVersion": "preprint (pre-print)",
    }

    if best_url:
        output += f"### ✅ Melhor link gratuito\n"
        output += f"**URL:** {best_url}\n"
        output += f"**Versão:** {version_labels.get(best_version, best_version)}\n"
        output += f"**Host:** {best_host}\n\n"

    # Outras localizações disponíveis
    other_locations = [loc for loc in locations if loc.get("url") != best_url]
    if other_locations:
        output += f"### Outras versões disponíveis\n"
        for loc in other_locations[:4]:
            url     = loc.get("url", "")
            version = version_labels.get(loc.get("version",""), loc.get("version",""))
            host    = loc.get("host_type","")
            output += f"- [{host} — {version}]({url})\n"

    return output


@mcp.tool()
async def find_free_fulltext_batch(dois: list[str]) -> str:
    """
    Verifica disponibilidade gratuita de múltiplos artigos de uma vez.
    Útil após uma busca para saber quais artigos tens acesso imediato.

    Args:
        dois: Lista de DOIs (ex: ['10.1016/j.jaad.2023.01.001', '10.1001/jama.2022.1234'])
    """
    tasks = [find_free_fulltext(doi) for doi in dois[:10]]  # máx 10
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = f"# Verificação de Acesso Gratuito — {len(dois)} artigos\n\n"
    for doi, result in zip(dois, results):
        if isinstance(result, Exception):
            output += f"## DOI: {doi}\n⚠️ Erro: {str(result)}\n\n"
        else:
            output += result + "\n---\n\n"
    return output


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")


# ─────────────────────────────────────────
# 10. JOURNAL IMPACT (OpenAlex Sources)
# ─────────────────────────────────────────

@mcp.tool()
async def get_journal_impact(journal_name: str) -> str:
    """
    Retorna métricas de impacto de um journal via OpenAlex.
    Inclui Impact Factor estimado (2yr mean citedness), h-index e open access status.

    Args:
        journal_name: Nome do journal (ex: 'Journal of the American Academy of Dermatology',
                      'JAMA Dermatology', 'Nature', 'NEJM')
    """
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://api.openalex.org/sources",
            params={
                "search": journal_name,
                "per-page": 5,
                "mailto": PUBMED_EMAIL,
                "select": (
                    "display_name,issn_l,cited_by_count,works_count,"
                    "summary_stats,is_oa,is_in_doaj,apc_usd,"
                    "host_organization_name,country_code"
                )
            }
        )
        r.raise_for_status()
        results = r.json().get("results", [])

    if not results:
        return f"Journal não encontrado: '{journal_name}'"

    output = f"## Journal Impact — '{journal_name}'\n\n"
    for j in results[:3]:
        name    = j.get("display_name", "")
        issn    = j.get("issn_l", "")
        is_oa   = j.get("is_oa", False)
        in_doaj = j.get("is_in_doaj", False)
        apc     = j.get("apc_usd")
        org     = j.get("host_organization_name", "")
        works   = j.get("works_count", 0)
        cited   = j.get("cited_by_count", 0)
        stats   = j.get("summary_stats") or {}
        if2yr   = stats.get("2yr_mean_citedness", 0)
        h_index = stats.get("h_index", 0)
        i10     = stats.get("i10_index", 0)
        oa_pct  = stats.get("oa_percent", 0)

        if   if2yr >= 8.0: quartil = "🥇 Q1 (top tier)"
        elif if2yr >= 4.0: quartil = "🥈 Q1/Q2"
        elif if2yr >= 2.5: quartil = "🥉 Q2/Q3"
        elif if2yr >= 1.0: quartil = "Q3/Q4"
        else:              quartil = "Q4 ou novo journal"

        output += f"### {name}\n"
        if issn: output += f"**ISSN:** {issn}\n"
        if org:  output += f"**Editora:** {org}\n"
        output += "\n**📊 Métricas de Impacto**\n"
        output += f"- **Impact Factor (2yr):** {if2yr:.2f}\n"
        output += f"- **Quartil estimado:** {quartil}\n"
        output += f"- **h-index:** {h_index}\n"
        output += f"- **i10-index:** {i10}\n"
        output += f"- **Total artigos:** {works:,}\n"
        output += f"- **Total citações:** {cited:,}\n"
        if oa_pct: output += f"- **% Open Access:** {oa_pct:.0f}%\n"
        output += "\n**📖 Acesso**\n"
        output += f"- **Open Access:** {'✅ Sim' if is_oa else '❌ Não'}\n"
        output += f"- **DOAJ:** {'✅ Indexado' if in_doaj else '❌ Não'}\n"
        if apc: output += f"- **APC:** USD {apc:,}\n"
        output += "\n---\n\n"

    return output


# ─────────────────────────────────────────
# 11. ARTIGOS DE ALTO IMPACTO
# ─────────────────────────────────────────

@mcp.tool()
async def search_high_impact_papers(
    query: str,
    min_citations: int = 50,
    max_results: int = 10,
    year_from: Optional[int] = None,
) -> str:
    """
    Busca artigos de alto impacto filtrados por número mínimo de citações.
    Ordenado por citações descendentes com badge de impacto.

    Args:
        query: Termos de pesquisa
        min_citations: Citações mínimas (padrão 50; use 200+ para landmark papers)
        max_results: Número de resultados desejados
        year_from: Filtrar a partir deste ano
    """
    params = {
        "query": query,
        "limit": min(max_results * 4, 100),
        "fields": "title,year,abstract,authors,citationCount,openAccessPdf,externalIds,journal",
        "sort": "citationCount"
    }
    if year_from:
        params["year"] = f"{year_from}-"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params
        )
        r.raise_for_status()
        papers = r.json().get("data", [])

    papers = [p for p in papers if (p.get("citationCount") or 0) >= min_citations]
    papers = sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)
    papers = papers[:max_results]

    if not papers:
        return (
            f"Nenhum artigo com ≥{min_citations} citações para '{query}'.\n"
            f"Tenta reduzir min_citations ou ampliar o período."
        )

    output = f"## Alto Impacto — '{query}'\n"
    output += f"*≥{min_citations} citações | {len(papers)} resultados*\n\n"

    for i, p in enumerate(papers, 1):
        authors   = ", ".join(a.get("name","") for a in (p.get("authors") or [])[:3])
        if len(p.get("authors") or []) > 3: authors += " et al."
        doi       = (p.get("externalIds") or {}).get("DOI","")
        pdf       = (p.get("openAccessPdf") or {}).get("url","")
        journal   = (p.get("journal") or {}).get("name","")
        abstract  = (p.get("abstract") or "")[:350]
        citations = p.get("citationCount", 0)

        if   citations >= 1000: badge = "🔥 Landmark"
        elif citations >= 500:  badge = "⭐⭐⭐ Very High"
        elif citations >= 200:  badge = "⭐⭐ High"
        elif citations >= 100:  badge = "⭐ Notable"
        else:                   badge = "📄 Cited"

        output += f"### {i}. {p.get('title','')} ({p.get('year','')})\n"
        output += f"**{badge} — {citations:,} citações**\n"
        output += f"**Autores:** {authors}\n"
        if journal:  output += f"**Journal:** {journal}\n"
        if doi:      output += f"**DOI:** https://doi.org/{doi}\n"
        if pdf:      output += f"**PDF:** {pdf}\n"
        if abstract: output += f"**Abstract:** {abstract}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 12. BIORXIV / MEDRXIV — Preprints
# ─────────────────────────────────────────

@mcp.tool()
async def search_preprints(
    query: str,
    max_results: int = 10,
    server: str = "both",
    days_back: int = 180
) -> str:
    """
    Busca preprints no bioRxiv e/ou medRxiv — resultados antes da publicação oficial.
    Útil para acompanhar evidências emergentes.

    Args:
        query: Termos de pesquisa
        max_results: Número de resultados
        server: 'biorxiv', 'medrxiv', ou 'both'
        days_back: Quantos dias para trás buscar (padrão: 180)
    """
    date_to   = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    servers = []
    if server in ("biorxiv", "both"):  servers.append("biorxiv")
    if server in ("medrxiv", "both"):  servers.append("medrxiv")

    all_results = []

    async with httpx.AsyncClient(timeout=30) as client:
        for srv in servers:
            # Busca via CrossRef que indexa preprints
            r = await client.get(
                "https://api.crossref.org/works",
                params={
                    "query": query,
                    "filter": f"from-posted-date:{date_from},until-posted-date:{date_to},type:posted-content",
                    "rows": max_results,
                    "select": "DOI,title,author,posted,abstract,institution,is-referenced-by-count",
                    "mailto": PUBMED_EMAIL
                }
            )
            if r.status_code == 200:
                items = r.json().get("message", {}).get("items", [])
                for item in items:
                    # Filtra pelo servidor correto
                    doi = item.get("DOI","").lower()
                    if srv == "medrxiv" and "medrxiv" not in doi:
                        continue
                    if srv == "biorxiv" and "biorxiv" not in doi:
                        continue
                    all_results.append((srv, item))

    if not all_results:
        # Fallback: busca direta na API do bioRxiv/medRxiv
        async with httpx.AsyncClient(timeout=30) as client:
            for srv in servers:
                r = await client.get(
                    f"https://api.biorxiv.org/details/{srv}/{date_from}/{date_to}/0/json"
                )
                if r.status_code == 200:
                    collection = r.json().get("collection", [])
                    for item in collection:
                        title    = item.get("title","").lower()
                        abstract = item.get("abstract","").lower()
                        terms    = query.lower().split()
                        if any(t in title or t in abstract for t in terms):
                            all_results.append((srv, item))

    if not all_results:
        return f"Nenhum preprint encontrado para '{query}' nos últimos {days_back} dias."

    output = f"## Preprints — '{query}'\n"
    output += f"*bioRxiv + medRxiv | últimos {days_back} dias*\n\n"

    for i, (srv, item) in enumerate(all_results[:max_results], 1):
        # CrossRef format
        if "DOI" in item:
            title   = (item.get("title") or [""])[0]
            authors = ", ".join(
                f"{a.get('given','')} {a.get('family','')}".strip()
                for a in (item.get("author") or [])[:3]
            )
            if len(item.get("author") or []) > 3: authors += " et al."
            doi      = item.get("DOI","")
            posted   = (item.get("posted") or {})
            date_str = f"{posted.get('date-parts',[['']])[0][0]}" if posted else ""
            abstract = item.get("abstract","")[:350]
            cited    = item.get("is-referenced-by-count", 0)
        else:
            # bioRxiv API format
            title    = item.get("title","")
            authors  = item.get("authors","")[:100]
            doi      = item.get("doi","")
            date_str = item.get("date","")
            abstract = item.get("abstract","")[:350]
            cited    = 0

        source_label = "🧬 bioRxiv" if "biorxiv" in srv else "🏥 medRxiv"
        output += f"### {i}. {title}\n"
        output += f"**{source_label}** | {date_str}\n"
        output += f"**Autores:** {authors}\n"
        if cited: output += f"**Citações:** {cited}\n"
        if doi:   output += f"**DOI:** https://doi.org/{doi}\n"
        output += f"**Link:** https://www.{srv}.org/content/{doi}\n"
        if abstract: output += f"**Abstract:** {abstract}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 13. CROSSREF — Referências completas
# ─────────────────────────────────────────

@mcp.tool()
async def get_references(doi: str) -> str:
    """
    Retorna as referências completas citadas em um artigo via CrossRef.
    Útil para rastrear a literatura base de um paper.

    Args:
        doi: DOI do artigo (ex: '10.1016/j.jaad.2023.01.001')
    """
    doi = doi.strip().lstrip("https://doi.org/")

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://api.crossref.org/works/{doi}",
            params={"mailto": PUBMED_EMAIL}
        )
        if r.status_code == 404:
            return f"DOI não encontrado no CrossRef: {doi}"
        r.raise_for_status()
        work = r.json().get("message", {})

    refs = work.get("reference", [])
    title = (work.get("title") or [""])[0]

    if not refs:
        return f"Nenhuma referência disponível para '{title}' (CrossRef não indexou as referências deste artigo)."

    output = f"## Referências — {title}\n"
    output += f"*{len(refs)} referências via CrossRef*\n\n"

    for i, ref in enumerate(refs, 1):
        author    = ref.get("author", "")
        year      = ref.get("year", "")
        art_title = ref.get("article-title", "") or ref.get("volume-title","")
        journal   = ref.get("journal-title","")
        ref_doi   = ref.get("DOI","")
        unstructured = ref.get("unstructured","")

        if art_title:
            output += f"**{i}.** {author} ({year}). {art_title}"
            if journal: output += f". *{journal}*"
            if ref_doi: output += f". https://doi.org/{ref_doi}"
            output += "\n"
        elif unstructured:
            output += f"**{i}.** {unstructured[:200]}\n"

    return output


# ─────────────────────────────────────────
# 14. CLINICALTRIALS.GOV
# ─────────────────────────────────────────

@mcp.tool()
async def search_clinical_trials(
    query: str,
    max_results: int = 10,
    status: Optional[str] = None,
    phase: Optional[str] = None
) -> str:
    """
    Busca ensaios clínicos no ClinicalTrials.gov.
    Útil para saber o que está em andamento ou recém-concluído.

    Args:
        query: Condição ou intervenção (ex: 'basal cell carcinoma vismodegib')
        max_results: Número de resultados
        status: 'RECRUITING', 'COMPLETED', 'ACTIVE_NOT_RECRUITING', 'NOT_YET_RECRUITING'
        phase: 'PHASE1', 'PHASE2', 'PHASE3', 'PHASE4'
    """
    params = {
        "query.term": query,
        "pageSize": min(max_results, 25),
        "format": "json",
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,StartDate,CompletionDate,EnrollmentCount,BriefSummary,Condition,InterventionName,LeadSponsorName,LocationCountry"
    }
    if status: params["filter.overallStatus"] = status
    if phase:  params["filter.phase"] = phase

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params=params
        )
        r.raise_for_status()
        studies = r.json().get("studies", [])

    if not studies:
        return f"Nenhum ensaio clínico encontrado para '{query}'."

    status_emoji = {
        "RECRUITING": "🟢",
        "COMPLETED": "✅",
        "ACTIVE_NOT_RECRUITING": "🔵",
        "NOT_YET_RECRUITING": "⏳",
        "TERMINATED": "🔴",
        "WITHDRAWN": "⚫",
    }

    output = f"## ClinicalTrials.gov — '{query}'\n"
    output += f"*{len(studies)} ensaios encontrados*\n\n"

    for i, study in enumerate(studies, 1):
        proto   = study.get("protocolSection", {})
        id_mod  = proto.get("identificationModule", {})
        stat_mod = proto.get("statusModule", {})
        desc_mod = proto.get("descriptionModule", {})
        design  = proto.get("designModule", {})
        sponsor = proto.get("sponsorCollaboratorsModule", {})
        cond    = proto.get("conditionsModule", {})
        interv  = proto.get("armsInterventionsModule", {})

        nct_id   = id_mod.get("nctId","")
        title    = id_mod.get("briefTitle","")
        ov_status = stat_mod.get("overallStatus","")
        phases   = design.get("phases", [])
        start    = stat_mod.get("startDateStruct",{}).get("date","")
        end      = stat_mod.get("completionDateStruct",{}).get("date","")
        enroll   = design.get("enrollmentInfo",{}).get("count","")
        summary  = desc_mod.get("briefSummary","")[:300]
        lead     = (sponsor.get("leadSponsor") or {}).get("name","")
        conditions = ", ".join(cond.get("conditions",[])[:3])
        interventions = ", ".join(
            i.get("name","") for i in (interv.get("interventions") or [])[:3]
        )

        emoji = status_emoji.get(ov_status, "❓")

        output += f"### {i}. {title}\n"
        output += f"**{emoji} {ov_status}** | {' / '.join(phases)}\n"
        output += f"**NCT:** https://clinicaltrials.gov/study/{nct_id}\n"
        if conditions:    output += f"**Condição:** {conditions}\n"
        if interventions: output += f"**Intervenção:** {interventions}\n"
        if lead:          output += f"**Patrocinador:** {lead}\n"
        if enroll:        output += f"**Participantes:** {enroll}\n"
        if start:         output += f"**Início:** {start}"
        if end:           output += f" → **Fim:** {end}"
        if start or end:  output += "\n"
        if summary:       output += f"**Sumário:** {summary}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 15. CHECK RETRACTION
# ─────────────────────────────────────────

@mcp.tool()
async def check_retraction(identifier: str) -> str:
    """
    Verifica se um artigo foi retratado via Retraction Watch / CrossRef.
    Essencial antes de citar qualquer artigo.

    Args:
        identifier: DOI (ex: '10.1016/j.jaad.2023.01.001') ou título do artigo
    """
    results = []

    async with httpx.AsyncClient(timeout=20) as client:
        # 1. CrossRef — verifica update type
        if identifier.startswith("10."):
            doi = identifier.strip().lstrip("https://doi.org/")
            r = await client.get(
                f"https://api.crossref.org/works/{doi}",
                params={"mailto": PUBMED_EMAIL}
            )
            if r.status_code == 200:
                work = r.json().get("message", {})
                update_to = work.get("update-to", [])
                relation  = work.get("relation", {})
                title     = (work.get("title") or [""])[0]

                # Verifica se é uma retratação
                for upd in update_to:
                    if upd.get("type") in ("retraction", "correction", "expression_of_concern"):
                        results.append(("crossref", upd.get("type"), upd.get("DOI","")))

                # Verifica se há relação com retratação
                is_retracted_by = relation.get("is-retracted-by", [])
                if is_retracted_by:
                    for r_item in is_retracted_by:
                        results.append(("crossref", "retraction", r_item.get("id","")))

        # 2. Retraction Watch API (via CrossRef polite pool)
        search_term = identifier if not identifier.startswith("10.") else identifier
        r2 = await client.get(
            "https://api.crossref.org/works",
            params={
                "query": search_term,
                "filter": "type:retraction",
                "rows": 5,
                "mailto": PUBMED_EMAIL
            }
        )
        if r2.status_code == 200:
            items = r2.json().get("message",{}).get("items",[])
            for item in items:
                item_doi = item.get("DOI","")
                item_title = (item.get("title") or [""])[0]
                if (identifier.startswith("10.") and identifier.lower() in item_doi.lower()) or \
                   (not identifier.startswith("10.") and identifier.lower() in item_title.lower()):
                    results.append(("retraction_watch", "retraction", item_doi))

    if results:
        output = f"## ⚠️ ALERTA DE RETRATAÇÃO\n\n"
        output += f"**Artigo:** {identifier}\n\n"
        for source, rtype, rdoi in results:
            type_labels = {
                "retraction": "🔴 RETRATADO",
                "correction": "🟡 CORRIGIDO",
                "expression_of_concern": "🟠 EXPRESSÃO DE PREOCUPAÇÃO"
            }
            output += f"**Status:** {type_labels.get(rtype, rtype.upper())}\n"
            output += f"**Fonte:** {source}\n"
            if rdoi: output += f"**Link:** https://doi.org/{rdoi}\n"
        output += "\n⚠️ **Não cite este artigo sem verificar o motivo da retratação.**\n"
    else:
        output  = f"## ✅ Sem retratação encontrada\n\n"
        output += f"**Artigo:** {identifier}\n\n"
        output += "Nenhuma retratação, correção ou expressão de preocupação encontrada no CrossRef.\n\n"
        output += "*Nota: Esta verificação cobre o CrossRef. Para verificação completa, consulte também:*\n"
        output += "- https://retractionwatch.com\n"
        output += "- https://pubpeer.com\n"

    return output


# ─────────────────────────────────────────
# 16. EXTRACT PICO
# ─────────────────────────────────────────

@mcp.tool()
async def extract_pico(abstract: str) -> str:
    """
    Extrai estrutura PICO (Population, Intervention, Comparison, Outcome)
    de um abstract usando Claude.

    Args:
        abstract: Texto do abstract do artigo
    """
    system_prompt = """You are a clinical research assistant specialized in evidence-based medicine.
Extract the PICO framework from the abstract. Be concise and precise.
Return ONLY a structured markdown with these exact sections:
## Population
## Intervention
## Comparison (or Control)
## Outcome (Primary and Secondary if available)
## Study Design
## Evidence Level (RCT/Systematic Review/Meta-analysis/Cohort/Case-control/Case series)
If a PICO element is not clearly stated, write "Not specified".
"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": abstract}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        block.get("text","") for block in data.get("content",[])
        if block.get("type") == "text"
    )
    return f"## Extração PICO\n\n{text}"


# ─────────────────────────────────────────
# 17. GENERATE BIBLIOGRAPHY
# ─────────────────────────────────────────

@mcp.tool()
async def generate_bibliography(
    dois: list[str],
    style: str = "vancouver"
) -> str:
    """
    Gera lista de referências formatada a partir de DOIs.

    Args:
        dois: Lista de DOIs
        style: 'vancouver' (padrão medicina), 'apa', 'abnt', 'ama'
    """
    async def fetch_ref(doi: str) -> dict:
        doi = doi.strip().lstrip("https://doi.org/")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.crossref.org/works/{doi}",
                params={"mailto": PUBMED_EMAIL}
            )
            if r.status_code == 200:
                return r.json().get("message", {})
        return {}

    works = await asyncio.gather(*[fetch_ref(doi) for doi in dois])

    def format_vancouver(work: dict, n: int) -> str:
        authors = work.get("author", [])
        if authors:
            author_str = ", ".join(
                f"{a.get('family','')} {a.get('given','')[0]}." if a.get('given') else a.get('family','')
                for a in authors[:6]
            )
            if len(authors) > 6: author_str += " et al"
        else:
            author_str = "Unknown"
        title   = (work.get("title") or [""])[0]
        journal = (work.get("short-container-title") or work.get("container-title") or [""])[0]
        year    = (work.get("published") or {}).get("date-parts",[[""]])[0][0]
        volume  = work.get("volume","")
        issue   = work.get("issue","")
        pages   = work.get("page","")
        doi     = work.get("DOI","")
        ref = f"{n}. {author_str}. {title}. {journal}. {year}"
        if volume: ref += f";{volume}"
        if issue:  ref += f"({issue})"
        if pages:  ref += f":{pages}"
        if doi:    ref += f". doi:{doi}"
        return ref + "."

    def format_apa(work: dict, n: int) -> str:
        authors = work.get("author", [])
        if authors:
            author_str = ", ".join(
                f"{a.get('family','')}, {a.get('given','')[0]}." if a.get('given') else a.get('family','')
                for a in authors[:6]
            )
            if len(authors) > 6: author_str += ", et al"
        else:
            author_str = "Unknown"
        title   = (work.get("title") or [""])[0]
        journal = (work.get("container-title") or [""])[0]
        year    = (work.get("published") or {}).get("date-parts",[[""]])[0][0]
        volume  = work.get("volume","")
        issue   = work.get("issue","")
        pages   = work.get("page","")
        doi     = work.get("DOI","")
        ref = f"{author_str} ({year}). {title}. *{journal}*"
        if volume: ref += f", *{volume}*"
        if issue:  ref += f"({issue})"
        if pages:  ref += f", {pages}"
        if doi:    ref += f". https://doi.org/{doi}"
        return ref

    formatters = {
        "vancouver": format_vancouver,
        "apa": format_apa,
    }
    formatter = formatters.get(style.lower(), format_vancouver)

    output = f"## Referências — {style.upper()}\n\n"
    for i, work in enumerate(works, 1):
        if work:
            output += formatter(work, i) + "\n\n"
        else:
            output += f"{i}. *[Não foi possível recuperar metadados para o DOI {dois[i-1]}]*\n\n"

    return output


# ─────────────────────────────────────────
# 18. AUTHOR PROFILE
# ─────────────────────────────────────────

@mcp.tool()
async def get_author_profile(author_name: str) -> str:
    """
    Retorna perfil bibliométrico de um autor via OpenAlex.
    Inclui h-index, total de citações, publicações e afiliação.

    Args:
        author_name: Nome do autor (ex: 'Reinhard Dummer', 'Alan Menter')
    """
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://api.openalex.org/authors",
            params={
                "search": author_name,
                "per-page": 5,
                "mailto": PUBMED_EMAIL,
                "select": "display_name,ids,affiliations,cited_by_count,works_count,summary_stats,topics"
            }
        )
        r.raise_for_status()
        authors = r.json().get("results", [])

    if not authors:
        return f"Autor não encontrado: '{author_name}'"

    output = f"## Perfil de Autor — '{author_name}'\n\n"

    for a in authors[:3]:
        name        = a.get("display_name","")
        works       = a.get("works_count", 0)
        cited       = a.get("cited_by_count", 0)
        stats       = a.get("summary_stats") or {}
        h_index     = stats.get("h_index", 0)
        i10         = stats.get("i10_index", 0)
        if2yr       = stats.get("2yr_mean_citedness", 0)

        affiliations = a.get("affiliations") or []
        current_aff  = ""
        if affiliations:
            current_aff = (affiliations[0].get("institution") or {}).get("display_name","")

        orcid = (a.get("ids") or {}).get("orcid","")
        openalex_id = (a.get("ids") or {}).get("openalex","")

        topics = a.get("topics") or []
        top_topics = [t.get("display_name","") for t in topics[:5]]

        output += f"### {name}\n"
        if current_aff: output += f"**Afiliação:** {current_aff}\n"
        if orcid:        output += f"**ORCID:** {orcid}\n"
        output += "\n**📊 Métricas**\n"
        output += f"- **h-index:** {h_index}\n"
        output += f"- **i10-index:** {i10}\n"
        output += f"- **Total publicações:** {works:,}\n"
        output += f"- **Total citações:** {cited:,}\n"
        output += f"- **Citedness média (2yr):** {if2yr:.2f}\n"
        if top_topics:
            output += f"\n**🔬 Principais temas:** {', '.join(top_topics)}\n"
        if openalex_id:
            output += f"\n**OpenAlex:** {openalex_id}\n"
        output += "\n---\n\n"

    return output


# ─────────────────────────────────────────
# 19. GET MESH TERMS
# ─────────────────────────────────────────

@mcp.tool()
async def get_mesh_terms(query: str) -> str:
    """
    Sugere termos MeSH oficiais para otimizar uma busca no PubMed.
    Retorna termos relacionados, entry terms e hierarquia MeSH.

    Args:
        query: Tema ou condição clínica (ex: 'basal cell carcinoma', 'atopic dermatitis')
    """
    async with httpx.AsyncClient(timeout=20) as client:
        # Busca no MeSH via NCBI
        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "mesh",
                "term": query,
                "retmax": 5,
                "retmode": "json",
                "tool": "research-mcp",
                "email": PUBMED_EMAIL
            }
        )
        r.raise_for_status()
        ids = r.json().get("esearchresult",{}).get("idlist",[])

        if not ids:
            return f"Nenhum termo MeSH encontrado para: '{query}'"

        r2 = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={
                "db": "mesh",
                "id": ",".join(ids[:5]),
                "retmode": "xml",
                "tool": "research-mcp",
                "email": PUBMED_EMAIL
            }
        )
        r2.raise_for_status()

    root = ET.fromstring(r2.text)
    output = f"## Termos MeSH para: '{query}'\n\n"

    for record in root.findall(".//DescriptorRecord"):
        name     = record.findtext(".//DescriptorName/String","")
        ui       = record.findtext(".//DescriptorUI","")
        scope    = record.findtext(".//ScopeNote","")

        entry_terms = [
            et.findtext("String","")
            for et in record.findall(".//EntryTerm")
        ]

        tree_nums = [
            tn.text for tn in record.findall(".//TreeNumber") if tn.text
        ]

        qualifiers = [
            q.findtext("QualifierName/String","")
            for q in record.findall(".//AllowableQualifier")
        ]

        output += f"### {name} [{ui}]\n"
        if scope:
            output += f"**Definição:** {scope[:300]}{'...' if len(scope)>300 else ''}\n\n"
        if entry_terms:
            output += f"**Entry Terms (sinônimos):** {', '.join(entry_terms[:8])}\n"
        if tree_nums:
            output += f"**Hierarquia MeSH:** {', '.join(tree_nums[:5])}\n"
        if qualifiers:
            output += f"**Subheadings:** {', '.join(q for q in qualifiers[:8] if q)}\n"

        # Sugere query PubMed
        output += f"\n**💡 Query PubMed sugerida:**\n"
        output += f"```\n\"{name}\"[MeSH Terms]\n```\n"
        if entry_terms:
            output += f"**Ou com sinônimos:**\n"
            output += f"```\n(\"{name}\"[MeSH Terms] OR \"{name}\"[All Fields])\n```\n"
        output += "\n---\n\n"

    return output


# ─────────────────────────────────────────
# 20. TRANSLATE QUERY — pergunta clínica → PubMed query
# ─────────────────────────────────────────

@mcp.tool()
async def translate_query(clinical_question: str) -> str:
    """
    Converte uma pergunta clínica em linguagem natural em query PubMed otimizada.
    Usa Claude para estruturar em formato PICO + MeSH.

    Args:
        clinical_question: Pergunta em linguagem natural
                          (ex: 'Qual o melhor tratamento para carcinoma basocelular superficial em pacientes imunocomprometidos?')
    """
    system_prompt = """You are an expert medical librarian specialized in PubMed search strategy.
Convert the clinical question into an optimized PubMed search query.
Return ONLY the following structured markdown (no extra text):

## Clinical Question Analysis
Brief PICO breakdown

## PubMed Query (Simple)
A basic query for quick searching

## PubMed Query (Advanced)
A comprehensive query with MeSH terms, Boolean operators, and filters

## Suggested Filters
List relevant PubMed filters (publication type, date range, species, etc.)

## Alternative Search Terms
Other relevant terms to consider

Use proper PubMed syntax: MeSH[MeSH Terms], [tiab], AND, OR, NOT, quotation marks.
"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": clinical_question}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        block.get("text","") for block in data.get("content",[])
        if block.get("type") == "text"
    )
    return f"## PubMed Query Builder\n**Pergunta:** {clinical_question}\n\n{text}"


# ─────────────────────────────────────────
# 21. SUMMARIZE PAPERS — síntese com Claude
# ─────────────────────────────────────────

@mcp.tool()
async def summarize_papers(abstracts: list[str], focus: Optional[str] = None) -> str:
    """
    Sintetiza múltiplos abstracts em um resumo estruturado usando Claude.
    Útil após uma busca para consolidar a evidência rapidamente.

    Args:
        abstracts: Lista de abstracts (máx 10)
        focus: Foco específico da síntese (ex: 'eficácia', 'segurança', 'metodologia')
    """
    if not abstracts:
        return "Nenhum abstract fornecido."

    abstracts = abstracts[:10]
    focus_instruction = f"Focus especially on: {focus}." if focus else ""

    combined = "\n\n---\n\n".join(
        f"**Abstract {i+1}:**\n{ab}" for i, ab in enumerate(abstracts)
    )

    system_prompt = f"""You are a clinical research assistant. Synthesize the provided abstracts into a structured evidence summary.
{focus_instruction}
Return ONLY structured markdown with:

## Evidence Summary
Overall synthesis of findings

## Key Findings
Bullet points of main results

## Agreements Across Studies
What the studies agree on

## Contradictions or Gaps
Discrepancies or missing evidence

## Clinical Implications
Practical takeaways for clinical practice

## Evidence Quality
Brief assessment of overall evidence quality

Be concise, precise, and clinically relevant.
"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "system": system_prompt,
                "messages": [{"role": "user", "content": combined}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        block.get("text","") for block in data.get("content",[])
        if block.get("type") == "text"
    )

    return (
        f"## Síntese de {len(abstracts)} Artigos\n"
        f"{'*Foco: ' + focus + '*' if focus else ''}\n\n"
        + text
    )


# ─────────────────────────────────────────
# CACHE (in-memory com TTL)
# ─────────────────────────────────────────

import time as _time
from functools import wraps

_cache: dict = {}
_CACHE_TTL = 3600  # 1 hora

def _cache_key(*args, **kwargs) -> str:
    return str(args) + str(sorted(kwargs.items()))

def cached(fn):
    """Decorator: cache in-memory com TTL de 1 hora."""
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        key = fn.__name__ + _cache_key(*args, **kwargs)
        if key in _cache:
            result, ts = _cache[key]
            if _time.time() - ts < _CACHE_TTL:
                return f"*(cached)*\n\n{result}"
        result = await fn(*args, **kwargs)
        _cache[key] = (result, _time.time())
        return result
    return wrapper


# ─────────────────────────────────────────
# 22. RANK EVIDENCE
# ─────────────────────────────────────────

EVIDENCE_HIERARCHY = {
    "Meta-Analysis": 7,
    "Systematic Review": 6,
    "Randomized Controlled Trial": 5,
    "Clinical Trial": 4,
    "Controlled Clinical Trial": 4,
    "Multicenter Study": 3,
    "Observational Study": 2,
    "Cohort Study": 2,
    "Case-Control Study": 2,
    "Case Reports": 1,
    "Review": 1,
    "Editorial": 0,
    "Letter": 0,
}

@mcp.tool()
async def rank_evidence(
    identifiers: list[str],
    include_journal_impact: bool = True
) -> str:
    """
    Ranqueia artigos por força de evidência combinando:
    hierarquia de desenho de estudo + citações + fator de impacto do journal.
    Retorna tabela ordenada do mais forte para o mais fraco.

    Args:
        identifiers: Lista de PMIDs ou DOIs (até 20)
        include_journal_impact: Incluir IF do journal no score (requer OpenAlex)
    """
    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY:
        base_params["api_key"] = PUBMED_API_KEY

    identifiers = identifiers[:20]

    # Resolve DOIs para PMIDs
    pmids = []
    doi_map = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for ident in identifiers:
            ident = ident.strip().lstrip("https://doi.org/")
            if ident.startswith("10."):
                r = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={**base_params, "db": "pubmed",
                            "term": f"{ident}[doi]", "retmode": "json"}
                )
                ids = r.json().get("esearchresult",{}).get("idlist",[])
                if ids:
                    pmids.append(ids[0])
                    doi_map[ids[0]] = ident
            else:
                pmids.append(ident)

        if not pmids:
            return "Nenhum artigo válido encontrado."

        # Fetch detalhes PubMed
        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={**base_params, "db": "pubmed",
                    "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"}
        )
        r.raise_for_status()

    root = ET.fromstring(r.text)
    articles_data = []

    for article in root.findall(".//PubmedArticle"):
        pmid    = article.findtext(".//PMID","")
        title   = article.findtext(".//ArticleTitle","").strip()
        year    = article.findtext(".//PubDate/Year","") or \
                  (article.findtext(".//PubDate/MedlineDate","") or "")[:4]
        journal = article.findtext(".//Journal/ISOAbbreviation","") or \
                  article.findtext(".//Journal/Title","")

        # Tipo de estudo → score hierárquico
        pub_types = [pt.text for pt in article.findall(".//PublicationType") if pt.text]
        evidence_score = 0
        evidence_label = "Unknown"
        for pt in pub_types:
            score = EVIDENCE_HIERARCHY.get(pt, -1)
            if score > evidence_score:
                evidence_score = score
                evidence_label = pt

        doi = doi_map.get(pmid,"")
        for eid in article.findall(".//ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""

        articles_data.append({
            "pmid": pmid, "title": title, "year": year,
            "journal": journal, "doi": doi,
            "pub_types": pub_types, "evidence_score": evidence_score,
            "evidence_label": evidence_label,
            "citations": 0, "if2yr": 0.0
        })

    # Enriquece com citações e IF via Semantic Scholar
    if articles_data:
        async with httpx.AsyncClient(timeout=30) as client:
            for item in articles_data:
                if item["doi"]:
                    try:
                        r = await client.get(
                            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{item['doi']}",
                            params={"fields": "citationCount"}
                        )
                        if r.status_code == 200:
                            item["citations"] = r.json().get("citationCount", 0) or 0
                    except Exception:
                        pass

                if include_journal_impact and item["journal"]:
                    try:
                        r2 = await client.get(
                            "https://api.openalex.org/sources",
                            params={"search": item["journal"], "per-page": 1,
                                    "select": "summary_stats", "mailto": PUBMED_EMAIL}
                        )
                        if r2.status_code == 200:
                            results = r2.json().get("results",[])
                            if results:
                                stats = results[0].get("summary_stats") or {}
                                item["if2yr"] = stats.get("2yr_mean_citedness", 0.0) or 0.0
                    except Exception:
                        pass

    # Score composto: evidência (0-7) × 40 + log(citações+1) × 30 + IF × 30
    for item in articles_data:
        item["composite_score"] = (
            item["evidence_score"] * 40 +
            math.log(item["citations"] + 1) * 30 +
            min(item["if2yr"], 20) * 30
        )

    articles_data.sort(key=lambda x: x["composite_score"], reverse=True)

    level_labels = {7:"🥇 Meta-Analysis", 6:"🥈 Systematic Review",
                    5:"🥉 RCT", 4:"🔵 Clinical Trial",
                    3:"🟢 Multicenter", 2:"🟡 Observational",
                    1:"🟠 Review/Case", 0:"⚪ Editorial/Letter"}

    output  = f"## Evidence Ranking — {len(articles_data)} artigos\n\n"
    output += "| # | Título | Ano | Design | Citações | IF | Score |\n"
    output += "|---|--------|-----|--------|----------|-----|-------|\n"
    for i, item in enumerate(articles_data, 1):
        short_title = item["title"][:55] + ("..." if len(item["title"])>55 else "")
        level       = level_labels.get(item["evidence_score"], "❓")
        link        = f"[PubMed](https://pubmed.ncbi.nlm.nih.gov/{item['pmid']}/)"
        output += (f"| {i} | {short_title} {link} | {item['year']} | "
                   f"{level} | {item['citations']:,} | "
                   f"{item['if2yr']:.1f} | {item['composite_score']:.0f} |\n")

    output += "\n**Score = Desenho×40 + log(Citações)×30 + IF×30**\n"
    return output


# ─────────────────────────────────────────
# 23. COMPARE PAPERS
# ─────────────────────────────────────────

@mcp.tool()
async def compare_papers(
    identifiers: list[str],
    comparison_focus: Optional[str] = None
) -> str:
    """
    Gera tabela comparativa estruturada entre múltiplos artigos usando Claude.
    Compara população, intervenção, outcomes, limitações e qualidade metodológica.

    Args:
        identifiers: Lista de PMIDs ou DOIs (2-8 artigos)
        comparison_focus: Aspecto específico a comparar (ex: 'efficacy', 'safety', 'methodology')
    """
    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY:
        base_params["api_key"] = PUBMED_API_KEY

    identifiers = identifiers[:8]

    # Fetch abstracts
    pmids = []
    async with httpx.AsyncClient(timeout=30) as client:
        for ident in identifiers:
            ident = ident.strip().lstrip("https://doi.org/")
            if ident.startswith("10."):
                r = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={**base_params, "db": "pubmed",
                            "term": f"{ident}[doi]", "retmode": "json"}
                )
                ids = r.json().get("esearchresult",{}).get("idlist",[])
                if ids: pmids.append(ids[0])
            else:
                pmids.append(ident)

        if not pmids:
            return "Nenhum artigo válido."

        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={**base_params, "db": "pubmed", "id": ",".join(pmids),
                    "retmode": "xml", "rettype": "abstract"}
        )
        r.raise_for_status()

    root = ET.fromstring(r.text)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        pmid  = article.findtext(".//PMID","")
        title = article.findtext(".//ArticleTitle","").strip()
        year  = article.findtext(".//PubDate/Year","")
        authors = []
        for a in article.findall(".//Author")[:2]:
            last = a.findtext("LastName","")
            if last: authors.append(last)
        abstract_parts = article.findall(".//AbstractText")
        abstract = " ".join(
            (f"[{p.get('Label')}] " if p.get('Label') else "") + (p.text or "")
            for p in abstract_parts
        )
        papers.append({"pmid": pmid, "title": title, "year": year,
                       "authors": authors, "abstract": abstract[:1500]})

    if not papers:
        return "Não foi possível recuperar os artigos."

    focus_instruction = f"Focus the comparison on: {comparison_focus}." if comparison_focus else ""
    papers_text = "\n\n---\n\n".join(
        f"**Paper {i+1}: {p['title']} ({p['year']}) — PMID {p['pmid']}**\n{p['abstract']}"
        for i, p in enumerate(papers)
    )

    system_prompt = f"""You are a systematic review expert. Compare the provided papers and return ONLY structured markdown.
{focus_instruction}
Use this exact structure:

## Comparison Table
A markdown table with columns: Paper | Authors (Year) | Study Design | Population | Intervention | Control | Primary Outcome | Result | Sample Size | Follow-up | Limitations

## Agreements
What the studies consistently show

## Contradictions
Where the studies disagree and possible reasons

## Methodological Quality
Brief assessment of each paper's strengths and weaknesses

## Overall Evidence Synthesis
2-3 sentence clinical bottom line

Be precise. Use the table format strictly.
"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": papers_text}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        block.get("text","") for block in data.get("content",[])
        if block.get("type") == "text"
    )

    header = f"## Comparação de {len(papers)} Artigos\n"
    if comparison_focus: header += f"*Foco: {comparison_focus}*\n"
    header += "\n"
    return header + text


# ─────────────────────────────────────────
# 24. EXPORT TO RIS (Zotero, Mendeley, EndNote)
# ─────────────────────────────────────────

@mcp.tool()
async def export_to_ris(dois: list[str]) -> str:
    """
    Exporta artigos em formato RIS — importável diretamente no Zotero,
    Mendeley, EndNote e outros gestores bibliográficos.

    Args:
        dois: Lista de DOIs (até 20)
    """
    async def fetch_work(doi: str) -> dict:
        doi = doi.strip().lstrip("https://doi.org/")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.crossref.org/works/{doi}",
                params={"mailto": PUBMED_EMAIL}
            )
            if r.status_code == 200:
                return r.json().get("message",{})
        return {}

    works = await asyncio.gather(*[fetch_work(doi) for doi in dois[:20]])

    type_map = {
        "journal-article": "JOUR",
        "book-chapter":    "CHAP",
        "book":            "BOOK",
        "proceedings-article": "CONF",
        "posted-content":  "UNPB",
        "review":          "JOUR",
        "report":          "RPRT",
    }

    ris_entries = []
    for work in works:
        if not work: continue
        work_type = work.get("type","journal-article")
        ris_type  = type_map.get(work_type, "JOUR")
        title     = (work.get("title") or [""])[0]
        journal   = (work.get("container-title") or [""])[0]
        short_j   = (work.get("short-container-title") or [""])[0]
        doi       = work.get("DOI","")
        volume    = work.get("volume","")
        issue     = work.get("issue","")
        pages     = work.get("page","")
        publisher = work.get("publisher","")
        abstract  = work.get("abstract","")

        pub_date  = work.get("published") or work.get("published-print") or {}
        date_parts = (pub_date.get("date-parts") or [[""]])[0]
        year  = str(date_parts[0]) if date_parts else ""
        month = str(date_parts[1]).zfill(2) if len(date_parts) > 1 else ""
        day   = str(date_parts[2]).zfill(2) if len(date_parts) > 2 else ""
        date_str = f"{year}/{month}/{day}/" if month else f"{year}///"

        authors = work.get("author",[])

        lines = [f"TY  - {ris_type}"]
        for a in authors:
            family = a.get("family","")
            given  = a.get("given","")
            if family: lines.append(f"AU  - {family}, {given}".strip(", "))
        lines.append(f"TI  - {title}")
        if journal: lines.append(f"JO  - {journal}")
        if short_j: lines.append(f"J2  - {short_j}")
        if year:    lines.append(f"PY  - {year}")
        if date_str.strip("/"): lines.append(f"DA  - {date_str}")
        if volume:  lines.append(f"VL  - {volume}")
        if issue:   lines.append(f"IS  - {issue}")
        if pages:
            parts = pages.split("-")
            lines.append(f"SP  - {parts[0]}")
            if len(parts) > 1: lines.append(f"EP  - {parts[1]}")
        if doi:       lines.append(f"DO  - {doi}")
        if doi:       lines.append(f"UR  - https://doi.org/{doi}")
        if publisher: lines.append(f"PB  - {publisher}")
        if abstract:  lines.append(f"AB  - {abstract[:500]}")
        lines.append("ER  - ")
        ris_entries.append("\n".join(lines))

    if not ris_entries:
        return "Nenhum artigo encontrado para exportar."

    ris_content = "\n\n".join(ris_entries)
    output  = f"## Exportação RIS — {len(ris_entries)} artigos\n\n"
    output += "Copia o conteúdo abaixo e salva como `references.ris`.\n"
    output += "Importa no Zotero: **File → Import → RIS**\n\n"
    output += f"```ris\n{ris_content}\n```"
    return output


# ─────────────────────────────────────────
# 25. EXPORT TO CSV
# ─────────────────────────────────────────

@mcp.tool()
async def export_to_csv(
    query: str,
    max_results: int = 20,
    year_from: Optional[int] = None
) -> str:
    """
    Busca artigos e exporta resultado em CSV estruturado.
    Pronto para importar no Rayyan, Excel, ou qualquer gestor de revisão sistemática.
    Inclui: título, autores, ano, journal, DOI, citações, IF, PMID, abstract.

    Args:
        query: Termos de pesquisa
        max_results: Número de artigos (máx 50)
        year_from: Filtrar a partir deste ano
    """

    # Busca PubMed
    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY:
        base_params["api_key"] = PUBMED_API_KEY

    search_q = query
    if year_from: search_q += f" AND {year_from}:3000[dp]"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={**base_params, "db": "pubmed", "term": search_q,
                    "retmax": min(max_results, 50), "retmode": "json"}
        )
        r.raise_for_status()
        ids = r.json().get("esearchresult",{}).get("idlist",[])

        if not ids:
            return f"Nenhum resultado para '{query}'."

        r2 = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={**base_params, "db": "pubmed", "id": ",".join(ids),
                    "retmode": "xml", "rettype": "abstract"}
        )
        r2.raise_for_status()

    root = ET.fromstring(r2.text)
    rows = []

    for article in root.findall(".//PubmedArticle"):
        pmid    = article.findtext(".//PMID","")
        title   = article.findtext(".//ArticleTitle","").strip()
        year    = article.findtext(".//PubDate/Year","") or \
                  (article.findtext(".//PubDate/MedlineDate","") or "")[:4]
        journal = article.findtext(".//Journal/Title","")
        volume  = article.findtext(".//Volume","")
        issue   = article.findtext(".//Issue","")
        pages   = article.findtext(".//MedlinePgn","")

        authors = []
        for a in article.findall(".//Author"):
            last = a.findtext("LastName","")
            first = a.findtext("ForeName","")
            if last: authors.append(f"{last} {first}".strip())

        abstract_parts = article.findall(".//AbstractText")
        abstract = " ".join(p.text or "" for p in abstract_parts)

        doi = ""
        for eid in article.findall(".//ArticleId"):
            if eid.get("IdType") == "doi": doi = eid.text or ""

        pub_types = [pt.text for pt in article.findall(".//PublicationType") if pt.text]
        relevant = [pt for pt in pub_types if pt in (
            "Randomized Controlled Trial","Systematic Review",
            "Meta-Analysis","Review","Clinical Trial","Case Reports"
        )]

        rows.append({
            "PMID": pmid,
            "Title": title,
            "Authors": "; ".join(authors[:6]),
            "Year": year,
            "Journal": journal,
            "Volume": volume,
            "Issue": issue,
            "Pages": pages,
            "DOI": doi,
            "PubMed_URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "Study_Type": "; ".join(relevant),
            "Abstract": abstract[:800],
        })

    # Enriquece com citações via Semantic Scholar (em batch)
    doi_list = [r["DOI"] for r in rows if r["DOI"]]
    if doi_list:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                r3 = await client.post(
                    "https://api.semanticscholar.org/graph/v1/paper/batch",
                    json={"ids": [f"DOI:{d}" for d in doi_list[:20]]},
                    params={"fields": "citationCount,externalIds"}
                )
                if r3.status_code == 200:
                    s2_papers = r3.json()
                    doi_citations = {}
                    for p in s2_papers:
                        if p and p.get("externalIds"):
                            pdoi = (p["externalIds"].get("DOI") or "").lower()
                            doi_citations[pdoi] = p.get("citationCount", 0) or 0
                    for row in rows:
                        row["Citations"] = doi_citations.get(row["DOI"].lower(), "")
            except Exception:
                for row in rows: row["Citations"] = ""
    else:
        for row in rows: row["Citations"] = ""

    # Gera CSV
    fieldnames = ["PMID","Title","Authors","Year","Journal","Volume","Issue",
                  "Pages","DOI","PubMed_URL","Study_Type","Citations","Abstract"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    csv_content = buf.getvalue()

    output  = f"## Exportação CSV — '{query}'\n"
    output += f"*{len(rows)} artigos | Pronto para Rayyan, Excel, Zotero*\n\n"
    output += "Salva o conteúdo abaixo como `results.csv`:\n\n"
    output += f"```csv\n{csv_content}\n```"
    return output


# ─────────────────────────────────────────
# 26. ARXIV SEARCH
# ─────────────────────────────────────────

@mcp.tool()
async def search_arxiv(
    query: str,
    max_results: int = 10,
    category: Optional[str] = None,
    year_from: Optional[int] = None,
) -> str:
    """
    Busca preprints e artigos no arXiv. Especialmente útil para:
    - IA/ML aplicada a dermatologia (diagnóstico, dermatoscopia, patologia computacional)
    - Física médica, bioinformática, genômica cutânea
    - Artigos que aparecem primeiro no arXiv antes de serem publicados

    Args:
        query: Termos de busca (ex: 'deep learning dermatoscopy melanoma')
        max_results: Número de resultados (máx 50)
        category: Categoria arXiv (ex: 'cs.CV', 'q-bio.GN', 'eess.IV', 'stat.ML')
        year_from: Filtrar a partir deste ano
    """
    search_query = query
    if category:
        search_query = f"cat:{category} AND ({query})"

    params = {
        "search_query": f"all:{search_query}",
        "start": 0,
        "max_results": min(max_results, 50),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    if year_from:
        # arXiv date filter via query
        params["search_query"] += f" AND submittedDate:[{year_from}01010000 TO 99991231235959]"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://export.arxiv.org/api/query",
            params=params
        )
        r.raise_for_status()

    # Parse Atom XML
    ns = {
        "atom":    "http://www.w3.org/2005/Atom",
        "arxiv":   "http://arxiv.org/schemas/atom",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/"
    }
    root = ET.fromstring(r.text)
    entries = root.findall("atom:entry", ns)

    if not entries:
        return f"Nenhum resultado no arXiv para: '{query}'"

    total = root.findtext("opensearch:totalResults", "?", ns)
    output  = f"## arXiv — '{query}'\n"
    output += f"*{len(entries)} de {total} resultados* 🔶 *Preprints — não peer-reviewed*\n\n"

    for i, entry in enumerate(entries, 1):
        title    = (entry.findtext("atom:title", "", ns) or "").replace("\n", " ").strip()
        abstract = (entry.findtext("atom:summary", "", ns) or "").replace("\n", " ").strip()[:400]
        published = entry.findtext("atom:published", "", ns)[:10]  # YYYY-MM-DD
        updated   = entry.findtext("atom:updated", "", ns)[:10]
        arxiv_id  = entry.findtext("atom:id", "", ns).split("/abs/")[-1]

        authors = []
        for a in entry.findall("atom:author", ns)[:3]:
            name = a.findtext("atom:name", "", ns)
            if name: authors.append(name)
        if len(entry.findall("atom:author", ns)) > 3:
            authors.append("et al.")

        # Categories
        cats = [
            tag.get("term","") for tag in entry.findall("atom:category", ns)
        ]
        primary_cat = cats[0] if cats else ""

        # DOI se já publicado
        doi_el = entry.find("arxiv:doi", ns)
        doi = doi_el.text if doi_el is not None else ""

        # Journal se já publicado
        journal_el = entry.find("arxiv:journal_ref", ns)
        journal = journal_el.text if journal_el is not None else ""

        output += f"### {i}. {title}\n"
        output += f"🔶 **arXiv:{arxiv_id}** | {published}"
        if updated != published: output += f" (updated {updated})"
        output += "\n"
        output += f"**Autores:** {', '.join(authors)}\n"
        if primary_cat: output += f"**Categoria:** {primary_cat}\n"
        if journal:     output += f"**Publicado em:** {journal}\n"
        if doi:         output += f"**DOI:** https://doi.org/{doi}\n"
        output += f"**arXiv:** https://arxiv.org/abs/{arxiv_id}\n"
        output += f"**PDF:** https://arxiv.org/pdf/{arxiv_id}\n"
        if abstract:    output += f"**Abstract:** {abstract}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 27. CORE SEARCH — repositórios OA institucionais
# ─────────────────────────────────────────

@mcp.tool()
async def search_core(
    query: str,
    max_results: int = 10,
    year_from: Optional[int] = None,
    open_access_only: bool = True,
) -> str:
    """
    Busca no CORE.ac.uk — 200M+ artigos open access de repositórios institucionais.
    Encontra artigos que não estão no PubMed: teses, relatórios, versões de autor,
    literatura cinzenta e artigos de países sub-representados nas grandes bases.

    Args:
        query: Termos de busca
        max_results: Número de resultados (máx 50)
        year_from: Filtrar a partir deste ano
        open_access_only: Apenas artigos com PDF gratuito (padrão True)
    """
    # CORE API v3 — gratuita sem autenticação (rate limited)
    params = {
        "q": query,
        "limit": min(max_results, 50),
        "sort": "relevance",
        "stats": "false",
    }
    if open_access_only:
        params["q"] += " AND (fullText:true)"
    if year_from:
        params["q"] += f" AND yearPublished:>={year_from}"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.core.ac.uk/v3/search/works",
            params=params,
            headers={"Accept": "application/json"}
        )

        # CORE v3 pode requerer API key para alguns endpoints
        if r.status_code == 401:
            # Fallback: CORE v2 sem autenticação
            r = await client.get(
                "https://core.ac.uk/api-v2/search",
                params={"q": query, "pageSize": min(max_results, 50),
                        "page": 1, "stats": "false"}
            )

        r.raise_for_status()
        data = r.json()

    # Handle both v2 and v3 response formats
    results = data.get("results", data.get("data", []))

    if not results:
        return f"Nenhum resultado no CORE para: '{query}'"

    output  = f"## CORE.ac.uk — '{query}'\n"
    output += f"*{len(results)} resultados | Repositórios OA institucionais*\n\n"

    for i, item in enumerate(results, 1):
        # Handle v2/v3 field differences
        title     = item.get("title","") or item.get("name","") or ""
        year      = item.get("yearPublished","") or item.get("year","") or ""
        doi       = item.get("doi","") or ""
        pdf_url   = item.get("downloadUrl","") or item.get("fullTextUrl","") or ""
        abstract  = (item.get("abstract","") or "")[:400]
        publisher = item.get("publisher","") or ""
        journal   = item.get("journals",[{}])[0].get("title","") if item.get("journals") else ""

        authors_raw = item.get("authors", [])
        if authors_raw and isinstance(authors_raw[0], dict):
            authors = ", ".join(a.get("name","") for a in authors_raw[:3])
        elif authors_raw and isinstance(authors_raw[0], str):
            authors = ", ".join(authors_raw[:3])
        else:
            authors = ""
        if len(authors_raw) > 3: authors += " et al."

        core_id = item.get("id","") or item.get("coreId","")

        output += f"### {i}. {title} ({year})\n"
        if authors:   output += f"**Autores:** {authors}\n"
        if journal:   output += f"**Journal:** {journal}\n"
        elif publisher: output += f"**Publisher:** {publisher}\n"
        if doi:       output += f"**DOI:** https://doi.org/{doi}\n"
        if pdf_url:   output += f"**PDF:** {pdf_url}\n"
        if core_id:   output += f"**CORE:** https://core.ac.uk/works/{core_id}\n"
        if abstract:  output += f"**Abstract:** {abstract}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 28. DOWNLOAD WITH FALLBACK
# ─────────────────────────────────────────

@mcp.tool()
async def download_paper(doi: str) -> str:
    """
    Tenta obter o PDF de um artigo tentando múltiplas fontes gratuitas e legais
    em sequência até encontrar um link funcional.

    Cadeia de fallback (ordem):
    1. Unpaywall (melhor link OA verificado)
    2. PubMed Central (PMC)
    3. Europe PMC
    4. CORE.ac.uk
    5. OpenAIRE
    6. Semantic Scholar
    7. arXiv (se for preprint)

    Args:
        doi: DOI do artigo (ex: '10.1016/j.jaad.2023.01.001')
    """
    doi = doi.strip().lstrip("https://doi.org/")
    found_links = []
    tried = []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:

        # 1. Unpaywall
        tried.append("Unpaywall")
        try:
            r = await client.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": PUBMED_EMAIL}
            )
            if r.status_code == 200:
                data = r.json()
                title = data.get("title","")
                year  = data.get("year","")
                best  = data.get("best_oa_location") or {}
                best_url = best.get("url","")
                version  = best.get("version","")
                if best_url:
                    found_links.append({
                        "source": "Unpaywall",
                        "url": best_url,
                        "version": version,
                        "quality": "high"
                    })
                # Collect all OA locations
                for loc in (data.get("oa_locations") or []):
                    url = loc.get("url","")
                    if url and url != best_url:
                        found_links.append({
                            "source": f"Unpaywall ({loc.get('host_type','')})",
                            "url": url,
                            "version": loc.get("version",""),
                            "quality": "medium"
                        })
        except Exception:
            pass

        # 2. PubMed Central
        tried.append("PubMed Central")
        try:
            base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
            r = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={**base_params, "db": "pmc",
                        "term": f"{doi}[doi]", "retmode": "json"}
            )
            if r.status_code == 200:
                pmc_ids = r.json().get("esearchresult",{}).get("idlist",[])
                if pmc_ids:
                    pmc_id = pmc_ids[0]
                    pmc_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_id}/"
                    pdf_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_id}/pdf/"
                    found_links.append({
                        "source": "PubMed Central",
                        "url": pmc_url,
                        "pdf": pdf_url,
                        "version": "publishedVersion",
                        "quality": "high"
                    })
        except Exception:
            pass

        # 3. Europe PMC
        tried.append("Europe PMC")
        try:
            r = await client.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={"query": f"DOI:{doi}", "format": "json",
                        "pageSize": 1, "resultType": "core"}
            )
            if r.status_code == 200:
                articles = r.json().get("resultList",{}).get("result",[])
                if articles:
                    a = articles[0]
                    pmid = a.get("pmid","")
                    has_ft = a.get("hasPDF","N") == "Y" or a.get("hasTextMinedTerms","N") == "Y"
                    if has_ft and pmid:
                        found_links.append({
                            "source": "Europe PMC",
                            "url": f"https://europepmc.org/article/MED/{pmid}",
                            "version": "publishedVersion",
                            "quality": "high"
                        })
        except Exception:
            pass

        # 4. CORE
        tried.append("CORE")
        try:
            r = await client.get(
                "https://api.core.ac.uk/v3/search/works",
                params={"q": f"doi:{doi}", "limit": 1}
            )
            if r.status_code == 200:
                results = r.json().get("results",[])
                if results:
                    pdf = results[0].get("downloadUrl","") or results[0].get("fullTextUrl","")
                    core_id = results[0].get("id","")
                    if pdf:
                        found_links.append({
                            "source": "CORE",
                            "url": pdf,
                            "version": "acceptedVersion",
                            "quality": "medium"
                        })
        except Exception:
            pass

        # 5. OpenAIRE
        tried.append("OpenAIRE")
        try:
            r = await client.get(
                "https://api.openaire.eu/search/publications",
                params={"doi": doi, "format": "json", "size": 1}
            )
            if r.status_code == 200:
                data = r.json()
                results = data.get("response",{}).get("results",{}).get("result",[])
                if results:
                    metadata = results[0].get("metadata",{})
                    oaf = metadata.get("oaf:entity",{}).get("oaf:result",{})
                    instances = oaf.get("children",{}).get("instance",[])
                    if not isinstance(instances, list): instances = [instances]
                    for inst in instances:
                        url = inst.get("webresource",{}).get("url","")
                        if url and "pdf" in url.lower():
                            found_links.append({
                                "source": "OpenAIRE",
                                "url": url,
                                "version": "acceptedVersion",
                                "quality": "medium"
                            })
                            break
        except Exception:
            pass

        # 6. Semantic Scholar
        tried.append("Semantic Scholar")
        try:
            r = await client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                params={"fields": "openAccessPdf,title"}
            )
            if r.status_code == 200:
                data = r.json()
                pdf = (data.get("openAccessPdf") or {}).get("url","")
                if pdf:
                    found_links.append({
                        "source": "Semantic Scholar",
                        "url": pdf,
                        "version": "publishedVersion",
                        "quality": "high"
                    })
        except Exception:
            pass

        # 7. arXiv (se o DOI apontar para arXiv)
        tried.append("arXiv")
        try:
            r = await client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": f"doi:{doi}", "max_results": 1}
            )
            if r.status_code == 200:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                root = ET.fromstring(r.text)
                entries = root.findall("atom:entry", ns)
                if entries:
                    arxiv_id = entries[0].findtext("atom:id","",ns).split("/abs/")[-1]
                    if arxiv_id:
                        found_links.append({
                            "source": "arXiv",
                            "url": f"https://arxiv.org/abs/{arxiv_id}",
                            "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
                            "version": "submittedVersion",
                            "quality": "medium"
                        })
        except Exception:
            pass

    version_labels = {
        "publishedVersion": "✅ Versão publicada",
        "acceptedVersion":  "📄 Post-print (accepted)",
        "submittedVersion": "🔶 Pre-print (submitted)",
    }

    if not found_links:
        output  = f"## ❌ PDF não encontrado\n\n"
        output += f"**DOI:** https://doi.org/{doi}\n\n"
        output += f"Tentativas: {', '.join(tried)}\n\n"
        output += "**Alternativas:**\n"
        output += "- Solicitar ao autor via ResearchGate ou email institucional\n"
        output += "- Verificar acesso via instituição\n"
        output += f"- Buscar título no Google Scholar\n"
        return output

    # Deduplica e prioriza por qualidade
    seen_urls = set()
    unique_links = []
    for link in found_links:
        url = link.get("url","")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_links.append(link)

    output  = f"## ✅ PDF encontrado — {len(unique_links)} fonte(s)\n\n"
    output += f"**DOI:** https://doi.org/{doi}\n\n"

    for i, link in enumerate(unique_links, 1):
        version = version_labels.get(link.get("version",""), link.get("version",""))
        output += f"### {i}. {link['source']}\n"
        output += f"**Link:** {link['url']}\n"
        if link.get("pdf") and link["pdf"] != link["url"]:
            output += f"**PDF direto:** {link['pdf']}\n"
        output += f"**Versão:** {version}\n\n"

    return output


# ─────────────────────────────────────────
# 29. ASSESS RISK OF BIAS (RoB 2 / ROBINS-I)
# ─────────────────────────────────────────

@mcp.tool()
async def assess_risk_of_bias(
    abstract: str,
    study_design: str = "auto"
) -> str:
    """
    Avalia risco de viés usando RoB 2 (RCTs) ou ROBINS-I (estudos observacionais)
    via Claude. Retorna avaliação por domínio com justificativa.

    Args:
        abstract: Texto do abstract (ou methods section se disponível)
        study_design: 'rct', 'observational', ou 'auto' (Claude detecta)
    """
    system_prompt = """You are a systematic review methodologist expert in risk of bias assessment.
Analyze the provided abstract and assess risk of bias.

First, determine the study design. Then apply the appropriate tool:
- RCTs → Cochrane RoB 2 tool (5 domains)
- Non-randomized studies → ROBINS-I tool (7 domains)
- Other designs → note limitations using appropriate framework

Return ONLY structured markdown:

## Study Design Detected
[State the design clearly]

## Risk of Bias Assessment
### [Tool Used: RoB 2 / ROBINS-I / Other]

For each domain, provide:
**Domain X: [Domain Name]**
- Judgment: [Low / Some concerns / High / Critical / NI (No Information)]
- Key signals: [Specific methodological elements supporting this judgment]

## Overall Risk of Bias
[Low / Moderate / Serious / Critical] — with one-sentence rationale

## Caveats
Note if full-text access would change the assessment.
Note any domain where NI was assigned due to limited abstract reporting.

Be precise. Do not inflate or deflate risk based on impact factor or conclusions."""

    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1200,
                "system": system_prompt,
                "messages": [{"role": "user", "content": abstract}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        b.get("text","") for b in data.get("content",[]) if b.get("type") == "text"
    )
    return f"## Risk of Bias Assessment\n*Based on abstract — full-text assessment recommended*\n\n{text}"


# ─────────────────────────────────────────
# 30. GRADE EVIDENCE BODY
# ─────────────────────────────────────────

@mcp.tool()
async def grade_evidence_body(
    abstracts: list[str],
    clinical_question: str,
    outcome: str
) -> str:
    """
    Aplica o framework GRADE a um corpo de evidências para uma pergunta e desfecho específicos.
    Avalia: risco de viés, inconsistência, imprecisão, evidência indireta, viés de publicação.

    Args:
        abstracts: Lista de abstracts dos estudos incluídos (2-10)
        clinical_question: Pergunta clínica estruturada (PICO)
        outcome: Desfecho específico sendo avaliado
    """
    abstracts = abstracts[:10]
    papers_text = "\n\n---\n\n".join(
        f"Study {i+1}:\n{ab}" for i, ab in enumerate(abstracts)
    )

    system_prompt = f"""You are a GRADE methodology expert.
Apply the GRADE framework to assess the certainty of evidence for:
Clinical question: {clinical_question}
Outcome: {outcome}

Evaluate all provided studies as a body of evidence.

Return ONLY structured markdown:

## Evidence Profile
**Clinical question:** {clinical_question}
**Outcome:** {outcome}
**Number of studies:** [n]
**Study designs:** [list]

## GRADE Domains

### 1. Risk of Bias
- Assessment: [Not serious / Serious / Very serious]
- Rationale: [specific methodological concerns across studies]

### 2. Inconsistency
- Assessment: [Not serious / Serious / Very serious]
- Rationale: [heterogeneity in results, I² if reported, direction of effects]

### 3. Indirectness
- Assessment: [Not serious / Serious / Very serious]
- Rationale: [population, intervention, comparator, outcome differences]

### 4. Imprecision
- Assessment: [Not serious / Serious / Very serious]
- Rationale: [sample sizes, confidence intervals, optimal information size]

### 5. Publication Bias
- Assessment: [Undetected / Suspected / Strongly suspected]
- Rationale: [funnel plot asymmetry, registered protocols, industry funding]

## Overall Certainty of Evidence
**⊕⊕⊕⊕ HIGH / ⊕⊕⊕◯ MODERATE / ⊕⊕◯◯ LOW / ⊕◯◯◯ VERY LOW**

## Implications
- For practice: [what clinicians should do with this evidence]
- For research: [what future research is needed]"""

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "system": system_prompt,
                "messages": [{"role": "user", "content": papers_text}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        b.get("text","") for b in data.get("content",[]) if b.get("type") == "text"
    )
    return f"## GRADE Assessment\n*{len(abstracts)} studies | Outcome: {outcome}*\n\n{text}"


# ─────────────────────────────────────────
# 31. EXTRACT META-ANALYSIS DATA
# ─────────────────────────────────────────

@mcp.tool()
async def extract_meta_analysis_data(
    abstracts: list[str],
    outcome_type: str = "dichotomous"
) -> str:
    """
    Extrai dados quantitativos de abstracts para uso em meta-análise.
    Retorna tabela estruturada com todos os dados necessários.

    Args:
        abstracts: Lista de abstracts (2-20 estudos)
        outcome_type: 'dichotomous' (eventos/total), 'continuous' (média/DP/n),
                      'time-to-event' (HR, CI), ou 'mixed'
    """
    abstracts = abstracts[:20]
    papers_text = "\n\n---\n\n".join(
        f"Study {i+1}:\n{ab}" for i, ab in enumerate(abstracts)
    )

    system_prompt = f"""You are a meta-analysis data extraction specialist.
Extract quantitative data from each abstract for meta-analysis with outcome type: {outcome_type}.

Return ONLY a structured markdown table and notes.

## Extraction Table

For DICHOTOMOUS outcomes:
| Study | Year | Design | n (intervention) | Events (intervention) | n (control) | Events (control) | Effect measure | Value | 95% CI | p-value | Follow-up |
|---|---|---|---|---|---|---|---|---|---|---|---|

For CONTINUOUS outcomes:
| Study | Year | Design | n (intervention) | Mean (intervention) | SD (intervention) | n (control) | Mean (control) | SD (control) | MD/SMD | 95% CI | p-value | Follow-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

For TIME-TO-EVENT outcomes:
| Study | Year | Design | n total | Events | HR | 95% CI | p-value | Median follow-up |
|---|---|---|---|---|---|---|---|---|

## Data Quality Notes
For each study where data was incomplete or imprecisable:
- Study [n]: [what is missing or unclear]

## Heterogeneity Assessment (preliminary)
- Variation in populations: [note]
- Variation in interventions: [note]
- Variation in follow-up: [note]
- Likely I² concern: [low/moderate/high]

## Missing Data
List studies where key data could not be extracted from abstract alone.

If data is not available in the abstract, write 'NR' (not reported). Do not estimate."""

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": papers_text}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        b.get("text","") for b in data.get("content",[]) if b.get("type") == "text"
    )
    return (f"## Meta-Analysis Data Extraction\n"
            f"*{len(abstracts)} studies | Outcome: {outcome_type}*\n\n{text}")


# ─────────────────────────────────────────
# 32. CALCULATE STATISTICS
# ─────────────────────────────────────────

@mcp.tool()
async def calculate_statistics(
    intervention_events: int,
    intervention_total: int,
    control_events: int,
    control_total: int,
    confidence_level: float = 0.95
) -> str:
    """
    Calcula OR, RR, ARR, ARI, NNT, NNH e intervalos de confiança
    a partir de dados de uma tabela 2×2 de estudo clínico.

    Args:
        intervention_events: Eventos no grupo intervenção
        intervention_total: Total no grupo intervenção
        control_events: Eventos no grupo controle
        control_total: Total no grupo controle
        confidence_level: Nível de confiança (padrão 0.95)
    """

    a = intervention_events
    b = intervention_total - intervention_events
    c = control_events
    d = control_total - control_events
    n1 = intervention_total
    n2 = control_total

    if 0 in [a, b, c, d]:
        # Haldane-Anscombe correction for zero cells
        a += 0.5; b += 0.5; c += 0.5; d += 0.5

    # Proportions
    p1 = (intervention_events / n1) if n1 > 0 else 0
    p2 = (control_events / n2) if n2 > 0 else 0

    # z for CI
    alpha = 1 - confidence_level
    z = 1.96 if confidence_level == 0.95 else (1.645 if confidence_level == 0.90 else 2.576)

    # Relative Risk
    rr = (a / (a + b)) / (c / (c + d)) if (c / (c + d)) > 0 else float('nan')
    log_rr = log(rr)
    se_log_rr = sqrt(b / (a * (a + b)) + d / (c * (c + d)))
    rr_lower = exp(log_rr - z * se_log_rr)
    rr_upper = exp(log_rr + z * se_log_rr)

    # Odds Ratio
    or_val = (a * d) / (b * c)
    log_or = log(or_val)
    se_log_or = sqrt(1/a + 1/b + 1/c + 1/d)
    or_lower = exp(log_or - z * se_log_or)
    or_upper = exp(log_or + z * se_log_or)

    # Absolute Risk Reduction / Increase
    arr = p2 - p1  # positive = reduction, negative = increase
    se_arr = sqrt((p1 * (1 - p1) / n1) + (p2 * (1 - p2) / n2))
    arr_lower = arr - z * se_arr
    arr_upper = arr + z * se_arr

    # NNT / NNH
    nnt = abs(1 / arr) if arr != 0 else float('inf')
    nnt_lower = abs(1 / arr_upper) if arr_upper != 0 else float('inf')
    nnt_upper = abs(1 / arr_lower) if arr_lower != 0 else float('inf')

    # Chi-square p-value (approximate)
    n_total = n1 + n2
    e_a = (intervention_events + control_events) * n1 / n_total
    chi2 = ((intervention_events - e_a) ** 2 / e_a +
            (control_events - (intervention_events + control_events) * n2 / n_total) ** 2 /
            max((intervention_events + control_events) * n2 / n_total, 0.001))

    # Approximate p-value from chi2 with 1 df
    p_approx = exp(-0.717 * chi2 - 0.416 * chi2**2) if chi2 < 10 else "<0.001"
    if isinstance(p_approx, float):
        p_str = f"{p_approx:.4f}" if p_approx >= 0.001 else "<0.001"
    else:
        p_str = p_approx

    direction = "reduction" if arr > 0 else "increase"
    nnt_label = "NNT (to benefit)" if arr > 0 else "NNH (to harm)"

    ci_pct = int(confidence_level * 100)
    output  = f"## Statistical Analysis\n\n"
    output += f"### Contingency Table\n"
    output += f"| | Events | No events | Total |\n"
    output += f"|---|---|---|---|\n"
    output += f"| **Intervention** | {intervention_events} | {intervention_total - intervention_events} | {intervention_total} |\n"
    output += f"| **Control** | {control_events} | {control_total - control_events} | {control_total} |\n\n"
    output += f"### Results ({ci_pct}% CI)\n\n"
    output += f"| Measure | Value | {ci_pct}% CI | Interpretation |\n"
    output += f"|---|---|---|---|\n"
    output += f"| **Event rate (intervention)** | {p1:.1%} | — | {intervention_events}/{intervention_total} |\n"
    output += f"| **Event rate (control)** | {p2:.1%} | — | {control_events}/{control_total} |\n"
    output += f"| **Relative Risk (RR)** | {rr:.2f} | {rr_lower:.2f}–{rr_upper:.2f} | {'Favours intervention' if rr < 1 else 'Favours control'} |\n"
    output += f"| **Odds Ratio (OR)** | {or_val:.2f} | {or_lower:.2f}–{or_upper:.2f} | {'Favours intervention' if or_val < 1 else 'Favours control'} |\n"
    output += f"| **ARR/ARI** | {abs(arr):.1%} | {abs(arr_lower):.1%}–{abs(arr_upper):.1%} | Absolute risk {direction} |\n"
    output += f"| **{nnt_label}** | {nnt:.1f} | {min(nnt_lower,nnt_upper):.1f}–{max(nnt_lower,nnt_upper):.1f} | Patients needed to treat |\n"
    output += f"| **p-value (χ²)** | {p_str} | — | — |\n\n"
    output += f"*Note: Haldane-Anscombe correction applied if any cell = 0.*\n"
    return output


# ─────────────────────────────────────────
# 33. SEARCH COCHRANE
# ─────────────────────────────────────────

@mcp.tool()
async def search_cochrane(query: str, max_results: int = 10) -> str:
    """
    Busca na Cochrane Library — revisões sistemáticas de maior qualidade metodológica.
    Usa a API pública do Cochrane via Wiley.

    Args:
        query: Termos de busca
        max_results: Número de resultados (máx 25)
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # Cochrane CENTRAL via Europe PMC (indexado)
        r = await client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f"{query} AND (SRC:PPR OR JOURNAL:\"cochrane database\" OR JOURNAL:\"cochrane\")",
                "format": "json",
                "pageSize": min(max_results, 25),
                "resultType": "core"
            }
        )

        # Primary: Cochrane via their search endpoint
        r2 = await client.get(
            "https://www.cochranelibrary.com/api/search",
            params={
                "searchBy": "3",
                "searchText": query,
                "selectedDomain": "main",
                "pageSize": min(max_results, 25),
                "pageNumber": 1
            },
            headers={"Accept": "application/json",
                     "User-Agent": "research-mcp/1.0"}
        )

    # Use Europe PMC results (more reliable without auth)
    articles = []
    if r.status_code == 200:
        articles = r.json().get("resultList",{}).get("result",[])
        # Filter to Cochrane reviews
        articles = [a for a in articles
                    if "cochrane" in (a.get("journalTitle","") or "").lower()
                    or "cochrane" in (a.get("source","") or "").lower()
                    or "systematic review" in (a.get("pubTypeList",{}).get("pubType",[""])[0] or "").lower()
                   ]

    # Fallback: search PubMed for Cochrane reviews
    if not articles:
        base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
        async with httpx.AsyncClient(timeout=30) as client:
            r3 = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={**base_params, "db": "pubmed",
                        "term": f"{query} AND (\"Cochrane Database Syst Rev\"[journal] OR systematic review[pt] OR meta-analysis[pt])",
                        "retmax": min(max_results, 25),
                        "retmode": "json", "sort": "relevance"}
            )
            ids = r3.json().get("esearchresult",{}).get("idlist",[])
            if ids:
                r4 = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                    params={**base_params, "db": "pubmed",
                            "id": ",".join(ids), "retmode": "xml", "rettype": "abstract"}
                )
                root = ET.fromstring(r4.text)
                output = f"## Cochrane / Systematic Reviews — '{query}'\n\n"
                for i, article in enumerate(root.findall(".//PubmedArticle"), 1):
                    pmid  = article.findtext(".//PMID","")
                    title = article.findtext(".//ArticleTitle","").strip()
                    year  = article.findtext(".//PubDate/Year","")
                    journal = article.findtext(".//Journal/Title","")
                    authors = []
                    for a in article.findall(".//Author")[:3]:
                        last = a.findtext("LastName","")
                        if last: authors.append(last)
                    abstract_parts = article.findall(".//AbstractText")
                    abstract = " ".join(p.text or "" for p in abstract_parts)[:400]
                    doi = ""
                    for eid in article.findall(".//ArticleId"):
                        if eid.get("IdType") == "doi": doi = eid.text or ""
                    is_cochrane = "cochrane" in journal.lower()
                    label = "🥇 Cochrane Review" if is_cochrane else "📊 Systematic Review / Meta-Analysis"
                    output += f"### {i}. {title} ({year})\n"
                    output += f"**{label}**\n"
                    output += f"**Autores:** {', '.join(authors)}\n"
                    output += f"**Journal:** {journal}\n"
                    output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n"
                    if doi: output += f"**DOI:** https://doi.org/{doi}\n"
                    if is_cochrane:
                        output += f"**Cochrane:** https://www.cochranelibrary.com/cdsr/doi/{doi}\n"
                    if abstract: output += f"**Abstract:** {abstract}...\n"
                    output += "\n"
                return output

    output = f"## Cochrane Library — '{query}'\n\n"
    for i, a in enumerate(articles[:max_results], 1):
        output += f"### {i}. {a.get('title','')} ({a.get('pubYear','')})\n"
        output += f"🥇 **Cochrane Review**\n"
        output += f"**Autores:** {a.get('authorString','')[:100]}\n"
        if a.get('doi'): output += f"**DOI:** https://doi.org/{a['doi']}\n"
        if a.get('pmid'): output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/\n"
        if a.get('abstractText'): output += f"**Abstract:** {a['abstractText'][:400]}...\n"
        output += "\n"
    return output


# ─────────────────────────────────────────
# 34. GET CITATION NETWORK
# ─────────────────────────────────────────

@mcp.tool()
async def get_citation_network(
    doi_or_s2id: str,
    direction: str = "both",
    max_results: int = 10
) -> str:
    """
    Mapeia a rede de citações de um artigo via Semantic Scholar.
    Retorna artigos que citam E artigos citados, com métricas de influência.

    Args:
        doi_or_s2id: DOI (ex: '10.1016/j.jaad.2023.01.001') ou Semantic Scholar ID
        direction: 'citing' (quem citou), 'cited' (quem foi citado), ou 'both'
        max_results: Resultados por direção (máx 25)
    """
    paper_id = f"DOI:{doi_or_s2id}" if doi_or_s2id.startswith("10.") else doi_or_s2id
    fields = "title,year,authors,citationCount,journal,externalIds,isInfluential"

    async with httpx.AsyncClient(timeout=30) as client:
        # Get paper info
        r0 = await client.get(
            f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
            params={"fields": "title,year,citationCount,referenceCount,authors"}
        )
        paper_info = r0.json() if r0.status_code == 200 else {}

        results = {}
        if direction in ("citing","both"):
            r1 = await client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations",
                params={"fields": fields, "limit": min(max_results, 25)}
            )
            if r1.status_code == 200:
                results["citing"] = r1.json().get("data",[])

        if direction in ("cited","both"):
            r2 = await client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references",
                params={"fields": fields, "limit": min(max_results, 25)}
            )
            if r2.status_code == 200:
                results["cited"] = r2.json().get("data",[])

    title = paper_info.get("title","")
    year  = paper_info.get("year","")
    total_citations = paper_info.get("citationCount",0)
    total_refs      = paper_info.get("referenceCount",0)

    output  = f"## Citation Network\n"
    output += f"**Seed paper:** {title} ({year})\n"
    output += f"**Total citations received:** {total_citations:,} | **Total references:** {total_refs:,}\n\n"

    def format_papers(papers: list, label: str) -> str:
        if not papers: return f"### {label}\nNo data available.\n\n"
        out = f"### {label} ({len(papers)} shown)\n\n"
        # Sort by citations descending
        sorted_papers = sorted(
            papers,
            key=lambda x: (x.get("citingPaper") or x.get("citedPaper") or {}).get("citationCount", 0),
            reverse=True
        )
        for i, item in enumerate(sorted_papers[:max_results], 1):
            p = item.get("citingPaper") or item.get("citedPaper") or {}
            ptitle   = p.get("title","")
            pyear    = p.get("year","")
            pcites   = p.get("citationCount",0)
            pjournal = (p.get("journal") or {}).get("name","")
            pdoi     = (p.get("externalIds") or {}).get("DOI","")
            pauthors = ", ".join(
                a.get("name","") for a in (p.get("authors") or [])[:2]
            )
            influential = item.get("isInfluential",False)
            flag = "⭐ Influential — " if influential else ""
            out += f"**{i}.** {ptitle} ({pyear})\n"
            out += f"{flag}{pcites:,} citations"
            if pjournal: out += f" | {pjournal}"
            if pauthors: out += f" | {pauthors}"
            if pdoi: out += f"\nhttps://doi.org/{pdoi}"
            out += "\n\n"
        return out

    if "citing" in results:
        output += format_papers(results["citing"], "📥 Papers that CITE this work")
    if "cited" in results:
        output += format_papers(results["cited"], "📤 Papers CITED by this work")

    return output


# ─────────────────────────────────────────
# 35. FIND RESEARCH GAPS
# ─────────────────────────────────────────

@mcp.tool()
async def find_research_gaps(
    query: str,
    abstracts: Optional[list[str]] = None
) -> str:
    """
    Analisa o estado de um campo de pesquisa e identifica lacunas,
    controvérsias não resolvidas e oportunidades de investigação.
    Pode usar abstracts fornecidos ou buscar automaticamente.

    Args:
        query: Tema ou campo de pesquisa
        abstracts: Abstracts opcionais (se não fornecidos, busca automaticamente)
    """
    if not abstracts:
        # Auto-fetch top papers
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": 15,
                        "fields": "title,abstract,year,citationCount",
                        "sort": "citationCount"}
            )
            if r.status_code == 200:
                papers = r.json().get("data",[])
                abstracts = [
                    f"Title: {p.get('title','')} ({p.get('year','')})\n{p.get('abstract','')}"
                    for p in papers if p.get("abstract")
                ][:12]

    if not abstracts:
        return f"Não foi possível recuperar artigos para análise de lacunas: '{query}'"

    papers_text = "\n\n---\n\n".join(abstracts[:12])

    system_prompt = f"""You are a senior research strategist and systematic reviewer.
Analyze the provided literature on "{query}" and identify research gaps and opportunities.

Return ONLY structured markdown:

## Field Overview
Brief synthesis of current state of knowledge (3-4 sentences)

## What Is Well-Established
Key findings with strong, consistent evidence

## Active Controversies
Areas of genuine scientific disagreement with competing evidence

## Research Gaps
### Critical Gaps (high priority, high feasibility)
- [Gap]: [Why it matters] [What study design could address it]

### Important Gaps (high priority, moderate feasibility)
- [Gap]: [Why it matters]

### Exploratory Gaps (interesting, lower priority)
- [Gap]: [Why it matters]

## Methodological Limitations in Current Literature
Systematic weaknesses across studies (population, design, outcomes, follow-up)

## Recommended Study Designs
For the top 2-3 gaps: what specific study would best address each

## Emerging Directions
Technologies, biomarkers, or approaches not yet well-studied

Be precise and evidence-based. Distinguish gaps from personal opinions."""

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1800,
                "system": system_prompt,
                "messages": [{"role": "user", "content": papers_text}]
            }
        )
        r.raise_for_status()
        data = r.json()

    text = "".join(
        b.get("text","") for b in data.get("content",[]) if b.get("type") == "text"
    )
    return f"## Research Gap Analysis: '{query}'\n*Based on {len(abstracts)} papers*\n\n{text}"


# ─────────────────────────────────────────
# 36. FIND EXPERT REVIEWERS
# ─────────────────────────────────────────

@mcp.tool()
async def find_expert_reviewers(
    topic: str,
    exclude_authors: Optional[list[str]] = None,
    max_results: int = 10
) -> str:
    """
    Sugere potenciais revisores para um manuscrito baseado em expertise,
    h-index e publicações recentes no tema. Útil para editores e autores.

    Args:
        topic: Tema do manuscrito
        exclude_authors: Lista de nomes a excluir (co-autores, conflitos)
        max_results: Número de revisores sugeridos
    """
    exclude_authors = exclude_authors or []

    async with httpx.AsyncClient(timeout=30) as client:
        # Find top authors via OpenAlex
        r = await client.get(
            "https://api.openalex.org/authors",
            params={
                "search": topic,
                "per-page": min(max_results * 3, 50),
                "sort": "cited_by_count:desc",
                "select": "display_name,ids,affiliations,cited_by_count,works_count,summary_stats,topics,last_known_institutions",
                "mailto": PUBMED_EMAIL
            }
        )
        r.raise_for_status()
        authors = r.json().get("results",[])

    # Filter excluded authors
    if exclude_authors:
        authors = [
            a for a in authors
            if not any(
                excl.lower() in a.get("display_name","").lower()
                for excl in exclude_authors
            )
        ]

    if not authors:
        return f"Nenhum revisor encontrado para: '{topic}'"

    output  = f"## Suggested Reviewers — '{topic}'\n"
    output += f"*Ranked by citations | Conflicts to verify manually*\n\n"

    for i, a in enumerate(authors[:max_results], 1):
        name       = a.get("display_name","")
        cited      = a.get("cited_by_count",0)
        works      = a.get("works_count",0)
        stats      = a.get("summary_stats") or {}
        h_index    = stats.get("h_index",0)
        if2yr      = stats.get("2yr_mean_citedness",0)
        orcid      = (a.get("ids") or {}).get("orcid","")
        openalex   = (a.get("ids") or {}).get("openalex","")

        institutions = a.get("last_known_institutions") or a.get("affiliations") or []
        affiliation = ""
        if institutions:
            inst = institutions[0]
            if isinstance(inst, dict):
                affiliation = inst.get("display_name","") or \
                              (inst.get("institution") or {}).get("display_name","")

        topics = a.get("topics") or []
        top_topics = [t.get("display_name","") for t in topics[:3]]

        output += f"### {i}. {name}\n"
        if affiliation: output += f"**Affiliation:** {affiliation}\n"
        output += f"**h-index:** {h_index} | **Citations:** {cited:,} | **Papers:** {works:,}\n"
        if top_topics:  output += f"**Topics:** {', '.join(top_topics)}\n"
        if orcid:       output += f"**ORCID:** {orcid}\n"
        if openalex:    output += f"**OpenAlex:** {openalex}\n"
        output += "\n"

    output += "\n⚠️ *Always verify COI, editorial board membership, and recent collaborations before inviting.*\n"
    return output


# ─────────────────────────────────────────
# 37. MONITOR TOPIC (SQLite persistence)
# ─────────────────────────────────────────

import sqlite3
import hashlib

_DB_PATH = "/tmp/research_monitor.db"

def _init_db():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitors (
            id TEXT PRIMARY KEY,
            query TEXT,
            label TEXT,
            last_checked TEXT,
            last_pmids TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_db()

@mcp.tool()
async def monitor_topic(
    action: str,
    query: str = "",
    label: str = "",
    monitor_id: str = ""
) -> str:
    """
    Cria e verifica alertas de literatura — salva uma query e retorna
    novos artigos desde a última verificação.

    Args:
        action: 'create' (novo monitor), 'check' (novos artigos), 'list' (ver monitores), 'delete'
        query: Query de busca PubMed (para action='create')
        label: Nome descritivo (ex: 'CBC Hedgehog inhibitors')
        monitor_id: ID do monitor (para action='check' ou 'delete')
    """

    conn = sqlite3.connect(_DB_PATH)

    if action == "list":
        rows = conn.execute("SELECT id, label, query, last_checked FROM monitors").fetchall()
        conn.close()
        if not rows:
            return "Nenhum monitor ativo. Use action='create' para criar um."
        output = "## Active Topic Monitors\n\n"
        for row in rows:
            output += f"**ID:** `{row[0]}`\n**Label:** {row[1]}\n**Query:** {row[2]}\n**Last checked:** {row[3]}\n\n---\n\n"
        return output

    if action == "create":
        if not query:
            return "Forneça uma query para criar um monitor."
        mid = hashlib.md5(query.encode()).hexdigest()[:8]
        lbl = label or query[:50]
        conn.execute(
            "INSERT OR REPLACE INTO monitors VALUES (?,?,?,?,?)",
            (mid, query, lbl, "never", "[]")
        )
        conn.commit()
        conn.close()
        return f"✅ Monitor criado\n**ID:** `{mid}`\n**Label:** {lbl}\n**Query:** {query}\n\nUse action='check' com monitor_id='{mid}' para verificar novos artigos."

    if action == "delete":
        conn.execute("DELETE FROM monitors WHERE id=?", (monitor_id,))
        conn.commit()
        conn.close()
        return f"🗑️ Monitor `{monitor_id}` removido."

    if action == "check":
        row = conn.execute(
            "SELECT query, label, last_checked, last_pmids FROM monitors WHERE id=?",
            (monitor_id,)
        ).fetchone()

        if not row:
            conn.close()
            return f"Monitor ID `{monitor_id}` não encontrado. Use action='list' para ver monitores ativos."

        query, label, last_checked, last_pmids_json = row
        last_pmids = set(json.loads(last_pmids_json) if last_pmids_json else [])
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Fetch latest articles
        base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
        if PUBMED_API_KEY: base_params["api_key"] = PUBMED_API_KEY

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={**base_params, "db": "pubmed", "term": query,
                        "retmax": 50, "retmode": "json", "sort": "pub_date"}
            )
            ids = r.json().get("esearchresult",{}).get("idlist",[])
            new_ids = [i for i in ids if i not in last_pmids]

        # Update DB
        all_pmids = list(set(ids) | last_pmids)[:200]
        conn.execute(
            "UPDATE monitors SET last_checked=?, last_pmids=? WHERE id=?",
            (now, json.dumps(all_pmids), monitor_id)
        )
        conn.commit()
        conn.close()

        if not new_ids:
            return f"## 🔔 Monitor: {label}\n\nNenhum artigo novo desde {last_checked}.\n*(Verificado: {now})*"

        # Fetch details of new articles
        result = await search_pubmed(
            query=" OR ".join(f"{i}[uid]" for i in new_ids[:20]),
            max_results=20
        )
        return (f"## 🔔 Monitor: {label}\n"
                f"**{len(new_ids)} novos artigos** desde {last_checked}\n"
                f"*(Verificado: {now})*\n\n{result}")

    conn.close()
    return "Ação inválida. Use: 'create', 'check', 'list', ou 'delete'."


# ─────────────────────────────────────────
# 38. DETECT DUPLICATES
# ─────────────────────────────────────────

@mcp.tool()
async def detect_duplicates(identifiers: list[str]) -> str:
    """
    Identifica duplicatas, publicações redundantes e artigos altamente
    similares numa lista de PMIDs ou DOIs.
    Útil na triagem de revisão sistemática.

    Args:
        identifiers: Lista de PMIDs ou DOIs (até 50)
    """

    base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
    if PUBMED_API_KEY: base_params["api_key"] = PUBMED_API_KEY

    identifiers = identifiers[:50]
    pmids = []

    async with httpx.AsyncClient(timeout=30) as client:
        for ident in identifiers:
            ident = ident.strip().lstrip("https://doi.org/")
            if ident.startswith("10."):
                r = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={**base_params, "db": "pubmed",
                            "term": f"{ident}[doi]", "retmode": "json"}
                )
                ids = r.json().get("esearchresult",{}).get("idlist",[])
                if ids: pmids.append(ids[0])
            else:
                pmids.append(ident)

        if not pmids:
            return "Nenhum artigo válido fornecido."

        r = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={**base_params, "db": "pubmed", "id": ",".join(pmids[:50]),
                    "retmode": "xml", "rettype": "abstract"}
        )

    root = ET.fromstring(r.text)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        pmid    = article.findtext(".//PMID","")
        title   = article.findtext(".//ArticleTitle","").strip().lower()
        authors = sorted([
            a.findtext("LastName","").lower()
            for a in article.findall(".//Author")
        ])
        year  = article.findtext(".//PubDate/Year","")
        doi = ""
        for eid in article.findall(".//ArticleId"):
            if eid.get("IdType") == "doi": doi = eid.text or ""
        papers.append({"pmid": pmid, "title": title, "authors": authors,
                       "year": year, "doi": doi, "title_orig": article.findtext(".//ArticleTitle","")})

    # Find duplicates
    duplicates = []
    seen = set()
    for i, p1 in enumerate(papers):
        for j, p2 in enumerate(papers):
            if i >= j: continue
            pair_key = tuple(sorted([p1["pmid"], p2["pmid"]]))
            if pair_key in seen: continue

            # Exact title match
            if p1["title"] == p2["title"]:
                duplicates.append(("exact", p1, p2, 1.0))
                seen.add(pair_key)
                continue

            # High similarity title
            sim = difflib.SequenceMatcher(None, p1["title"], p2["title"]).ratio()
            if sim > 0.85:
                duplicates.append(("similar", p1, p2, sim))
                seen.add(pair_key)
                continue

            # Same authors + same year = possible redundant publication
            if p1["authors"] == p2["authors"] and p1["year"] == p2["year"] and p1["authors"]:
                author_match_sim = difflib.SequenceMatcher(None, p1["title"], p2["title"]).ratio()
                if author_match_sim > 0.5:
                    duplicates.append(("same_authors_year", p1, p2, author_match_sim))
                    seen.add(pair_key)

    if not duplicates:
        return (f"## ✅ No Duplicates Detected\n\n"
                f"Analysed {len(papers)} articles — no exact duplicates or "
                f"highly similar titles found (threshold: 85% similarity).")

    output  = f"## ⚠️ Duplicate Detection Report\n"
    output += f"*{len(papers)} articles analysed | {len(duplicates)} potential duplicates found*\n\n"

    type_labels = {
        "exact":            "🔴 EXACT DUPLICATE",
        "similar":          "🟡 HIGHLY SIMILAR TITLES",
        "same_authors_year":"🟠 SAME AUTHORS + YEAR",
    }

    for dtype, p1, p2, sim in duplicates:
        output += f"### {type_labels[dtype]} (similarity: {sim:.0%})\n"
        output += f"**A:** {p1['title_orig']} (PMID {p1['pmid']})\n"
        output += f"**B:** {p2['title_orig']} (PMID {p2['pmid']})\n"
        output += f"**Action:** Verify manually — may be duplicate, translation, or erratum\n\n"

    return output


# ─────────────────────────────────────────
# 39. TRANSLATE ABSTRACT
# ─────────────────────────────────────────

@mcp.tool()
async def translate_abstract(
    text: str,
    target_language: str = "English",
    preserve_structure: bool = True
) -> str:
    """
    Traduz abstract de qualquer língua para o idioma alvo,
    preservando estrutura (BACKGROUND, METHODS, etc.) e terminologia médica.

    Args:
        text: Texto do abstract para traduzir
        target_language: Idioma alvo (ex: 'English', 'Portuguese', 'Spanish')
        preserve_structure: Preservar labels estruturais (BACKGROUND:, METHODS:, etc.)
    """
    system_prompt = f"""You are a medical translator specialized in dermatology and clinical research.
Translate the provided abstract to {target_language}.

Rules:
1. Preserve all medical terminology accurately — do not simplify
2. {"Preserve structured labels (BACKGROUND:, METHODS:, RESULTS:, CONCLUSIONS:) exactly" if preserve_structure else "Translate as continuous text"}
3. Preserve all numbers, statistics, units, and drug names exactly
4. If the original contains abbreviations, keep them with full form on first use
5. Do not add, remove, or interpret content — translate only
6. If you detect the source language, note it at the top

Return format:
**Source language:** [detected language]
**Translation:**
[translated text]"""

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "system": system_prompt,
                "messages": [{"role": "user", "content": text}]
            }
        )
        r.raise_for_status()
        data = r.json()

    translated = "".join(
        b.get("text","") for b in data.get("content",[]) if b.get("type") == "text"
    )
    return f"## Abstract Translation → {target_language}\n\n{translated}"


# ─────────────────────────────────────────
# 40. SEARCH NIH REPORTER (grants)
# ─────────────────────────────────────────

@mcp.tool()
async def search_nih_reporter(
    query: str,
    max_results: int = 10,
    fiscal_year: Optional[int] = None,
    active_only: bool = True
) -> str:
    """
    Busca grants NIH ativos por tema via NIH RePORTER API.
    Útil para inteligência de financiamento, identificar grupos de pesquisa
    ativos e justificar novidade em protocolos de pesquisa.

    Args:
        query: Tema de pesquisa
        max_results: Número de resultados
        fiscal_year: Ano fiscal específico (ex: 2024)
        active_only: Apenas grants ativos
    """
    payload = {
        "criteria": {
            "advanced_text_search": {
                "operator": "and",
                "search_field": "all",
                "search_text": query
            }
        },
        "limit": min(max_results, 25),
        "offset": 0,
        "sort_field": "award_amount",
        "sort_order": "desc",
        "fields": [
            "project_num","project_title","abstract_text","organization",
            "pi_names","fiscal_year","award_amount","project_start_date",
            "project_end_date","agency_ic_fundings","terms"
        ]
    }

    if fiscal_year:
        payload["criteria"]["fiscal_years"] = [fiscal_year]
    if active_only:
            payload["criteria"]["project_end_date"] = {"from_date": datetime.now().strftime("%Y-%m-%d")}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.reporter.nih.gov/v2/projects/search",
            json=payload,
            headers={"Content-Type": "application/json", "accept": "application/json"}
        )
        r.raise_for_status()
        data = r.json()

    projects = data.get("results",[])
    total    = data.get("meta",{}).get("total",0)

    if not projects:
        return f"Nenhum grant NIH encontrado para: '{query}'"

    output  = f"## NIH RePORTER — '{query}'\n"
    output += f"*{total:,} total grants | Showing {len(projects)} | Sorted by award amount*\n\n"

    for i, p in enumerate(projects, 1):
        title    = p.get("project_title","")
        num      = p.get("project_num","")
        abstract = (p.get("abstract_text","") or "")[:300]
        org      = (p.get("organization") or {}).get("org_name","")
        amount   = p.get("award_amount",0)
        start    = (p.get("project_start_date","") or "")[:10]
        end      = (p.get("project_end_date","") or "")[:10]
        year     = p.get("fiscal_year","")
        pis      = [f"{pi.get('first_name','')} {pi.get('last_name','')}".strip()
                    for pi in (p.get("pi_names") or [])[:3]]

        output += f"### {i}. {title}\n"
        output += f"**Grant:** {num} | FY{year}\n"
        if pis: output += f"**PI:** {', '.join(pis)}\n"
        if org: output += f"**Institution:** {org}\n"
        if amount: output += f"**Award:** ${amount:,.0f}\n"
        if start:  output += f"**Period:** {start} → {end}\n"
        if num:    output += f"**Link:** https://reporter.nih.gov/project-details/{num.replace(' ','%20')}\n"
        if abstract: output += f"**Abstract:** {abstract}...\n"
        output += "\n"

    return output


# ─────────────────────────────────────────
# 41. SEARCH FDA APPROVALS
# ─────────────────────────────────────────

@mcp.tool()
async def search_fda_approvals(
    query: str,
    search_type: str = "drug",
    max_results: int = 10
) -> str:
    """
    Busca aprovações, alertas de segurança e drug labels da FDA via openFDA API.
    Útil para informação regulatória atualizada sobre medicamentos e dispositivos.

    Args:
        query: Nome do medicamento, condição ou ingrediente ativo
        search_type: 'drug' (aprovações), 'label' (bula/prescribing info),
                     'adverse_events' (farmacovigilância), 'recall' (recalls)
        max_results: Número de resultados
    """
    endpoints = {
        "drug":           "https://api.fda.gov/drug/nda.json",
        "label":          "https://api.fda.gov/drug/label.json",
        "adverse_events": "https://api.fda.gov/drug/event.json",
        "recall":         "https://api.fda.gov/drug/enforcement.json",
    }

    endpoint = endpoints.get(search_type, endpoints["drug"])

    # Build search query for openFDA
    search_queries = {
        "drug":   f'brand_name:"{query}"+generic_name:"{query}"',
        "label":  f'openfda.brand_name:"{query}"+openfda.generic_name:"{query}"+openfda.substance_name:"{query}"',
        "adverse_events": f'patient.drug.openfda.brand_name:"{query}"+patient.drug.openfda.generic_name:"{query}"',
        "recall": f'product_description:"{query}"+openfda.brand_name:"{query}"',
    }

    params = {
        "search": search_queries.get(search_type, f'openfda.generic_name:"{query}"'),
        "limit": min(max_results, 25),
        "sort": "application_date:desc" if search_type == "drug" else None
    }
    params = {k: v for k, v in params.items() if v is not None}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(endpoint, params=params)

        if r.status_code == 404:
            # Try broader search
            params["search"] = query
            r = await client.get(endpoint, params=params)

        if r.status_code not in (200, 404):
            r.raise_for_status()

    if r.status_code == 404:
        return f"Nenhum resultado FDA encontrado para: '{query}' (tipo: {search_type})"

    data    = r.json()
    results = data.get("results",[])
    total   = data.get("meta",{}).get("results",{}).get("total",0)

    type_labels = {
        "drug":           "💊 FDA Drug Approvals",
        "label":          "📋 FDA Drug Labels",
        "adverse_events": "⚠️ FDA Adverse Events",
        "recall":         "🔴 FDA Drug Recalls",
    }

    output  = f"## {type_labels.get(search_type, 'FDA')} — '{query}'\n"
    output += f"*{total:,} total results | Showing {len(results)}*\n\n"

    for i, item in enumerate(results[:max_results], 1):
        openfda = item.get("openfda",{})

        if search_type == "drug":
            name      = (openfda.get("brand_name",[""])[0] or
                         openfda.get("generic_name",[""])[0] or "")
            app_num   = item.get("application_number","")
            sponsor   = item.get("sponsor_name","")
            products  = item.get("products",[])
            output += f"### {i}. {name}\n"
            output += f"**Application:** {app_num} | **Sponsor:** {sponsor}\n"
            if products:
                for prod in products[:3]:
                    output += f"- {prod.get('brand_name','')} {prod.get('dosage_form','')} {prod.get('strength','')}\n"

        elif search_type == "label":
            brand   = (openfda.get("brand_name",[""])[0] or "")
            generic = (openfda.get("generic_name",[""])[0] or "")
            name    = brand or generic
            indications = (item.get("indications_and_usage",[""])[0] or "")[:400]
            warnings    = (item.get("warnings",[""])[0] or "")[:200]
            output += f"### {i}. {name}\n"
            if generic and brand: output += f"**Generic:** {generic}\n"
            if indications: output += f"**Indications:** {indications}...\n"
            if warnings:    output += f"**Key warnings:** {warnings}...\n"

        elif search_type == "adverse_events":
            drug   = (item.get("patient",{}).get("drug",[{}])[0]
                      .get("openfda",{}).get("brand_name",[""])[0] or query)
            serious = item.get("serious","")
            reactions = [r.get("reactionmeddrapt","")
                         for r in item.get("patient",{}).get("reaction",[])[:5]]
            output += f"### {i}. Report #{item.get('safetyreportid','')}\n"
            output += f"**Drug:** {drug} | **Serious:** {'Yes' if serious == '1' else 'No'}\n"
            if reactions: output += f"**Reactions:** {', '.join(r for r in reactions if r)}\n"

        elif search_type == "recall":
            product  = item.get("product_description","")[:150]
            reason   = item.get("reason_for_recall","")[:200]
            status   = item.get("status","")
            date     = item.get("recall_initiation_date","")
            output += f"### {i}. {product}\n"
            output += f"**Status:** {status} | **Date:** {date}\n"
            if reason: output += f"**Reason:** {reason}\n"

        output += "\n"

    output += f"\n*Source: openFDA — https://open.fda.gov*\n"
    return output


# ─────────────────────────────────────────
# 42. SEARCH OMIM (genetics)
# ─────────────────────────────────────────

@mcp.tool()
async def search_omim(query: str, max_results: int = 10) -> str:
    """
    Busca no OMIM (Online Mendelian Inheritance in Man) — base de dados de
    doenças genéticas, genes e fenótipos. Essencial para dermatoses hereditárias,
    genodermatoses, síndromes com manifestações cutâneas e farmacogenômica.

    Args:
        query: Nome da doença, gene ou fenótipo (ex: 'epidermolysis bullosa',
               'ichthyosis', 'neurofibromatosis', 'TP53', 'BRCA2 melanoma')
        max_results: Número de resultados
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # OMIM via their search API (public, no key required for basic search)
        r = await client.get(
            "https://omim.org/api/entry/search",
            params={
                "search": query,
                "limit": min(max_results, 20),
                "format": "json",
                "include": "geneMap,externalLinks,contributors"
            },
            headers={"User-Agent": "research-mcp/1.0 (research tool)"}
        )

        # Fallback: OMIM via Europe PMC
        if r.status_code != 200:
            r2 = await client.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={
                    "query": f"{query} AND SRC:OMIM",
                    "format": "json",
                    "pageSize": min(max_results, 20),
                    "resultType": "core"
                }
            )
            if r2.status_code == 200:
                articles = r2.json().get("resultList",{}).get("result",[])
                output = f"## OMIM / Genetic Dermatology — '{query}'\n\n"
                if not articles:
                    output += "Nenhuma entrada encontrada.\n"
                    output += f"🔗 Buscar diretamente: https://omim.org/search?search={query.replace(' ','+')}\n"
                    return output
                for i, a in enumerate(articles[:max_results], 1):
                    output += f"### {i}. {a.get('title','')}\n"
                    if a.get('doi'): output += f"**OMIM:** https://omim.org/entry/{a.get('pmid','')}\n"
                    if a.get('abstractText'): output += f"**Summary:** {a['abstractText'][:300]}...\n"
                    output += "\n"
                return output

    # OMIM API response
    if r.status_code == 200:
        try:
            data    = r.json()
            entries = (data.get("omim",{}).get("searchResponse",{})
                       .get("entryList",[]))
        except Exception:
            entries = []
    else:
        entries = []

    if not entries:
        output  = f"## OMIM — '{query}'\n\n"
        output += "Acesso direto à API OMIM requer chave. Resultados via link direto:\n\n"
        output += f"🔗 **OMIM Search:** https://omim.org/search?search={query.replace(' ','+')}\n\n"
        output += "**Recursos adicionais de genética dermatológica:**\n"
        output += f"- OMIM: https://omim.org/search?search={query.replace(' ','+')}\n"
        output += f"- ClinVar: https://www.ncbi.nlm.nih.gov/clinvar/?term={query.replace(' ','+')}\n"
        output += f"- GeneCards: https://www.genecards.org/Search/Keyword?queryString={query.replace(' ','+')}\n"
        output += f"- Orphanet: https://www.orpha.net/consor/cgi-bin/Disease_Search.php?lng=EN&data_id=&Disease_Disease_Search_diseaseGroup={query.replace(' ','+')}\n"
        return output

    output = f"## OMIM — '{query}'\n*{len(entries)} entries*\n\n"
    for i, item in enumerate(entries[:max_results], 1):
        entry    = item.get("entry",{})
        mim_num  = entry.get("mimNumber","")
        title    = entry.get("titles",{}).get("preferredTitle","")
        etype    = entry.get("type","")  # phenotype, gene, etc
        gene_map = entry.get("geneMap",{})
        gene     = gene_map.get("geneSymbols","")
        locus    = gene_map.get("chromosomeLocation","")

        type_labels = {
            "phenotype": "🧬 Phenotype",
            "gene": "🔬 Gene",
            "predominantly phenotypes": "🩺 Phenotype",
        }

        output += f"### {i}. {title}\n"
        output += f"**MIM #{mim_num}** | {type_labels.get(etype, etype)}\n"
        if gene:  output += f"**Gene:** {gene}\n"
        if locus: output += f"**Locus:** {locus}\n"
        output += f"**OMIM:** https://omim.org/entry/{mim_num}\n\n"

    return output


# ─────────────────────────────────────────
# 43. SEARCH WHO GUIDELINES
# ─────────────────────────────────────────

@mcp.tool()
async def search_who_guidelines(
    query: str,
    max_results: int = 10
) -> str:
    """
    Busca diretrizes, relatórios e publicações da OMS/WHO via IRIS
    (Institutional Repository for Information Sharing).
    Útil para diretrizes internacionais, dados epidemiológicos globais
    e recomendações de saúde pública relevantes para dermatologia.

    Args:
        query: Tema de busca (ex: 'skin cancer prevention', 'melanoma',
               'leishmaniasis cutaneous', 'leprosy guidelines')
        max_results: Número de resultados
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # WHO IRIS API
        r = await client.get(
            "https://iris.who.int/rest/items/find-by-metadata-field",
            params={
                "metadata.key": "dc.subject",
                "metadata.value": query,
                "limit": min(max_results, 20)
            },
            headers={"Accept": "application/json"}
        )

        # Primary: WHO IRIS search endpoint
        r2 = await client.get(
            "https://iris.who.int/rest/discover/search/objects",
            params={
                "query": query,
                "dsoType": "item",
                "configuration": "defaultConfiguration",
                "page": 0,
                "size": min(max_results, 20)
            },
            headers={"Accept": "application/json"}
        )

        # Fallback: Europe PMC with WHO filter
        r3 = await client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f"{query} AND (AUTH:\"World Health Organization\" OR JOURNAL:\"WHO\" OR JOURNAL:\"World Health\")",
                "format": "json",
                "pageSize": min(max_results, 20),
                "resultType": "core"
            }
        )

    output = f"## WHO Guidelines & Publications — '{query}'\n\n"
    found  = False

    # Try Europe PMC WHO results
    if r3.status_code == 200:
        articles = r3.json().get("resultList",{}).get("result",[])
        if articles:
            found = True
            for i, a in enumerate(articles[:max_results], 1):
                output += f"### {i}. {a.get('title','')} ({a.get('pubYear','')})\n"
                output += f"🏥 **WHO Publication**\n"
                if a.get('authorString'): output += f"**Authors:** {a['authorString'][:100]}\n"
                if a.get('doi'):   output += f"**DOI:** https://doi.org/{a['doi']}\n"
                if a.get('pmid'):  output += f"**PubMed:** https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/\n"
                if a.get('abstractText'):
                    output += f"**Summary:** {a['abstractText'][:350]}...\n"
                output += "\n"

    if not found:
        output += "Resultados diretos não disponíveis. Links para busca manual:\n\n"
        output += f"🔗 **WHO IRIS:** https://iris.who.int/discover?query={query.replace(' ','+')}\n"
        output += f"🔗 **WHO Publications:** https://www.who.int/publications/find?q={query.replace(' ','+')}\n"
        output += f"🔗 **PubMed WHO:** https://pubmed.ncbi.nlm.nih.gov/?term={query.replace(' ','+')}+AND+%22World+Health+Organization%22%5BCorporate+Author%5D\n\n"

        # Still try to get WHO data from PubMed
        base_params = {"tool": "research-mcp", "email": PUBMED_EMAIL}
        async with httpx.AsyncClient(timeout=20) as client:
            r4 = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={**base_params, "db": "pubmed",
                        "term": f"{query} AND (\"World Health Organization\"[Corporate Author] OR \"WHO\"[Corporate Author] OR guideline[pt])",
                        "retmax": max_results, "retmode": "json"}
            )
            ids = r4.json().get("esearchresult",{}).get("idlist",[])
            if ids:
                result = await search_pubmed(
                    " OR ".join(f"{i}[uid]" for i in ids[:max_results]),
                    max_results=max_results
                )
                output += "**Related guidelines from PubMed:**\n\n" + result

    return output
