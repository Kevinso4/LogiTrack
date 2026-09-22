<#
    subir-a-github.ps1 — LogiTrack

    Deja el repositorio listo y lo sube a GitHub, de principio a fin.

    Es IDEMPOTENTE y NO DESTRUCTIVO: se puede correr varias veces sin daño.
    Nunca sobrescribe un archivo que ya existe — a .gitignore solo le AÑADE
    las líneas que falten, y los Dockerfile los verifica, no los genera.
    Si algo falta de verdad, se detiene y te dice qué, en vez de inventar un
    archivo que podría no coincidir con tu proyecto.
#>

$ErrorActionPreference = 'Stop'

# --- Configuración -----------------------------------------------------------
$Proyecto   = 'C:\Users\keyne\Documents\LogiTrack'
$NombreRepo = 'LogiTrack'
$Visibilidad = '--public'          # cámbialo a '--private' si no quieres que lo vea nadie más
$Servicios  = @(
    'fleet-service',
    'tracking-service',
    'routing-service',
    'shipment-service',
    'interop-bridge'
)

function Titulo($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Aviso($t)  { Write-Host "  [!]    $t" -ForegroundColor Yellow }
function Fallo($t)  { Write-Host "  [X]    $t" -ForegroundColor Red }

# =============================================================================
# 0. Comprobaciones previas
# =============================================================================
Titulo '0. Herramientas'

foreach ($cmd in @('git', 'gh')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Fallo "'$cmd' no está instalado."
        if ($cmd -eq 'gh') {
            Write-Host @"

  Instálalo con uno de estos y vuelve a correr el script:
      winget install --id GitHub.cli
      choco install gh

  Si no quieres instalarlo, crea el repo a mano en github.com y luego:
      cd $Proyecto
      git remote add origin https://github.com/TU-USUARIO/$NombreRepo.git
      git push -u origin main
"@ -ForegroundColor Yellow
        }
        exit 1
    }
    Ok "$cmd disponible"
}

if (-not (Test-Path $Proyecto)) { Fallo "No existe la carpeta $Proyecto"; exit 1 }
Set-Location $Proyecto
Ok "Carpeta: $Proyecto"

# =============================================================================
# 1. .gitignore — se AÑADE lo que falte, nunca se reemplaza
# =============================================================================
Titulo '1. .gitignore'

$Patrones = @(
    '__pycache__/', '*.py[cod]', '.pytest_cache/', '.ruff_cache/',
    '.venv/', 'venv/', 'env/', '.env', '.env.*', '!.env.example',
    '*.db', '*.sqlite3', '.coverage', 'htmlcov/',
    '.idea/', '.vscode/', '*.log',
    'docker-compose.override.yml', '.DS_Store', 'Thumbs.db'
)

$rutaGi = Join-Path $Proyecto '.gitignore'
if (Test-Path $rutaGi) {
    $actuales = Get-Content $rutaGi
    Ok ".gitignore existe ($($actuales.Count) líneas), se conserva"
} else {
    $actuales = @()
    Aviso ".gitignore no existía, se crea"
}

$faltantes = $Patrones | Where-Object { $actuales -notcontains $_ }
if ($faltantes) {
    Add-Content $rutaGi "`n# --- añadido por subir-a-github.ps1 ---"
    $faltantes | ForEach-Object { Add-Content $rutaGi $_ }
    Ok "Añadidos $($faltantes.Count) patrones: $($faltantes -join ', ')"
} else {
    Ok "Ya cubre todo lo necesario"
}

# .gitattributes: sin esto, Windows guarda los .sh con CRLF y el entrypoint
# revienta dentro del contenedor Linux con 'no such file or directory'.
# Es LA causa número uno de que a un compañero no le arranque el stack.
$rutaGa = Join-Path $Proyecto '.gitattributes'
if (-not (Test-Path $rutaGa) -or -not (Select-String -Path $rutaGa -Pattern '\*\.sh' -Quiet)) {
    Add-Content $rutaGa "`n*.sh text eol=lf"
    Add-Content $rutaGa "entrypoint.sh text eol=lf"
    Ok "Forzado LF en los scripts .sh (evita que el entrypoint falle al clonar)"
} else {
    Ok ".gitattributes ya fuerza LF en los .sh"
}

# =============================================================================
# 2. Verificación del stack (verifica, NO genera)
# =============================================================================
Titulo '2. Estructura Docker'

$problemas = @()

if (-not (Test-Path (Join-Path $Proyecto 'docker-compose.yml'))) {
    $problemas += 'falta docker-compose.yml en la raíz'
} else { Ok 'docker-compose.yml presente' }

foreach ($s in $Servicios) {
    $dir = Join-Path $Proyecto $s
    if (-not (Test-Path $dir)) { Aviso "$s no existe en esta carpeta (se omite)"; continue }
    if (Test-Path (Join-Path $dir 'Dockerfile')) {
        Ok "$s/Dockerfile"
    } else {
        $problemas += "$s no tiene Dockerfile"
    }
}

