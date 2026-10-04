#Requires -Version 5.1
<#
.SYNOPSIS
  Sora3rd JP Restore - 空之轨迹 the 3rd (Steam 英文版) 日文还原补丁器
.DESCRIPTION
  把用户自备的 DLsite 日文版 (VJ009177) 中的剧本、系统文本库、原版字体、
  预渲染素材（标题/卡片/立绘/结尾 STAFF 表）灌入 Steam 英文版。
  本工具不含任何游戏数据。
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
.PARAMETER NoTextures
  跳过预渲染素材替换（只换剧本/文本库/字体）。
.PARAMETER StaffRoll
  同时替换结尾 STAFF 表影像（ED6_DT51）。若检测到 ffmpeg 则转码为可播放的
  XviD AVI，否则直接拷入日版 MPEG（部分系统缺少 MPEG-PS 解码器时无法播放）。
.EXAMPLE
  .\Convert-Sora3JP.ps1 -JpSource D:\dl\sora3rd_w8\ED_SORA3 -StaffRoll
.EXAMPLE
  .\Convert-Sora3JP.ps1 -Restore
#>
[CmdletBinding()]
param(
  [string]$GameDir,
  [string]$JpSource,
  [switch]$Restore,
  [string]$BackupDir,
  [switch]$KeepHdFont,
  [switch]$NoTextures,
  [switch]$StaffRoll
)
$ErrorActionPreference = 'Stop'

