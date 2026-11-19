<#
.SYNOPSIS
    Start End Z with an immortal, light-workload config and drive it with
    scripted WASD/SPACE input so cloud-X capture runs never need a human.

.DESCRIPTION
    Phase A/B measurements need 60-70 s of uninterrupted gameplay on X. This
    script writes an isolated config to %TEMP%\fyp_phaseA\game_config.json
    (player max_hp 1000, obstacle/bot damage 0, light workload) and passes it to
    Z through FYP_GAME_CONFIG, so the repository game_config.json is untouched.

    It stops any running z_client.py (Middle Y and Cloud X are left alone),
    starts a fresh Z from the repo code with its logs in the temp directory,
    waits for the pygame window, then holds D/W/A/S and taps SPACE in a loop.

    The player takes no damage, so the match cannot end and the capture can run
    unattended. Press Ctrl+C to stop the input loop without stopping Z; do that
    before using the dashboard for the pause/stream check.

.PARAMETER Minutes
    How long to keep sending input (default 20). Z keeps running afterwards.

.PARAMETER Workload
    Gameplay workload passed to Z (default light). Keep it identical for every
    A0/A1/A2 run so the keyframe comparison stays valid.

.PARAMETER YAddress
    Middle Y address (default 127.0.0.1 for the home tier).

.PARAMETER Root
    Repository root (default: parent of this script).

.PARAMETER NoAutoplay
    Start the immortal match but do not send keyboard input.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\autoplay_z.ps1 -Minutes 20

.NOTES
    Run this after the current manual A0 finishes (or discard that run): A0, A1
    and A2 must share this config and this Z build to be comparable. Stop the
    autoplay with Ctrl+C before touching the dashboard. Z is left running when
    the script exits.
#>
param(
    [int]$Minutes = 20,
    [ValidateSet('light', 'medium', 'heavy')]
    [string]$Workload = 'light',
    [string]$YAddress = '127.0.0.1',
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$NoAutoplay
)

$ErrorActionPreference = 'Stop'

$python = Join-Path $Root 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python not found at $python; pass -Root or create venv." }
$temp = Join-Path $env:TEMP 'fyp_phaseA'
New-Item -ItemType Directory -Force $temp | Out-Null
New-Item -ItemType Directory -Force (Join-Path $temp 'logs') | Out-Null
$cfgPath = Join-Path $temp 'game_config.json'

# Isolated config: max_hp clamps to 1000 in game.settings; zero damage means the
# player can never die, so the match survives any capture length.
$cfg = Get-Content (Join-Path $Root 'game_config.json') -Raw | ConvertFrom-Json
$cfg.default_workload = $Workload
$cfg.player.max_hp = 1000
$cfg.player.obstacle_damage = 0
$cfg.player.bot_damage = 0
[IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 10))
$check = Get-Content $cfgPath -Raw | ConvertFrom-Json
Write-Host ("Test config: {0} (max_hp={1} obstacle_damage={2} bot_damage={3} workload={4})" -f `
    $cfgPath, $check.player.max_hp, $check.player.obstacle_damage, $check.player.bot_damage, $check.default_workload)

# Restart only Z; the Y process and its cloud-X link stay up across X restarts.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'z_client\.py' } |
    ForEach-Object {
        Write-Host "Stopping old Z PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1

Remove-Item Env:SDL_VIDEODRIVER -ErrorAction SilentlyContinue
Remove-Item Env:FYP_X_INTRA_REFRESH -ErrorAction SilentlyContinue
$env:FYP_SKIP_MENU = '1'
$env:FYP_MENU_WORKLOAD = $Workload
$env:FYP_Y_IP = $YAddress
$env:FYP_GAME_CONFIG = $cfgPath
$zOut = Join-Path $temp 'z.out'
$zErr = Join-Path $temp 'z.err'
$pz = Start-Process -FilePath $python -ArgumentList '-u', (Join-Path $Root 'z_client.py') `
    -WorkingDirectory $temp -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $zOut -RedirectStandardError $zErr
foreach ($n in 'FYP_SKIP_MENU', 'FYP_MENU_WORKLOAD', 'FYP_Y_IP', 'FYP_GAME_CONFIG') {
    Remove-Item "Env:$n" -ErrorAction SilentlyContinue
}

$wsh = New-Object -ComObject WScript.Shell
$title = 'Z - end node'
$found = $false
for ($i = 0; $i -lt 30; $i++) {
    if ($pz.HasExited) { break }
    if ($wsh.AppActivate($title)) { $found = $true; break }
    Start-Sleep -Milliseconds 500
}
if ($pz.HasExited) {
    Get-Content $zErr -ErrorAction SilentlyContinue
    throw "Z exited early; see $zOut and $zErr"
}
if (-not $found) { Write-Warning "Z window not found; click it once so autoplay can reach it." }
Start-Sleep -Seconds 2
Write-Host "Z running (PID $($pz.Id)); logs: $(Join-Path $temp 'logs\log_z.csv')"

if ($NoAutoplay) {
    Write-Host "Autoplay disabled; the match is already immortal."
    return
}

if (-not ('FypKb' -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class FypKb {
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
}
"@
}

$down = 0
$up = 2
$keys = [byte[]](0x44, 0x57, 0x41, 0x53)   # D W A S
$space = [byte]0x20
$end = (Get-Date).AddMinutes($Minutes)
try {
    while ((Get-Date) -lt $end -and -not $pz.HasExited) {
        $wsh.AppActivate($title) | Out-Null
        foreach ($vk in $keys) {
            [FypKb]::keybd_event($vk, 0, $down, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 700
            [FypKb]::keybd_event($vk, 0, $up, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 80
        }
        [FypKb]::keybd_event($space, 0, $down, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 120
        [FypKb]::keybd_event($space, 0, $up, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 80
    }
} finally {
    foreach ($vk in $keys) { [FypKb]::keybd_event($vk, 0, $up, [UIntPtr]::Zero) }
    [FypKb]::keybd_event($space, 0, $up, [UIntPtr]::Zero)
}
Write-Host "Autoplay finished; Z (PID $($pz.Id)) is still running with the immortal match."
