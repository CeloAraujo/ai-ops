# AI-Ops

Plataforma de apoio à operação de aplicações. O projeto tem três partes com objetivos diferentes: um verificador leve para executar localmente, um serviço de produção que consulta Kubernetes e Prometheus e responde perguntas com um agente de IA, e laboratórios didáticos com exemplos e simulações.

**Autor: Marcelo Araujo**

## O que o AI-Ops faz

Na instalação de produção, o AI-Ops roda como um serviço separado dentro do Kubernetes. Com acesso somente de leitura, ele lista os pods do namespace em que está instalado e consulta as métricas Prometheus que você configurar. O endpoint `/ask` envia a pergunta e essas evidências para o modelo configurado e devolve uma resposta em português. O endpoint `/diagnostics` mostra as evidências coletadas, e `/metrics` expõe métricas do próprio serviço.

O agente atual ajuda a resumir dados e apontar sinais que merecem investigação. Ele não altera deployments, reinicia pods, corrige incidentes nem descobre automaticamente todas as fontes de dados. Logs, traces, alertas, outros namespaces e ações automáticas exigem integrações adicionais. A chave Groq é usada para gerar respostas; os dados e consultas vêm do cluster e do Prometheus configurados.

## Arquitetura em contexto

```text
Aplicações e pods no namespace
             │ leitura via Kubernetes API
             ▼
         AI-Ops API ─────────► Prometheus (consultas PromQL configuradas)
             │
             ├── GET /diagnostics  evidências atuais
             ├── POST /ask         resposta do agente baseada nas evidências
             ├── GET /metrics      métricas do serviço AI-Ops
             └── /health/*         probes do Kubernetes
```

- **Kubernetes** executa e mantém aplicações em containers. Um cluster é o ambiente Kubernetes; pods são as unidades onde containers rodam. O AI-Ops é implantado como outro Deployment, separado da aplicação monitorada.
- **Prometheus** coleta e consulta séries numéricas, como uso de CPU e reinícios de containers. No AI-Ops, as consultas PromQL são definidas na configuração do Deployment.
- **Grafana** pode exibir painéis com dados do Prometheus. Ele não é necessário para o AI-Ops consultar métricas e não está conectado automaticamente nesta versão.
- **Agente de IA** interpreta a pergunta junto com o snapshot de pods e resultados Prometheus. A IA não coleta esses dados por conta própria; as integrações do AI-Ops os obtêm e os fornecem como contexto.
- **Terraform** aparece nos laboratórios como ferramenta de Infraestrutura como Código. Ele pode criar infraestrutura de nuvem de forma declarativa, mas não é necessário para construir ou instalar o AI-Ops no Kubernetes usando os manifestos incluídos.

## Instalação de produção no Kubernetes

Clone este repositório e entre na pasta:

```bash
git clone https://github.com/CeloAraujo/ai-ops.git
cd ai-ops
```

### Pré-requisitos

- Cluster Kubernetes acessível e `kubectl` configurado.
- Docker ou outro construtor de imagens e um registry acessível pelo cluster.
- Prometheus instalado e acessível pela rede interna do cluster, com as métricas consultadas disponíveis (por exemplo, métricas de containers fornecidas por kube-state-metrics/cAdvisor).
- Chave de API Groq para habilitar respostas do agente.
- Permissão para criar Deployment, Service, ServiceAccount, Role, RoleBinding e Secret no namespace escolhido.

### 1. Escolha o namespace e configure os manifestos

Na pasta `AI-ops`, crie o namespace que o AI-Ops observará. A Role incluída lista pods somente no namespace de instalação, então mantenha o AI-Ops no namespace da aplicação que deseja analisar.

```bash
kubectl create namespace minha-aplicacao
```

Edite `production/kubernetes.yaml` antes de instalar:

