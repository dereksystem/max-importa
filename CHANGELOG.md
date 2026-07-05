# Changelog — Max_Importa

Formato **MAJOR.MINOR.PATCH**. A versão fica em `max_importa.py` → `APP_VERSION`
e aparece na tela de login, nos títulos das janelas e no cabeçalho dos relatórios.

> Registro em markdown. O histórico detalhado original também está em
> [`CHANGELOG.txt`](CHANGELOG.txt).

---

## [3.6.2] — 2026-07-05

### Visual — Clean Corporate agora aplica as superfícies (correção)
- Na 3.6.1 só os **acentos** (vermelho/tons) tinham mudado; janela, cards e inputs
  seguiam no cinza do tema interno do CustomTkinter — no claro a diferença ficava quase
  imperceptível.
- Agora o tema sobrescreve as **superfícies** (uma função no startup): janela = página
  clara (`#F7F8FA`/`#16181C`), **cards brancos** (`#FFFFFF`/`#1D2025`), inputs/combos/
  textbox/checkbox/scroll/segmented no padrão Clean Corporate. Botões seguem o vermelho da
  marca (`#CC0000`). Sem alterar nenhuma função — só tema.

---

## [3.6.1] — 2026-07-05

### Visual — tema "Clean Corporate" (paleta claro/escuro)
- Retematização para um visual mais limpo/corporativo, **sem alterar nenhuma função ou
  lógica** — só cores/tons e a fonte do log.
- Paleta centralizada em `mi_config.py` passou a usar **tuplas `(claro, escuro)`** — o
  CustomTkinter alterna sozinho; o botão de tema do menu deixa os dois modos consistentes.
- **Vermelho da marca mantido** (`#CC0000` no claro, `#E5433D` no escuro), agora como
  **acento** e não plano de fundo. Fundos obrigatório/chave em **vermelho suave** (fim do
  rosa saturado); texto principal mais nítido; verde de "campo mapeado" mais discreto.
- Modo padrão continua **claro**. Log em **Consolas** no lugar de Courier.

---

## [3.6.0] — 2026-07-05

### Mapeamento de colunas — feedback visual
- Nas telas de importação (**Produtos, Clientes, Financeiro**), cada campo do mapeamento
  mostra um **indicador**: **✓** (verde) mapeado · **✗** (vermelho) obrigatório não mapeado ·
  **—** (cinza) opcional não mapeado.
- A **linha inteira** do campo fica com um **verde suave** quando mapeada (volta à cor
  original ao desmapear).
- Um **resumo** abaixo da lista informa em tempo real: `✓ X/Y campos mapeados — todos os
  obrigatórios OK.` ou `⚠ X/Y — faltam obrigatórios: <lista>`.
- Atualiza a cada seleção de coluna e após o auto-mapeamento (ao carregar o arquivo).

---

## [3.5.0] — 2026-07-04

### Auditoria no destino — tabela `MaxImporta_Auditoria`
- Ao final de cada **migração**, registra no próprio banco de **destino** o que foi
  feito, numa tabela **criada automaticamente** (`dbo.MaxImporta_Auditoria`, prefixo
  próprio — não colide com o MaxData).
- **Uma linha por entidade migrada**: data/hora, versão, origem, destino, **usuário SQL**
  (`SUSER_SNAME()`), entidade, inseridos/pulados/erros, cancelada, e `audSessao` (agrupa
  a execução).
- Histórico acumulado (a tabela é reaproveitada). Registro **best-effort** — não
  interrompe a migração se falhar.
- Consulta: `SELECT * FROM MaxImporta_Auditoria ORDER BY audDataHora DESC`.

---

## [3.4.0] — 2026-07-04

### Logs estruturados — exportação em JSON e CSV (além do `.txt`)
- Ao concluir cada importação (**Produtos/Clientes/Financeiro**), além do
  `RELATORIO_*.txt`, são gerados na pasta de logs:
  - `RESULTADO_<OP>_<data_hora>.json` — resumo estruturado: versão, banco, contagens
    (inseridos/pulados/erros), itens com erro e, no Financeiro, os CPF/CNPJ não encontrados.
  - `ERROS_<OP>_<data_hora>.csv` — itens com erro em CSV (abre no Excel; UTF-8 com BOM),
    quando houver erros.
- Na **migração**: `RESULTADO_MIGRACAO_<data_hora>.json` com os **totais por entidade**,
  origem e se foi cancelada.
