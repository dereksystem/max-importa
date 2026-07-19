"""mi_validacao — regras de validação PURAS da importação por arquivo.

Extraído dos métodos `_iniciar` das janelas na refatoração do monólito. São funções
puras (recebem o DataFrame + o mapping campo→coluna e devolvem o resultado), sem GUI e
sem banco — logo, testáveis diretamente. As janelas continuam cuidando da parte de
interface (ler os combos, mostrar messagebox, disparar a thread).

Convenção de "vazio": '', 'NULL', 'NONE', 'NAN' (case-insensitive) contam como vazio.
As linhas retornadas são 1-based do ARQUIVO (idx do DataFrame + 2, contando o cabeçalho).
"""

import re
from datetime import datetime

_VAZIOS = ("", "NULL", "NONE", "NAN")


def _e_vazio(valor) -> bool:
    s = str(valor).strip() if valor is not None else ""
    return s.upper() in _VAZIOS


# ─────────────────────────────────────────────────────────────────────────────
# Regras de NEGÓCIO por célula (usadas durante a importação, linha a linha).
# Todas devolvem True/False e NUNCA lançam — dado ruim não pode derrubar o import.
# Convenção: valor vazio NÃO é inválido (é ausência); quem exige preenchimento é a
# validação de obrigatórios.
# ─────────────────────────────────────────────────────────────────────────────
def so_digitos(valor) -> str:
    """Mantém apenas os dígitos (tira ponto, traço, barra, espaço)."""
    return re.sub(r"\D", "", str(valor)) if valor is not None else ""


def cpf_valido(doc) -> bool:
    """Dígitos verificadores do CPF (11 dígitos). Rejeita repetidos (111...)."""
    d = so_digitos(doc)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for tam in (9, 10):
        soma = sum(int(d[i]) * (tam + 1 - i) for i in range(tam))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[tam]):
            return False
    return True


def cnpj_valido(doc) -> bool:
    """Dígitos verificadores do CNPJ (14 dígitos). Rejeita repetidos."""
    d = so_digitos(doc)
    if len(d) != 14 or d == d[0] * 14:
        return False
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
                  [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        tam = len(pesos)
        soma = sum(int(d[i]) * pesos[i] for i in range(tam))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[tam]):
            return False
    return True


def cpf_cnpj_valido(doc) -> bool:
    """True se for CPF (11) ou CNPJ (14) com dígitos verificadores corretos.
    Vazio devolve True (ausência não é erro de formato)."""
    if _e_vazio(doc):
        return True
    d = so_digitos(doc)
    if len(d) == 11:
        return cpf_valido(d)
    if len(d) == 14:
        return cnpj_valido(d)
    return False          # nem CPF nem CNPJ (quantidade de dígitos errada)


_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def email_valido(valor) -> bool:
    """Formato de e-mail. Vazio é válido (ausência não é erro)."""
    if _e_vazio(valor):
        return True
    return bool(_RE_EMAIL.match(str(valor).strip()))


def data_plausivel(dt, ano_min: int = 1900, ano_max: int = None) -> bool:
    """Data dentro de uma faixa razoável. Fora disso costuma ser erro de parse
    (ex.: dia/mês trocados virando 0202, ou serial Excel lido como ano).
    None é plausível (ausência). ano_max padrão = ano atual + 10."""
    if dt is None:
        return True
    if ano_max is None:
        ano_max = datetime.now().year + 10
    try:
        return ano_min <= dt.year <= ano_max
    except Exception:
        return True


def valor_positivo(valor) -> bool:
    """Valor monetário/quantidade não-negativo. Vazio é válido."""
    if valor is None:
        return True
    try:
        return float(valor) >= 0
    except Exception:
        return True       # não numérico é problema de outra regra, não desta


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