1. Atualize `AIOPS_APP_NAME` para identificar sua aplicação.
2. Troque `ai-ops:production` pelo nome da imagem que será publicada no seu registry.
3. Configure `PROMETHEUS_URL` com o endereço DNS e porta do serviço Prometheus no seu cluster.
4. Ajuste as consultas em `PROMETHEUS_QUERIES` para as métricas disponíveis no seu Prometheus. O marcador `{namespace}` é substituído pelo namespace onde o AI-Ops está instalado.

O manifesto contém consultas de exemplo para CPU e reinícios de pods. Se as séries usadas por elas não existirem no seu Prometheus, `/diagnostics` mostrará erro ou resultado vazio para essas consultas; use os nomes de métricas presentes no seu ambiente. O serviço limita a 12 consultas configuradas, 50 amostras por consulta e tamanho máximo de 2 MB por resposta.

### 2. Construa e publique a imagem

Execute os comandos na pasta `AI-ops`, trocando o registry pelo seu:

```bash
docker build -f production/Dockerfile -t SEU_REGISTRY/ai-ops:1.0.0 .
docker push SEU_REGISTRY/ai-ops:1.0.0
```

Confirme que o campo `image` no `production/kubernetes.yaml` usa essa mesma imagem. Se o cluster não puder acessar o registry, publique a imagem em um registry privado acessível ou carregue-a no cluster seguindo o procedimento da sua plataforma.

### 3. Crie o segredo da API

Não coloque a chave no manifesto nem no Git. Prefira integrar um gerenciador de segredos da sua plataforma. Para uma instalação inicial, no Bash:

```bash
export AIOPS_API_TOKEN="$(openssl rand -hex 32)"
kubectl -n minha-aplicacao create secret generic ai-ops-secrets \
  --from-literal=groq-api-key="$GROQ_API_KEY" \
  --from-literal=api-token="$AIOPS_API_TOKEN"
```

No PowerShell:

```powershell
$env:AIOPS_API_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
kubectl -n minha-aplicacao create secret generic ai-ops-secrets `
  --from-literal=groq-api-key=$env:GROQ_API_KEY `
  --from-literal=api-token=$env:AIOPS_API_TOKEN
```

O Secret precisa conter `groq-api-key`, usada para chamar o modelo, e `api-token`, usado para proteger a API. Se já tiver criado o Secret com somente a chave Groq, atualize-o pelo gerenciador de segredos ou recrie-o com as duas entradas. Entregue o token somente a clientes autorizados e planeje sua rotação.

### 4. Instale o serviço

```bash
kubectl -n minha-aplicacao apply -f production/kubernetes.yaml
kubectl -n minha-aplicacao get pods,services
kubectl -n minha-aplicacao rollout status deployment/ai-ops
```

O Deployment roda duas réplicas sem estado e sem root, espalha os pods entre nós quando possível, protege uma réplica contra interrupções voluntárias e atualiza sem reduzir a quantidade disponível. Também define limites de CPU e memória e probes de vida e prontidão. O ServiceAccount pode apenas listar pods; não pode editar ou reiniciar recursos. O AI-Ops precisa de saída de rede para o Prometheus e para a API Groq.

### Segurança e dados

As rotas `/ask` e `/diagnostics` usam um token Bearer compartilhado de pelo menos 32 caracteres. Distribua-o somente a clientes autorizados, guarde-o num gerenciador de segredos e faça rotação quando necessário (a rotação do Secret exige reiniciar os pods). Para um ambiente com vários usuários, coloque a API atrás do gateway corporativo com identidade individual (OIDC), TLS e limite de requisições. O serviço também limita perguntas simultâneas por réplica; isso não substitui rate limiting no gateway nem controle corporativo de identidade.

O endpoint `/metrics` não pede esse token para que Prometheus possa coletá-lo; restrinja o acesso de rede a essa rota ao coletor. O Service incluído é interno ao cluster e não cria um Ingress público. O manifesto ainda não instala uma NetworkPolicy porque as origens de tráfego, o CNI e a rede do Kubernetes variam por empresa; restrinja o tráfego ao gateway autorizado, ao scraper e ao plano de controle conforme a política do seu cluster. Se publicar a API fora do cluster, use TLS e autenticação no gateway. A chamada do agente envia a pergunta e um resumo agregado de status de pods e valores numéricos de métricas à API da Groq. A rota autenticada `/diagnostics` mostra detalhes mais completos, incluindo nomes de pods e labels devolvidos pelas consultas. Verifique a política de dados da sua empresa antes de ativar o agente com dados reais.

