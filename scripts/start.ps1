param([switch]$Portable, [switch]$Gpu, [switch]$Admin)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop을 설치하고 실행해 주세요.' }
docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop이 실행 중인지 확인해 주세요.' }
if (-not (Test-Path -LiteralPath '.env')) {
    $projectName = ((Split-Path (Get-Location).Path -Leaf).ToLower() -replace '[^a-z0-9_-]', '')
    $existing = docker volume ls --filter "label=com.docker.compose.project=$projectName" --format '{{.Name}}'
    if ($existing) { throw '기존 DB 볼륨이 있습니다. 기존 .env를 복원한 뒤 실행해 주세요. 비밀번호를 덮어쓰지 않습니다.' }
    if (-not $Portable) { throw '새 PC에서는 .\start.cmd -Portable 을 사용해 주세요.' }
    $bytes = New-Object byte[] 24
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    $password = [BitConverter]::ToString($bytes).Replace('-', '')
    [System.IO.File]::WriteAllLines((Join-Path (Get-Location).Path '.env'), @("POSTGRES_PASSWORD=$password", "DB_PASSWORD=$password", 'DB_NAME=ai_sales', 'DB_USER=ai_user'), (New-Object System.Text.UTF8Encoding($false)))
}
$composeArgs = @('compose','-f','compose.yaml','-f','deploy/compose.backend.yaml')
if ($Portable) { $composeArgs += @('-f','deploy/compose.portable.yaml') }
if ($Gpu) {
    if (-not $Portable) { throw '-Gpu는 -Portable과 함께 사용합니다.' }
    $composeArgs += @('-f','deploy/compose.gpu.yaml')
}
& docker @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose 설정을 확인해 주세요.' }
Write-Host '서비스를 준비합니다. Portable 첫 실행에서는 모델 다운로드에 시간이 걸립니다.'
$targets = @('web')
if ($Admin) { $targets += 'app' }
& docker @composeArgs up -d --build @targets
if ($LASTEXITCODE -ne 0) { throw '실행에 실패했습니다. 위 로그를 확인해 주세요.' }
Write-Host '고객 화면: http://localhost:8080'
Write-Host 'API 문서: http://localhost:8000/docs'

if ($Admin) { Write-Host '관리 화면: http://localhost:8501' }
