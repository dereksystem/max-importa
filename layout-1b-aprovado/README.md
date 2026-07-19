# Layout 1b — Dashboard com Sidebar (APROVADO)

Referência de redesign do **Max_Importa** (app desktop Python / customtkinter).
Guardado para aplicar mais adiante. **Nada do app foi alterado** — esta pasta é só especificação.

## Arquivos
- `Layout_1b.dc.html` — protótipo visual navegável: menu principal (referência escura) + fluxo em tema claro (Login `3a`, Importação/Mapeamento `3b`, Migração `3c`).
- `logo_maxdata.png` — logo usada nos mockups.

## Estrutura do layout
Janela dividida em duas colunas:
- **Sidebar fixa** (largura `236px`) — logo no topo, grupos de navegação ("Importar", "Ferramentas") com rótulo em caixa alta, item ativo destacado, e no rodapé o status de conexão (bolinha + nome do banco).
- **Área principal** — cabeçalho (breadcrumb pequeno + título grande), alternador **Inserir / Atualizar**, conteúdo da tela e barra de ação no rodapé.

## Paleta
| Uso | Hex |
|-----|-----|
| Vermelho MaxData (acento / item ativo / ação primária) | `#CC0000` |
| Vermelho hover | `#990000` |
| Texto principal | `#16181C` |
| Texto secundário | `#5B6470` |
| Texto suave / placeholder | `#8A9099` |
| Rótulo de seção (sidebar) | `#A2A9B2` |
| Verde sucesso / conectado | `#2E9E6B` |
| Âmbar de alerta (texto) | `#8A6D3B` / fundo `#FFF7ED` / borda `#F5E0BE` |
| Fundo do app (canvas) | `#E9EBEF` |
| Sidebar clara | `#F7F8FA` (borda `#EAECEF`) |
| Card / superfície | `#FFFFFF` (borda `#E3E6EA`) |
| Botão neutro escuro | `#16181C` |

### Tema escuro (menu de referência)
Fundo `#16181C`, sidebar `#1B1E24`, cards `#1B1E24`, bordas `#2A2E36`, texto claro `#E6E8EB`, verde conectado `#35B37E`.

## Tipografia
- Família: **Inter** (400–800). Substitui a fonte padrão do customtkinter.
- Título de tela: 22–23px / peso 800 / `letter-spacing:-.01em`.
- Rótulos de seção: 10.5–11px / peso 700 / caixa alta / `letter-spacing:.06–.14em`.
- Corpo: 12.5–13.5px.

## Componentes-chave
- **Alternador Inserir/Atualizar**: pílula em fundo `#F0F2F5`, opção ativa em `#CC0000` texto branco, raio 6–7px.
- **Status de conexão**: bolinha verde com halo (`box-shadow:0 0 0 3px rgba(46,158,107,.18)`) + nome do banco.
- **Mapeamento de colunas** (`3b`): linhas com estados por cor —
  - chave: fundo `#FBEEEC`, texto `#A93226`, badge "CHAVE";
  - mapeado: fundo `#EAF7F0`, check verde;
  - faltando: fundo `#FDECEC`, "✗" vermelho, badge "FALTA".
  - Rodapé com contador "X de Y" + barra de progresso vermelha.
- **Migração** (`3c`): Origem → seta escura → Destino (destino com borda vermelha), grade de checkboxes do que migrar, aviso âmbar de backup, botão "Iniciar migração".
- **Raios**: cards 12–14px, controles 8–9px, pílulas 999px.
- **Sombra de janela**: `0 24px 60px -24px rgba(20,24,28,.4)`.

## Notas de implementação (Python / customtkinter)
- customtkinter não tem "sidebar" pronta: montar com um `CTkFrame` fixo à esquerda + `CTkFrame` de conteúdo à direita dentro de um grid 2 colunas.
- Ícones: os mockups usam SVG monolineares (lucide-like). No app, usar PNGs monocromáticos ou uma fonte de ícones equivalente.
- Item ativo da sidebar = `fg_color="#CC0000"`; itens inativos transparentes com texto `#5B6470`.
- Manter os textos/rótulos e a lógica atuais; muda só a apresentação.