$cs = @'
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;

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

  public void SetFields(int i, int size, uint flags) {
    Array.Copy(BitConverter.GetBytes(size), 0, Records[i], 16, 4);
    Array.Copy(BitConverter.GetBytes(flags), 0, Records[i], 20, 4);
    Array.Copy(BitConverter.GetBytes(size), 0, Records[i], 24, 4);
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

  public void ReplaceFrom(LB src, bool skipMissing, params string[] names) {
    foreach (var n in names) {
      int si = src.Find(n);
      if (si < 0) { if (skipMissing) continue; throw new Exception("src missing " + n); }
      int bi = Find(n);
      if (bi < 0) { if (skipMissing) continue; throw new Exception("base missing " + n); }
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
        Array.Copy(BitConverter.GetBytes(offs[i]), 0, Records[i], 32, 4);
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

public static class Bz {
  // Falcom bzip decompressor (mode1 + mode2)
  class R {
    public byte[] d; public int p;
    public R(byte[] x) { d = x; p = 0; }
    public int U8() { return d[p++]; }
    public int U16() { int v = BitConverter.ToUInt16(d, p); p += 2; return v; }
    public byte[] Slice(int n) { var v = new byte[n]; Array.Copy(d, p, v, 0, n); p += n; return v; }
    public int Left { get { return d.Length - p; } }
  }
  static int bitsVal, bitsNext;
  static void Renew(R f) { bitsVal = f.U16(); bitsNext = 1; }
  static int Bit(R f) {
    if (bitsNext == 0) Renew(f);
    int v = (bitsVal & bitsNext) != 0 ? 1 : 0;
    bitsNext = (bitsNext << 1) & 0xFFFF;
    return v;
  }
  static int Bits(int n, R f) {
    int x = 0;
    for (int i = 0; i < n % 8; i++) x = (x << 1) | Bit(f);
    for (int i = 0; i < n / 8; i++) x = (x << 8) | f.U8();
    return x;
  }
  static int ReadCount(R f) {
    if (Bit(f) == 1) return 2;
    if (Bit(f) == 1) return 3;
    if (Bit(f) == 1) return 4;
    if (Bit(f) == 1) return 5;
    if (Bit(f) == 1) return 6 + Bits(3, f);
    return 14 + Bits(8, f);
  }
  static void Rep(List<byte> o, int n, int off) {
    for (int i = 0; i < n; i++) o.Add(o[o.Count - off]);
  }
  static void Const(List<byte> o, int n, int v) { for (int i = 0; i < n; i++) o.Add((byte)v); }

  static void Mode2(byte[] data, List<byte> o) {
    var f = new R(data);
    bitsVal = 0; bitsNext = 0;
    Renew(f); bitsNext <<= 8;
    while (true) {
      if (Bit(f) == 0) { o.Add((byte)f.U8()); continue; }
      if (Bit(f) == 0) {
        int off = Bits(8, f), n = ReadCount(f);
        Rep(o, n, off);
      } else {
        int o2 = Bits(13, f);
        if (o2 == 0) break;
        if (o2 == 1) {
          int n = (Bit(f) == 1) ? Bits(12, f) : Bits(4, f);
          Const(o, 14 + n, f.U8());
        } else {
          int n = ReadCount(f);
          Rep(o, n, o2);
        }
      }
    }
  }

  static void Mode1(byte[] data, List<byte> o) {
    var f = new R(data);
    int lastO = 0;
    while (f.Left > 0) {
      int c = f.U8();
      if ((c & 0xC0) == 0x00) {
        int n = c & 0x1F;
        if ((c & 0x20) != 0) n = (n << 8) | f.U8();
        o.AddRange(f.Slice(n));
      } else if ((c & 0xE0) == 0x40) {
        int n = c & 0x0F;
        if ((c & 0x10) != 0) n = (n << 8) | f.U8();
        Const(o, 4 + n, f.U8());
      } else if ((c & 0xE0) == 0x60) {
        Rep(o, c & 0x1F, lastO);
      } else {
        int n = (c >> 5) & 0x03;
        lastO = ((c & 0x1F) << 8) | f.U8();
        Rep(o, 4 + n, lastO);
      }
    }
  }

  public static byte[] Decompress(byte[] data) {
    var o = new List<byte>();
    if (data.Length > 0 && data[0] == 0) Mode2(data, o); else Mode1(data, o);
    return o.ToArray();
  }
}

public static class Ed6 {
  public static byte[] Decompress(byte[] data) {
    var f = new MemoryStream(data);
    var br = new BinaryReader(f);
    var o = new List<byte>();
    while (true) {
      int len = br.ReadUInt16() - 2;
      byte[] chunk = br.ReadBytes(len);
      o.AddRange(Bz.Decompress(chunk));
      if (br.ReadByte() == 0) break;
    }
    return o.ToArray();
  }

  public static byte[] CompressLiterals(byte[] data) {
    var chunks = new List<byte[]>();
    int pos = 0;
    while (pos < data.Length) {
      int n = Math.Min(0xF000, data.Length - pos);
      var enc = new List<byte>();
      int i = 0;
      while (i < n) {
        int m = Math.Min(n - i, 8191);
        if (m <= 31) enc.Add((byte)m);
        else { enc.Add((byte)(0x20 | (m >> 8))); enc.Add((byte)(m & 0xFF)); }
        for (int k = 0; k < m; k++) enc.Add(data[pos + i + k]);
        i += m;
      }
      chunks.Add(enc.ToArray());
      pos += n;
    }
    var o = new List<byte>();
    for (int c = 0; c < chunks.Count; c++) {
      o.AddRange(BitConverter.GetBytes((ushort)(chunks[c].Length + 2)));
      o.AddRange(chunks[c]);
      o.Add((byte)(chunks.Count - 1 - c));
    }
    return o.ToArray();
  }

  public static byte[] Argb1555ToBgra(byte[] raw) {
    var o = new byte[raw.Length * 2];
    for (int i = 0, j = 0; i < raw.Length; i += 2, j += 4) {
      int v = raw[i] | (raw[i + 1] << 8);
      int a = (v & 0x8000) != 0 ? 255 : 0;
      int r = (v >> 10) & 0x1F, g = (v >> 5) & 0x1F, b = v & 0x1F;
      o[j] = (byte)((b << 3) | (b >> 2));
      o[j + 1] = (byte)((g << 3) | (g >> 2));
      o[j + 2] = (byte)((r << 3) | (r >> 2));
      o[j + 3] = (byte)a;
    }
    return o;
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
  foreach ($a in 'ED6_DT20', 'ED6_DT21', 'ED6_DT22', 'ED6_DT24') {
    if (Test-Path "$BackupDir\$a.dat") { Copy-Item "$BackupDir\$a.dat", "$BackupDir\$a.dir" $GameDir -Force }
  }
  if (Test-Path "$BackupDir\ED6_DT51.dat") { Copy-Item "$BackupDir\ED6_DT51.dat" $GameDir -Force }
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
foreach ($a in 'ED6_DT20', 'ED6_DT21', 'ED6_DT22', 'ED6_DT24') {
  Copy-Item "$GameDir\$a.dat", "$GameDir\$a.dir" $bk
}
if ($StaffRoll -and (Test-Path "$GameDir\ED6_DT51.dat")) { Copy-Item "$GameDir\ED6_DT51.dat" $bk }
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

# ---------- DT20 字体 + 界面素材 ----------
if ($KeepHdFont) {
  Write-Host '跳过字体（保留 XSEED 高清字体）'
} else {
  Write-Host '处理 DT20（日版原点位图字体 FONT8-FONT32）…'
  $en20 = [LB]::Load("$GameDir\ED6_DT20.dir", "$GameDir\ED6_DT20.dat")
  $jp20 = [LB]::Load("$jpDir\ED6_DT20.dir", "$jpDir\ED6_DT20.dat")
  $en20.ReplaceFrom($jp20, $false, 'FONT8', 'FONT12', 'FONT16', 'FONT20', 'FONT24', 'FONT32')
  $en20.Save("$GameDir\ED6_DT20.dir", "$GameDir\ED6_DT20.dat")
  Ok 'DT20 字体：6 档原版字体已换入'
}

if (-not $NoTextures) {
  Write-Host '处理 DT20 界面素材（SUBTI/STATUS/ICON/NOTE）…'
  $en20t = [LB]::Load("$GameDir\ED6_DT20.dir", "$GameDir\ED6_DT20.dat")
  $jp20t = [LB]::Load("$jpDir\ED6_DT20.dir", "$jpDir\ED6_DT20.dat")
  $en20t.ReplaceFrom($jp20t, $true, 'C_SUBTI', 'C_STATUS._CH', 'C_ICON1', 'C_NOTE1')

  Write-Host '处理角色立绘 C_STCH（ARGB1555 → 32bpp 转换）…'
  $stchNames = @()
  foreach ($i in 0..18) { $stchNames += ('C_STCH{0:00}._CH' -f $i) }
  $stchNames += 'C_STCH32._CH', 'C_STCH35._CH', 'C_STCH36._CH'
  $conv = 0
  foreach ($n in $stchNames) {
    $si = $jp20t.Find($n); $bi = $en20t.Find($n)
    if ($si -lt 0 -or $bi -lt 0) { continue }
    $raw = [Ed6]::Decompress($jp20t.Contents[$si])
    if ($raw.Length -ne (512 * 512 * 2)) { Write-Host "  [跳过] $n（raw $($raw.Length)）"; continue }
    $bgra = [Ed6]::Argb1555ToBgra($raw)
    $packed = [Ed6]::CompressLiterals($bgra)
    $en20t.Contents[$bi] = $packed
    $en20t.SetFields($bi, $packed.Length, 0x00080000)
    $conv++
  }
  $en20t.Save("$GameDir\ED6_DT20.dir", "$GameDir\ED6_DT20.dat")
  Ok "DT20 素材：界面素材换入 + $conv 张立绘转为 32bpp（修复 16 位色不渲染问题）"

  Write-Host '处理 DT24（剧情卡/地名卡/门标题卡/标题界面）…'
  $en24 = [LB]::Load("$GameDir\ED6_DT24.dir", "$GameDir\ED6_DT24.dat")
  $jp24 = [LB]::Load("$jpDir\ED6_DT24.dir", "$jpDir\ED6_DT24.dat")
  $names = @()
  for ($i = 0; $i -lt $en24.Count; $i++) { if ($en24.Names[$i] -like 'C_*') { $names += $en24.Names[$i] } }
  $en24.ReplaceFrom($jp24, $true, [string[]]$names)

  # C_TITLE1 特殊处理：整包替换会让难度按钮丢失（日版图集布局不同）——
  # 合成"日版顶部 185 行（空轨 logo）+ 英文版底部（按钮/装饰）"
  $enTitle1 = [LB]::Load("$bk\ED6_DT24.dir", "$bk\ED6_DT24.dat")
  $biE = $enTitle1.Find('C_TITLE1._CH'); $biJ = $jp24.Find('C_TITLE1._CH'); $biC = $en24.Find('C_TITLE1._CH')
  if ($biE -ge 0 -and $biJ -ge 0 -and $biC -ge 0) {
    $rawE = [Ed6]::Decompress($enTitle1.Contents[$biE])
    $rawJ = [Ed6]::Decompress($jp24.Contents[$biJ])
    if ($rawE.Length -eq $rawJ.Length -and $rawE.Length -ge (512 * 512 * 2)) {
      $spliced = [byte[]]$rawE.Clone()
      [Array]::Copy($rawJ, 0, $spliced, 0, 185 * 512 * 2)
      $packed = [Ed6]::CompressLiterals($spliced)
      $en24.Contents[$biC] = $packed
      $en24.SetFields($biC, $packed.Length, 0x000F0000)
      Ok '  C_TITLE1：已合成（日版 logo 顶行 + 英文版按钮区）'
    }
  }
  $en24.Save("$GameDir\ED6_DT24.dir", "$GameDir\ED6_DT24.dat")
  Ok "DT24：$($names.Count) 项素材换为日版"
}

# ---------- 结尾 STAFF 表（可选） ----------
if ($StaffRoll) {
  $jp51 = Join-Path $jpDir 'ED6_DT51.dat'
  if (Test-Path $jp51) {
    $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $imgFf = Join-Path $env:APPDATA 'Python\Python310\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
    if ($ff) { $ffmpeg = $ff.Source }
    elseif (Test-Path $imgFf) { $ffmpeg = $imgFf }
    else { $ffmpeg = $null }
    if ($ffmpeg) {
      Write-Host '转码结尾 STAFF 表为 XviD AVI（日版原片，含 Evolution 声优表）…'
      & $ffmpeg -hide_banner -loglevel error -y -i $jp51 -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 `
        -c:v libxvid -qscale:v 4 -vf "scale=1920:960,pad=1920:1080:0:60" -r 30 -c:a libmp3lame -b:a 192k -shortest `
        "$GameDir\ED6_DT51.dat"
      if ($LASTEXITCODE -ne 0) { Fail 'ffmpeg 转码失败' }
      Ok 'ED6_DT51：日版结尾 STAFF 表（XviD AVI，可播放）'
    } else {
      Copy-Item $jp51 "$GameDir\ED6_DT51.dat" -Force
      Write-Host '  [注意] 未找到 ffmpeg，已直接拷入日版 MPEG；若结尾影像无法播放，请安装 LAV Filters 或提供 ffmpeg 后重跑。'
    }
  } else {
    Write-Host '  [注意] 日文版中未找到 ED6_DT51.dat，跳过结尾 STAFF 表。'
  }
}

# ---------- 日文菜单开关 + 渲染设置 ----------
New-Item -ItemType File -Force "$GameDir\dll\lang_jpn.dll" | Out-Null
Ok 'dll\lang_jpn.dll（日文菜单开关）'
if (Test-Path $ini) {
  $c = Get-Content $ini
  if (-not $KeepHdFont) {
    $c = $c -replace '^HighResoText=\d', 'HighResoText=0'
    Ok 'ed6_win3.ini: HighResoText=0（经典字体渲染，修复名称/正文漂移）'
  }
  if (-not $NoTextures) {
    $c = $c -replace '^HighResoAssets=\d', 'HighResoAssets=0'
    Ok 'ed6_win3.ini: HighResoAssets=0（使用日版标准素材，标题/卡片全部日文）'
  }
  $c | Set-Content $ini -Encoding ASCII
}

if ($tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host "`n完成。启动游戏即为日文原版体验（详见 README）。"
Write-Host "说明：START/EASY 等按钮与 Now Loading 在日版原版中即为英文，属正常现象。"
Write-Host "如需还原英文版：执行 还原.bat 或本脚本加 -Restore"
