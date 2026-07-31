# Funcionalidades e Regras de Negócio

Registro de tudo que está implementado no código (`max_importa.py`, v3.0.1),
por módulo. Estas regras valem para a **importação por arquivo**; diferenças na
migração banco→banco estão em [MIGRACAO.md](MIGRACAO.md).

---

## Comum a todos os importadores

### Leitura do arquivo
- Extensões `.txt` / `.csv`; separador detectado automaticamente (TAB → `;` → `,`).
- Encoding **Latin-1**.
- Primeira linha = cabeçalho (nomes de coluna); demais = dados.
- Valores tratados como NULL: vazio e os textos `NULL`, `NONE`, `NAN` (maiús/minús).

### Multi-loja (`mi_multiloja`)
Um banco é multi-loja quando a tabela `config` tem **mais de uma linha**: cada `cofId` é
uma empresa e vira o `empId` de `produto_empresa`, `cliente_empresa` e `vendaPgto`.

- Antes de iniciar, se houver mais de uma empresa, o sistema **pergunta em quais lojas**
  a importação vale. Com uma só, nada é perguntado e o comportamento é o de sempre.
- ⚠️ A marcação quer dizer **coisas diferentes** por operação:
  - **INSERT** — onde o registro vai **aparecer**. Os dados são gravados em **todas** as
    empresas (1 linha por `cofId`); a marcação vira linhas em **`empresaFiltro`**.
  - **UPDATE** — em quais lojas os **dados** mudam (`WHERE … AND empId IN (…)`). O
    `empresaFiltro` **não é alterado**: a visibilidade pode ter sido ajustada no Manager.
- `empresaFiltro` é gravado com `IF NOT EXISTS` (reimportar não duplica), `emfUsuId = 2`
  (admin — a coluna é `NOT NULL` sem default) e `emfPkField` na grafia canônica
  (`proId` / `cliId`).
- **Financeiro é diferente:** `vendaPgto` não é replicado, cada título é de UMA loja. O
  campo **`empId`** é opcional no arquivo; vazio ou ausente → empresa **1**. `empId` fora
  da `config` **não é gravado** — a linha é pulada e entra no arquivo de erros.
- **Migração Max→Max:** a seleção é um passo do wizard, coletada antes de começar.
  A migração de **Clientes** é cópia "banco zero" e **não** passa pelo importador —
  ela cria as N linhas de `cliente_empresa` por conta própria, com `cleId` novo para
  as empresas extras (a PK vai com `IDENTITY_INSERT` ligado), e grava o
  `empresaFiltro` das marcadas.
- Desempenho: os N blocos por empresa vão **no mesmo comando**, então continua **1
  round-trip por registro**.

### UPDATE: célula vazia **não apaga** (`_montar_set_update`, em `mi_db`)
Regra única dos três caminhos de UPDATE (Produtos, Clientes por `cliId`, Clientes por
CPF/CNPJ):

- O SET é montado com os campos **mapeados E preenchidos naquela linha**. Campo com a
  célula vazia fica **de fora do SET** — o valor que está no banco é preservado.
- Vale por linha: a mesma coluna pode atualizar a linha 1 e ser ignorada na linha 2.
- **Não existe** como apagar um campo pelo arquivo. Para limpar um campo, use o Manager.
- A checagem olha o valor **cru** da célula, não o retorno dos `_get_*`: para os campos
  de `FLOAT_NOT_NULL` (`proVenda`, `proCusto`, …) o `_get_float` converte vazio em `0.0`
  — correto no INSERT (coluna NOT NULL), destrutivo no UPDATE, onde zeraria o preço.
- `0` é **valor**, não vazio: `cliDesativa = 0` (ativo) e `proVenda = 0` são gravados.
- **Obrigatório no UPDATE é só a CHAVE** (`proId` / `cliId`) — `_obrigatorios_efetivos`.
  Ainda é preciso mapear ao menos um campo além dela, senão não há o que atualizar.
  A tela reflete isso: sem selo `FALTA`, contador de obrigatórios contando só a chave e
  a seção renomeada para *"CAMPOS PRINCIPAIS (opcionais no UPDATE)"*.

