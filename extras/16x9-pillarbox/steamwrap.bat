@echo off
rem Steam launch wrapper for Trails in the Sky the 3rd (16:9 pillarbox).
rem Usage: Steam -> game Properties -> Launch Options, paste ONE line:
rem   <本文件的绝对路径>\steamwrap.bat %%command%%
rem Example: D:\tools\16x9-pillarbox\steamwrap.bat %command%
start "" /min powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0watch.ps1"
%*
