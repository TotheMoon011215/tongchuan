# 从魔搭（ModelScope）下载 faster-whisper 模型
# 国内可直连；HuggingFace / GitHub 在多数网络下不可用

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dir  = Join-Path $root "models\faster-whisper-large-v3-turbo"
$base = "https://www.modelscope.cn/models/pengzhendong/faster-whisper-large-v3-turbo/resolve/master"

New-Item -ItemType Directory -Force -Path $dir | Out-Null
$files = @('config.json', 'preprocessor_config.json', 'tokenizer.json', 'vocabulary.json', 'model.bin')

foreach ($f in $files) {
    $dst = Join-Path $dir $f
    Write-Host "==> $f" -ForegroundColor Cyan
    & curl.exe -L --fail --retry 5 --retry-delay 2 -C - --progress-bar -o $dst "$base/$f"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "下载失败：$f" -ForegroundColor Red
        exit 1
    }
}

$sizeMB = [math]::Round((Get-Item (Join-Path $dir 'model.bin')).Length / 1MB, 1)
Write-Host ""
Write-Host "完成：$dir  (model.bin = $sizeMB MB)" -ForegroundColor Green
