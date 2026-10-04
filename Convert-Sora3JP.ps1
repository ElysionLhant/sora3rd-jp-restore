#Requires -Version 5.1
<#
.SYNOPSIS
  Sora3rd JP Restore - 空之轨迹 the 3rd (Steam 英文版) 日文还原补丁器
.DESCRIPTION
  把用户自备的 DLsite 日文版 (VJ009177) 中的剧本、系统文本库、原版字体
  灌入 Steam 英文版。本工具不含任何游戏数据。
.PARAMETER GameDir
  Steam 英文版游戏目录（含 ed6_win3_DX9.exe）。缺省自动从注册表探测。
.PARAMETER JpSource
  日文版来源：安装目录（或其任意上级目录）或 VJ009177.zip。缺省交互询问。
.PARAMETER Restore
  从备份还原为英文原版。
.PARAMETER BackupDir
  指定用于还原的备份目录（缺省取 backup\ 下最新一个）。
.PARAMETER KeepHdFont
  保留 XSEED 高清字体，不换日版原点位图字体（也不改 HighResoText）。
.EXAMPLE
  .\Convert-Sora3JP.ps1 -JpSource D:\dl\sora3rd_w8\ED_SORA3
.EXAMPLE
  .\Convert-Sora3JP.ps1 -Restore
#>
[CmdletBinding()]
param(
  [string]$GameDir,
  [string]$JpSource,
  [switch]$Restore,
  [string]$BackupDir,
  [switch]$KeepHdFont
)
$ErrorActionPreference = 'Stop'

$cs = @'
using System;
using System.IO;
using System.Text;

public class LB {
  public int Count;
  public byte[] DirHeader = new byte[16];
  public byte[][] Records;
  public byte[][] Contents;
  public string[] Names;

  public static LB Load(string dirPath, string datPath) {
    var lb = new LB();
    byte[] d = File.ReadAllBytes(dirPath);
    byte[] b = File.ReadAllBytes(datPath);
    lb.Count = BitConverter.ToInt32(d, 8);
    Array.Copy(d, 0, lb.DirHeader, 0, 16);
    lb.Records = new byte[lb.Count][];
    lb.Contents = new byte[lb.Count][];
    lb.Names = new string[lb.Count];
    int[] off = new int[lb.Count + 1];
    for (int i = 0; i <= lb.Count; i++) off[i] = BitConverter.ToInt32(b, 16 + 4 * i);
    for (int i = 0; i < lb.Count; i++) {
      byte[] rec = new byte[36];
      Array.Copy(d, 16 + 36 * i, rec, 0, 36);
      lb.Records[i] = rec;
      string n = Encoding.ASCII.GetString(rec, 0, 12);
      int cut = n.IndexOfAny(new char[] { '\0', ' ' });
      if (cut >= 0) n = n.Substring(0, cut);
      lb.Names[i] = n;
      int next = (i + 1 <= lb.Count - 1) ? off[i + 1] : b.Length;
      int len = next - off[i];
      if (len < 0) len = 0;
      byte[] c = new byte[len];
      Array.Copy(b, off[i], c, 0, len);
      lb.Contents[i] = c;
    }
    return lb;
  }

  public int Find(string name) {
    for (int i = 0; i < Count; i++)
      if (string.Equals(Names[i], name, StringComparison.OrdinalIgnoreCase)) return i;
    return -1;
  }

  public int FindEmpty() {
    for (int i = 0; i < Count; i++)
      if (Names[i].Length == 0 || Names[i].StartsWith("/_")) return i;
    return -1;
  }

  public void GraftFrom(LB src, params string[] names) {
    foreach (var n in names) {
      int si = src.Find(n);
      if (si < 0) throw new Exception("src missing " + n);
      int slot = FindEmpty();
      if (slot < 0) throw new Exception("no empty slot");
      Records[slot] = src.Records[si];
      Contents[slot] = src.Contents[si];
      Names[slot] = src.Names[si];
    }
  }

