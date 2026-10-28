@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] 生成图标 ...
python make_icon.py || goto :err

echo [2/3] 安装/更新 PyInstaller ...
python -m pip install --quiet --upgrade pyinstaller || goto :err

echo [3/3] 打包单文件 exe ...
python -m PyInstaller --noconfirm --onefile --windowed --name CodePin ^
  --icon "assets\icon.ico" --add-data "assets;assets" main.py || goto :err

echo.
echo 完成：%~dp0dist\CodePin.exe
pause
exit /b 0

:err
echo.
echo 打包失败，请检查上面的错误信息。
pause
exit /b 1
