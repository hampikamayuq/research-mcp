# Research MCP Server v2

MCP server com busca científica em 4 fontes gratuitas + acesso a full-text legal.

## Ferramentas (9)

| Ferramenta | Fonte | Descrição |
|---|---|---|
| `search_pubmed` | PubMed/NCBI | Busca com filtros MeSH, tipo de artigo, free full text |
| `get_paper_details` | PubMed + S2 | Detalhes completos por PMID ou DOI |
| `find_related_articles` | PubMed | Artigos similares a partir de um PMID |
| `search_semantic_scholar` | Semantic Scholar | Busca semântica em 200M+ artigos |
| `search_openalex` | OpenAlex | Filtros avançados em 250M+ works |
| `search_europe_pmc` | Europe PMC | Full-text e revisões sistemáticas |
| `research_all_sources` | Todas | Busca simultânea nas 4 fontes |
| `find_free_fulltext` | Unpaywall | Melhor link gratuito/legal por DOI |
| `find_free_fulltext_batch` | Unpaywall | Verifica acesso de até 10 DOIs de uma vez |

---

## Deploy no Render.com (gratuito)

### 1. GitHub
1. Cria repositório `research-mcp` em github.com
2. Faz upload dos 4 arquivos: `server.py`, `requirements.txt`, `render.yaml`, `README.md`

### 2. Render
1. render.com → **New → Web Service**
2. Conecta o repositório GitHub
3. Render detecta o `render.yaml` automaticamente
4. **Deploy**
5. Copia a URL gerada (ex: `https://research-mcp.onrender.com`)

### 3. Variáveis de ambiente (opcionais mas recomendadas)
No Render → Environment → Add Environment Variable:

| Variável | Onde obter | Efeito |
|---|---|---|
| `PUBMED_API_KEY` | ncbi.nlm.nih.gov/account | Rate limit 3→10 req/s |
| `PUBMED_EMAIL` | teu email | Boa prática NCBI |

### 4. Conectar no Claude.ai
1. claude.ai → **Settings → Integrations → Add Integration**
2. URL: `https://research-mcp.onrender.com/mcp`
3. Nome: `Research MCP`

---

## Workflow recomendado

```
1. research_all_sources("query")          → visão geral de 4 fontes
2. find_free_fulltext_batch([doi1, doi2]) → quais tenho acesso gratuito?
3. get_paper_details("PMID")             → abstract completo + MeSH terms
4. find_related_articles("PMID")         → expandir revisão
```

---

## ⚠️ Render free tier

O serviço hiberna após 15 min de inatividade — primeira requisição demora ~30s.
Para manter acordado: [UptimeRobot](https://uptimerobot.com) (gratuito) com ping a cada 10 min na URL `/mcp`.
