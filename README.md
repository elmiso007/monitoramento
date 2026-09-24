# Monitoramento de Contatos — Suporte Locaweb (Octadesk)

Pipeline batch que detecta picos e quedas anormais no volume de atendimentos
de chat/WhatsApp do suporte Locaweb, agendado para rodar de tempos em tempos
(via Task Scheduler do Windows). Quando o volume atual desvia do
comportamento histórico, o pipeline opcionalmente aciona o **Google Gemini**
para identificar os principais motivos de contato e dispara um alerta no
**Slack**.

---

## Sumário

- [Visão geral](#visão-geral)
- [Como funciona](#como-funciona)
- [Estrutura de arquivos](#estrutura-de-arquivos)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Execução](#execução)
- [Agendamento](#agendamento)
- [Limiares e ajuste fino](#limiares-e-ajuste-fino)
- [Esquema do banco de dados](#esquema-do-banco-de-dados)
- [LGPD e anonimização](#lgpd-e-anonimização)
- [Custos do Gemini](#custos-do-gemini)
- [Logs e troubleshooting](#logs-e-troubleshooting)
- [Limitações conhecidas](#limitações-conhecidas)

---

## Visão geral

A cada execução, o script:

1. Confere se a hora local está entre **06:00 e 22:00** — fora disso, encerra
2. Confere se o dia é útil (segunda-sexta, sem feriado nacional via `holidays.Brazil()`) — em fim de semana ou feriado, encerra
3. Consulta o PostgreSQL para pegar os atendimentos do setor **Suporte** nos
   **últimos 30 minutos**, comparando com a média dos **mesmos 30 minutos nos
   7 dias úteis anteriores**
4. Calcula o **percentual de variação** vs. a média histórica
5. Decide o que fazer:
   - **Alta ≥ +20%** → busca as conversas do período, anonimiza dados
     sensíveis (LGPD), envia para o **Gemini 2.5 Flash** para identificar
     os 3 principais motivos de contato, e dispara alerta no Slack
   - **Queda ≤ -20%** → envia notificação informativa no Slack (sem chamar
     Gemini)
   - Caso contrário, apenas grava o ciclo no banco e sai
6. Persiste a verificação (e a análise IA, quando houver) em tabelas
   PostgreSQL

> Os limiares **+20 / -20** são constantes em [verificador.py](verificador.py)
> ([`LIMIAR_ALTA_PERCENTUAL`](verificador.py#L30) e
> [`LIMIAR_QUEDA_PERCENTUAL`](verificador.py#L34)) — ajuste conforme
> sensibilidade desejada.

---

## Como funciona

```
┌──────────────────────────────────────────────────────────────────────┐
│  ExecutaVerificacao.bat  (Task Scheduler dispara a cada N minutos)   │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  verificador.py                                                       │
│  1) Valida horário 06:00–22:00 e dia útil                             │
│  2) Lê config.ini → credenciais Postgres                              │
│  3) Query (últimos 11 dias) em lw_octadesk.chat                       │
│  4) Calcula média dos últimos 7 dias úteis no MESMO horário           │
│  5) Calcula variação % vs. atendimentos atuais                        │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
            ┌──────────┼───────────────────┐
            │          │                   │
            ▼          ▼                   ▼
   percentual ≥ +20  |percentual| < 20   percentual ≤ -20
            │          │                   │
            ▼          ▼                   ▼
   ┌─────────────┐  (só grava no    ┌──────────────────────┐
   │ Gemini path │   banco e sai)   │ notifica_boas_       │
   │             │                  │ noticias() → Slack   │
   │ get_        │                  └──────────────────────┘
   │  atendi-    │
   │  mentos.py  │
   │   ↓ anonimi-│
   │   zação LGPD│
   │ PromptGemini│
   │  .py        │
   │   ↓ Gemini  │
   │   2.5 Flash │
   │ notifica()  │
   │   → Slack   │
   └─────────────┘
            │
            └──┬──────────────────────┬─────────────────────┘
               ▼                      ▼
   ┌──────────────────────┐ ┌──────────────────────────┐
   │ lw_octadesk.         │ │ lw_octadesk.             │
   │ monitoramento_       │ │ analise_monitoramento_   │
   │ contatos             │ │ contatos                 │
   │ (uma linha por ciclo)│ │ (apenas quando IA rodou) │
   └──────────────────────┘ └──────────────────────────┘
```

---

## Estrutura de arquivos

```
Locaweb/Monitoramento/
├── ExecutaVerificacao.bat      # entrypoint para Task Scheduler
├── verificador.py              # script principal (orquestra tudo)
├── conecta_banco.py            # leitura de [database] do config.ini + factories de conexão
├── notifica.py                 # envio de mensagens no Slack (alta e queda)
├── get_atendimentos.py         # consulta + anonimização LGPD das conversas
├── PromptGemini.py             # chamada do Gemini 2.5 Flash
├── insereDados.sql             # rawdata_monitoramento → monitoramento_contatos
├── insereDadosAnaliseIA.sql    # rawdata_analise_monitoramento → analise_monitoramento_contatos
├── requirements.txt            # dependências Python (a criar — ver seção Instalação)
├── resposta_gemini.md          # dump da última resposta do Gemini (sobrescrita)
└── README.md                   # este arquivo
```

O arquivo `dados.txt` é gerado em runtime pelo pipeline (carga anonimizada
enviada ao Gemini). Está bloqueado pelo `.gitignore` da raiz do monorepo —
**não deve ser versionado**.

---

## Pré-requisitos

| Item | Versão / observação |
|------|---------------------|
| Python | 3.10+ (testado em 3.11) |
| PostgreSQL ODBC Driver | `PostgreSQL Unicode(x64)` instalado no Windows |
| Acesso de rede ao Postgres | host do banco configurado no ambiente / `seu_host:5432` |
| Acesso à API Gemini | chave válida do provedor configurada via ambiente ou `config.ini` |
| Slack App | Bot Token com escopo `chat:write` e os canais adicionados ao app |
| Locale `pt_BR.utf8` | usado por `notifica.py` para nome de mês — deve estar disponível no Windows |

---

## Instalação

```powershell
# 1. Criar e ativar venv (recomendado)
cd "Locaweb\Monitoramento"
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install pandas sqlalchemy pyodbc psycopg2-binary slack_sdk google-genai spacy holidays beautifulsoup4 numpy

# 3. (Opcional) baixar modelo spaCy português — só se for ativar a anonimização
#    de nomes via NER. Hoje o trecho do spaCy está comentado em get_atendimentos.py.
python -m spacy download pt_core_news_sm
```

> **Dica**: gere um `requirements.txt` com `pip freeze > requirements.txt`
> dentro do venv. Hoje o arquivo não existe — cada máquina instala "no olho".

---

## Configuração

Todas as credenciais ficam em um arquivo **`config.ini`** que **não deve
ser versionado** (já bloqueado pelo `.gitignore`). Copie o template
`config.ini.example` e preencha com seus valores:

```powershell
Copy-Item config.ini.example config.ini
notepad config.ini
```

Estrutura esperada:

```ini
[database]
server   = your.postgres.host
port     = 5432
database = your_database
uid      = your_user
pwd      = your_password

[slack]
bot_token = xoxb-your-token-here
; canais sao configurados em notifica.py (variavel destinatarios)

[gemini]
api_key = your-gemini-api-key-here
model = gemini-2.5-flash
```

### Caminho do `config.ini`

A função [`resolver_caminho_config()`](conecta_banco.py#L12) procura nesta
ordem:

1. Variável de ambiente `CAMINHO_ARQUIVO_CONFIGURACAO` (path absoluto)
2. `./config.ini` (mesma pasta dos scripts) — caso mais comum num clone
   isolado deste repositório
3. `../config.ini`, `../../config.ini`, `../../../config.ini` — útil quando
   o repo está dentro de uma pasta-pai que centraliza configurações de
   múltiplos projetos

Se nenhum caminho válido for encontrado, lança `FileNotFoundError` na
primeira chamada de `get_sqlalchemy_engine()`, `_get_client()` ou
`_carregar_config_gemini()`.

### Carregamento sob demanda

`conecta_banco.py`, `notifica.py` e `PromptGemini.py` fazem **lazy load**:
o `config.ini` só é lido na primeira chamada de uma função que precise
dele. Importar os módulos sem `config.ini` disponível **não quebra** —
útil para testes unitários e ambientes auxiliares.

---

## Variáveis de ambiente

Quando definidas, têm **prioridade** sobre os valores do `config.ini`:

| Variável | Efeito |
|----------|--------|
| `CAMINHO_ARQUIVO_CONFIGURACAO` | Path absoluto para um `config.ini` alternativo |
| `SLACK_BOT_TOKEN` | Sobrescreve o `[slack].bot_token` do `config.ini` |
| `GEMINI_API_KEY` | Sobrescreve a `[gemini].api_key` do `config.ini` |

Use isso em produção / CI para evitar credenciais em disco quando possível.

---

## Execução

### Manual

```powershell
cd "Locaweb\Monitoramento"
.\.venv\Scripts\Activate.ps1
python verificador.py
```

### Via `.bat`

```cmd
ExecutaVerificacao.bat
```

> O `.bat` atual contém apenas `python verificador.py`. Ele **não ativa o
> venv nem captura saída**. Se o seu Python "default" do sistema não tem as
> dependências, o `.bat` falha em silêncio quando agendado. Recomendação:
> apontar para o `python.exe` do venv e redirecionar saída para um log.

Exemplo de `.bat` mais robusto:

```cmd
@echo off
cd /d "%~dp0"
".\.venv\Scripts\python.exe" verificador.py >> logs\monitoramento.log 2>&1
```

---

## Agendamento

Sugerido: **a cada 15 ou 30 minutos**, entre 06:00 e 22:00, dias úteis. Como
o próprio script já checa horário e dia útil, é seguro agendar mais
agressivamente — execuções fora da janela são abortadas em poucos
milissegundos.

Passos no **Windows Task Scheduler**:

1. Trigger: "Daily, repeat every 15 minutes for a duration of 16 hours"
2. Action: caminho do `ExecutaVerificacao.bat`
3. Conditions → desmarque "Start the task only if the computer is on AC
   power" (se for laptop)
4. Settings → "Stop the task if it runs longer than 10 minutes" (proteção
   contra travas)

---

## Limiares e ajuste fino

Constantes definidas no topo de `verificador.py`:

| Constante | Padrão | Significado |
|-----------|--------|-------------|
| `LIMIAR_ALTA_PERCENTUAL` | `20` | Dispara análise IA + alerta Slack se variação ≥ +20% |
| `LIMIAR_QUEDA_PERCENTUAL` | `-20` | Dispara notificação informativa se variação ≤ -20% |

**Janela operacional** (em `verificador.py:43-50`):

- Hora mínima: `06:00:00`
- Hora máxima: `22:00:00`

**Janela histórica** (em `verificador.py:75`):

- `data_primaria = hoje - 11 dias` — busca 11 dias para cima para garantir
  que sobrem 7 dias úteis distintos para a média

**Período medido** (em `verificador.py:55-60`):

- Atual: últimos **30 minutos** até "agora"
- Histórico: mesmo intervalo `[H-30min, H]` em cada um dos 7 dias úteis
  anteriores
- Médio aritmético simples dos 7 valores

**Filtros da query** (em `verificador.py:106-124`):

- `a.setor = 'Suporte'`
- `d.dia_util IS TRUE`
- `JOIN public.dias d` — usa a tabela calendário corporativa para classificar
  feriados / fins de semana / mês

---

## Esquema do banco de dados

### Tabelas de **staging** (sobrescritas a cada execução)

> Atenção: ambas usam `df.to_sql(..., if_exists='replace')`, o que **dropa e
> recria** a tabela em cada ciclo. Concorrência entre execuções paralelas
> não é segura — confie no agendamento serial.

#### `lw_octadesk.rawdata_monitoramento`

Uma linha por ciclo, gerada por `verificador.py:217-234`.

| Coluna | Tipo (após cast em SQL) | Origem |
|--------|--------|--------|
| `data` | timestamp | `datetime.now()` |
| `data_inicio` | date | `data_primaria` |
| `hora_inicio` | time | `hora_10_minutos_atras_formatada` |
| `data_fim` | date | `data_hoje` |
| `hora_fim` | time | `hora_atual_formatada` |
| `dia_util` | boolean | sempre `True` |
| `media_comparativa` | float | média dos 7 dias úteis |
| `atendimentos` | integer | volume atual (30 min) |
| `percentual` | float | variação % vs. média |
| `notificou` | boolean | `True` se enviou Slack (alta ou queda) |
| `chave_analise` | varchar | UUID gerado por ciclo |
| `created_at` / `updated_at` | timestamp | `datetime.now()` |

#### `lw_octadesk.rawdata_analise_monitoramento`

Uma linha por **ciclo que disparou o Gemini** (`PromptGemini.py:156-176`).

| Coluna | Origem |
|--------|--------|
| `request` | timestamp da chamada |
| `chave` | mesmo UUID que aparece em `rawdata_monitoramento.chave_analise` |
| `tarefa` | `'monitoramento_lw_octadesk'` |
| `dados_de` / `dados_ate` | janela enviada ao Gemini |
| `analise` | rótulo da análise (= `task`) |
| `setor` | método unbound `df['setor'].unique` (legado — sai como string) |
| `input_text` | prompt completo enviado ao Gemini |
| `request_id` | identificador do candidato Gemini |
| `resposta_json` | metadados (model, tokens, snippet) em JSON |
| `resposta_text` | resposta integral em texto |
| `token_prompt` / `token_completion` | tokens consumidos |
| `model` | `'gemini-2.5-flash'` |
| `created_at` / `updated_at` | timestamp |

### Tabelas **oficiais** (append, via `INSERT INTO ... SELECT`)

Os arquivos `.sql` movem os dados das `rawdata_*` para tabelas históricas.
Execute-os apenas após o `to_sql` correspondente:

- [`insereDados.sql`](insereDados.sql) → `lw_octadesk.monitoramento_contatos`
- [`insereDadosAnaliseIA.sql`](insereDadosAnaliseIA.sql) →
  `lw_octadesk.analise_monitoramento_contatos`

Ambas as tabelas oficiais devem existir previamente — não há `CREATE TABLE`
neste repositório.

### Tabelas **consultadas** (não modificadas)

| Tabela | Uso |
|--------|-----|
| `lw_octadesk.chat` | atendimentos (1 linha por protocolo) |
| `lw_octadesk.mensagens` | conteúdo das interações (JSON com array de mensagens) |
| `public.depara_chat` | mapeamento fila → produto / equipe / setor |
| `public.dias` | calendário com `dia_util`, `feriado`, `dia_semana`, `mes` |

---

## LGPD e anonimização

Antes de enviar conversas ao Gemini, o módulo
[`get_atendimentos.py`](get_atendimentos.py) aplica uma sequência de regex
em cada mensagem (`dados_sensiveis()`):

| Padrão removido | Substituído por |
|-----------------|-----------------|
| E-mails | `[email]` |
| CPFs (`xxx.xxx.xxx-xx`) | `[CPF]` |
| CNPJs | `[CNPJ]` |
| Telefones (com/sem DDD) | `[telefone]` |
| IPs | `[IP]` |
| URLs (`http://`, `https://`) | `[link]` |
| Domínios (.com, .br, .gov.br, ...) | `[dominio]` |
| Subdomínios padrão Locaweb (`a123-cliente`) | `[subdomínio]` |
| Códigos de barras (12–14 dígitos) | `[codigo_de_barras]` |
| Nomes da Locaweb / Octadesk | `[empresa]` |
| Concorrentes (Hostgator, GoDaddy, Wix, etc.) | `[concorrente]` |
| `login: <valor>`, `senha: <valor>`, `usuário: <valor>` | `[login]`, `[senha]`, `[usuario]` |
| Palavrões selecionados | `[palavrão]` |

> **Limitação conhecida**: nomes de pessoas **não** são anonimizados por
> regex. Existia um trecho com `spaCy NER` para isso, mas está comentado.
> Para ativá-lo, descomente as linhas em
> [`get_atendimentos.py:77-80`](get_atendimentos.py#L77-L80) e garanta que
> `pt_core_news_sm` está instalado.

A carga enviada ao Gemini também é **truncada em 100.000 caracteres**
([`PromptGemini.py:42`](PromptGemini.py#L42)) — protege contra estourar o
contexto e limita o pior caso de vazamento.

---

## Custos do Gemini

O modelo padrão é `gemini-2.5-flash`, com `max_output_tokens=4096`.

- **Tokens são persistidos** por ciclo em
  `rawdata_analise_monitoramento.token_prompt` e `token_completion`
- Use essa tabela para auditar consumo e custo mensal
- O retry envolve **até 5 tentativas** com `time.sleep(20 * (i+1))` entre
  cada uma — em casos de `RESOURCE_EXHAUSTED`, isso pode adicionar 1-2
  minutos de execução





---

## Logs e troubleshooting

O pipeline usa `print()` para tudo — não há `logging` estruturado. Saída
típica de um ciclo bem-sucedido:

```
2026-05-14 e um dia util.
ultimos dias [12, 15, 18, 14, 11, 19, 16]
8f3a-...-uuid
A media da ultima semana é 15.0
A quantidade de atendimentos de hoje é: 21
O percentual em relação a mesma janela de horário é de : 40.0
Analisando interações de clientes!
 Período :2026-05-14  10:30:00 a 2026-05-14 11:00:00
Conteúdo exportado para .../dados.txt
Tentativa 1 de 5...
Resposta salva em 'resposta_gemini.md' e no banco de dados.
Mensagem enviada para o canal configurado.
Gravando verificação no banco...
```

### Cenários comuns

| Sintoma | Causa provável | Onde olhar |
|--------|---------------|------------|
| `FileNotFoundError: config.ini` | `config.ini` fora dos paths conhecidos | `CAMINHO_ARQUIVO_CONFIGURACAO` ou mova o arquivo |
| `ModuleNotFoundError: pyodbc` | venv não ativo no `.bat` | apontar para o `python.exe` do venv |
| `Locale not supported: pt_BR.utf8` | locale ausente no Windows | instalar idioma português ou trocar para `Portuguese_Brazil.1252` em `notifica.py:15` |
| Slack retorna `not_in_channel` | bot não foi convidado para o canal configurado em `destinatarios` | `/invite @nome-do-bot` no canal |
| `RESOURCE_EXHAUSTED` no Gemini | quota / RPM excedido | aguardar reset diário no Google Cloud |
| `df.empty` → encerra silenciosamente | query não retornou nada (sem chats nos últimos 11 dias?) | rodar o SQL manualmente |

---

## Limitações conhecidas

Itens em aberto, em ordem aproximada de impacto:

| Item | Risco |
|------|-------|
| `from conecta_banco import *` em alguns arquivos | Acoplamento ruim; `import *` mascara dependências |
| Sem `try/except` global em `verificador.py` | Falha silenciosa em produção sem alerta |
| Sem `logging` estruturado / arquivo de log rotativo | Diagnóstico fica preso no stdout do `.bat` |
| Conexões podem vazar em caminhos de exceção | Em ambiente com pool/limite de conexões, vira esgotamento |
| Anonimização de **nomes** desligada (spaCy comentado) | Risco LGPD residual nas conversas enviadas ao Gemini |
| `if_exists='replace'` nas rawdata | Não suporta concorrência |
| `setor = df['setor'].unique` é método unbound (já removido) | Resolvido — listado para histórico |
| Query usa f-string em vez de parâmetros nomeados | Sem injeção real hoje (valores controlados), mas é hábito a evitar |

---

## Quem mexer aqui depois...

- **Mudou os limiares?** Considere que pequenas alterações (ex.: de 20 para
  10) podem **multiplicar** as chamadas ao Gemini → impacto direto em custo
- **Mudou a janela de 30 min?** Atualize tanto `hora_30_minutos_atras` quanto
  o cálculo da `media_ultima_semana` (precisam ser o mesmo intervalo)
- **Mudou os canais Slack?** Edite a variável `destinatarios` em
  [`notifica.py:41`](notifica.py#L41). Para enviar a múltiplos canais, use
  uma lista; para enviar como DM, use IDs `U...` em vez de `C...`
- **Mudou o modelo do Gemini?** Atualize o literal `model = "gemini-2.5-flash"`
  em [`PromptGemini.py:37`](PromptGemini.py#L37). Modelos diferentes têm
  estruturas de resposta e custos distintos
