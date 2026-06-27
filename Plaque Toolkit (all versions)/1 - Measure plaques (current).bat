@echo off
rem Convenience launcher - runs the real tool in the parent folder so every path resolves.
rem Current (enhanced) engine: size + turbidity columns. Drag photo(s) onto this file.
call "%~dp0..\Measure Plaques.bat" %*
