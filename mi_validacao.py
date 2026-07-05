"""mi_validacao — regras de validação PURAS da importação por arquivo.

Extraído dos métodos `_iniciar` das janelas na refatoração do monólito. São funções
puras (recebem o DataFrame + o mapping campo→coluna e devolvem o resultado), sem GUI e
sem banco — logo, testáveis diretamente. As janelas continuam cuidando da parte de
interface (ler os combos, mostrar messagebox, disparar a thread).

Convenção de "vazio": '', 'NULL', 'NONE', 'NAN' (case-insensitive) contam como vazio.
As linhas retornadas são 1-based do ARQUIVO (idx do DataFrame + 2, contando o cabeçalho).
"""

_VAZIOS = ("", "NULL", "NONE", "NAN")


def _e_vazio(valor) -> bool:
    s = str(valor).strip() if valor is not None else ""
    return s.upper() in _VAZIOS


def campos_nao_mapeados(mapping: dict, campos_obrigatorios) -> list:
    """Retorna os campos obrigatórios que NÃO estão no mapping (ordem de entrada)."""
    return [c for c in campos_obrigatorios if c not in mapping]


def validar_obrigatorios(df, mapping: dict, campos_obrigatorios,
                         apenas_mapeados: bool = False) -> dict:
    """Retorna {campo_db: [linha_arquivo, ...]} das células obrigatórias VAZIAS.

    - apenas_mapeados=False (modo INSERT): checa todos os obrigatórios (assume que já
      foram validados como mapeados antes);
    - apenas_mapeados=True (modo UPDATE): checa só os obrigatórios que ESTÃO mapeados
      (os não mapeados mantêm o valor atual do banco).
    """
    invalidos = {}
    for idx, row in df.iterrows():
        linha = idx + 2
        for campo in campos_obrigatorios:
            col = mapping.get(campo)
            if col is None:
                continue   # não mapeado: INSERT já barrou antes; UPDATE mantém o banco
            if _e_vazio(row.get(col, None)):
                invalidos.setdefault(campo, []).append(linha)
    return invalidos


def linhas_ao_menos_um(df, mapping: dict, campo_a: str, campo_b: str) -> list:
    """Regra 'ao menos um dos dois preenchido por linha' (ex.: pgtTipoVista/pgtTipoPrazo).
    Retorna as linhas do arquivo em que AMBOS estão vazios. Se nenhum dos dois está
    mapeado, não há o que validar (retorna [])."""
    col_a = mapping.get(campo_a)
    col_b = mapping.get(campo_b)
    if not (col_a or col_b):
        return []
    erros = []
    for idx, row in df.iterrows():
        vazio_a = _e_vazio(row.get(col_a, "")) if col_a else True
        vazio_b = _e_vazio(row.get(col_b, "")) if col_b else True
        if vazio_a and vazio_b:
            erros.append(idx + 2)
    return erros


def ids_reservados(df, mapping: dict, campo: str, limite: int = 10) -> list:
    """Retorna os IDs (< limite) informados no arquivo que são RESERVADOS pelo sistema
    (ex.: cliId < 10). Ignora vazios e valores não numéricos. Se o campo não está
    mapeado, retorna []."""
    col = mapping.get(campo)
    if not col:
        return []
    reservados = []
    for _idx, row in df.iterrows():
        raw = str(row.get(col, "")).strip()
        if raw.upper() in _VAZIOS:
            continue
        try:
            v = int(float(raw))
        except Exception:
            continue
        if v < limite:
            reservados.append(v)
    return reservados
