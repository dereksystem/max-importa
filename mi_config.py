"""mi_config — configuração e utilitários SEM GUI do Max_Importa.

Extraído de max_importa.py na refatoração do monólito. Contém:
  - versão do app e paleta de cores/tema;
  - resolução de caminho de recurso (funciona no .py e no .exe/PyInstaller);
  - pasta de logs configurável no max_importa.ini;
  - criptografia da senha via Windows DPAPI (ctypes, sem dependência externa);
  - persistência das credenciais de conexão (seção [Conexao] do .ini).

Sem dependências de customtkinter/tkinter — só stdlib. Assim pode ser testado e
reutilizado sem abrir janela.
"""
import os
import sys
import base64
import ctypes
import configparser
from ctypes import wintypes

# ── Versao do aplicativo (MAJOR.MINOR.PATCH) ───────────────────────────────────
APP_VERSION = "4.1.1"

# ── Paleta "Clean Corporate" — tuplas (claro, escuro) ──────────────────────────
# O CustomTkinter troca a cor conforme o modo (light/dark) automaticamente.
# Vermelho da MARCA MaxData mantido no claro (#CC0000); no escuro usa uma versão
# mais viva para contraste. O tom saturado deixa de ser plano de fundo e vira acento.
MD_RED      = ("#CC0000", "#E5433D")   # vermelho da marca (ações/identidade)
MD_RED_HOV  = ("#990000", "#C0362F")   # hover do vermelho
MD_GRAY     = ("#5B6470", "#8A9099")   # cinza secundário (texto de apoio / chips)
MD_GRAY_HOV = ("#454C56", "#6E7680")   # hover do cinza

# ── Cores adaptáveis ao tema (claro, escuro) ───────────────────────────────────
TC_TEXT_MAIN     = ("#1A1D21", "#E6E8EB")    # texto principal
TC_FIELD_OBL_BG  = ("#FDECEC", "#2A1A1A")    # fundo linha obrigatória (vermelho suave)
TC_FIELD_OBL_TXT = ("#A93226", "#E5706A")    # texto/realce campo obrigatório
TC_FIELD_KEY_BG  = ("#FBEEEC", "#241C1C")    # fundo linha CHAVE (neutro-vermelho suave)
TC_FIELD_KEY_TXT = ("#A93226", "#E5706A")    # texto campo CHAVE
TC_STATUS_OK     = ("#2E9E6B", "#35B37E")    # sucesso / campo mapeado


