# extras/voice — 剧情语音（Evolution 语音）注入管线

给"Steam 英文版引擎 + 日版内容"的成品补上 **Evo 版剧情语音**。本目录是开发管线文档与核心工具，**不是一键补丁**——需要若干自备材料与手工步骤。

## 原理

PC 版 3rd（日英皆然）本身没有剧情语音；语音是 Evo/PSV 版独占。中文社区 **J31why** 的《3rd Steam 版语音整合包》把 Evo 语音移植到了 Steam 英文版，但它的剧本是英文/中文文本——直接安装会覆盖日文剧本。

解决方案：**只取语音 ID，灌进日版剧本**。

1. J31why 语音剧本的文本里嵌有 `#77284v` 这样的语音指令（`#<id>v` 前缀，挂在每句对白开头）。
2. 其 `voice/ed_voice.dll`（SoraVoice Lite 改）内嵌一张 101070 行的 ID 表：`表[id] → Evo 语音文件名`（如 `77284 → 0010610649 → voice/ogg/ch0010610649.ogg`）。游戏显示文本时，dll 解析该前缀、播放对应 ogg、并把前缀从画面中剥掉。
3. 日版与英文/中文版剧本的**代码结构完全一致**（同一份剧本字节码，仅文本不同），因此可以按结构对齐：把 J31why 剧本里每句对白的语音 ID，搬到同位置日版对白的开头，重新编译装回。

对齐器 `voice_merge.py` 的做法：

- 把反编译剧本（EDDecompiler 输出的 `.py`）按行解析为 代码 / 字符串组 记号流，用 difflib 对齐英中版与日版（函数名/lambda 名按偏移命名，先归一化）。
- 字符串组再按消息分段（`\x02`/`\x03` 为消息边界；无转义码的独立串是说话人名）。
- 语音指令的位置按 **表情码（`#xxxF`）** 一一对应验证；无表情码的旁白句靠分段序号对齐；分段数不一致时用**全角/半角字母数字 token 单调锚定**（如 `コードＢ３` 的 `Ｂ３`），拒绝一切表情码冲突的可疑对齐（宁可缺，不可错）。
- 英版特有的大文件拆分（`E1000→E1000+E1000_1`、`U7002` 系列拆分点不同）按"家族"全组合对齐，按配对质量（表情码一致数 + 双无码对齐数）择优。
- 最终 24172 / 25045 条语音指令成功注入（96.5%），其中约 75% 有表情码验证；未注入的 800 余条全部记录于报告（多为 Evo 未录制或结构不可对齐的内容——即使在 J31why 原包中这些句子同样无声）。

## 材料（全部自备）

- 本仓库主补丁产出的日版化游戏（`ED6_DT21` 已是日版剧本）
- J31why《3rd Steam 正版补丁1》（Evo 语音 ogg，约 2.5 万个文件）与《补丁2》（`voice/ed_voice.dll`、`dinput8.dll`、语音剧本 `.sn`）
- [SoraVoiceScripts](https://github.com/ZhenjianYang/SoraVoiceScripts) 工具链（反编译/重编译剧本；需按其 README 初始化子模块，并给 `tools/PyLibs/ml.py` 顶部加 `collections.abc` 兼容 shim 以支持 Python 3.10+）
- Python 3（依赖 `xmltodict aiohttp rsa hexdump`）

## 步骤概要

1. 解包补丁2，用 SoraVoiceScripts 的 `ED63RDScenarioScript.py`（`--cp=ms932`）分别反编译 J31why 语音剧本（→ `j31_sn/`）与日版 DT21 剧本（→ `jp_sn_raw/`）。
2. 运行 `python voice_merge.py`：输出 `merged_sn/*.py`（日版文本 + 语音指令）与 `voice_merge_report.txt`（逐条注入/丢弃记录）。
3. 用同一工具链重编译 merged 剧本 → `._SN`，按主补丁的 ed6 纯字面量格式重打包，写回游戏 `ED6_DT21`（条目名去掉 `._SN` 后缀）。
4. 安装运行库：补丁2 的 `dinput8.dll` 放游戏根目录（它是代理加载器，顺带加载 `voice/ed_voice.dll`，不依赖汉化系统）；`voice/ed_voice.dll` 与 `voice/dll/{ogg,vorbis,vorbisfile}.dll` 放游戏 `voice/`；补丁1 的 `voice/ogg/*.ogg` 解到游戏 `voice/ogg/`。
5. 启动游戏：标题栏出现 `- SoraVoice (Lite)` 即加载成功。

注意：**不要**安装补丁2 的 `rdata/`、`rdata.exe`、`rdata.json`（那是中文运行时翻译系统，会覆盖日文文本），也不要装它的 `data/ED6_DT2*`（中文剧本）。

## 与主补丁的关系

- 主补丁 `一键转换.bat` 不覆盖语音；但它会重写 `ED6_DT21`——**重跑一键转换后需重跑本管线**才能恢复语音。
- `还原.bat` 恢复英文档案后不卸载 `dinput8.dll`；英文剧本里没有语音指令，SoraVoice 保持空转，无副作用，可留可删。
- 语音 ogg 与 ed_voice.dll 的版权/许可归各自作者（Falcom / ZhenjianYang 与 J31why 整合），请自行获取，不要二次分发。
