"""mi_perfis — perfis de MAPEAMENTO de colunas, por layout de arquivo.

O auto-mapeamento casa coluna do arquivo com campo do banco só quando os nomes são
IDÊNTICOS. Arquivos de terceiros (exportações de outro ERP, planilhas do cliente)
quase nunca batem, e o usuário remapeia tudo na mão a cada importação.

Um PERFIL guarda esse trabalho: {campo_do_banco: coluna_do_arquivo}, nomeado e por
módulo (PRODUTOS/CLIENTES/FINANCEIRO). Fica em `max_importa_perfis.json`, ao lado do
executável (mesma pasta do max_importa.ini — ver mi_config._APP_DIR).

Funções puras de I/O, sem GUI: nunca lançam para o chamador (best-effort), porque
perder um perfil não pode impedir a importação.
"""
import json
import os

from mi_config import _APP_DIR

_PERFIS_PATH = os.path.join(_APP_DIR, "max_importa_perfis.json")


def _carregar_tudo() -> dict:
    """{modulo: {nome_perfil: {campo: coluna}}}. {} se não existir/estiver corrompido."""
    try:
        if not os.path.exists(_PERFIS_PATH):
            return {}
        with open(_PERFIS_PATH, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def _gravar_tudo(dados: dict) -> bool:
    try:
        with open(_PERFIS_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


def listar(modulo: str) -> list:
    """Nomes dos perfis do módulo, em ordem alfabética."""
    return sorted(_carregar_tudo().get(modulo, {}).keys())


def obter(modulo: str, nome: str):
    """Mapeamento {campo: coluna} do perfil, ou None se não existir."""
    perfil = _carregar_tudo().get(modulo, {}).get(nome)
    return dict(perfil) if isinstance(perfil, dict) else None


def salvar(modulo: str, nome: str, mapping: dict) -> bool:
    """Cria/sobrescreve o perfil. Ignora nome vazio e mapping vazio."""
    nome = (nome or "").strip()
    if not nome or not mapping:
        return False
    dados = _carregar_tudo()
    dados.setdefault(modulo, {})[nome] = {str(k): str(v) for k, v in mapping.items()}
    return _gravar_tudo(dados)


def excluir(modulo: str, nome: str) -> bool:
    dados = _carregar_tudo()
    if nome in dados.get(modulo, {}):
        del dados[modulo][nome]
        if not dados[modulo]:
            del dados[modulo]
        return _gravar_tudo(dados)
    return False


def aplicavel(mapping: dict, colunas_arquivo) -> tuple:
    """Confronta um perfil com as colunas do arquivo carregado.
    Retorna (aplicaveis, ausentes): campos cuja coluna EXISTE no arquivo e campos
    cuja coluna sumiu (layout mudou). Não altera nada — quem aplica é a GUI."""
    cols = {str(c) for c in (colunas_arquivo or [])}
    aplicaveis, ausentes = {}, {}
    for campo, coluna in (mapping or {}).items():
        if coluna in cols:
            aplicaveis[campo] = coluna
        else:
            ausentes[campo] = coluna
    return aplicaveis, ausentes
