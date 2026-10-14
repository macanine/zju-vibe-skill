# 学在浙大：课程列表与课件下载

## courses —— 列出课程

```bash
./zju-vibe courses                              # 全部课程
./zju-vibe courses --year 2024-2025             # 学年子串匹配
./zju-vibe courses --semester 秋冬              # 学期子串匹配
./zju-vibe courses --json                       # 机器可读, 用于解析 ID
```

输出行格式：`  [<id>] <课程名> (学年<academic_year_id> 学期<semester_id>)`。

- `--year` / `--semester` 都是**子串**匹配真实学年/学期名。找不到时会列出可用值，agent 应据此纠正用户说法。
- 部分课程接口不返回 `academic_year_id` / `semester_id`（显示 `None`），此时按名字或 ID 指定即可，不要因为筛选不出结果就断定课程不存在。

## learn —— 课件批量下载

```bash
./zju-vibe learn --course 12345 --course 67890   # 指定课程 ID, 可重复
./zju-vibe learn --all                            # 全部课程 (先 --list-only!)
./zju-vibe learn --year 2024-2025 --semester 秋冬 # 按学期筛选
./zju-vibe learn --course 12345 --list-only       # 只列清单不下载
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--out` | `~/Downloads/zju-vibe` | 下载根目录 |
| `--list-only` | 关 | 打印清单后退出，不下载 |
| `--no-homework` | 关 | 不含作业附件（默认**含**作业） |
| `--no-skip` | 关 | 不跳过已存在且大小一致的文件 |
| `--no-preview` | 关 | 禁用 Preview 兜底，只下开放下载的文件 |
| `--ext-exclude` | 无 | 排除扩展名，逗号分隔，如 `mp4,zip` |
| `--workers` | 4 | 并发下载数 |

三选一决定范围：`--course`（优先）/ `--all` / `--year`+`--semester`。都没给会按学年学期筛选，为空则退出码 2。
`--course` 传了不在列表里的 ID 只告警不中止（stderr `警告: 以下课程 ID 不在你的课程列表中`）。

## 标准任务序列

```bash
# 1. 拿到 ID
./zju-vibe courses --json

# 2. 预演：确认文件数与体积, 把结果回报给用户
./zju-vibe learn --course 99852 --course 100085 --list-only

# 3. 用户确认后下载
./zju-vibe learn --course 99852 --course 100085 --out ~/Downloads/zju-vibe
```

## 输出与文件布局

```
<out>/<课程名>/<服务端文件名>
```

- 一个课程一个子目录，文件名**以服务端 `name=` 参数为准**，可能和 `courses`/清单里显示的名字不同——这是正常行为，不要当成 bug。
- 课程名中的 `/` 会被替换为 `-`，智云侧则替换为 `_`。

## 数据来源与去重

- 课程 activities 的 uploads + 作业（`homework-activities`）的 uploads，按 `(id, reference_id)` 去重。
- 作业接口失败只静默跳过该课程（`ApiError` 被吞），不会中断整体。

## 常见问题

| 现象 | 处理 |
|---|---|
| `FAIL xxx.pdf: 下载失败` | 多为文件已撤下或未开放。去掉 `--no-preview` 让 Preview 兜底生效再试一次；仍失败则如实报告该文件不可下。 |
| 文件已存在却重下 | 大小与元数据不一致（上次中断）。重跑即可自愈，或 `--no-skip` 强制覆盖。 |
| 列表巨大（`--all` 几十 GB） | 立刻停下，用 `--year` / `--semester` / `--course` 缩小范围，先与用户确认体积。 |
| HTTP 403 批量出现 | 会话过期或触发限流。重新 `login`；仍不行则降低 `--workers` 到 2 并分批跑。 |