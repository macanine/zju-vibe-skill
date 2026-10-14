---
name: zju-vibe
description: 用仓库内置的 zju-vibe 命令行工具（./zju-vibe）批量抓取浙大课程资料——学在浙大课件与作业附件、智云课堂 PPT（自动合成 PDF）、智云课堂字幕（转 SRT），并支持列出课程与统一身份认证登录。当用户要下载/抓取/导出浙大课件、课件列表、智云 PPT、字幕或 SRT，或提到学在浙大、智云课堂、courses.zju.edu.cn、classroom.zju.edu.cn、zju-vibe，或要查看/操作该命令行工具时使用。
---

# 浙大课件下载

驱动 `./zju-vibe`（纯 Python3 命令行工具）完成课件抓取。**不要**自己写 requests 脚本直接调浙大接口——该工具已封装登录、重试、增量跳过与 PDF 合成。

## 0. 准备环境（每次会话首次使用前）

`zju-vibe` 与本 `SKILL.md` 同级，都在**本 skill 目录**下。先定位该目录（harness 会给出 base directory），
把工作目录切到它，再执行命令；入口脚本自带 `.venv` 解释器。

```bash
# <skill-dir> 即 SKILL.md 所在目录, 替换成实际路径
cd <skill-dir>
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
./zju-vibe --version        # 0.1.0
```

参数不确定时先看帮助，不要猜 flag：

```bash
./zju-vibe --help
./zju-vibe learn --help
```

## 1. 登录门禁（未登录时你直接代为登录）

`courses` / `learn` / `classroom` / `subtitle` 都要求本地已有会话。未登录时命令**退出码 2**，stderr 打印「尚未登录, 请先运行 …」，且不做任何网络请求。

**遇到退出码 2 就走这套流程，不要把命令甩回给用户：**

1. 问用户要**学号和密码**（一句话问清即可，例如「需要你的浙大学号和统一身份认证密码才能登录」）。
2. 用户给出后执行：

   ```bash
   ./zju-vibe login -u <学号> -p '<密码>'      # 密码用单引号包住, 防特殊字符与 shell 展开
   ```

3. 看到「登录成功: <学号>」即完成；随后自动重新执行原本的命令，**不要**因为登录这一步就把任务停下。
4. 登录失败（`用户名或密码错误` / `无法打开统一身份认证页面`）→ 把错误原文告诉用户并停止，密码错误时请用户核对后再来一次，不要连续重试。

密码只在登录这一次用到：会话 cookies 存 `~/.zju-vibe/session.pkl`，之后所有命令都不再需要密码，直到会话过期。

其他要点：

- **不要**把密码写进脚本、配置文件、`.env` 或提交记录，也不要 echo 到日志里；只在 `-p` 参数里用一次。
- `-p` 会留在 shell 历史和进程列表里，所以**优先只登一次**，之后复用会话；用户想清理就执行 `./zju-vibe logout`。
- 若用户不想把密码交给你，可以请他自己跑一次 `./zju-vibe login -u <学号>`（交互式输入）。该命令会尝试把密码写进系统 keyring，装了 `keyring` 的话下次连这一步都能省掉——但这属于可选项，不是必须。
- 智云 `_token` 缺失时 CLI 会自动重走预热链补齐，一般不需要重新登录。

## 2. 通用工作纪律

