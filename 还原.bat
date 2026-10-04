@echo off
chcp 65001 >nul
title 空之轨迹 the 3rd - 还原英文版
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Convert-Sora3JP.ps1" -Restore
pause
