@echo off
rem Convenience launcher - runs the real tool in the parent folder so every path resolves.
rem Current engine, whole folder -> one CSV per plate + summary.csv. Drag a FOLDER onto this.
call "%~dp0..\Batch Plates (CSV per plate).bat" %*
