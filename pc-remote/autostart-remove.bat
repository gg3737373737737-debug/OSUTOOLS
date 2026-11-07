@echo off
chcp 65001 >nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PC Remote.lnk" 2>nul
echo PC Remote удалён из автозагрузки. Чтобы остановить его сейчас, перезагрузите ПК.
pause