- Exportação **best-effort**: se falhar, só registra um aviso e não interrompe a operação.

---

## [3.3.0] — 2026-07-04

### Progresso por registro — contador "X de Y (NN%)"
- Além da barra, um **rótulo** mostra em tempo real quantos registros já foram
  processados — ex.: `1.250 de 8.000 (15%)`.
- Vale para os 3 importadores (**Produtos, Clientes, Financeiro**), incluindo os
  UPDATEs. Na **migração**, mostra a etapa com o nome da entidade — ex.:
  `Clientes — 1 de 5 (20%)`.
- Reinicia (`iniciando...`) a cada operação; atualização thread-safe (agendada na GUI).

---

## [3.2.2] — 2026-07-04

### Login — Botão "Confirmar Banco e Avançar" só após validar
- O botão **"Confirmar Banco e Avançar"** agora **aparece somente após a conexão ser
  validada** (credenciais OK e bancos listados). Antes ficava sempre visível, apenas
  desabilitado.
- Some novamente ao **trocar credenciais**, em **falha de conexão** ou quando **nenhum
  banco** é encontrado — reforçando que é preciso conectar de novo.

---

## [3.2.1] — 2026-07-04

### Segurança — Credenciais de conexão
- A **senha padrão saiu do binário**. Antes o app trazia `sa`/`macro01` **fixos no
  código** (extraíveis do `.exe`). Agora só o usuário `sa` (não é segredo) é sugerido;
  a **senha começa vazia** e é digitada pelo usuário.
- Novo seletor de **autenticação** em *Editar credenciais*:
  - **SQL Server** (usuário + senha), ou
  - **Windows** (integrada — `Trusted_Connection`, **sem senha**; campos usuário/senha
    ficam desabilitados e nada sensível é guardado).
- Novo **"Lembrar credenciais nesta máquina"**: salva servidor/usuário/modo no
  `max_importa.ini` e a **senha criptografada via Windows DPAPI** (`CryptProtectData`).
  O texto cifrado só é decifrável pelo **mesmo usuário Windows, na mesma máquina** — não
  fica em texto puro nem é portável. Sem "lembrar", a seção `[Conexao]` é **removida**.
  Criptografia via `ctypes` (API nativa do Windows) — **sem dependência nova**.
- Connection string centralizada em `_montar_base_conn_str` (login/menu/migração
  reaproveitam a mesma base; SQL auth idêntico ao anterior).

---

## [3.2.0] — 2026-07-04

### Botão Cancelar — interromper importação/migração com segurança
- Todas as janelas (**Produtos, Clientes, Financeiro e Migração**) ganharam um botão
  **"⏹ Cancelar"**, habilitado apenas enquanto uma operação está em andamento.
- Cancelamento **cooperativo**, apenas em pontos **seguros**:
  - **Importadores** (Produtos/Clientes/Financeiro): **entre registros**. Como o commit
    é por linha, os registros já gravados permanecem e nada fica pela metade.
  - **Migração**: **entre entidades**. A entidade em andamento é concluída inteira
    (banco consistente, FKs reabilitadas) e as restantes **não** são executadas. Não
    interrompe no meio de uma entidade (FKs desabilitadas, `IDENTITY_INSERT`, commits em
    lote) para não deixar o destino inconsistente.
- Migração cancelada mostra **título/mensagem próprios**, lista no log as entidades não
  migradas e só faz a **conferência** (origem × destino) das entidades efetivamente migradas.
- O botão é **rearmado automaticamente** a cada nova operação.

---

## [3.1.5] — 2026-07-04

### Migração — Performance
- **Permissões** e **Códigos de Barras** passaram a ser copiados via
  **cross-database `INSERT...SELECT`** (uma única instrução — origem e destino na
  mesma instância) em vez de linha a linha. Ex.: ~907 permissões em ~0,2s. A guarda
  de FK continua (só copia registros cujo `cliId`/`proId` exista no destino).
- **Produtos:** cache em memória (por execução) dos lookups de **NCM/CEST**. Como é
  somente leitura, é seguro e elimina milhares de SELECTs repetidos em catálogos
  grandes (1000 lookups → 3 SELECTs no teste).

---

## [3.1.4] — 2026-07-04

### Migração — Idempotência do Financeiro (não duplica)
- Na migração de **Financeiro**, antes de inserir cada lançamento, verifica se já
  existe um **igual** no destino e, se existir, **pula** (não duplica). Rodar a
  migração 2× (ex.: após falha) **não gera lançamentos repetidos**.
