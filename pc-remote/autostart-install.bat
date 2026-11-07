@echo off
chcp 65001 >nul
rem Добавляет PC Remote в автозагрузку Windows (без окна консоли).
cd /d "%~dp0"
for /f "delims=" %%i in ('where pythonw') do set PYW=%%i& goto found
echo Не найден pythonw.exe. Установите Python с python.org и отметьте "Add to PATH".
pause & exit /b 1
:found
set LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PC Remote.lnk
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');$s.TargetPath='%PYW%';$s.Arguments='\"%~dp0server.py\"';$s.WorkingDirectory='%~dp0';$s.Save()"
echo Готово. PC Remote будет запускаться при входе в Windows.
start "" "%PYW%" "%~dp0server.py"
pause