### Mapeamento de colunas
- Cada campo do banco é mapeado a uma coluna do arquivo (auto-mapeamento por nome igual).
- Campos não usados ficam em `[ ignorar ]`.

### Mensagens de erro amigáveis (validação de obrigatórios)
Função `_montar_msg_obrigatorios`. Quando faltam campos obrigatórios, a mensagem traz:
- Nome **amigável** do campo + nome técnico entre `[ ]`
- Quantidade por campo (ordenado do mais problemático ao menos) e total de linhas
- Bloco **"O QUE FAZER"**
- Caminho do arquivo `ERROS_*` gerado
- Vale para os 3 importadores.

### Pós-importação (evita duplicidade)
Função `_pos_importacao`. Ao concluir (com ou sem erro):
1. Gera `ERROS_<MODULO>_*.txt` com os **nomes** dos itens/clientes que falharam.
2. **Renomeia** o arquivo importado: `<nome>_IMPORTADO_OK_<data>.<ext>` ou `..._IMPORTADO_COM_ERROS_...`.
3. **Limpa a seleção** na tela (zera dataframe, rótulo e botão) para não reimportar.

### Relatórios
- `LOG_MAX_IMPORTA_*.log` (tempo real) e `RELATORIO_MAX_IMPORTA[_CLI|_FIN]_*.txt` (fechamento).
- O cabeçalho do relatório inclui `Versao: <APP_VERSION>`.
- Relatório e `ERROS_*` são gerados **também quando a validação falha**.

---

## 📦 Produtos (`_inserir_produtos` / `_atualizar_produtos`)

Tabelas: `produto`, `produto_empresa`, `codBarras` (+ lookups).

### proId — numeração pelo banco (INSERT)
- **proId vazio** → segue o IDENTITY do banco; o ID gerado é capturado por
  `SCOPE_IDENTITY()` (INSERT + SELECT no mesmo batch, com `SET NOCOUNT ON` por
  causa das triggers AFTER) e vinculado a `produto_empresa` e `codBarras`.
- **proId informado** → INSERT explícito com `SET IDENTITY_INSERT`, com `IF NOT EXISTS`.
- Ao final, o seed do IDENTITY é reajustado para `MAX(proId)`.

### Unidade automática (`_get_or_create_unidade`)
- A unidade (`proUn`) é procurada em `produtoUn` (case-insensitive).
- **Se não existir, é cadastrada automaticamente** (`unpUn`=código, `unpDescricao`=código,
  `unpDesativar`=0, `DataInclusao`=GETDATE()) e vinculada em `proUnComercialId`,
  `proUnTrib`, `proUnTribId`.
- Ao final, lista as unidades criadas para conferência.

### Lookups / auto-criação
- **Auto-cria** se não existir: `fabricante` (fabNome), `grupoProd` (gdpNome),
  `subGrupoProd` (sgpNome, vinculado ao grupo), `produtoClasse` (pclDescricao).
- **Lookup** (deve existir): `proNCM` (ncmCodigoNCM), `proCEST` (cesCodigo).
- Código de barras (`cdbCodigo`) inserido em `codBarras` vinculado ao proId.

### CST do produto — `proCodCst1` (origem) + `proCodCst2` (tributação)
As duas partes ficam em `produto_empresa` e juntas formam o CST.
- **`proCodCst1`** é **INT** (não texto) e aceita **um único dígito de 0 a 9** —
  a origem da mercadoria; `0` = Nacional.
- **Opcional.** Não mapeado → entra o padrão **`0`** no INSERT
  (`ProdutosImportMixin.CST1_DEFAULT`), acompanhando o resto da base.
- **Valor fora de 0–9** (`55`, `A`, `1,5`) **não é gravado**: vira alerta no log e no
  relatório e o campo é ignorado — no INSERT cai no padrão, no UPDATE mantém o banco.
  A linha **não** falha por causa disso (padrão das demais regras de negócio).
- Célula vazia é ausência, não erro. Também é migrado no Max→Max (`_sql_produtos`).

### Corte automático de textos (evita erro 22001 "dados truncados")
Método `_get_str_max`. Limites aplicados: `proDescricao` 100, `proLocalizador` 20,
`proPrateleira` 20, `proCodigo` 50, `proUn` 10, `proCodCSOSN` 3, `proCodCst2` 2,
`proTipo` 1. (`proAplicacao` é varchar(max), sem corte.)

