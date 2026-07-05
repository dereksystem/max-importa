# Build e Empacotamento

Como o `Max_Importa.exe` é gerado, e o que o `BUILD.bat` faz automaticamente.

---

## Arquivos necessários (mesma pasta)

- `max_importa.py` — código-fonte
- `logo_maxdata.png` — logo exibida na interface (embutida no .exe)
- `max_x.ico` — ícone do executável
- `max_importa.spec` — configuração do PyInstaller
- `BUILD.bat` — script de build

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
3. **Dependências:** `pip install customtkinter pyodbc pandas pillow "pyinstaller<7.0"`.
4. **Limpeza:** remove `.exe` anterior e as pastas `build`/`dist`.
5. **Compilação:** `python -m PyInstaller max_importa.spec --noconfirm --clean`.
6. **Finalização:** copia `dist\Max_Importa.exe` para a pasta raiz.

---

## max_importa.spec

- **Onefile** — um único `.exe` com tudo embutido.
- `datas`: `logo_maxdata.png` + a pasta do `customtkinter` (temas/imagens).
- `hiddenimports`: inclui `PIL`, `PIL.Image`, `PIL.ImageTk`, `PIL._tkinter_finder`
  (garante o Pillow no pacote — evita o erro *"No module named 'PIL'"*).
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
