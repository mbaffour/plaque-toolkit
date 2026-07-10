@echo off

setlocal

cd /d "%~dp0"

title Plaque Stats - R-Shiny App



echo ==================================================

echo    Plaque Stats - R-Shiny App (app.R)

echo ==================================================

echo.

echo This opens the R version of the app in your web browser.

echo (Prefer no-setup? Use "Run Analysis App.bat" - the Python app.)

echo.



set "RSCRIPT=C:\Program Files\R\R-4.5.0\bin\Rscript.exe"

if exist "%RSCRIPT%" goto :haveR



echo R 4.5.0 not found at the default location; trying Rscript on PATH...

where Rscript >nul 2>nul

if not errorlevel 1 (

    set "RSCRIPT=Rscript"

    goto :haveR

)



echo.

echo *** R was not found on this PC. ***

echo To use the R app, install R from https://cran.r-project.org/ then, in R, run:

echo     install.packages(c("shiny","ggplot2","dplyr","tidyr","readr","DT","rstatix","ggpubr","scales","svglite"))

echo Or just use the Python app instead:  "Run Analysis App.bat"

echo.

pause

goto :eof



:haveR

echo Using Rscript:

echo     %RSCRIPT%

echo (First run only: this needs the R packages listed in README.md.)

echo.

"%RSCRIPT%" -e "shiny::runApp('.', launch.browser=TRUE)"

if errorlevel 1 (

    echo.

    echo *** The R app exited with an error. ***

    echo     Most often this means an R package is missing - see the hint above.

)

echo.

echo The R app has stopped.

pause

endlocal