### Acerto de estoque (`_verificar_acerto_apos_sucesso` / `_gerar_acerto_estoque`)
- Após INSERT/UPDATE **com sucesso**, verifica `produto_empresa.proEstoqueAtual > 0`:
  - Sem estoque → informa que não há acerto a gerar.
  - Com estoque → habilita o botão **"Gerar Acerto de Estoque"**.
- O botão cria um **acerto PENDENTE** (`produtoAcertoEstoque` status `'A'` +
  `produtoAcertoEstoqueItem`), usando o usuário admin (`cliUsuLoginId = 2`) e o
  `empId` do destino. Deve ser **rodado no Manager** depois.
- Captura do `paeId` via `SCOPE_IDENTITY()` (triggers AFTER na tabela).

---

## 👥 Clientes (`_inserir_clientes` / `_atualizar_clientes` / `_atualizar_clientes_por_cpf`)

Tabelas: `cliente`, `cliente_empresa`.

### Campos obrigatórios (arquivo)
`cliCpfCgc`, `cliNome`, `cliFatEnd`, `cliFatBairro`, `cliFatCidade`,
`cliFatCidCodIBGE`, `cliFatUf`, `cliFatCep`.

### Campos interativos (`_tratar_campos_vazios_clientes`)
Ao clicar em INSERIR, se vazios, o sistema **pergunta** (não bloqueia):
- **cliFantasia**: se CPF → branco automático; se CNPJ → pergunta se repete o Nome
  (com aviso de risco em documentos fiscais).
- **cliRgInsc**: se CPF → branco automático; se CNPJ → pergunta ISENTO ou branco.
- **cliFatEndNumero**: pergunta S/N ou vazio.

### cliTipo (`_calc_cli_tipo`) — 0 = Pessoa Física, 1 = Pessoa Jurídica
- Se mapeado e preenchido → usa o valor.
- Se **não mapeado ou vazio** → deriva do `cliCpfCgc`: **11 díg → 0**, **14 díg → 1**.
- CPF/CNPJ vazio → deixa vazio (NULL). Trata pontuação (remove `\D`).
- Aplicado no INSERT e no UPDATE.

### cliId (INSERT)
- Com `cliId` no arquivo → INSERT explícito; IDs já existentes são **pulados**.
- Sem `cliId` → IDENTITY automático (a partir de 11).
- `cliId` de **1 a 10 são reservados** e rejeitados na importação por arquivo.

### cliente_empresa
- A cada cliente inserido, cria automaticamente o registro em `cliente_empresa`
  (empId do destino + valores padrão + cliDatCad).

### UPDATE
- Por `cliId` (chave) ou, se ausente, por **CPF/CNPJ** (o sistema pergunta).
- **Obrigatório apenas o `cliId`** (ou o `cliCpfCgc`, quando é a chave). Todos os
  demais campos são opcionais — ver *"UPDATE: célula vazia não apaga"* abaixo.
- O preenchimento assistido (Fantasia / RG-Insc / Número) **não roda no UPDATE**: ele
  preenche células vazias, que é exatamente o que não deve ser gravado por cima.
- Corte de textos (`_get_str_max`): cliNome 50, cliFantasia 50, cliRgInsc 20, etc.

---

## 💰 Financeiro (`_inserir_financeiro`)

Tabela: `vendaPgto`. **Somente INSERT.**

- Localiza o cliente pelo **CPF/CNPJ** (`_lookup_cli_id`).
- **CPF/CNPJ não encontrado** → linha pulada e registrada; ao final, janela lista os
  não inseridos com opção de salvar em `.txt`.
- Regra `pgtTipoVista` / `pgtTipoPrazo`: ao menos um dos dois preenchido por linha.
- Datas e decimais normalizados (vírgula/ponto; vários formatos de data).

---

## Modelos de importação
- `MaxImporta_Modelos_Importacao.xlsx` (abas Produtos, Clientes, Financeiro).
- `modelo de importação_cliente.txt`, `modelo de importação_Financeiro.txt`,
  `modele de importação_produto_v2.txt`.
- A aba/modelo de Clientes inclui a coluna **`cliTipo`** (0=PF, 1=PJ).
