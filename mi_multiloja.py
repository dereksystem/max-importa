"""mi_multiloja — núcleo do suporte a banco MaxData com mais de uma loja.

Um banco MaxData é multi-loja quando a tabela `config` tem **mais de uma linha**: cada
`cofId` é uma empresa, e é esse valor que aparece como `empId` em `produto_empresa`,
`cliente_empresa` e `vendaPgto`.

O que o MaxImporta fazia antes: `MapeamentoDBMixin._get_emp_id` resolvia o `empId` com
`SELECT TOP 1 cofId FROM config`. Em banco de uma loja está certo; em multi-loja
**escolhe uma empresa arbitrária** — o produto nasce em uma loja só e o UPDATE altera
uma loja só, sem erro e sem aviso.

Regras (ver `docs/superpowers/specs/2026-07-31-multiloja-design.md`):
  - `produto_empresa` / `cliente_empresa` recebem **uma linha por `cofId`** — sempre
    todas as empresas, independente da marcação do usuário;
  - quem define **onde o registro aparece** é a tabela `empresaFiltro`, que recebe uma
    linha por empresa **marcada**;
  - `vendaPgto` é diferente: cada título pertence a UMA empresa, informada no próprio
    arquivo de importação.

Só depende de um cursor pyodbc — sem GUI, sem estado global.
"""

# empresaFiltro.emfUsuId é `int NOT NULL` e **não tem default** no banco: precisa ir
# preenchido. Usamos o mesmo admin que o acerto de estoque já grava em paeUsuId.
USU_ID_PADRAO = 2

# Financeiro: `vendaPgto` não é replicado por loja — cada título é de UMA empresa,
# informada no arquivo. Sem o campo `empId` mapeado (ou com a célula vazia), o título
# vai para a empresa 1, que é o comportamento histórico de banco de uma loja.
EMP_ID_PADRAO_FINANCEIRO = 1

# Módulo do MaxImporta → (tabela, chave primária) como o empresaFiltro os nomeia.
# ⚠️ A base real do MAX_GROW grava `emfPkField` com grafia inconsistente ('cliId' nas
# empresas 1 e 2, 'cliid' na 3). Aqui a grafia é sempre esta — não propagamos a bagunça.
TABELA_POR_MODULO = {
    "PRODUTOS": ("produto", "proId"),
    "CLIENTES": ("cliente", "cliId"),
}

_SQL_EMPRESAS = "SELECT cofId, cofEmpFantasia FROM config ORDER BY cofId"

# IF NOT EXISTS para que reimportar o mesmo arquivo não duplique a visibilidade.
_SQL_FILTRO = (
    "IF NOT EXISTS (SELECT 1 FROM empresaFiltro\n"
    "               WHERE empId = ? AND emfTable = ? AND emfPkField = ? AND emfPkValue = ?)\n"
    "  INSERT INTO empresaFiltro (empId, emfTable, emfPkField, emfPkValue,\n"
    "                             emfDataOcorrencia, emfUsuId)\n"
    "  VALUES (?, ?, ?, ?, GETDATE(), ?)"
)


def listar_empresas(cursor):
    """Empresas do banco, em ordem de `cofId`.

    Devolve `[{"cofId": int, "cofEmpFantasia": str}, …]`. Fantasia vazia vira um rótulo
    genérico — na tela de seleção, "None" não ajuda ninguém a escolher a loja."""
    linhas = cursor.execute(_SQL_EMPRESAS).fetchall()
    empresas = []
    for cof_id, fantasia in linhas:
        nome = (str(fantasia).strip() if fantasia is not None else "")
        empresas.append({"cofId": int(cof_id), "cofEmpFantasia": nome or "(sem nome)"})
    return empresas


def e_multiloja(cursor) -> bool:
    """True quando o banco tem mais de uma empresa cadastrada em `config`."""
    return len(listar_empresas(cursor)) > 1


def registrar_filtro(cursor, emp_ids, tabela, pk_field, pk_value,
                     usu_id=USU_ID_PADRAO) -> int:
    """Vincula um registro às empresas em que ele deve aparecer (`empresaFiltro`).

    Uma linha por empresa de `emp_ids`, sem duplicar o que já existe. Devolve quantos
    INSERTs foram tentados (ou seja, quantas empresas distintas foram processadas).

    Sem empresas ou sem `pk_value` não faz nada: `pk_value` vem do id gerado no INSERT,
    e uma linha que falhou antes disso não tem o que vincular."""
    if not emp_ids or pk_value is None:
        return 0

    vistas = []
    for emp in emp_ids:                     # dedupe preservando a ordem
        if emp not in vistas:
            vistas.append(emp)

    for emp in vistas:
        cursor.execute(_SQL_FILTRO,
                       (emp, tabela, pk_field, pk_value,      # IF NOT EXISTS
                        emp, tabela, pk_field, pk_value, usu_id))
    return len(vistas)