O modelo não deve receber segredos nas métricas nem nas perguntas. Restrinja quem pode configurar PromQL, limite a saída de rede ao necessário e use TLS no acesso ao Prometheus quando houver certificado confiável. Esta versão não configura autenticação no Prometheus; se ele exigir credenciais, conecte por um proxy interno autenticado ou implemente o método aprovado pela sua plataforma. O AI-Ops não executa ferramentas ou comandos sugeridos pelo modelo. A prontidão verifica Kubernetes e `/-/ready` do Prometheus, mas não faz uma chamada de teste à Groq nem valida cada consulta PromQL.

As perguntas simultâneas são limitadas por processo (quatro por réplica por padrão; excesso recebe HTTP 429). Isso protege recursos, mas não limita a quantidade total de chamadas ou custos por minuto. Configure limite de taxa e quota no gateway/API corporativa. O número de perguntas bem-sucedidas, falhas, falhas de autenticação, erros de fonte e duração aparecem em `/metrics` sem labels de usuário ou token.

### 5. Faça uma pergunta e confira os dados

Abra um túnel local para o serviço:

```bash
kubectl -n minha-aplicacao port-forward service/ai-ops 8080:8080
```

Em outro terminal, consulte o serviço:

```bash
curl http://localhost:8080/health/ready
curl -H "Authorization: Bearer $AIOPS_API_TOKEN" http://localhost:8080/diagnostics
curl -X POST http://localhost:8080/ask \
  -H "Authorization: Bearer $AIOPS_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Quais pods tiveram reinícios e o que mostram as métricas de CPU?"}'
curl http://localhost:8080/metrics
```

No PowerShell, os endpoints GET podem ser acessados com `Invoke-RestMethod`. Para `/ask`:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8080/ask `
  -Headers @{ Authorization = "Bearer $env:AIOPS_API_TOKEN" } `
  -ContentType 'application/json' `
  -Body '{"question":"Quais pods tiveram reinícios?"}'
```

`/health/live` indica que o processo está ativo. `/health/ready` verifica a configuração e o acesso ao Kubernetes e ao endpoint de prontidão do Prometheus; ela não valida cada expressão PromQL nem testa a API Groq. `/diagnostics` exibe os pods e o resultado de cada consulta configurada. `/ask` responde usando contexto agregado: não envia nomes de pods ou labels de métricas ao modelo. Ambos exigem `Authorization: Bearer SEU_TOKEN`. `/metrics` expõe métricas Python e contagem de perguntas para coleta pelo Prometheus; esse endpoint não usa o token da API e deve ficar acessível apenas ao coletor de métricas na rede do cluster. As anotações de scrape do Pod são um exemplo; dependendo da instalação Prometheus, configure um `ServiceMonitor` ou a descoberta de serviços compatível com o seu ambiente.

### Ajustes comuns e diagnóstico

- **Pods não aparecem:** confirme que o AI-Ops está no namespace esperado e que o Pod está usando o ServiceAccount `ai-ops` criado pelo manifesto.
- **Erro ao consultar Prometheus:** confira DNS, porta, acesso de rede, URL e se o endpoint Prometheus permite consultas a partir do AI-Ops. Esta versão não envia credenciais Prometheus; se forem necessárias, use um proxy interno aprovado ou implemente a autenticação antes da instalação.
- **Consulta sem resultados:** verifique no Prometheus/Grafana se a série existe e ajuste a expressão PromQL e o label de namespace.
- **`/ask` ou `/diagnostics` retorna 401:** envie o token correto no cabeçalho `Authorization: Bearer ...`.
- **`/ask` retorna erro da Groq:** confirme que o Secret tem a chave correta, que a rede permite a saída para a API Groq e que a chave/modelo estão válidos.
- **Resposta sem dados de logs ou traces:** esta versão não consulta logs nem tracing; só usa inventário de pods e consultas Prometheus configuradas.
- **Rotação de segredo:** atualize o Secret no seu gerenciador e reinicie o Deployment para os containers carregarem os novos valores.