- Chave: `empId + pgtClienteId + pgtValor + pgtData + pgtVecmto + pgtNumDoc + pgtTipoConta`.
- A importação por **arquivo** continua sem dedup (inalterada); o dedup vale só na migração.

---

## [3.1.3] — 2026-07-03

### Migração — Backup automático e FKs desabilitadas
- **Backup automático** do banco de destino antes de migrar (opção no wizard, marcada
  por padrão): gera um `.bak` **COPY_ONLY** na pasta de backup padrão do SQL Server.
  Se o backup falhar, a migração é **abortada por segurança**.
- **Pré-flight:** ao iniciar, detecta FKs **desabilitadas** (`is_disabled=1`) no destino
  — sinal de migração anterior **interrompida** — e oferece **reabilitá-las** (com
  validação). Ignora as apenas "não confiáveis" (`is_not_trusted`), normais no MaxData.

---

## [3.1.2] — 2026-07-02

### Migração — Wizard de decisões antecipadas (execução não assistida)
- Todas as perguntas que antes apareciam **durante** a migração foram movidas para
  um **único diálogo antes de iniciar** (wizard). A migração roda do início ao fim
  **sem interação** — ideal para bases grandes.
- O wizard coleta: **Clientes** (ciência da limpeza + política de duplicados) e
  **Produtos** (estoque migrar/zerar + negativos zerar/manter).
- O aviso de "acerto de estoque gerado" **não interrompe mais o fluxo**: vai para o
  log e para o **resumo final** da migração.

---

## [3.1.1] — 2026-07-02

### Migração — NCM/CEST faltantes (evita perda fiscal silenciosa)
- Ao migrar **Produtos**, o sistema **copia** da origem para o destino os cadastros
  de **NCM** (`proNCM`) e **CEST** (`proCEST`) usados pelos produtos que não existem
  no destino — assim o produto migra com o NCM/CEST correto (antes ficava
  `proNcmId`/`proCestId = NULL` sem avisar, impedindo emissão fiscal).
  - Copia só os códigos **usados e faltantes**; o id é gerado pelo destino; colunas
    de identity e de auditoria são ignoradas.
- A **conferência pós-migração** passou a incluir "produtos sem NCM (proNcmId nulo)"
  no destino, com alerta quando > 0.

---

## [3.1.0] — 2026-07-02

### Migração — Conferência ORIGEM × DESTINO (reconciliação)
- Ao final da migração, o sistema **confere automaticamente** a origem contra o
  destino e mostra o comparativo na tela, no log e no `RELATORIO_MIGRACAO_*.txt`:
  - **Contagens:** `cliente`, `cliente_empresa`, `UsuarioPermissao`, `produto`,
    `codBarras`, `vendaPgto`;
  - **Somas:** estoque (`SUM proEstoqueAtual` por empresa) e financeiro
    (`SUM pgtValor`).
- Status por linha: **✅ confere**, **ℹ️ diferença esperada** (ex.: estoque zerado
  por opção do usuário) ou **⚠️ divergente** (com a possível causa).
- Só confere as entidades migradas na execução.

---

## [3.0.4] — 2026-07-02

### Migração — Códigos de Barras (codBarras)
- Nova opção **"Códigos de Barras"** na migração: copia o conteúdo **completo** da
  tabela `codBarras` (todos os códigos de cada produto), com a **mesma lógica das
  permissões** (limpa o destino + cópia idêntica; o `cdbId` é gerado pelo destino).
- Ordem: `Clientes → Permissões → Produtos → Códigos de Barras → Financeiro`
  (codBarras entra após Produtos por causa da FK `cdbIdProd → produto.proId`).
- Ignora (sem erro) códigos cujo produto não existe no destino; `cdbProUnId`
  inexistente vira NULL. Desabilita a FK `proLote → codBarras` para permitir a
  limpeza e a reabilita ao final.

---

## [3.0.3] — 2026-07-02

### Migração de Clientes — limpeza robusta (FK) e Permissões idênticas
- **Corrige** o erro `DELETE conflitou com a restrição REFERENCE fk_UsuarioPermissao…`
  ao limpar o destino. Num banco "zero", os usuários-base são referenciados por
  **284 FKs** — limpar só a `UsuarioPermissao` não bastava.
