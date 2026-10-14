<div align="center">
  <h1>zju-vibe-skill</h1>
  <p><b>让 AI 直接帮你批量抓取浙大课程资料</b></p>
  <p><sub>学在浙大课件 · 智云课堂 PPT → PDF · 智云课堂字幕 → SRT</sub></p>
</div>

<br>

一个 **Agent Skill + 纯 Python3 命令行工具**。装上之后，你跟 AI 说「把微积分的课件下下来」，它自己列课程、自己登录、自己下载、自己拼 PDF。

| 能力 | 说明 |
|---|---|
| **学在浙大课件** | 批量下载课程 activities 与作业附件。`reference/blob` 优先，失败自动兜底 `uploads/{id}/blob`（老师未开放下载的 Preview 版）。支持增量跳过、并发下载、扩展名排除。 |
| **智云课堂 PPT** | 按日期区间 / 按月 / 整课 / 全库搜索拉取小节，多线程下载幻灯片并拼成 PDF（每图一页、页面尺寸=图片尺寸）。 |
| **智云课堂字幕** | 按小节或整课批量拉取转写文本，导出 SRT（中文 / 英文 / 中英双语）。 |

技能本体只是**编排层**：负责登录门禁、`--list-only` 预演、课程 ID 解析、并发与输出目录决策、失败汇总。
真正的抓取逻辑全在 `./zju-vibe` 里，登录、重试、增量跳过、PDF 合成都已封装。

无 Node / 浏览器 / 系统 WebView 依赖，第三方依赖只有 `requests` `Pillow` `tqdm`。

---

## 安装

### 方式一：复制给 AI（推荐）

把下面这段话直接发给你的 AI（OpenCode / Claude Code / Cursor 等支持 Agent Skill 的都行）：

```text
帮我安装「浙大课件下载」这个 agent skill：

1. 把仓库克隆到我的 skills 目录下，目录名用 zju-vibe：
   git clone --depth 1 https://github.com/macanine/zju-vibe-skill.git <skills-dir>/zju-vibe
   <skills-dir> 按你的 harness 选：OpenCode 用 ~/.config/opencode/skills，Claude Code 用 ~/.claude/skills。
   如果 <skills-dir>/zju-vibe 已存在，改用：git -C <skills-dir>/zju-vibe pull --ff-only

2. 确认 <skills-dir>/zju-vibe/SKILL.md 存在，且 frontmatter 里的 name 是 zju-vibe。

3. 告诉我怎么验证装好了，并说明首次使用还需要做什么（首次要登录浙大统一身份认证，可以直接让我代为登录）。
```

### 方式二：自己动手

```bash
# OpenCode
git clone --depth 1 https://github.com/macanine/zju-vibe-skill.git ~/.config/opencode/skills/zju-vibe
# Claude Code
git clone --depth 1 https://github.com/macanine/zju-vibe-skill.git ~/.claude/skills/zju-vibe
```

### 方式三：开发时用软链（改代码即时生效）

```bash
ln -s /path/to/zju-vibe-skill ~/.config/opencode/skills/zju-vibe
```

### 验证

安装后**重启 agent 会话**，然后任选一句：

```text
@zju-vibe 帮我看下我这学期的浙大课程
帮我把「微积分（甲）Ⅰ」的课件下下来
把「探索人类语言的奥秘」这周的智云 PPT 导成 PDF
```

未安装成功时，AI 会看不到这个技能；如果它照着文档去写 `requests` 脚本调浙大接口，说明没加载上。

### 首次使用要登录

工具需要你的浙大统一身份认证。**AI 会直接代你登录**——它遇到未登录（退出码 2）时会主动问你要学号和密码，
然后执行 `./zju-vibe login -u <学号> -p '<密码>'`，登录成功后自动继续原本的任务，不用你手动敲命令。

所以首次只要一句话：

```text
帮我下载「微积分（甲）Ⅰ」的课件        # AI 会问你要学号和密码
```

密码只在登录这一次用到：会话 cookies 存 `~/.zju-vibe/session.pkl`，之后所有命令都不再需要密码，
直到会话过期。AI 不会把密码写进脚本、配置或提交记录，任务结束你可以让它执行 `./zju-vibe logout` 清理。

**不想把密码给 AI 的话**，自己跑一次交互式登录即可，之后 AI 也不再需要密码：

```bash
cd ~/.config/opencode/skills/zju-vibe
./zju-vibe login -u <学号>      # 密码交互输入
```

装了 `keyring` 的话这次输入会被存进系统密钥环，AI 下次登录也能免密；没装则下次仍需重输。

---

## 目录结构

