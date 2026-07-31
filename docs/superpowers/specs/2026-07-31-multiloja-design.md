# Multi-loja no MaxImporta — design

**Data:** 2026-07-31 · **Estado:** aprovado, em implementação

## Problema

O MaxImporta assume banco de **uma loja**. Todo lugar que precisa de `empId` chama
`MapeamentoDBMixin._get_emp_id`, que faz `SELECT TOP 1 cofId FROM config`. Num banco
multi-loja isso **escolhe uma empresa arbitrária** — o produto é criado em uma loja só e
o UPDATE altera uma loja só, sem erro e sem aviso.

## O que o banco real mostra (MAX_GROW, 3 empresas)

| tabela | distribuição | conclusão |
|---|---|---|
| `produto_empresa` | 2.488 × 3, exato | 1 linha por `cofId` |
| `cliente_empresa` | 6.971 / 6.345 / 6.345 | **não** é uniforme (a loja 1 tem 626 a mais) |
| `vendaPgto` | 26.552 / 11.626 / 1.275, sem repetir `pgtId` | cada título é de UMA loja |

`empresaFiltro` (`emfId` PK identity, `empId`, `emfTable`, `emfPkField`, `emfPkValue`,
`emfDataOcorrencia`, **`emfUsuId` int NOT NULL sem default**):

- clientes: 6.322 de 6.345 listados, a maioria em **1** empresa
- produtos: **35** de 2.488, todos nas 3 empresas

Não há view, procedure ou trigger citando a tabela — **a regra de visibilidade vive
dentro do MaxManager**. A leitura mais coerente com os dois conjuntos é *lista de
restrição*: sem linha = visível em todas; com linha = só nas listadas. Gravar uma linha
por empresa marcada **funciona nas duas leituras**, então a decisão não depende de
fechar essa dúvida.

⚠️ A base real grava `emfPkField` com grafia inconsistente (`cliId` nas empresas 1 e 2,
`cliid` na 3). O MaxImporta grava sempre `proId` / `cliId`.

## Decisões (do usuário)

| Questão | Decisão |
|---|---|
| Escopo | INSERT por arquivo, UPDATE por arquivo **e** migração Max→Max |
| `empresaFiltro` no UPDATE | **não tocar** — a loja pode ter ajustado no Manager |
| Dados no UPDATE | só as empresas **marcadas** na tela |
| `emfUsuId` | fixo **2** (admin), mesma convenção do acerto de estoque |
| Marcar "TODAS" no INSERT | grava **uma linha por empresa** (explícito) |
| Multi-loja na migração | passo novo no **wizard**, como no arquivo |
| `empId` inválido no Financeiro | **pula a linha** e registra no arquivo de erros |

Consequência a deixar explícita na tela: a marcação significa **coisas diferentes** por
operação — no INSERT define *onde o registro aparece* (`empresaFiltro`); no UPDATE define
*onde os dados mudam*.

## Arquitetura

### `mi_multiloja.py` (novo, sem GUI)

- `listar_empresas(cursor)` → `[{"cofId": int, "cofEmpFantasia": str}, …]`
- `e_multiloja(cursor)` → `bool`
- `registrar_filtro(cursor, emp_ids, tabela, pk_field, pk_value, usu_id=2)` — um INSERT
  por empresa, com `IF NOT EXISTS` (reimportar não duplica)
- `TABELA_POR_MODULO` = `{"PRODUTOS": ("produto", "proId"), "CLIENTES": ("cliente", "cliId")}`

### Estado no importador

- `self.empresas_alvo`: lista de `empId` **marcados**. `None` = banco de uma loja →
  comportamento de hoje (`_get_emp_id`), nada muda.
- `self.empresas_todas`: todos os `cofId` — usado para criar as N linhas de
  `produto_empresa` / `cliente_empresa`.

### INSERT (Produtos / Clientes)

- `produto_empresa` / `cliente_empresa`: **uma linha por `cofId`**, sempre todas
- `empresaFiltro`: uma linha por empresa **marcada**

A v4.0.1 juntou os INSERTs num **batch único por linha** (~4,2×). Isso é preservado: a
lista de `VALUES` das N empresas é montada **dentro do mesmo comando**. Com 3 lojas
continua **1 round-trip por registro**, não N.

### UPDATE (Produtos / Clientes)

- dados: `WHERE proId = ? AND empId IN (…marcadas…)` — um comando, não N
- `empresaFiltro`: intocado

### Financeiro

- campo mapeável novo `empId`, **opcional**, padrão `1`
- multi-loja + campo não mapeado → diálogo de confirmação antes de gravar
- `empId` fora da `config` → linha pulada, motivo no arquivo de erros

### Tela

Diálogo modal antes de iniciar, **só** quando `config` tem mais de uma linha. Colunas
`SELECIONAR` / `ID (cofId)` / `NOME (cofEmpFantasia)`, com a linha **TODAS** funcionando
como marcar-tudo. Texto conforme a operação (ver "Consequência" acima).

### Migração Max→Max

Passo novo em `_dialogo_opcoes`, só se o **destino** for multi-loja. Guardado em
`_opcoes["empresas"]` e injetado nos importadores headless — a execução segue não
assistida (o wizard coleta tudo antes de começar).

## Testes

⚠️ **Desvio consciente da instrução original.** O `MAX_GROW` é base real e não
descartável; a suíte reverte um *Database Snapshot* a cada teste, o que só existe no
`BD_ZERO_TEST`.

- **MAX_GROW** — somente leitura, para conferir schema e distribuição contra a base real
- **BD_ZERO_TEST** — os testes que gravam inserem 2 linhas em `config` para tornar a
  cópia descartável multi-loja; o revert do snapshot limpa

Cobertura pretendida:

1. unidade — `listar_empresas`, `e_multiloja`, SQL do `registrar_filtro`, dedupe
2. unidade — INSERT monta N linhas de `produto_empresa` no mesmo batch
3. unidade — UPDATE usa `empId IN (…)` só com as marcadas
4. integração — INSERT em banco de 3 lojas cria 3 linhas de `produto_empresa` e as
   linhas de `empresaFiltro` das marcadas
5. integração — reimportar não duplica `empresaFiltro`
6. integração — UPDATE altera só as marcadas e **não** mexe no `empresaFiltro`
7. integração — Financeiro com `empId` do arquivo; `empId` inexistente pula a linha
8. regressão — banco de **uma** loja continua idêntico ao de hoje

## Fora de escopo

- Preço/estoque diferente por loja no INSERT (as N linhas nascem iguais)
- Reconstruir o `empresaFiltro` de registros já existentes
- Migrar o `empresaFiltro` da origem (decidido: vem do wizard)
