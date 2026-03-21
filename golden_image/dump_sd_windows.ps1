# 골든 이미지 SD 카드 덤프 스크립트 (Windows PowerShell)
# SD 카드의 전체 내용을 .img 파일로 덤프합니다.
#
# 용법: .\dump_sd_windows.ps1 -DiskNumber 3 -OutputPath .\ttlak-golden.img
# 관리자 권한 필요

param(
    [Parameter(Mandatory=$true)]
    [int]$DiskNumber,

    [Parameter(Mandatory=$false)]
    [string]$OutputPath = ".\ttlak-golden.img"
)

# 관리자 권한 확인
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "관리자 권한으로 실행해야 합니다."
    exit 1
}

$physicalDrive = "\\.\PhysicalDrive$DiskNumber"

# 디스크 정보 확인
$disk = Get-Disk -Number $DiskNumber -ErrorAction Stop
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host "대상 디스크: $physicalDrive"
Write-Host "디스크 이름: $($disk.FriendlyName)"
Write-Host "디스크 크기: $([math]::Round($disk.Size / 1GB, 2)) GB"
Write-Host "버스 타입:   $($disk.BusType)"
Write-Host "출력 파일:   $OutputPath"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 확인
$confirm = Read-Host "이 디스크를 덤프하시겠습니까? (y/N)"
if ($confirm -ne "y") {
    Write-Host "취소되었습니다."
    exit 0
}

# 파티션 마운트 해제
Write-Host "`n파티션 오프라인 처리 중..."
Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.DriveLetter) {
        Write-Host "  -> $($_.DriveLetter): 볼륨 해제"
    }
}
Set-Disk -Number $DiskNumber -IsOffline $true -ErrorAction SilentlyContinue

# 덤프 실행
Write-Host "`n덤프 시작... (시간이 걸릴 수 있습니다)"
$blockSize = 4MB
$totalBytes = $disk.Size
$bytesRead = 0

try {
    $source = [System.IO.File]::Open($physicalDrive, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $dest = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
    $buffer = New-Object byte[] $blockSize

    while ($true) {
        $read = $source.Read($buffer, 0, $blockSize)
        if ($read -eq 0) { break }
        $dest.Write($buffer, 0, $read)
        $bytesRead += $read
        $percent = [math]::Round(($bytesRead / $totalBytes) * 100, 1)
        Write-Progress -Activity "SD 카드 덤프 중" -Status "$percent% ($([math]::Round($bytesRead / 1MB)) MB / $([math]::Round($totalBytes / 1MB)) MB)" -PercentComplete $percent
    }
} finally {
    if ($source) { $source.Close() }
    if ($dest) { $dest.Close() }
    # 디스크 다시 온라인
    Set-Disk -Number $DiskNumber -IsOffline $false -ErrorAction SilentlyContinue
}

$fileSize = (Get-Item $OutputPath).Length
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host "덤프 완료!"
Write-Host "파일: $OutputPath"
Write-Host "크기: $([math]::Round($fileSize / 1GB, 2)) GB"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