def _resource_path(filename: str) -> str:
    """Resolve caminho de recurso — funciona tanto no .py quanto no .exe (PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)


# ── Configuração de pasta de logs (max_importa.ini) ───────────────────────────
# IMPORTANTE: no .exe (PyInstaller *one-file*), __file__ aponta para a pasta TEMP
# de extração (sys._MEIPASS), que é APAGADA ao fechar o app. Se usássemos __file__,
# o max_importa.ini e a pasta Log iriam parar na temp — a config nunca persistiria e
# os logs sumiriam. Por isso, quando "frozen", usamos a pasta REAL do executável
# (onde ele foi instalado, ex.: C:\Max\MaxImporta) → padrão vira C:\Max\MaxImporta\Log.
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
_INI_PATH        = os.path.join(_APP_DIR, "max_importa.ini")
_DEFAULT_LOG_DIR = os.path.join(_APP_DIR, "Log")


def _get_log_dir() -> str:
    """Retorna o diretório de logs configurado (ou o padrão)."""
    cfg = configparser.ConfigParser()
    if os.path.exists(_INI_PATH):
        cfg.read(_INI_PATH, encoding="utf-8")
    return cfg.get("Paths", "log_dir", fallback=_DEFAULT_LOG_DIR)


def _set_log_dir(path: str) -> None:
    """Salva o diretório de logs no .ini e cria a pasta se necessário."""
    cfg = configparser.ConfigParser()
    if os.path.exists(_INI_PATH):
        cfg.read(_INI_PATH, encoding="utf-8")
    if "Paths" not in cfg:
        cfg["Paths"] = {}
    cfg["Paths"]["log_dir"] = path
    with open(_INI_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)
    os.makedirs(path, exist_ok=True)


# OBS: NÃO criamos a pasta de logs aqui no import. Quem cuida disso é a GUI
# (garantir_pasta_logs, em max_importa.py), que PERGUNTA ao usuário antes de criar
# caso a pasta não exista. As gravações de log mantêm um os.makedirs(exist_ok=True)
# como rede de segurança, então nada quebra se a pasta for removida durante o uso.


# ── Criptografia da senha via Windows DPAPI (CryptProtectData) ─────────────────
# Sem dependência externa: usa a API nativa do Windows por ctypes. O texto cifrado
# só pode ser decifrado pelo MESMO usuário do Windows na MESMA máquina — por isso
# é seguro guardar a senha no .ini (não fica em texto puro e não é portável).
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


try:
    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _CryptProtectData = _crypt32.CryptProtectData
    _CryptProtectData.argtypes = [ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR,
                                  ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
                                  ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(_DATA_BLOB)]
    _CryptProtectData.restype = wintypes.BOOL
    _CryptUnprotectData = _crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
                                    ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(_DATA_BLOB)]
    _CryptUnprotectData.restype = wintypes.BOOL
    _DPAPI_OK = True
except Exception:
    _DPAPI_OK = False

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _dpapi_encrypt(texto: str):
    """Cifra 'texto' com DPAPI (usuário+máquina atuais). Retorna base64 (str) ou
    None se vazio/indisponível."""
    if not texto or not _DPAPI_OK:
        return None
    try:
        dados = texto.encode("utf-8")
        buf = ctypes.create_string_buffer(dados, len(dados))
        blob_in = _DATA_BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not _CryptProtectData(ctypes.byref(blob_in), "MaxImporta", None, None,
                                 None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
            return None
        cifrado = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        _kernel32.LocalFree(blob_out.pbData)
        return base64.b64encode(cifrado).decode("ascii")
    except Exception:
        return None


def _dpapi_decrypt(b64: str):
    """Decifra um base64 gerado por _dpapi_encrypt. Retorna o texto ou None se
    falhar (ex.: outro usuário/máquina, dado corrompido)."""
    if not b64 or not _DPAPI_OK:
        return None
    try:
        dados = base64.b64decode(b64.encode("ascii"))
        buf = ctypes.create_string_buffer(dados, len(dados))
        blob_in = _DATA_BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not _CryptUnprotectData(ctypes.byref(blob_in), None, None, None,
                                   None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
            return None
        texto = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        _kernel32.LocalFree(blob_out.pbData)
        return texto.decode("utf-8")
    except Exception:
        return None


# ── Persistência das credenciais de conexão (seção [Conexao] do .ini) ──────────
def _get_conexao() -> dict:
    """Lê as credenciais salvas. Retorna dict com servidor, usuario, auth
    ('sql'|'windows'), senha (decifrada) e lembrar (bool). Campos ausentes ficam
    None/'' e lembrar=False."""
    cfg = configparser.ConfigParser(interpolation=None)
    if os.path.exists(_INI_PATH):
        cfg.read(_INI_PATH, encoding="utf-8")
    if "Conexao" not in cfg:
        return {"servidor": None, "usuario": None, "auth": "sql",
                "senha": "", "lembrar": False}
    sec = cfg["Conexao"]
    senha_b64 = sec.get("senha", "")
    return {
        "servidor": sec.get("servidor") or None,
        "usuario":  sec.get("usuario") or None,
        "auth":     sec.get("auth", "sql"),
        "senha":    (_dpapi_decrypt(senha_b64) or "") if senha_b64 else "",
        "lembrar":  sec.getboolean("lembrar", fallback=False),
    }


def _set_conexao(servidor: str, usuario: str, auth: str, senha: str,
                 lembrar: bool) -> None:
    """Grava (ou limpa) as credenciais no .ini. Se lembrar=False, remove a seção
    [Conexao] inteira (não deixa nada sensível). A senha é gravada SEMPRE cifrada
    via DPAPI e só quando auth='sql' e há senha."""
    cfg = configparser.ConfigParser(interpolation=None)
    if os.path.exists(_INI_PATH):
        cfg.read(_INI_PATH, encoding="utf-8")
    if not lembrar:
        if "Conexao" in cfg:
            cfg.remove_section("Conexao")
    else:
        if "Conexao" not in cfg:
            cfg["Conexao"] = {}
        cfg["Conexao"]["servidor"] = servidor or ""
        cfg["Conexao"]["usuario"]  = usuario or ""
        cfg["Conexao"]["auth"]     = auth or "sql"
        cfg["Conexao"]["lembrar"]  = "1"
        cifrada = _dpapi_encrypt(senha) if (auth == "sql" and senha) else None
        cfg["Conexao"]["senha"] = cifrada or ""
    with open(_INI_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)
