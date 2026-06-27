@echo off
rem Convenience launcher - runs the real tool in the parent folder so every path resolves.
rem VALIDATED published algorithm, whole FOLDER -> CSV per plate + summary. Drag a folder on.
call "%~dp0..\Original Plaque Size Tool (batch).bat" %*
