# Research MCP Server

MCP server com busca científica em 3 fontes gratuitas:
- **Semantic Scholar** — 200M+ papers, busca semântica
- **OpenAlex** — 250M+ works, filtros avançados
- **Europe PMC** — full-text, revisões sistemáticas

## Ferramentas disponíveis

| Ferramenta | Descrição |
|---|---|
| `search_semantic_scholar` | Busca no Semantic Scholar |
| `search_openalex` | Busca no OpenAlex |
| `search_europe_pmc` | Busca no Europe PMC |
| `research_all_sources` | Busca nas 3 fontes simultâneas |

---

## Deploy no Render.com (gratuito)

### 1. Criar conta e repositório

1. Cria conta em [render.com](https://render.com)
2. Cria conta em [github.com](https://github.com) (se não tens)
3. Cria novo repositório no GitHub chamado `research-mcp`
4. Faz upload dos 3 arquivos: `server.py`, `requirements.txt`, `render.yaml`

### 2. Deploy no Render

1. No Render: **New → Web Service**
2. Conecta teu repositório GitHub
3. Render detecta o `render.yaml` automaticamente
4. Clica em **Deploy**
5. Aguarda ~2 minutos
6. Copia a URL pública gerada (ex: `https://research-mcp.onrender.com`)

### 3. Conectar no Claude.ai

1. Vai em [claude.ai](https://claude.ai) → **Settings → Integrations**
2. Clica em **Add Integration**
3. Cola a URL: `https://research-mcp.onrender.com/mcp`
4. Nome: `Research MCP`
5. Salva

### 4. Testar

No chat do Claude:
```
Busca evidência sobre tratamento de carcinoma basocelular superficial 
em todas as fontes, apenas artigos open access dos últimos 5 anos
```

---

## Rodar localmente (opcional)

```bash
pip install -r requirements.txt
python server.py
# Servidor em http://localhost:8000
```

---

## ⚠️ Aviso sobre Render free tier

O serviço gratuito do Render **hiberna após 15 min de inatividade**.
A primeira requisição depois de inativo demora ~30 segundos para acordar.

Para evitar: usa [UptimeRobot](https://uptimerobot.com) (gratuito) para fazer ping a cada 10 min na URL `/mcp`.
