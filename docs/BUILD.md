# Build e Empacotamento

Como o `Max_Importa.exe` é gerado, e o que o `BUILD.bat` faz automaticamente.

---

## Arquivos necessários (mesma pasta)

- `max_importa.py` — camada GUI (entry point)
- **Módulos** `mi_config.py`, `mi_report.py`, `mi_db.py`, `mi_migracao.py`,
  `mi_importadores.py`, `mi_validacao.py` — a lógica (o `.spec` os lista em `hiddenimports`)
- `logo_maxdata.png` — logo exibida na interface (embutida no .exe)
- `max_x.ico` — ícone do executável
- `max_importa.spec` — configuração do PyInstaller
- `BUILD.bat` — script de build
- `pytest.ini` + pasta `tests/` — a suíte de testes (o build roda um *gate* de testes)

---

## BUILD.bat — passo a passo

1. **Anti-elevação:** se o `BUILD.bat` for aberto como **Administrador**, ele se
   reabre sozinho **sem privilégios** (via `explorer.exe`), porque o PyInstaller não
   roda elevado. Proteção anti-loop com flag em `%TEMP%`.
2. **Python automático:** se o `python` não for encontrado, o script **instala o
   Python 3.12 automaticamente**:
   - Tenta `winget` (`Python.Python.3.12 --scope user --silent`);
   - Se não houver winget, baixa o instalador oficial do python.org e roda em modo
     silencioso com `PrependPath=1`.
   - Em seguida se **reabre** (via `explorer.exe`) para o PATH atualizado valer.
   - Flag anti-loop em `%TEMP%`.
3. **Dependências:** `pip install customtkinter pyodbc pandas pillow "pyinstaller<7.0" pytest`.
4. **Gate de testes:** roda `python -m pytest`. Por padrão só os **unitários**
   (`-m "not db"`, ~1s); se algum falhar, o build é **abortado** (o `.exe` não é gerado).
   - `set MI_TEST_DB=1` → inclui os testes de **integração** (precisam do SQL Server de teste).
   - `set MI_SKIP_TESTS=1` → pula os testes (só emergência).
5. **Limpeza:** remove `.exe` anterior e as pastas `build`/`dist`.
6. **Compilação:** `python -m PyInstaller max_importa.spec --noconfirm --clean`.
7. **Finalização:** copia `dist\Max_Importa.exe` para a pasta raiz.

---

## max_importa.spec

- **Onefile** — um único `.exe` com tudo embutido.
- `datas`: `logo_maxdata.png` + a pasta do `customtkinter` (temas/imagens).
- `hiddenimports`: os **módulos próprios** (`mi_config`, `mi_report`, `mi_db`,
  `mi_migracao`, `mi_importadores`, `mi_validacao`) + `PIL`, `PIL.Image`, `PIL.ImageTk`,
  `PIL._tkinter_finder` (garante o Pillow no pacote — evita *"No module named 'PIL'"*).
- `icon='max_x.ico'` — ícone do executável.
- `console=False` — sem janela de console.

---

## Ícone (`max_x.ico`)

- Baseado no **"X" da logo MaxData** (vermelho `#C71016`, amostrado da própria logo).
- Gerado com Pillow como `.ico` multi-resolução (256/128/64/48/32/16 px).
- Embutido no `.exe` pelo PyInstaller (parâmetro `icon` do `.spec`).
- **Cache de ícone do Windows:** se o ícone antigo persistir, limpe com
  `ie4uinit.exe -show` ou reinicie o Explorer.

---

## Distribuição para outra máquina

- Basta copiar o **`Max_Importa.exe`** (tudo embutido).
- A máquina precisa apenas do **ODBC Driver 17 for SQL Server** (https://aka.ms/odbc17).
- Não precisa de Python no computador que só **executa** o app.
