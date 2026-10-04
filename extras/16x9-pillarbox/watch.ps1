# Trails in the Sky the 3rd - 16:9 pillarbox watcher (on-demand)
# Started by steamwrap.bat / the launcher bat. Waits for the game window,
# strips borders and centers it, exits when the game exits. Singleton.
$ErrorActionPreference = 'SilentlyContinue'
$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'Sora3Watch', [ref]$created)
if (-not $created) { exit }

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class U32W {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
  [DllImport("user32.dll")] public static extern int GetWindowLongW(IntPtr h, int i);
  [DllImport("user32.dll")] public static extern int SetWindowLongW(IntPtr h, int i, int v);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
[U32W]::SetProcessDPIAware() | Out-Null

$ini = Join-Path $env:USERPROFILE 'Saved Games\Falcom\ED_SORA3\ed6_win3.ini'
$GWL_STYLE = -16
$WS_BAD = 0x01770000   # CAPTION|THICKFRAME|SYSMENU|MIN/MAXIMIZEBOX|BORDER|DLGFRAME|MAXIMIZE
$SWP = 0x0034          # NOZORDER|NOACTIVATE|FRAMECHANGED

$seen = $false
$waited = 0
while ($true) {
  $p = Get-Process -Name ed6_win3_DX9, ed6_win3 | Select-Object -First 1
  if (-not $p) {
    if ($seen) { break }                 # game was running and exited -> done
    $waited += 2
    if ($waited -gt 300) { break }       # game never showed up -> give up
    Start-Sleep -Seconds 2
    continue
  }
  $seen = $true
  $h = $p.MainWindowHandle
  if ($h -ne [IntPtr]::Zero) {
    $w = 3840; $hh = 2160
    $c = Get-Content $ini
    $m = $c | Where-Object { $_ -match '^WidthDX9=(\d+)' }  | Select-Object -First 1
    if ($m -match '^WidthDX9=(\d+)')  { $w  = [int]$Matches[1] }
    $m = $c | Where-Object { $_ -match '^HeightDX9=(\d+)' } | Select-Object -First 1
    if ($m -match '^HeightDX9=(\d+)') { $hh = [int]$Matches[1] }
    $x = [int](([U32W]::GetSystemMetrics(0) - $w) / 2)
    $y = [int](([U32W]::GetSystemMetrics(1) - $hh) / 2)

    $style = [U32W]::GetWindowLongW($h, $GWL_STYLE)
    $new = $style -band (-bnot $WS_BAD)
    if ($new -ne $style) { [U32W]::SetWindowLongW($h, $GWL_STYLE, $new) | Out-Null }

    $r = New-Object U32W+RECT
    [U32W]::GetWindowRect($h, [ref]$r) | Out-Null
    if ($r.Left -ne $x -or $r.Top -ne $y -or ($r.Right - $r.Left) -ne $w -or ($r.Bottom - $r.Top) -ne $hh) {
      [U32W]::SetWindowPos($h, [IntPtr]::Zero, $x, $y, $w, $hh, $SWP) | Out-Null
    }
  }
  Start-Sleep -Milliseconds 800
}
