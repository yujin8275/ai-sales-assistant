$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.env.ngrok')) {
    throw 'deploy/.env.ngrok.example을 .env.ngrok으로 복사한 뒤 본인 토큰을 로컬 파일에 입력해 주세요. 대화로 보내지 마세요.'
}
$settings = Get-Content -LiteralPath '.env.ngrok' -Raw -Encoding UTF8
if ($settings -notmatch '(?m)^NGROK_AUTHTOKEN=\S+\s*$' -or $settings -match '여기에_본인') {
    throw '.env.ngrok의 NGROK_AUTHTOKEN 설정을 확인해 주세요.'
}
docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.public.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw '공개 설정을 확인해 주세요.' }
# 이미 실행한 고객 화면만 연결한다. 현재 모델 실행 방식을 바꾸지 않는다.
docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.public.yaml up -d --no-deps ngrok
if ($LASTEXITCODE -ne 0) { throw 'ngrok 연결을 시작하지 못했습니다.' }
Write-Host '연결 주소는 아래 명령 또는 ngrok 대시보드에서 확인하세요.'
Write-Host 'docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.public.yaml logs --tail=20 ngrok'
