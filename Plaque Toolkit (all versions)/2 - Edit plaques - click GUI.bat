@echo off
rem Convenience launcher - runs the real tool in the parent folder so every path resolves.
rem Interactive click-GUI: zoom, add/remove plaques, live Sensitive toggle, dish circle.
call "%~dp0..\Edit Plaques (GUI).bat" %*