- A migração de Clientes agora **desabilita temporariamente** as FKs que referenciam
  `cliente`/`cliente_empresa`, **limpa** `UsuarioPermissao` + `cliente_empresa` +
  `cliente`, insere idêntico (mantendo os `cliId`) e **reabilita** as FKs (validando;
  como os cliId são preservados, as referências das demais tabelas seguem válidas).
- **`UsuarioPermissao`** passou a ser **limpa e recopiada idêntica** à origem.
- Permissões entram **automaticamente** quando Clientes é migrado.

---

## [3.0.2] — 2026-07-01

### Migração de Produtos — estoque e acerto automático
- Ao iniciar a migração de **Produtos**, pergunta se deseja **migrar o estoque atual**
  (`proEstoqueAtual`):
  - **Não** → todos os produtos entram com estoque **zero** no destino.
  - **Sim** → se houver produtos com estoque **negativo** na origem, pergunta se
    deseja iniciá-los com zero (Sim = zera só os negativos | Não = mantém da origem).
- Após concluir a migração de produtos, se houver estoque > 0 no destino, gera
  automaticamente o **acerto de estoque PENDENTE** (status `'A'`) com esses produtos
  e avisa o usuário para **rodar o acerto no Manager**.

---

## [3.0.1] — 2026-07-01

### Migração de Clientes — modo "banco zero"
- A migração de **Clientes** passou a ser uma **cópia idêntica com limpeza do destino**:
  - Antes de iniciar, **avisa** que `cliente` e `cliente_empresa` do destino serão
    **apagadas** e sugere usar um **banco zerado**.
  - Após ciência, **limpa** as duas tabelas (em transação — se houver dados
    relacionados/FK, a limpeza é bloqueada e nada é apagado) e **reseta os identities**
    (`DBCC CHECKIDENT reseed 0` → começa do 1).
  - Copia **todos os `cliId`** (inclusive 1–10) idênticos à origem, **sem** validação
    de obrigatórios e **sem** a regra de cliId reservado.
  - **Duplicados** (`cliNome` + `cliCpfCgc`): pergunta se deseja **desativar** os
    repetidos (mantém ativo só o mais novo — maior cliId — e `cliDesativa = -1` nos
    demais) ou manter todos.

---

## [3.0.0] — 2026-07-01 — Migração entre Bancos MaxData

### Novo módulo — Migração banco → banco
- Copia dados direto de um banco para outro da **mesma instância SQL**, sem arquivo.
- Escolha de **origem** e **destino**; migra **Clientes, Permissões, Produtos, Financeiro**.
- Ordem: `Clientes → Permissões → Produtos → Financeiro`.
- Reutiliza a lógica de INSERT dos importadores.

### Resiliência a schema + relatório
- SELECTs de origem **montados dinamicamente**; colunas ausentes viram `NULL`
  (funciona entre versões/schemas diferentes do MaxData).
- **Sempre** gera `RELATORIO_MIGRACAO_*.txt`, inclusive em erro.

### Permissões e totais
- Opção **Permissões de Usuário** (`UsuarioPermissao`): pula existentes; ignora
  (sem erro) usuários inexistentes no destino.
- **Totais consolidados** na tela ao final.

### Acerto de estoque (produtos)
- Após import/update de produtos com sucesso, se houver `proEstoqueAtual > 0`,
  habilita **"Gerar Acerto de Estoque"** (cria acerto PENDENTE para rodar no Manager).

### Correções
- Tela de login redimensionada (botão "Confirmar Banco" visível).

---

## [2.1.0] — 2026-07-01 — Baseline (pré-migração)

### Produtos
- `proId` vazio segue a numeração do banco (IDENTITY via `SCOPE_IDENTITY`).
- **Unidade** inexistente cadastrada automaticamente em `produtoUn`.
- **Corte automático** de textos longos (fim do erro "dados truncados").

### Clientes
- Novo campo **`cliTipo`** (0=PF, 1=PJ); derivado do CPF/CNPJ quando não mapeado.
- Campos **Fantasia / RG / Número** com tratamento interativo (não bloqueiam).

### Mensagens / Logs
- Mensagens de erro de obrigatórios **amigáveis** (3 importadores).
- Relatório + `ERROS_*` gerados também na falha de validação.
- Arquivo importado **renomeado** com status + data/hora; seleção limpa na tela.

### Build
- `BUILD.bat` instala o **Python** automaticamente e se reabre **sem elevação**.
- **Pillow** empacotado no `.exe` (fim do erro "No module named 'PIL'").
- **Ícone** do X da MaxData aplicado ao `.exe`.