## O que você pode ganhar com o AI-Ops

- Reunir estado básico dos pods e métricas escolhidas num único diagnóstico.
- Perguntar em linguagem natural sobre os dados coletados, reduzindo o tempo para localizar sinais de reinícios ou consumo elevado.
- Padronizar consultas e verificações operacionais entre aplicações.
- Expor métricas do próprio serviço para acompanhar uso e integrar à observabilidade existente.
- Começar com acesso restrito de leitura e ampliar fontes de dados de forma controlada.
- Limitar o consumo do agente com controle de concorrência por réplica, limites de saída e métricas de erro, acesso não autorizado e duração.
- Usar o resultado como apoio à análise humana; decisões e mudanças de produção continuam com a equipe.

Os benefícios dependem da qualidade das métricas, das consultas e da configuração de rede. O AI-Ops não substitui Prometheus, Grafana, alertas, logs, tracing, runbooks nem a experiência de quem opera o sistema.

## Verificador genérico local

O script `aiops.py` é uma ferramenta leve e separada do serviço de produção. Ele verifica URLs HTTP e executa comandos de saúde definidos em JSON, sem precisar instalar as dependências de produção.

```bash
python aiops.py aiops.config.demo.json
```

Para conectá-lo a uma aplicação, copie `aiops.config.example.json` para `aiops.config.json`, substitua a URL de exemplo pelo health endpoint real e rode `python aiops.py`. A opção `--json` imprime o resultado como JSON. O processo retorna código `0` se todas as verificações passaram, `1` se alguma falhou e `2` se a configuração for inválida. Esse verificador não consulta Kubernetes nem envia perguntas a um agente.

## Laboratórios e simulações

Os diretórios `labs/`, `tools/`, `ui/`, `data/`, `k8s/` e `slides/` contêm materiais didáticos que vieram com o projeto, incluindo exemplos de CrewAI, Terraform, LocalStack, Kubernetes e cenários de incidentes. Os manifestos `checkout-broken.yaml` e `checkout-k8s-fix.yaml` foram colocados em `labs/simulations/`. Eles não são instalados pelo perfil de produção e não são incluídos na imagem `production/Dockerfile`. `k8s/secret.example.yml` é apenas um modelo; o arquivo local preenchido `k8s/secret.yml` é ignorado pelo Git.

As dependências adicionais desses materiais estão em `requirements.txt`. Para instalá-las em ambiente virtual:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Alguns laboratórios exigem `GROQ_API_KEY`, `kubectl`, cluster acessível, LocalStack ou outros serviços. Eles são demonstrações independentes e não representam conectores de produção automaticamente habilitados.

## Verificações automatizadas

Os testes de produção cobrem autenticação Bearer, rejeição de campos inesperados, remoção de nomes e labels do contexto enviado ao agente e substituição do namespace nas consultas PromQL. Com a imagem de produção construída, rode:

```bash
docker run --rm --entrypoint python -v "$PWD/tests:/tests:ro" ai-ops:production -m unittest discover -s /tests -v
```

Esses testes não substituem um teste de integração num cluster real. Antes de publicar uma versão, valide também acesso RBAC, rede para Prometheus e Groq, consultas do seu ambiente e regras de segurança do cluster.

## Arquivos principais

```text
production/app.py               API do serviço de produção e agente
production/Dockerfile            imagem enxuta do serviço de produção
production/kubernetes.yaml      RBAC, Deployment e Service
requirements-production.txt    dependências diretas da produção
requirements-production.lock.txt versões resolvidas para builds repetíveis
aiops.py                         verificador HTTP/comandos local
labs/simulations/                manifestos de cenários didáticos
```

## Autor

Marcelo Araujo
