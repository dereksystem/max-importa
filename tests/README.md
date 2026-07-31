# Testes — Max_Importa

Suíte de regressão para não quebrar regras de negócio a cada alteração.

## Fase A — funções puras, sem GUI e sem banco
Cobre parsing e regras que não dependem de tela nem de SQL Server:

| Arquivo | O que cobre |
|---|---|
| `test_update_preserva.py` | **UPDATE não apaga**: célula vazia fica fora do SET (Produtos e Clientes), `0` continua sendo gravado (`cliDesativa=0` é *ativo*), linha sem dado nenhum não gera UPDATE, e a obrigatoriedade por operação (`_obrigatorios_efetivos`: INSERT = tudo / UPDATE = só a chave) |
| `test_layout.py` | **geometria de janela Tk real** (3 telas × 2 resoluções): o botão de ação nunca sai da janela, o mapeamento fica com a maior parte da altura, o bloco do log não estoura o textbox, e as listas de campos ficam ordenadas por seção (obrigatórios antes dos opcionais). Faz **SKIP** sozinho sem display |
| `test_helpers.py` | `_to_decimal` (número BR/US), `_get_int`/`_get_str`, `_get_str_max` (corte de coluna), `_calc_cli_tipo` (CPF→PF / CNPJ→PJ), **DPAPI** (cifra/decifra da senha), **`[Conexao]`** no `.ini` (sem plaintext, Windows sem senha, limpeza), `_montar_msg_obrigatorios` (contagem) |

Os métodos de parsing são das janelas, mas só usam `self.mapping`; os testes criam
a instância via `Classe.__new__(Classe)` — **não** roda `__init__`, então nenhuma
janela é aberta.

## Fase B — integração contra banco MaxData real (descartável)

| Arquivo | O que cobre |
|---|---|
| `test_integration_db.py` | smoke (a cópia subiu); **importação de produtos** (proId AUTO via SCOPE_IDENTITY, unidade auto-criada, vínculo `produto_empresa`, preço, corte em 100); **importação de clientes** (cliId AUTO, `cliente_empresa`, `cliTipo` derivado de CPF/CNPJ); **importação de financeiro** (lookup CPF→cliId, não-encontrado pulado); **migração** de permissões (cross-database `INSERT...SELECT`) e de **clientes "banco zero"** (desabilita/reabilita as ~FKs, limpa e recopia); prova de **isolamento** por revert; **UPDATE preserva o banco** (insere cadastro completo, atualiza só a descrição e confere preço/custo/aplicação/fantasia/endereço); **`proCodCst1`** (grava como INT, padrão `0` quando não mapeado, valor fora de 0–9 não derruba a linha e no UPDATE preserva o valor anterior) |

**Isolamento (banco descartável, o `BD_ZERO` NUNCA é tocado):** o `conftest.py` cria
uma vez por sessão o `BD_ZERO_TEST` por **cópia** do `BD_ZERO` (backup `COPY_ONLY` +
restore) e um **Database Snapshot**. Cada teste roda a lógica real (que dá `commit`)
e, no teardown, o snapshot é **revertido** — desfazendo tudo, inclusive DDL não
transacional (DBCC/IDENTITY). No fim da sessão, o `BD_ZERO_TEST` e o snapshot são
**dropados**.

**Harness headless:** cria a janela via `__new__(...)`, injeta `conn`/`df`/`mapping` e
stuba as chamadas de GUI (`_log`, `after`, `progress`, `_salvar_relatorio`, ...) — assim
os workers reais (`_inserir_produtos`/`_inserir_clientes`/`_inserir_financeiro`) e as
rotinas de migração (`_migrar_permissoes`/`_migrar_clientes`) rodam de verdade contra o
banco, sem abrir tela. As migrações de **produtos/financeiro** reusam a janela
importadora (constroem GUI) e por isso ficam para a Fase B+ (exigem um modo headless em
`_get_importador`).

**Requer** o SQL Server de teste acessível **e a variável `MI_TEST_PASS` definida**;
senão, os testes de banco fazem **SKIP** (a suíte continua verde). Credenciais via
env: `MI_TEST_SERVER` / `MI_TEST_USER` / `MI_TEST_PASS` / `MI_TEST_SRCDB`
(defaults: `localhost\BD_2022`, `sa`, **sem default — obrigatória**, `BD_ZERO`).
A senha **nunca** fica no código-fonte. Ex.:

```
set MI_TEST_PASS=suasenha
python -m pytest
```

## Como rodar
Na pasta da instalação (`C:\Max\MaxImporta\instalacao`):

```
python -m pytest              # roda tudo (unitários + integração de banco)
python -m pytest -m "not db"  # só unitários (rápido, sem SQL Server)
python -m pytest -v           # verboso (nome de cada teste)
python -m pytest -k dpapi     # só os que casam com "dpapi"
```

Os testes de integração levam o marcador `db` (exigem o SQL Server de teste).

Requer as mesmas dependências do app (customtkinter, pandas, pyodbc, pillow) mais
`pytest`. Importar `max_importa` não abre janela (a GUI só sobe no `__main__`).

## Fase C — gate no BUILD.bat (feita)
O `BUILD.bat` roda os testes ANTES do PyInstaller e **aborta o build se algum falhar**
(o `.exe` não é gerado). Por padrão roda só os **unitários** (`-m "not db"`, ~1s, sem
tocar o SQL Server). Variáveis de ambiente:

| Variável | Efeito |
|---|---|
| `set MI_TEST_DB=1`    | inclui os testes de **integração** (banco) no gate |
| `set MI_SKIP_TESTS=1` | **pula** os testes (não recomendado — só emergência) |

## Fase B+ — migração via headless + orquestrador completo (feita)
`JanelaMigracao._get_importador` cria importadores **HEADLESS** (sem GUI —
`ProdutosImportadorHeadless`/`FinanceiroImportadorHeadless` em `mi_importadores.py`),
então `_migrar_entidade("produtos"/"financeiro", ...)` roda ponta-a-ponta sem abrir
janela. Testes: `test_migracao_produtos_via_headless` (idempotente, pula os já
existentes) e `test_migracao_financeiro_via_headless` (insere via lookup CPF→cliId).

**Orquestrador completo:** `test_migrar_orquestrador_ponta_a_ponta` roda o `_migrar`
inteiro (Clientes → Permissões → Produtos → CodBarras → Financeiro) numa execução,
injetando em `self._opcoes` as decisões que o wizard coletaria (mesmo contrato) —
confere 0 erros nas 5 entidades, contagem de clientes, FKs reabilitadas, 5 linhas de
auditoria na mesma `audSessao` e a reconciliação no log.

## Próximas fases (opcionais)
- Separar a validação pura do `_iniciar` das janelas (ainda mistura GUI + regra).