if ($problemas) {
    Fallo 'Faltan piezas del stack:'
    $problemas | ForEach-Object { Write-Host "         - $_" -ForegroundColor Red }
    Write-Host @"

  El script NO los genera a propósito: un Dockerfile inventado que no
  coincida con tu proyecto es peor que no tenerlo, porque falla al
  construir y cuesta más encontrar por qué.
  Créalos o dime cuáles faltan y te los escribo a medida.
"@ -ForegroundColor Yellow
    exit 1
}

# Validación real de la sintaxis y las variables del compose.
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose config --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok 'docker compose config válido' }
    else { Aviso 'docker compose config devolvió errores (revísalo antes de que tu compañero clone)' }
} else {
    Aviso 'Docker no está en el PATH, se omite la validación del compose'
}

# =============================================================================
# 3. Git: init si hace falta, y commit de lo pendiente
# =============================================================================
Titulo '3. Git'

if (-not (Test-Path (Join-Path $Proyecto '.git'))) {
    git init -q
    Ok 'Repositorio inicializado'
} else {
    Ok "Repositorio ya existía ($(git rev-list --count HEAD 2>$null) commits)"
}

# Rama main (el nombre que GitHub espera por defecto).
$rama = git branch --show-current
if (-not $rama) { git checkout -q -b main; $rama = 'main' }
elseif ($rama -ne 'main') { git branch -M main; $rama = 'main' }
Ok "Rama: $rama"

if (-not (git config user.email)) {
    git config user.email 'kevinayaso95@gmail.com'
    git config user.name  'Kevin Ayazo'
    Ok 'Identidad de git configurada para este repo'
}

git add -A
$pendientes = git diff --cached --name-only
if ($pendientes) {
    git commit -q -m "preparacion para publicar: gitignore, atributos de fin de linea y verificacion del stack"
    Ok "Commit creado ($(($pendientes | Measure-Object).Count) archivos)"
} else {
    Ok 'No había cambios pendientes'
}

# =============================================================================
# 4. GitHub: autenticación, creación del repo y push
# =============================================================================
Titulo '4. GitHub'

# PowerShell 5.1 convierte en excepción fatal cualquier cosa que un programa
# externo escriba por la salida de error cuando ErrorActionPreference vale
# 'Stop'. `gh auth status` informa por esa vía que no hay sesión, lo cual es
# información normal, no un fallo. A partir de aquí comprobamos el resultado
# con $LASTEXITCODE, que es lo que de verdad dice si el comando funcionó.
$ErrorActionPreference = 'Continue'

gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Aviso 'No hay sesión de GitHub. Se abre el login...'
    Write-Host '  Elige: GitHub.com -> HTTPS -> Y -> Login with a web browser' -ForegroundColor Yellow
    Write-Host '  (copia el código de 8 caracteres que aparece y pégalo en el navegador)' -ForegroundColor Yellow
    Write-Host ''
    gh auth login --hostname github.com --git-protocol https --web
    gh auth status *> $null
    if ($LASTEXITCODE -ne 0) { Fallo 'El login no se completó. Corre el script otra vez.'; exit 1 }
}

$usuario = (gh api user --jq .login 2>$null)
if (-not $usuario) { Fallo 'No pude leer tu usuario de GitHub.'; exit 1 }
Ok "Autenticado como: $usuario"

$remoto = git remote get-url origin 2>$null
if ($remoto) {
    Ok "El remoto ya existe: $remoto"
    git push -u origin main
} else {
    gh repo create $NombreRepo $Visibilidad --source=. --remote=origin --push `
        --description "LogiTrack - plataforma de gestion de flotas en microservicios (FastAPI, PostgreSQL, RabbitMQ, Docker)"
}

if ($LASTEXITCODE -ne 0) { Fallo 'El push falló. Mira el mensaje de arriba.'; exit 1 }

$url = "https://github.com/$usuario/$NombreRepo"

# =============================================================================
# 5. Listo
# =============================================================================
Write-Host "`n$('=' * 70)" -ForegroundColor Green
Write-Host " REPOSITORIO PUBLICADO" -ForegroundColor Green
Write-Host "$('=' * 70)" -ForegroundColor Green
Write-Host "`n  $url`n"

Write-Host " Mándale ESTO a tu companero (una sola linea):" -ForegroundColor Cyan
Write-Host ""
Write-Host "   git clone $url.git && cd $NombreRepo && docker compose up --build -d" -ForegroundColor White
Write-Host ""
Write-Host " Cuando termine, el stack queda en:" -ForegroundColor Cyan
Write-Host "   Fleet    http://localhost:8001/docs"
Write-Host "   Tracking http://localhost:8002/docs"
Write-Host "   Routing  http://localhost:8003/docs"
Write-Host "   Shipment http://localhost:8004/docs"
Write-Host "   RabbitMQ http://localhost:15672  (logitrack / logitrack)"
Write-Host "   Panel    abre panel.html con doble clic"
Write-Host ""
Write-Host " El puente de interoperabilidad NO arranca solo (esta bajo perfil):" -ForegroundColor Cyan
Write-Host "   docker compose --profile interop up -d"
Write-Host ""