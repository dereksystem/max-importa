# Max_Importa

**Importador e Migrador de dados para o MaxManager (MaxData ERP).**

Aplicação desktop em Python (customtkinter + pyodbc + pandas) que importa grandes
volumes de dados para o banco SQL Server do MaxManager a partir de arquivos
`.txt`/`.csv`, e migra dados diretamente **entre dois bancos MaxData** (banco → banco).

- **Versão atual:** `3.7.0` (definida em [`mi_config.py`](mi_config.py) → `APP_VERSION`)
- **Plataforma:** Windows 10/11 (64 bits)
- **Banco:** SQL Server (ODBC Driver 17)

---

## Módulos

| Módulo | O que faz |
|---|---|
| 👥 **Clientes / Fornecedores** | INSERT e UPDATE em `cliente` + `cliente_empresa` (arquivo) |
| 📦 **Produtos** | INSERT e UPDATE em `produto` + `produto_empresa` (+ lookups) |
| 💰 **Financeiro** | INSERT de lançamentos em `vendaPgto` |
| 🔄 **Migração entre Bancos MaxData** | Copia Clientes, Permissões, Produtos e Financeiro de um banco para outro na mesma instância |

---

## Requisitos

- **Windows 10/11 (64 bits)**
- **ODBC Driver 17 for SQL Server** — obrigatório para rodar (https://aka.ms/odbc17)
- **SQL Server** com as tabelas do MaxManager acessíveis
- **Python 3.10+** — apenas para **gerar** o `.exe` (o `BUILD.bat` instala automaticamente se faltar)

---

## Como gerar o executável

1. Deixe na mesma pasta os fontes + build:
   - `max_importa.py` **e os 6 módulos** `mi_config.py`, `mi_report.py`, `mi_db.py`,
     `mi_migracao.py`, `mi_importadores.py`, `mi_validacao.py`
   - `max_importa.spec`, `BUILD.bat`, `logo_maxdata.png`, `max_x.ico`
   - `pytest.ini` + a pasta `tests/` (o `BUILD.bat` roda os testes como *gate* antes de compilar)
2. Duplo clique em **`BUILD.bat`**
   - Instala Python + dependências (customtkinter, pyodbc, pandas, pillow, pyinstaller, pytest) se faltarem
   - Roda os testes unitários; se algum falhar, **aborta** (o `.exe` não é gerado).
     Para incluir os testes de banco: `set MI_TEST_DB=1`. Para pular: `set MI_SKIP_TESTS=1`.
   - Se abrir como Administrador, ele se reabre sozinho sem elevação
3. O `Max_Importa.exe` é gerado na mesma pasta

Detalhes: [docs/BUILD.md](docs/BUILD.md)

---

## Como usar

1. Abra o `Max_Importa.exe`
2. **Login:** em *Editar credenciais*, escolha a autenticação — **SQL Server** (usuário/senha) ou **Windows** (integrada, sem senha) — conecte e escolha o banco. A senha **não** vem embutida; marque *"Lembrar credenciais"* para salvá-la **criptografada** (DPAPI, só nesta máquina/usuário)
3. **Menu:** escolha o módulo (Clientes, Produtos, Financeiro ou Migração)
4. **Importação por arquivo:** selecione o `.xlsx`/`.txt`/`.csv` (o encoding é detectado automaticamente), confira o mapeamento de colunas e clique em Importar. No Financeiro há a opção **"🔎 Simular (não grava)"** para conferir o resultado antes de gravar
5. **Migração:** escolha banco de origem e destino, marque o que migrar e inicie

Modelos de arquivo: `MaxImporta_Modelos_Importacao.xlsx` e os `modelo de importação_*.txt`.

---

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md) | Todas as regras de negócio por módulo (proId AUTO, unidade automática, cliTipo, acerto de estoque, etc.) |
| [docs/MIGRACAO.md](docs/MIGRACAO.md) | Migração Max → Max em detalhe (clientes "banco zero", permissões, resiliência a schema) |
| [docs/BUILD.md](docs/BUILD.md) | Build, empacotamento, ícone, instalação automática do Python |
| [docs/ESTRUTURA.md](docs/ESTRUTURA.md) | Estrutura do código (classes, métodos, tabelas) |
| [CHANGELOG.txt](CHANGELOG.txt) | Histórico de versões |
| [documentacao_max_importa.html](documentacao_max_importa.html) | Documentação técnica visual (HTML) |
| [tests/README.md](tests/README.md) | Suíte de testes de regressão (`python -m pytest`) |

---

## Pasta de logs

Configurável no menu principal. Padrão: `C:\Max\MaxImporta\Log\`. São gerados:

- `LOG_MAX_IMPORTA_*.log` — log em tempo real
- `RELATORIO_MAX_IMPORTA_*.txt` — relatório de fechamento (produtos/clientes/financeiro)
- `RELATORIO_MIGRACAO_*.txt` — relatório da migração
- `RESULTADO_*_*.json` — resumo **estruturado** de cada operação (versão, banco, contagens, erros)
- `ERROS_*_*.txt` / `ERROS_*_*.csv` — itens/clientes que falharam (o `.csv` abre no Excel)
- Arquivo importado renomeado: `*_IMPORTADO_OK_*` / `*_IMPORTADO_COM_ERROS_*`
