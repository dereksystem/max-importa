# -*- mode: python ; coding: utf-8 -*-
# max_importa.spec — PyInstaller spec file
# Gerado automaticamente pelo Max_Importa build

import os, customtkinter
_CTK_DIR = os.path.dirname(customtkinter.__file__)

block_cipher = None

a = Analysis(
    ['max_importa.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Logo MaxData — embutida no executável
        ('logo_maxdata.png', '.'),
        # Arquivos do customtkinter (temas, imagens, fontes)
        (_CTK_DIR, 'customtkinter'),
    ],
    hiddenimports=[
        'mi_config',        # módulo próprio (config/cores/DPAPI/credenciais)
        'mi_report',        # módulo próprio (relatórios/export JSON-CSV)
        'mi_db',            # módulo próprio (mixin de leitura de células + banco)
        'mi_migracao',      # módulo próprio (mixin da lógica de migração)
        'mi_importadores',  # módulo próprio (mixins de importação por entidade)
        'mi_validacao',     # módulo próprio (regras de validação puras)
        'mi_arquivo',       # módulo próprio (leitura xlsx/csv + autodetecção encoding)
        'mi_perfis',        # módulo próprio (perfis de mapeamento por layout)
        'mi_multiloja',     # módulo próprio (empresas/config + empresaFiltro)
        'customtkinter',
        'pyodbc',
        'pandas',
        'openpyxl',         # engine de leitura de .xlsx (pd.read_excel)
        'openpyxl.cell._writer',  # submódulo que o PyInstaller às vezes não pega sozinho
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL._tkinter_finder',
        'decimal',
        'configparser',
        'threading',
        'logging',
        'sys',
        'os',
        're',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # scipy/matplotlib sao dependencias OPCIONAIS do pandas (extra "computation"/
    # plot) e NAO sao usadas pelo Max_Importa (que so le .txt/.csv via read_csv).
    # Eram arrastadas sem necessidade — incham o build e o UPX de um .pyd do scipy
    # (_gufuncs) chegou a falhar com PermissionError (antivirus travando o arquivo
    # comprimido). Excluir remove o inchaco e o arquivo problematico.
    excludes=['scipy', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Max_Importa',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # False = sem janela de console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='max_x.ico',   # ícone do X da MaxData
)
