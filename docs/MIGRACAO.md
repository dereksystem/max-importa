# Migração entre Bancos MaxData (banco → banco)

Classe `JanelaMigracao` em `max_importa.py` (v3.0.1). Copia dados **direto de um
banco para outro da MESMA instância SQL**, sem arquivo.

---

## Visão geral

- O usuário escolhe **banco de ORIGEM** e **banco de DESTINO** (lista dos bancos ONLINE).
- Marca o que migrar: **Clientes**, **Permissões**, **Produtos**, **Financeiro**.
- **Ordem fixa:** `Clientes → Permissões → Produtos → Códigos de Barras → Financeiro`
  (clientes primeiro porque os demais dependem deles).
- Produtos e Financeiro **reutilizam a lógica de INSERT** dos importadores (unidade
  automática, corte de tamanho, cliTipo, etc.).
- **NÃO** roda a validação de obrigatórios nem os prompts interativos (isso é só na
  importação por arquivo).
- Sempre gera **`RELATORIO_MIGRACAO_*.txt`** (mesmo com erro) + os relatórios por entidade.
- No fim, mostra os **TOTAIS CONSOLIDADOS** de todas as opções migradas juntas.

---

## Resiliência a schema (importante)

Os `SELECT` na origem são **montados dinamicamente** (`_sql_produtos`, `_sql_clientes`,
`_sql_financeiro` + `_cols`, `_c`, `_lookup_sub`):

- Detecta quais colunas **existem** no banco de origem.
- Colunas ausentes viram `NULL` em vez de quebrar a query.
- Funciona entre **versões/schemas diferentes** do MaxData (corrige erros como
  `cliDatCad` / `ncmCodigoNCM` inválido em bancos de schema diferente).

---

## 👥 Clientes — modo "banco zero" (`_migrar_clientes`)

> ⚠️ **DESTRUTIVO no destino.** Recomenda-se **banco de destino ZERADO**.

Fluxo:

1. **Ciência do usuário:** diálogo avisando que `cliente` e `cliente_empresa` do
   destino serão **APAGADAS** e recriadas a partir da origem. Só segue se confirmar.
2. **Leitura da origem:** TODOS os clientes (inclusive `cliId` 1–10), com os campos:
   `cliCpfCgc, DataInclusao, cliDesativa, cliEmail, cliFantasia, cliFatBairro,
   cliFatCep, cliFatCidade, cliFatCidCodIBGE, cliFatEnd, cliFatEndNumero, cliFatUf,
   cliFone, cliId, cliNome, cliRgInsc, cliTipoCad, cliTipo`.
3. **Duplicados** (critério: `cliNome` + `cliCpfCgc` iguais): informa quantos se
   repetem e pergunta:
   - **Desativar repetidos** → mantém ativo só o **mais novo (maior cliId)** e coloca
     `cliDesativa = -1` nos demais;
   - **Manter todos** → igual à origem.
4. **Desabilita as FKs** que referenciam `cliente`/`cliente_empresa`. Num banco
   "zero" os usuários-base são referenciados por **~284 FKs** (lotacUsuario,
   UsuarioPermissao, etc.); desabilitá-las permite limpar a `cliente`.
5. **Limpeza (em transação):** `DELETE FROM UsuarioPermissao` + `cliente_empresa` +
   `cliente`. Se falhar, faz rollback (nada é apagado).
6. **Reset dos identities:** `DBCC CHECKIDENT('cliente'/'cliente_empresa'/'UsuarioPermissao', RESEED, 0)`.
7. **INSERT idêntico** mantendo `cliId` (`SET IDENTITY_INSERT`), **sem** validação de
   obrigatórios e **sem** a regra de cliId reservado. Recria o vínculo em
   `cliente_empresa` (empId do destino + cliDatCad). Commit em lotes de 500.
8. **Ajuste final:** `IDENTITY_INSERT OFF` e reseed para `MAX(cliId)`.
9. **Reabilita as FKs** (sempre, via `finally`): `WITH CHECK CHECK CONSTRAINT` —
   como os cliId foram preservados, as referências das demais tabelas continuam
   válidas. Se alguma não validar, é reabilitada sem validação (com aviso no log).