| 规则 | 说明 |
|---|---|
| **先 `--list-only` 再真下** | `learn` / `classroom` 都支持。绝大多数下载请求先跑一次 dry-run，把「共 N 个文件 / 合计 X MB」「共 N 节课 / X 页」回报给用户，再执行下载。 |
| **不要盲跑 `--all`** | `learn --all` 会扫全部课程（含历史学期），可能几十 GB。先 `--all --list-only` 看规模，或用 `--year` / `--semester` / `--course` 缩小。 |
| **退出码 0 ≠ 全部成功** | `1` = 全部失败或抓取出错；`2` = 未登录/未选中课程。部分失败时退出码仍是 `0`，必须读 stderr 的 `FAIL` 行再汇总给用户。 |
| **下载是长任务** | 几十个文件 / 上百页 PPT 可能跑几分钟到几十分钟。用后台执行或设足够长的超时（≥ 600s），不要中途打断。 |
| **中断可自愈** | 文件流式直写目标路径，中断会留半截文件；重跑时因大小不符会自动重下，不必手动删。 |
| **默认增量跳过** | 已存在且大小一致的文件直接跳过；`--no-skip` 强制重下。 |
| **输出目录** | `--out` 缺省读 `~/.zju-vibe/config.json` 的 `save_dir`，无配置则 `~/Downloads/zju-vibe`。用户没指定就别擅自换目录。 |
| **并发** | `--workers` 默认：`learn` 4、`classroom` 8、`subtitle` 批量 4。网络不稳时降到 2。 |
| **不要回放视频** | 出于版权考虑 CLI 不支持智云回放下载，用户提出时直接说明不支持。 |

## 3. 意图路由

| 用户想要 | 命令 | 细节 |
|---|---|---|
| 我有哪些课 / 查课程 ID | `courses` | [references/learn.md](references/learn.md) |
| 下载学在浙大课件、作业附件 | `learn` | [references/learn.md](references/learn.md) |
| 智云 PPT / 课件截图 / 转 PDF | `classroom` | [references/classroom.md](references/classroom.md) |
| 智云字幕 / SRT / 转写文本 | `subtitle` | [references/subtitle.md](references/subtitle.md) |
| 登录 / 退出 | `login` / `logout` | 本文第 1 节 |

### ID 解析链（关键，别跳步）

- **学在浙大**：`./zju-vibe courses --json` → 取 `id` → `./zju-vibe learn --course <id> [--course <id> …]`
- **智云整课**：`./zju-vibe classroom --search-title 高等数学 --search-teacher 张三` → 打印 `course_id=…` → `./zju-vibe classroom --course-id <id>`
- **智云单节字幕**：`./zju-vibe classroom --list-only`（输出含 `sub=1979437`）→ `./zju-vibe subtitle 1979437`

### 输出目录结构

```
<out>/<课程名>/<服务端文件名>                    # learn
<out>/<课程名>/<小节名>/<课程>-<小节>.pdf      # classroom（同级还有 ppt_images/1.jpg…）
<out>/<课程名>/<小节名>.<lang>.srt              # subtitle 批量（小节名自带日期，如 2026-10-13第9-9节）
```

## 4. 常见故障

| 现象 | 处理 |
|---|---|
| 退出码 2 / 「尚未登录」 | 走第 1 节登录。 |
| 「智云 token 缺失」且自动补预热后仍失败 | 报错给用户，建议 `./zju-vibe logout` 后重新 `login`。 |
| `FAIL … HTTP 403` / 「下载失败」 | 学在浙大已停止开放或文件已删除；如配了 `--no-preview` 可去掉重试以启用 Preview 兜底。 |
| 文件名与列表显示不同 | 正常：下载文件名以服务端 `name=` 为准，可能与列表显示的不同。 |
| 「未找到学期 '…'」 | `courses --year/--semester` 的值是子串匹配，先跑 `courses` 看真实学年/学期名。 |
| 字幕显示「暂无语音」 | 该小节未开课或未录制（接口 `code=10002`），不算失败，跳过即可。 |
| `Errno 24 Too many open files` | 极高页数 PPT 拼 PDF；CLI 已逐张 load 关闭，若仍触发请减小范围分批下载。 |

## 5. 汇报模板

下载结束后给用户：成功 / 跳过 / 失败 计数、失败清单（含文件名与错误）、实际落盘目录与体积；智云任务额外给出 PDF 路径。批量字幕额外区分「无字幕 / 暂无语音」数量。