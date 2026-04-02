# Benchmark Analyzer — 对标账号全自动拆解

> 输入一个 Excel，输出一套完整的对标账号分析资料库。

![](https://img.shields.io/badge/Claude%20Code-Skill-blue)
![](https://img.shields.io/badge/python-3.9+-green)

## 它能做什么

一键完成从 **数据 → 音频 → 语料 → 报告** 的全流程：

1. **读取 Excel**（社媒助手导出的达人视频数据）
2. **生成「爆款内容体检报告」** — 含数据概览、点赞/收藏/评论/分享/综合互动排行榜、主题分布、时长分析、发布时间分析等 13 个维度
3. **下载 Top10 音频**
4. **本地 Whisper 转写** — 默认使用 `ggml-medium` 模型，适配 3-5 分钟中长口播
5. **OpenCC 繁简转换 + 基础错别字修正**
6. **AI 二次精修**（由 Claude 静默完成）
7. **生成「文案分析报告」** — 含钩子、标题公式、内容结构、情绪触发器、金句、复用框架、AI 复刻指南

---

## 安装环境（一次性）

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 whisper-cpp

```bash
# macOS (Homebrew)
brew install whisper-cpp

# 其他平台请参考：https://github.com/ggerganov/whisper.cpp
```

### 3. 下载语音模型

**推荐 `medium` 模型**（性价比最高，5 分钟口播质量足够好）：

```bash
mkdir -p ~/whisper-models
curl -L -o ~/whisper-models/ggml-medium.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin
```

> 如果下载速度慢，可替换为国内镜像：
> ```bash
> curl -L -o ~/whisper-models/ggml-medium.bin \
>   https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin
> ```

**可选：如果磁盘空间有限，可用 `small` 模型回退**（质量中等，466MB）：

```bash
curl -L -o ~/whisper-models/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

> 脚本会自动检测模型路径，优先使用 `medium`，找不到时回退 `tiny`。

### 4.  Claude Code 安装 Skill

将你的 Skill 目录放入 Claude Code 的 skills 目录：

```bash
# 确认 Claude Code 的 skills 目录位置
ls ~/.claude/skills/

# 创建软链接（推荐，便于后续更新）
ln -s "$(pwd)" ~/.claude/skills/benchmark-analyzer
```

或者直接将整个文件夹复制进去：

```bash
cp -r benchmark-analyzer ~/.claude/skills/
```

> 安装后，重启 Claude Code 或在对话中输入 `/skills` 刷新技能列表。

---

## 使用方式

### 方式一：直接对话（最方便）

复制下面这段 prompt，直接发给 Claude Code：

```markdown
benchmark-analyzer

帮我拆解这个博主：/path/to/你的Excel文件.xlsx
```

> 把 `/path/to/你的Excel文件.xlsx` 替换成你本地 Excel 的真实路径即可。

### 方式二：手动执行脚本

如果你只想跑前半程（Excel → 报告 + 音频 + 语料），不需要 Claude 生成文案分析：

```bash
python3 scripts/benchmark_analyzer.py /path/to/你的Excel文件.xlsx
```

---

## 输出结构

每个博主会生成一个独立文件夹，结构如下：

```
对标账号案例库/
└── 博主名/
    ├── 原始数据/
    │   └── 【社媒助手】达人「博主名」的视频数据-xxx.xlsx
    ├── 爆款内容体检报告_博主名.md    ← 数据层面的体检报告
    ├── 文案分析报告.md                ← 语料层面的深度拆解
    ├── 音频/
    │   ├── 01_xxx.mp3
    │   ├── 02_xxx.mp3
    │   └── ...
    └── 语料/
        ├── 01_xxx.md
        ├── 02_xxx.md
        └── ...
```

---

## 可分享的 Prompt

你可以直接把下面这段发给任何已安装该 Skill 的 Claude Code 用户，对方复制粘贴即可使用：

```markdown
benchmark-analyzer

帮我拆解这个博主：/path/to/你的Excel文件.xlsx

要求：
1. 读取上面的 Excel，生成功能完整的「爆款内容体检报告」
2. 下载 Top10 音频，并用本地 medium 模型转写为纯净语料
3. 语料需要简体中文，并自动修正 whisper 转写错误（不需要告诉我你改了哪些字）
4. 基于修正后的语料，生成包含 10 个章节的「文案分析报告」
5. 如果我在做 content-os 公众号项目，请在报告中追加「下游使用建议」，说明这些产出如何用于 topic-miner / content-researcher / auto-pilot
6. 最终输出完整的对标账号分析文件夹
```

---

## 和 content-os 其他 skills 的协同

`benchmark-analyzer` 不是一个孤立的工具，它是 content-os 内容生产链路的前置环节。它的产出可以直接服务下游 skills：

### → topic-miner（选题矿工）
- **输入**：`爆款内容体检报告` 中的「高频主题分布」+「爆款高频词」
- **作用**：基于对标账号已经验证过的爆款方向，批量衍生新选题

### → content-researcher（素材搜集）
- **输入**：`文案分析报告` 中的「标题公式」+「情绪触发器」+「金句提取」
- **作用**：按对标账号的高互动主题定向搜索素材、案例、数据

### → auto-pilot（全自动撰稿）
- **输入**：`语料/` 文件夹（逐字稿）+ `文案分析报告.md`
- **作用**：把对标账号的爆款公式、语气、结构喂给 auto-pilot，直接生成同风格文章

### 推荐 workflow

```
Step 1: benchmark-analyzer  →  产出报告 + 语料库
Step 2: topic-miner         →  基于爆款主题找新选题
Step 3: content-researcher  →  为新选题搜素材
Step 4: auto-pilot          →  用对标语料+素材生成文章
```

---

## 配置说明

如需修改默认路径，编辑 `scripts/benchmark_analyzer.py` 顶部的配置区：

```python
# 输出目录（默认）
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Documents/项目/文案提取/对标账号案例库")

# whisper-cli 路径
WHISPER_CLI = "/opt/homebrew/Cellar/whisper-cpp/1.8.3/bin/whisper-cli"

# 模型路径
MODEL_PATH = os.path.expanduser("~/whisper-models/ggml-medium.bin")
```

---

## 适用场景

- 收集对标账号，建立个人/团队案例库
- 拆解爆款规律，提炼可复用的内容模板
- 为 AI 复刻账号人设积累语料和指标
- 快速了解一个新赛道的头部内容策略

---

## 作者

[@兰独立](https://github.com/你的github用户名)
