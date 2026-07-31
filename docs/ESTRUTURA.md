# Estrutura do Código

Mapa da aplicação (v3.6.2). Desde a refatoração, o monólito foi dividido em módulos:
`max_importa.py` guarda **só a camada GUI**; a lógica vive em módulos `mi_*`.

---

## Módulos (visão geral)

| Arquivo | Papel | GUI? |
|---|---|---|
| `max_importa.py` | as 6 janelas (Login, Menu, Produtos, Clientes, Financeiro, Migração), o `CancelavelMixin` (rodapé único via `_montar_rodape`/`_criar_barra_acoes` e a obrigatoriedade por operação em `_obrigatorios_efetivos`), o tema Clean Corporate e o `entry point` | sim |
| `mi_config.py` | `APP_VERSION`, cores/tema (`MD_*`/`TC_*`), `_resource_path`, pasta de logs (`_get_log_dir`/`_set_log_dir`), **DPAPI** (`_dpapi_encrypt/decrypt`), credenciais (`_get_conexao`/`_set_conexao`, `_INI_PATH`) | não (stdlib) |
| `mi_report.py` | relatórios/export ao fim da importação: `_gerar_arquivo_erros`, `_montar_msg_obrigatorios`, `_marcar_arquivo_importado`, `_resetar_selecao`, `_nome_banco`, `_exportar_resultado` (JSON/CSV), `_pos_importacao` | não |
| `mi_db.py` | **`MapeamentoDBMixin`** — leitura de células (`_get_str/_get_str_max/_get_int/_get_float/_get_decimal/_get_datetime/_to_decimal`) e utilidades de banco (`_lookup`, `_get_or_create`, `_get_emp_id`, `_lookup_unidade`, `_get_or_create_unidade`, `_lookup_cli_id`) + o **SET do UPDATE** (`_celula_preenchida`/`_montar_set_update`: célula vazia fica fora do SET e não apaga o banco) | não |
| `mi_migracao.py` | **`MigracaoMixin`** — lógica da migração banco→banco (`_migrar`, `_migrar_entidade`, `_migrar_clientes/permissoes/codbarras`, `_sql_*`, `_reconciliar`, `_salvar_relatorio_migracao`, `_registrar_auditoria`, `_backup_destino`, …) | não |
| `mi_importadores.py` | **`ProdutosImportMixin`/`ClientesImportMixin`/`FinanceiroImportMixin`** (lógica de `_inserir_*`/`_atualizar_*`, `_calc_cli_tipo`, `_get_cst1`) + **importadores HEADLESS** usados pela migração (`ProdutosImportadorHeadless`, …) | não |
| `mi_validacao.py` | regras de validação **puras** dos `_iniciar`: `campos_nao_mapeados`, `validar_obrigatorios`, `linhas_ao_menos_um`, `ids_reservados` | não |

As janelas importadoras herdam os mixins:
`class JanelaProdutos(ProdutosImportMixin, MapeamentoDBMixin, CancelavelMixin, ctk.CTkToplevel)`
(idem Clientes/Financeiro). `JanelaMigracao` herda `MigracaoMixin, CancelavelMixin`.

---

## Janelas (em `max_importa.py`)

### `JanelaLogin`
Conexão SQL Server (auth **SQL** ou **Windows**), "lembrar credenciais" (senha cifrada
via DPAPI), escolha do banco. `_montar_base_conn_str`, `_editar_credenciais`, `_conectar`,
`_confirmar` (botão de avançar só aparece após validar).

### `JanelaMenu`
Abre os módulos, a configuração de pasta de logs e o **toggle de tema** claro/escuro
(`_toggle_tema` → `ctk.set_appearance_mode`).

### `JanelaProdutos` / `JanelaClientes` / `JanelaFinanceiro`
Camada GUI: `__init__`, `_build` (inclui o **feedback de mapeamento** — indicador
✓/✗/— por campo e o rótulo-resumo), `_selecionar_arquivo`, `_carregar_colunas`,
`_iniciar` (validação via `mi_validacao` + dispara a thread), `_log`, `_salvar_relatorio`,
`_fechar`. A **lógica** (`_inserir_*`/`_atualizar_*`) vem dos mixins de `mi_importadores`.
`_calc_cli_tipo` fica em `JanelaClientes` (domínio).

### `JanelaMigracao`
GUI + orquestração: `_build`, `_dialogo_opcoes` (wizard), `_iniciar`, `_get_importador`
(cria os **importadores headless**), `_pergunta_thread`, `_bancos_disponiveis`, `_fechar`
+ constantes `_ROTULOS/_ORDEM/_TOTAL_FMT`. A lógica vem de `MigracaoMixin`.

---

## Tema "Clean Corporate" (v3.6.1/3.6.2)
- Paleta em `mi_config.py` como tuplas `(claro, escuro)`; vermelho da marca `#CC0000`.
- As **superfícies** (janela, cards, inputs, combos, textbox, scroll, segmented) são
  sobrescritas em `max_importa._aplicar_tema_clean_corporate()` (roda no import): página
  `#F7F8FA`/`#16181C`, cards brancos `#FFFFFF`/`#1D2025`.
- Padrão **claro**; o menu tem o toggle claro/escuro.

---

## Padrões importantes
- **Captura de IDENTITY:** `INSERT + SELECT SCOPE_IDENTITY()` no **mesmo batch** com
  `SET NOCOUNT ON` (triggers AFTER de datas).
- **Resiliência a schema (migração):** SELECTs montados a partir das colunas reais da
  origem; ausência → `NULL`.
- **Cancelamento cooperativo** (`CancelavelMixin`): importadores entre linhas, migração
  entre entidades (ponto seguro).
- **Relatórios sempre gerados** (`.txt`) + export estruturado `RESULTADO_*.json` e
  `ERROS_*.csv`; auditoria no destino (`MaxImporta_Auditoria`).

---

## Testes (`tests/`)
`pytest` — rodar `python -m pytest` na pasta da instalação. Ver `tests/README.md`.
- `test_helpers.py` — funções puras (parsing, DPAPI, `[Conexao]`, validação, feedback de
  mapeamento).
- `test_integration_db.py` — integração contra banco MaxData real via **banco descartável**
  (`BD_ZERO_TEST` = cópia do `BD_ZERO` + snapshot revertido por teste).
- Gate no `BUILD.bat`: roda os testes antes do PyInstaller (aborta se falhar).

---

## Arquivos do projeto (para compilar)

| Arquivo | Papel |
|---|---|
| `max_importa.py` + `mi_*.py` (6) | código-fonte (GUI + módulos) |
| `max_importa.spec` | build PyInstaller (lista os `mi_*` em `hiddenimports`) |
| `BUILD.bat` | build (instala Python/deps, roda o gate de testes, gera o `.exe`) |
| `logo_maxdata.png`, `max_x.ico` | logo e ícone |
| `pytest.ini`, `tests/` | suíte de testes (necessária para o gate do BUILD) |
| `MaxImporta_Modelos_Importacao.xlsx`, `modelo de importação_*.txt` | modelos |
| `README.md`, `CHANGELOG.txt/.md`, `docs/*.md`, `documentacao_max_importa.html` | docs |

Não versionados / não empacotados: `max_importa.ini` (credenciais), `build/`, `dist/`,
`__pycache__/`, `Log/`, `*.exe`, `*.rar`.
