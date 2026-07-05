@echo off
:: ============================================================
::  BUILD.BAT - Gera o executavel Max_Importa.exe
::  Pode abrir com duplo clique normal. Se for aberto como
::  Administrador, ele se reabre sozinho sem elevacao.
:: ============================================================

cd /d "%~dp0"

echo.
echo  ============================================
echo   MAX_IMPORTA - Build do Executavel
echo  ============================================
echo.
echo  Pasta: %CD%
echo.

:: ============================================================
::  Se foi aberto como ADMINISTRADOR, re-executa automaticamente
::  SEM privilegios elevados (via explorer.exe, que roda com o
::  usuario normal) e fecha esta instancia elevada. Nao precisa
::  fechar e abrir de novo manualmente.
:: ============================================================
net session >nul 2>&1
if not errorlevel 1 (
    if exist "%TEMP%\maximporta_deelev.flag" (
        del "%TEMP%\maximporta_deelev.flag" >nul 2>&1
        echo [AVISO] Nao foi possivel remover a elevacao automaticamente.
        echo         Continuando assim mesmo...
        echo.
    ) else (
        echo Detectado modo "Executar como administrador".
        echo Reabrindo automaticamente SEM privilegios elevados...
        echo. > "%TEMP%\maximporta_deelev.flag"
        start "" explorer.exe "%~f0"
        exit /b 0
    )
) else (
    if exist "%TEMP%\maximporta_deelev.flag" del "%TEMP%\maximporta_deelev.flag" >nul 2>&1
)

:: ============================================================
::  Verificar Python — se nao existir, INSTALA automaticamente
:: ============================================================
python --version >nul 2>&1
if not errorlevel 1 goto PYTHON_OK

:: Python nao encontrado
if exist "%TEMP%\maximporta_pyinstall.flag" (
    del "%TEMP%\maximporta_pyinstall.flag" >nul 2>&1
    echo [ERRO] Python ainda nao foi encontrado apos a tentativa de instalacao.
    echo        Instale manualmente em https://www.python.org/downloads/
    echo        marcando a opcao "Add Python to PATH".
    pause & exit /b 1
)

echo Python nao encontrado. Instalando automaticamente (aguarde)...
echo.

:: 1) Tenta via winget (Windows 10/11)
where winget >nul 2>&1
if not errorlevel 1 (
    echo Instalando Python via winget...
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    goto PY_REABRIR
)

:: 2) Sem winget: baixa o instalador oficial e instala em modo silencioso
echo Baixando o instalador oficial do Python...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile ($env:TEMP + '\python_setup.exe') } catch { exit 1 }"
if errorlevel 1 (
    echo [ERRO] Falha ao baixar o Python. Verifique a conexao com a internet.
    pause & exit /b 1
)
echo Instalando Python (silencioso, com PATH)...
"%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1

:PY_REABRIR
echo.
echo Python instalado. Reabrindo o build para aplicar o PATH...
echo. > "%TEMP%\maximporta_pyinstall.flag"
start "" explorer.exe "%~f0"
exit /b 0

:PYTHON_OK
:: Instalacao deu certo (ou ja existia) — limpa o marcador
if exist "%TEMP%\maximporta_pyinstall.flag" del "%TEMP%\maximporta_pyinstall.flag" >nul 2>&1
echo Python: & python --version
echo.

:: Instalar dependencias
echo [1/5] Instalando dependencias...
python -m pip install customtkinter pyodbc pandas pillow "pyinstaller<7.0" pytest --quiet
echo       OK
echo.

:: ============================================================
::  Testes de regressao (GATE) — nao gera o .exe se algum falhar.
::  Por padrao roda so os unitarios (rapido, sem banco). Para
::  incluir os testes de integracao (SQL Server): set MI_TEST_DB=1
::  Para pular os testes (nao recomendado):        set MI_SKIP_TESTS=1
:: ============================================================
echo [2/5] Rodando testes de regressao...
if "%MI_SKIP_TESTS%"=="1" (
    echo       PULADO ^(MI_SKIP_TESTS=1^).
    echo.
    goto TESTES_OK
)
if "%MI_TEST_DB%"=="1" (
    echo       Incluindo testes de banco ^(MI_TEST_DB=1^)...
    python -m pytest -q
) else (
    python -m pytest -m "not db" -q
)
if errorlevel 1 (
    echo.
    echo  ============================================
    echo   [ERRO] TESTES FALHARAM - build ABORTADO.
    echo   O executavel NAO foi gerado. Corrija os testes
    echo   acima ^(ou use MI_SKIP_TESTS=1 por sua conta e risco^).
    echo  ============================================
    pause & exit /b 1
)
echo       OK
echo.
:TESTES_OK

:: Forcar remocao de qualquer .exe anterior (inclusive na pasta dist)
echo [3/5] Limpando builds anteriores...
if exist "dist\Max_Importa.exe" (
    taskkill /f /im Max_Importa.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
    del /f /q "dist\Max_Importa.exe" >nul 2>&1
    if exist "dist\Max_Importa.exe" (
        echo [ERRO] Nao foi possivel remover dist\Max_Importa.exe
        echo        Feche o programa se estiver aberto e tente novamente.
        pause & exit /b 1
    )
)
if exist "Max_Importa.exe" (
    taskkill /f /im Max_Importa.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
    del /f /q "Max_Importa.exe" >nul 2>&1
)
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist "dist"  rmdir /s /q "dist"  >nul 2>&1
echo       OK
echo.

:: Gerar executavel
echo [4/5] Gerando executavel (aguarde alguns minutos)...
python -m PyInstaller "%~dp0max_importa.spec" --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERRO] Falha no PyInstaller. Veja mensagem acima.
    pause & exit /b 1
)
echo       OK
echo.

:: Copiar .exe para pasta raiz
echo [5/5] Finalizando...
if exist "dist\Max_Importa.exe" (
    copy /y "dist\Max_Importa.exe" "%~dp0Max_Importa.exe" >nul
    echo.
    echo  ============================================
    echo   SUCESSO!
    echo   Executavel: %~dp0Max_Importa.exe
    echo  ============================================
    echo.
) else (
    echo [ERRO] Executavel nao foi gerado.
)

pause