Resumo: `👥 Clientes: N inseridos | M desativados | K erros`.

`DataInclusao` → gravado em `cliDatCad`. Conversões via `_to_str` / `_to_int` / `_to_dt`.

---

## 🔐 Permissões (`_migrar_permissoes`)

Tabela `UsuarioPermissao` (uspUsuId, uspObjeto).

- **Limpa** a `UsuarioPermissao` do destino e **copia idêntica** da origem
  (o `uspId` é gerado pelo destino).
- **Ignora sem erro** permissões cujo usuário não existe no destino
  (FK `uspUsuId → cliente.cliId`) — por isso migrar Clientes antes.
- É **incluída automaticamente** quando Clientes é migrado (a limpeza de
  Clientes apaga a UsuarioPermissao, que precisa ser reposta).

Resumo: `🔐 Permissões: N inseridos | M não inseridas | K erros`.

---

## 🏷️ Códigos de Barras (`_migrar_codbarras`)

Tabela `codBarras` — **mesma lógica das permissões** (wipe + cópia idêntica).

- Copia o conteúdo **completo** (`cdbIdProd`, `cdbCodigo`, `cdbCxFechada`,
  `cdbCxFechadaQtde`, `cdbCxFechadaVlrUn`, `cdbProUnId`); o `cdbId` é gerado pelo destino.
- **Limpa** a `codBarras` do destino e recopia idêntica da origem.
- **Ignora sem erro** códigos cujo produto (`cdbIdProd`) não existe no destino
  (FK `cdbIdProd → produto.proId`) — por isso roda **depois** de Produtos.
- `cdbProUnId` inexistente no destino vira `NULL`.
- Desabilita temporariamente a FK `proLote → codBarras` para permitir o DELETE e a
  reabilita ao final.

Resumo: `🏷️ Cód. Barras: N inseridos | M sem produto | K erros`.

---

## 📦 Produtos (via `_inserir_produtos`)

- Origem: `produto` + `produto_empresa` + lookups (unidade, NCM, CEST, fabricante,
  grupo, subgrupo, código de barras) — SELECT resiliente.
- **Mantém o `proId`**; produtos já existentes (mesmo proId) **não são duplicados**.
- Aplica todas as regras do importador: unidade automática, auto-criação de
  fabricante/grupo/subgrupo/classe, corte de textos.
- **NCM/CEST faltantes:** antes de inserir, copia da origem para o destino os
  cadastros de `proNCM`/`proCEST` usados pelos produtos que não existem no destino
  (`_copiar_ref_faltante`), evitando produto com `proNcmId`/`proCestId` NULL (risco
  fiscal). Copia só os códigos usados e faltantes; o id é gerado pelo destino.

### Estoque (`_tratar_estoque_migracao`) — pergunta ao iniciar
- **"Deseja migrar o estoque atual?"**
  - **Não** → `proEstoqueAtual = 0` para todos os produtos no destino.
  - **Sim** → se houver produtos com estoque **negativo** na origem, pergunta:
    - **Sim** → zera apenas os negativos;
    - **Não** → mantém os valores da origem.

### Acerto de estoque pós-migração (`_acerto_estoque_pos_migracao`)
- Ao concluir a migração de produtos, se houver `proEstoqueAtual > 0` no destino,
  gera automaticamente o **acerto de estoque PENDENTE** (status `'A'`, obs
  `MAXDATA SISTEMA - MIGRACAO`, usuário admin `cliUsuLoginId = 2`) com esses
  produtos, e um diálogo avisa o usuário para **rodar o acerto no Manager**.
- O diálogo de acerto por entidade do importador continua suprimido — o acerto da
  migração é gerado por esta rotina própria.

---

## 💰 Financeiro (via `_inserir_financeiro`)

- Origem: `vendaPgto`, trazendo o CPF/CNPJ do cliente (via `pgtClienteId`).
- Localiza o cliente **no destino pelo CPF/CNPJ**. Não encontrado → **pulado**.
- **Gera novo `pgtId`** no destino (não mantém o da origem).
- **Idempotente:** antes de inserir, verifica se já existe um lançamento igual no
  destino (chave: `empId + pgtClienteId + pgtValor + pgtData + pgtVecmto + pgtNumDoc
  + pgtTipoConta`) e, se existir, **pula**. Rodar 2× não duplica.

