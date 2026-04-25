"""
Research MCP Server v2
Fontes: PubMed, Semantic Scholar, OpenAlex, Europe PMC
Extras: busca por PMID/DOI, artigos relacionados, busca combinada
Deploy: Render.com (free tier)
"""

from mcp.server.fastmcp import FastMCP
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import Optional
import os

import os as _os
_port = int(_os.environ.get("PORT", 8000))
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
    from datetime import datetime, timedelta
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

    import xml.etree.ElementTree as ET
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

    import xml.etree.ElementTree as ET
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
    import math
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

    import xml.etree.ElementTree as ET
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
    import csv, io

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

    import xml.etree.ElementTree as ET
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
