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
