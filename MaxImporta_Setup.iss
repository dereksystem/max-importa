; ============================================================================
;  MaxImporta_Setup.iss  -  Inno Setup 6
;  Gera o instalador do Max_Importa (executavel onefile).
;
;  Compilar (linha de comando):
;    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" MaxImporta_Setup.iss
;  Ou abra este .iss no Inno Setup e clique em Build > Compile (Ctrl+F9).
;
;  Saida: installer\MaxImporta_Setup_<versao>.exe
;
;  Conteudo instalado:
;    - Max_Importa.exe (o app)
;    - LEIA-ME.txt e documentacao_max_importa.html (documentacao)
;    - Modelos\  (planilha + .txt de importacao)
;    - BD_ZERO\BD_ZERO.rar  (banco "zero" compactado, para restaurar como destino
;      de migracao / testes)
;    - Pre-requisitos (so se faltarem): VC++ Redistributable e ODBC Driver 17
;
;  IMPORTANTE: instala em C:\Max\MaxImporta (NAO em Program Files), porque o app
;  grava max_importa.ini e a subpasta Log AO LADO do exe. Program Files nao e
;  gravavel por usuarios comuns. A pasta e criada com permissao de escrita p/
;  o grupo Usuarios (secao [Dirs]).
; ============================================================================

#define MyAppName "Max Importa"
#define MyAppVersion "4.0.1"
#define MyAppPublisher "MaxData"
#define MyAppExeName "Max_Importa.exe"

[Setup]
; AppId identifica o produto (mantenha fixo entre versoes p/ upgrades corretos).
AppId={{7C4A9E12-3B6D-4F82-A5E1-9D2C8B4F1E60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={sd}\Max\MaxImporta
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=MaxImporta_Setup_{#MyAppVersion}
SetupIconFile=max_x.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
; App gravavel: o programa escreve max_importa.ini e Log\ aqui dentro.
Name: "{app}"; Permissions: users-modify
Name: "{app}\Log"; Permissions: users-modify
Name: "{app}\Modelos"
Name: "{app}\BD_ZERO"

[Files]
Source: "Max_Importa.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "max_x.ico"; DestDir: "{app}"; Flags: ignoreversion
; Documentacao tecnica visual (abre no navegador).
Source: "documentacao_max_importa.html"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; Historico de versoes (gerado do CHANGELOG.md por gerar_historico.py).
Source: "historico_versoes.html"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; Modelos de importacao (planilha + .txt). Wildcard ASCII evita problemas de
; acento nos nomes ("modelo de importacao_*.txt").
Source: "MaxImporta_Modelos_Importacao.xlsx"; DestDir: "{app}\Modelos"; Flags: ignoreversion
Source: "mod*importa*.txt"; DestDir: "{app}\Modelos"; Flags: ignoreversion skipifsourcedoesntexist
; Banco "zero" compactado (backup .bak dentro do .rar) — destino de migracao/testes.
; Renomeado para BD_ZERO.rar no destino.
Source: "BD_ZERO_MAI26_c usuario.rar"; DestDir: "{app}\BD_ZERO"; DestName: "BD_ZERO.rar"; Flags: ignoreversion skipifsourcedoesntexist
; Pre-requisitos: extraidos p/ pasta TEMP e apagados no fim. So sao extraidos
; quando faltam na maquina (Check), evitando copiar ~29 MB a toa.
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not VCRedistInstalado
Source: "redist\msodbcsql17_x64.msi"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not OdbcDriver17Instalado

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\max_x.ico"
Name: "{group}\Documentacao (HTML)"; Filename: "{app}\documentacao_max_importa.html"
Name: "{group}\Historico de Versoes"; Filename: "{app}\historico_versoes.html"
Name: "{group}\LEIA-ME"; Filename: "{app}\LEIA-ME.txt"
Name: "{group}\Pasta do Banco ZERO"; Filename: "{app}\BD_ZERO"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\max_x.ico"; Tasks: desktopicon

[Run]
; 1) Visual C++ Redistributable (dependencia do ODBC) — instala so se faltar.
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando Microsoft Visual C++ Redistributable..."; Check: not VCRedistInstalado; Flags: waituntilterminated
; 2) ODBC Driver 17 for SQL Server (obrigatorio p/ conectar) — instala so se faltar.
Filename: "{sys}\msiexec.exe"; Parameters: "/i ""{tmp}\msodbcsql17_x64.msi"" /qn IACCEPTMSODBCSQLLICENSETERMS=YES ADDLOCAL=ALL /norestart"; StatusMsg: "Instalando Microsoft ODBC Driver 17 for SQL Server..."; Check: not OdbcDriver17Instalado; Flags: waituntilterminated
; 3) Iniciar o Max Importa ao final (opcional).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ Detecta o ODBC Driver 17 for SQL Server (dependencia obrigatoria).
  Le tanto a view 64-bit (HKLM64) quanto a 32-bit (HKLM32). }
function OdbcDriver17Instalado(): Boolean;
var
  Chave: string;
begin
  Chave := 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server';
  Result := RegKeyExists(HKLM64, Chave) or RegKeyExists(HKLM32, Chave);
end;

{ Detecta o Visual C++ Redistributable x64 (familia 2015-2022 = runtime v14),
  pre-requisito do MSI do ODBC. Checa a flag Installed=1 nas duas views. }
function VCRedistInstalado(): Boolean;
var
  Chave: string;
  Instalado: Cardinal;
begin
  Chave := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  Result := (RegQueryDWordValue(HKLM64, Chave, 'Installed', Instalado) and (Instalado = 1))
         or (RegQueryDWordValue(HKLM32, Chave, 'Installed', Instalado) and (Instalado = 1));
end;

{ Ao final, avisa apenas se — mesmo apos a instalacao — o driver ODBC ainda
  nao estiver presente (ex.: o MSI falhou por falta do VC++). }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
  begin
    if not OdbcDriver17Instalado() then
      MsgBox('Atencao: o "ODBC Driver 17 for SQL Server" ainda nao esta instalado.'
        + #13#10#13#10
        + 'O Max Importa precisa dele para conectar ao SQL Server.' + #13#10
        + 'Instale manualmente a partir de: https://aka.ms/odbc17',
        mbInformation, MB_OK);
  end;
end;
