@echo off
chcp 65001 >nul
title 空之轨迹 the 3rd - 日文还原（一键转换）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Convert-Sora3JP.ps1"
pause