```text
zju-vibe-skill/
├── SKILL.md            # 技能入口: 登录门禁 / 通用纪律 / 意图路由 / 故障速查
├── references/
│   ├── learn.md        # 学在浙大: courses / learn 全参数与排错
│   ├── classroom.md    # 智云课堂: PPT 取课四种方式、PDF 布局、排错
│   └── subtitle.md     # 字幕: 单节 vs 整课、状态分类、SRT 格式细节
├── zju-vibe            # 命令行入口（自带 .venv 解释器）
├── zju_vibe/           # Python 包
│   ├── auth.py         # 统一身份认证 + RSA 无填充加密
│   ├── client.py       # 学在浙大 / 智云 API 封装（带重试）
│   ├── download.py     # 流式下载 / 增量跳过 / 图片转 PDF / SRT
│   ├── store.py        # 本地会话与配置
│   └── cli.py          # 子命令与参数
├── requirements.txt
└── LICENSE
```

`SKILL.md` 与 `zju-vibe` 同级，所以无论把仓库放在哪，技能都能找到自己的命令行工具。

---

## 手动使用 CLI

技能之外也能直接当命令行工具用。命令都在本仓库根目录（或安装目录）执行：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 登录
./zju-vibe login -u <学号>

# 查看课程（可按学年/学期过滤）
./zju-vibe courses
./zju-vibe courses --year 2024-2025 --semester 秋冬
./zju-vibe courses --json

# 学在浙大：先 --list-only 确认，再去掉下载
./zju-vibe learn --all --list-only
./zju-vibe learn --course 12345 --course 67890 --out ~/Downloads/zju-vibe
./zju-vibe learn --year 2024-2025 --semester 秋冬 --ext-exclude mp4,zip --workers 4

# 智云课堂（默认本周；先 --list-only 确认）
./zju-vibe classroom --list-only
./zju-vibe classroom --start 2024-09-01 --end 2024-09-07
./zju-vibe classroom --month 2024-09 --no-pdf
./zju-vibe classroom --search-title 高等数学 --search-teacher 张三
./zju-vibe classroom --course-id 123456 --out ~/Downloads/zju-vibe

# 字幕：单节预览 / 导出，或整课批量
./zju-vibe subtitle 1979437 --preview-only
./zju-vibe subtitle 1979437 --lang mixed --out /tmp/sub.srt
./zju-vibe subtitle --course-id 85937 --lang zh --out ~/Downloads/zju-vibe

# 退出（清除本地会话）
./zju-vibe logout
```

完整参数见 `./zju-vibe <子命令> --help`。

<details>
<summary>输出目录布局</summary>

```text
<out>/<课程名>/<服务端文件名>                    # learn
<out>/<课程名>/<小节名>/<课程>-<小节>.pdf      # classroom（同级还有 ppt_images/）
<out>/<课程名>/<小节名>.<lang>.srt              # 字幕批量（小节名自带日期，如 2026-10-13第9-9节）
```

`<out>` 缺省为 `~/Downloads/zju-vibe`，可在 `~/.zju-vibe/config.json` 写 `{"save_dir": "…"}` 改。
</details>

---

---

## 行为说明

- 登录流程：取 `execution` → 取 RSA 公钥 → `rsa_no_padding` 加密（无填充 `pow(m,e,n)` 十六进制）→ POST 登录 → 预热 courses/classroom。
- 学在浙大文件名以服务端 `name=` 为准，可能与列表显示的名字不同，这是正常行为。
- 默认增量跳过已存在且大小一致的文件；`--no-skip` 强制重下。中断留下的半截文件会因大小不符自动重下。
- `learn` 默认包含作业附件，`--no-homework` 可关闭。
- 智云 `_token` 缺失时会自动重走 OAuth 预热链补齐，一般不需要重新登录。
- 退出码：`0` 成功（**部分失败时也是 0，务必看 stderr 的 `FAIL` 行**）、`1` 全部失败、`2` 未登录或未选中课程。

## 我的信息是否安全？

本工具实质上是一个爬虫，模拟登录学在浙大、获取课件列表、下载课件，因此需要你的学号、密码才能正常运行。

**本工具不会把学号、密码上传到任何服务器。** 本地只保存账号 cookies（`~/.zju-vibe/session.pkl`），密码仅尝试写入操作系统自带的
密钥管理服务（可选依赖 `keyring`），不存明文密码。使用过程中只会访问：

- `zju.edu.cn`：登录学在浙大、获取课件列表、下载课件

## 免责

仅模拟正常浏览器操作，请遵守校规、尊重课件版权。出于版权考虑，不支持智云回放视频下载。

## License

MIT，见 [LICENSE](LICENSE)。