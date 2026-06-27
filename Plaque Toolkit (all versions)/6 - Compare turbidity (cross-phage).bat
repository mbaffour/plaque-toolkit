@echo off
rem Convenience launcher - runs the real tool in the parent folder so every path resolves.
rem Cross-phage turbidity (optical density) over a folder of plates. Drag a FOLDER onto this.
call "%~dp0..\Compare Turbidity.bat" %*