  public void ReplaceFrom(LB src, params string[] names) {
    foreach (var n in names) {
      int si = src.Find(n);
      if (si < 0) throw new Exception("src missing " + n);
      int bi = Find(n);
      if (bi < 0) throw new Exception("base missing " + n);
      Records[bi] = src.Records[si];
      Contents[bi] = src.Contents[si];
      Names[bi] = src.Names[si];
    }
  }

  public void Save(string dirPath, string datPath) {
    using (var fs = new FileStream(datPath, FileMode.Create)) {
      var bw = new BinaryWriter(fs);
      bw.Write(new byte[] { 0x4C, 0x42, 0x20, 0x44, 0x41, 0x54, 0x1A, 0x00 });
      bw.Write(Count);
      bw.Write(0);
      long tablePos = fs.Position;
      for (int i = 0; i <= Count; i++) bw.Write(0);
      int[] offs = new int[Count + 1];
      for (int i = 0; i < Count; i++) {
        offs[i] = (int)fs.Position;
        fs.Write(Contents[i], 0, Contents[i].Length);
        byte[] o = BitConverter.GetBytes(offs[i]);
        Array.Copy(o, 0, Records[i], 32, 4);
      }
      offs[Count] = (int)fs.Position;
      fs.Position = tablePos;
      for (int i = 0; i <= Count; i++) bw.Write(offs[i]);
    }
    using (var fs = new FileStream(dirPath, FileMode.Create)) {
      fs.Write(DirHeader, 0, 16);
      for (int i = 0; i < Count; i++) fs.Write(Records[i], 0, 36);
    }
  }
}
'@
Add-Type -TypeDefinition $cs -Language CSharp

function Fail($msg) { Write-Host "`n[失败] $msg" -ForegroundColor Red; exit 1 }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }

# ---------- 定位英文版 ----------
if (-not $GameDir) {
  $steam = (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam' -ErrorAction SilentlyContinue).InstallPath
  if ($steam) { $GameDir = Join-Path $steam 'steamapps\common\Trails in the Sky the 3rd' }
}
if (-not (Test-Path "$GameDir\ed6_win3_DX9.exe")) { Fail "找不到 Steam 英文版：$GameDir（可用 -GameDir 指定）" }
if (Get-Process -Name ed6_win3, ed6_win3_DX9 -ErrorAction SilentlyContinue) { Fail '游戏正在运行，请先关闭再执行。' }

$ToolDir = $PSScriptRoot
$backupRoot = Join-Path $ToolDir 'backup'
$ini = Join-Path $env:USERPROFILE 'Saved Games\Falcom\ED_SORA3\ed6_win3.ini'

# ---------- 还原 ----------
if ($Restore) {
  if (-not $BackupDir) {
    $BackupDir = Get-ChildItem $backupRoot -Directory -ErrorAction SilentlyContinue |
      Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
  }
  if (-not $BackupDir -or -not (Test-Path "$BackupDir\ED6_DT21.dat")) { Fail "找不到备份（$BackupDir）" }
  foreach ($a in 'ED6_DT20', 'ED6_DT21', 'ED6_DT22') {
    Copy-Item "$BackupDir\$a.dat", "$BackupDir\$a.dir" $GameDir -Force
  }
  Remove-Item "$GameDir\dll\lang_jpn.dll" -Force -ErrorAction SilentlyContinue
  if (Test-Path "$BackupDir\ed6_win3.ini") { Copy-Item "$BackupDir\ed6_win3.ini" $ini -Force }
  Ok "已从 $BackupDir 还原为英文原版"
  return
}

# ---------- 定位日文版 ----------
if (-not $JpSource) {
  $JpSource = Read-Host '请输入日文版路径（安装目录、或其上级目录、或 VJ009177.zip）'
}
$tmp = $null
if (Test-Path $JpSource -PathType Leaf) {
  Write-Host '解压日文版压缩包…'
  $tmp = Join-Path $env:TEMP ('sora3jp-' + [guid]::NewGuid())
  Expand-Archive -Path $JpSource -DestinationPath $tmp
  $JpSource = $tmp
}
$hit = Get-ChildItem -Path $JpSource -Recurse -Filter 'ED6_DT21.dir' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $hit) { Fail '在该路径下找不到日文版封包 ED6_DT21.dir' }
$jpDir = $hit.DirectoryName
foreach ($a in 'ED6_DT20', 'ED6_DT21', 'ED6_DT22') {
  if (-not (Test-Path "$jpDir\$a.dat")) { Fail "日文版缺少 $a.dat：$jpDir" }
}
Ok "日文版：$jpDir"

