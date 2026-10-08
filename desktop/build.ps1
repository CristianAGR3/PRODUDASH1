param([string]$Python = "py")
$ErrorActionPreference = "Stop"
$produSource = $PSScriptRoot
& $Python -m pip install -r (Join-Path $produSource "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }
if (-not (Test-Path -LiteralPath (Join-Path $produSource "produ.ico"))) {
    & $Python -c "from PIL import Image; import sys; Image.open(sys.argv[1]).save(sys.argv[2],sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" (Join-Path $produSource "../icon-512.png") (Join-Path $produSource "produ.ico")
    if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar el icono." }
}
& $Python -m PyInstaller --noconfirm --onefile --windowed --name PRODU_Control --icon (Join-Path $produSource "produ.ico") --add-data ((Join-Path $produSource "produ.ico") + ";.") --collect-all ttkbootstrap --collect-all tzdata --exclude-module numpy --exclude-module matplotlib --exclude-module IPython --distpath (Join-Path $produSource "dist") --workpath (Join-Path $produSource "build") --specpath $produSource (Join-Path $produSource "app.py")
if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar el programa." }