---

## Totais consolidados (tela final)

```
Migração de <ORIGEM> para <DESTINO> finalizada.

TOTAIS MIGRADOS:

👥 Clientes:    N inseridos | M desativados | K erros
🔐 Permissões:  N inseridos | M não inseridas | K erros
📦 Produtos:    N inseridos | K erros
💰 Financeiro:  N inseridos | M não encontrados | K erros
```

Cada importador registra seu resultado em `_ultimo_resultado`; a migração acumula em
`self._totais` e formata em `_resumo_totais`.

---

## Conferência ORIGEM × DESTINO (`_reconciliar`)

Ao final da migração, o sistema **confere automaticamente** origem contra destino e
mostra o comparativo na tela, no log e no `RELATORIO_MIGRACAO_*.txt` (apenas das
entidades migradas na execução):

| Verificação | O que compara |
|---|---|
| 👥 cliente / cliente_empresa | contagem de linhas / clientes vinculados |
| 🔐 UsuarioPermissao | contagem de linhas |
| 📦 produto | contagem de linhas |
| 📦 estoque | `SUM(proEstoqueAtual)` por empresa (origem × destino) |
| 🏷️ codBarras | contagem de linhas |
| 💰 vendaPgto | contagem de linhas e `SUM(pgtValor)` |

Status por linha:
- **✅ confere** — origem e destino iguais;
- **ℹ️ diferença esperada** — ex.: estoque zerado por opção do usuário na migração
  (o motivo aparece na própria linha, rastreado em `_estoque_obs`);
- **⚠️ divergente** — com a possível causa (permissões de usuários inexistentes,
  códigos sem produto, lançamentos pulados/pré-existentes etc.).

---

## Segurança — Backup e FKs desabilitadas

- **Backup automático** (opção no wizard, marcada por padrão): antes de migrar, gera
  um `.bak` **COPY_ONLY** do banco de destino na pasta de backup do SQL Server
  (`_backup_destino`). Se falhar, a migração é **abortada**.
- **Pré-flight de FKs** (`_fks_desabilitadas`): ao iniciar, detecta FKs
  **desabilitadas** (`is_disabled=1`) no destino — resto de migração interrompida — e
  oferece reabilitá-las (`_reabilitar_fks`). As apenas "não confiáveis" são ignoradas
  (normais no MaxData).

## Wizard de decisões (execução não assistida)

Ao clicar em "Iniciar Migração", um **único diálogo** (`_dialogo_opcoes`) coleta
todas as decisões **antes** de começar — depois a migração roda **sem interrupções**:

- **Segurança:** backup do destino (sim/não).
- **Clientes:** ciência da limpeza do destino (checkbox obrigatório) + política de
  duplicados (desativar repetidos × manter todos).
- **Produtos:** estoque (migrar × zerar) + negativos (zerar × manter da origem).

As escolhas ficam em `self._opcoes` e são lidas por `_migrar_clientes` e
`_tratar_estoque_migracao`. O aviso de acerto de estoque não abre caixa no meio do
fluxo — vai para o log e para o resumo final.

## Performance

- **Permissões** e **Códigos de Barras** são copiados com **cross-database
  `INSERT...SELECT`** (uma instrução), pois origem e destino estão na mesma instância
  — muito mais rápido que linha a linha. A guarda de FK é feita no próprio SELECT
  (`WHERE ... IN (SELECT ... FROM <tabela do destino>)`).
- **Produtos:** os lookups de NCM/CEST usam **cache em memória** por execução
  (`_lookup_cache`, somente leitura), eliminando SELECTs repetidos.

## Detalhes técnicos

- Só restam diálogos em **caminhos de erro** (ex.: falha ao limpar o destino) e no
  **resumo final**; nenhuma decisão é pedida no meio da migração.
- Origem e destino precisam estar na **mesma instância SQL** (a conectada no login).
- **Faça BACKUP do destino antes de migrar.**