# ---------- 备份 ----------
$bk = Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Force $bk | Out-Null
foreach ($a in 'ED6_DT20', 'ED6_DT21', 'ED6_DT22') {
  Copy-Item "$GameDir\$a.dat", "$GameDir\$a.dir" $bk
}
if (Test-Path $ini) { Copy-Item $ini $bk }
Ok "英文原版已备份到 $bk"

# ---------- DT21 剧本 ----------
Write-Host '处理 DT21（全地图剧本）…'
$en21 = [LB]::Load("$GameDir\ED6_DT21.dir", "$GameDir\ED6_DT21.dat")
$jp21 = [LB]::Load("$jpDir\ED6_DT21.dir", "$jpDir\ED6_DT21.dat")
[string[]]$need21 = 'M7408_1', 'U7003_6', 'E1000_1', 'T4206_1', 'U7002_6' | Where-Object { $en21.Find($_) -ge 0 }
if ($need21.Count) { $jp21.GraftFrom($en21, $need21) }
$jp21.Save("$GameDir\ED6_DT21.dir", "$GameDir\ED6_DT21.dat")
Ok "DT21：日版剧本 $($jp21.Count) 项 + 回填英文版独有 $($need21.Count) 项"

# ---------- DT22 系统文本库 ----------
Write-Host '处理 DT22（物品/魔法/任务/书物等文本库）…'
$en22 = [LB]::Load("$GameDir\ED6_DT22.dir", "$GameDir\ED6_DT22.dat")
$jp22 = [LB]::Load("$jpDir\ED6_DT22.dir", "$jpDir\ED6_DT22.dat")
[string[]]$need22 = 'T_QUIZ04._DT', 'T_BTREV' | Where-Object { $en22.Find($_) -ge 0 }
if ($need22.Count) { $jp22.GraftFrom($en22, $need22) }
$jp22.Save("$GameDir\ED6_DT22.dir", "$GameDir\ED6_DT22.dat")
Ok "DT22：日版文本库 $($jp22.Count) 项 + 回填英文版独有 $($need22.Count) 项（T_BTREV 为引擎启动必需）"

# ---------- DT20 原版字体 ----------
if ($KeepHdFont) {
  Write-Host '跳过字体（保留 XSEED 高清字体）'
} else {
  Write-Host '处理 DT20（日版原点位图字体 FONT8-FONT32）…'
  $en20 = [LB]::Load("$GameDir\ED6_DT20.dir", "$GameDir\ED6_DT20.dat")
  $jp20 = [LB]::Load("$jpDir\ED6_DT20.dir", "$jpDir\ED6_DT20.dat")
  $en20.ReplaceFrom($jp20, 'FONT8', 'FONT12', 'FONT16', 'FONT20', 'FONT24', 'FONT32')
  $en20.Save("$GameDir\ED6_DT20.dir", "$GameDir\ED6_DT20.dat")
  Ok 'DT20：6 档原版字体已换入'
}

# ---------- 日文菜单开关 + 经典渲染 ----------
New-Item -ItemType File -Force "$GameDir\dll\lang_jpn.dll" | Out-Null
Ok 'dll\lang_jpn.dll（日文菜单开关）'
if (-not $KeepHdFont -and (Test-Path $ini)) {
  (Get-Content $ini) -replace '^HighResoText=\d', 'HighResoText=0' | Set-Content $ini -Encoding ASCII
  Ok 'ed6_win3.ini: HighResoText=0（经典字体渲染，修复名称/正文漂移）'
}

if ($tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host "`n完成。启动游戏即为日文原版体验（贴图类如 LOGO/按钮仍为英文，见 README）。"
Write-Host "如需还原英文版：执行 还原.bat 或本脚本加 -Restore"
