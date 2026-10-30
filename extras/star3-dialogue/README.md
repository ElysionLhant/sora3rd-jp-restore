# 星门 3 对话触发与 64 KiB 扩展修复

修复《空之轨迹 the 3rd》星门 3 中 **NPC 对话无法触发** 的问题。该问题已在实际游戏中确认修复。

本目录只包含补丁生成器、离线验证工具和文档，**不包含任何游戏 EXE、剧本、语音或其他游戏数据**。请使用自己合法持有的文件。

## 修复内容

完整语音版 `T4206` 超过 64 KiB 后，原引擎的 16 位函数表、字符串表和 VM 指令位置会截断，导致里夏尔等 NPC 的 Talk 分派无法正确启动。本修复包括：

- 接通 `DeclNpc → 角色 Talk 字段 → 0x53A140` 的函数入口解析，避免脚本基址重复相加。
- 使用完整函数入口和返回页处理 `Call`、`Return`、普通分派及跨场景调用。
- 按当前函数的完整范围恢复执行位置，覆盖函数 79 跨越 `0xFFFF` 的顺序执行与 `0xFFD3 → 0x10081` 跳转。
- 修正状态指针的绝对地址读取、扩展尾部注册字段及字符串表偏移。
- 保留完整剧本的 88 个函数和 730 个语音标签，不通过删减剧情或语音规避大小限制。

## 已知限制

部分 NPC 语音仍然缺失。本修复针对对话无法触发的问题，不承诺 730 个语音标签全部能在实际游戏中播放。

## 自备材料

- 原始 `ed6_win3_DX9.exe`，SHA-256：`6939b938b71b280ad9115e30ace16f97923a5c232414ce71f75f7f326ab9c75a`。
- 完整语音版 `T4206   ._SN`：67,506 字节、88 个函数、730 个语音标签，放到游戏目录的 `.analysis/full-allvoices/T4206   ._SN`。
- Python 3 与 Capstone。

不要以已经修改过的 EXE 作为生成输入。

## 生成与离线验证

关闭游戏并备份原文件，然后在游戏根目录运行：

```bash
python extras/star3-dialogue/build_snx_patch.py /path/to/original/ed6_win3_DX9.exe
python extras/star3-dialogue/verify_snx_machine.py
```

生成结果仅写入 `.analysis/snx-lift/`，不会自动替换游戏文件。验证器直接解释生成的机器码，覆盖：

- 8 个静态场景槽、扩展脚本注册、大小检查和字符串表；
- 88/88 函数初始分派；
- 低页与高页 `Call`、`prepare`、普通及跨界分派、`Return` 返回页；
- 管理器脚本基址恢复。

在上述确定输入下，预期输出 SHA-256：

```text
ed6_win3_DX9.exe  7642c0b6cca9e54dcdb51edb4a5ba332fbd54dfdb78d847e4c2728267dbda714
T4206   ._SN      6ba988c302dbe9188e3fc1dabcddb2ca7f66857f514acc7d67973bdfd14ac714
```

确认备份后再自行部署，并在实际游戏中检查对话文字、语音、后续剧情和退出。离线验证不能替代实机验收。

## 文件

```text
build_snx_patch.py     EXE 与扩展剧本生成器
x86asm.py              小型 x86 汇编器
re_sn_limit.py         PE 读取与反汇编辅助
verify_snx_machine.py  生成机器码的离线执行验证
```
