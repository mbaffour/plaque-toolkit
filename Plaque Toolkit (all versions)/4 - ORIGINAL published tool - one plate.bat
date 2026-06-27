@echo off
rem Convenience launcher - runs the real tool in the parent folder so every path resolves.
rem VALIDATED published algorithm (Trofimova & Jaschke 2021), ONE plate. Drag one photo on.
call "%~dp0..\Original Plaque Size Tool (1 plate).bat" %*
