# 智云课堂：字幕转 SRT

字幕来自 `yjapi.cmc.zju.edu.cn/.../search-trans-result` 的 `all_content`（含 `BeginSec` / `EndSec` / `Text` / `TransText`），带登录 cookies 即可，不需要 Bearer token。

## 两种模式

`sub_id`（位置参数）与 `--course-id` 二选一，**`--course-id` 优先**。

### 单节

```bash
./zju-vibe subtitle 1979437 --preview-only          # 只看前 5 条, 不落盘
./zju-vibe subtitle 1979437 --preview 20            # 多看几条
./zju-vibe subtitle 1979437 --lang zh --out /tmp/sub.srt
```

`--out` 语义：**以 `.srt` 结尾视为文件路径，否则视为目录**，自动拼成 `<目录>/sub_<sub_id>.<lang>.srt`。省略时用默认下载目录。

单节模式也会打印前 `--preview`（默认 5）条内容到 stdout。

### 整课批量

```bash
./zju-vibe subtitle --course-id 85937 --lang zh --out ~/Downloads/zju-vibe
./zju-vibe subtitle --course-id 85937 --lang mixed --workers 8 --no-skip
```

`--out` 在批量模式**始终是目录**。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--lang` | `zh` | `zh` 中文 / `en` 英文(TransText) / `mixed` 中英双语（中文在上、英文在下） |
| `--out` | `~/Downloads/zju-vibe` | 单节：srt 路径或目录；批量：目录 |
| `--preview` | 5 | 单节预览条数 |
| `--preview-only` | 关 | 单节只预览不保存 |
| `--no-skip` | 关 | 批量：不跳过已存在文件 |
| `--workers` | 4 | 批量并发数 |

两个都不给会报「请指定 sub_id 或 --course-id」，退出码 2。

## 输出布局与命名

```
<out>/<课程名>/<小节名>.<lang>.srt      # 批量, 如 2026-10-13第9-9节.zh.srt
```

小节名本身带日期，**按文件名排序即按时间顺序**——用户要「按时间顺序整理字幕」时直接依赖这一点，不要再解析内容。

## 状态分类（批量模式的关键）

批量结束会打印 `完成: 成功 N, 跳过 N, 无字幕 N, 失败 N`，其中**「无字幕」包含两种不同情况**，stdout 行可区分：

| 输出行 | 含义 | 是否失败 |
|---|---|---|
| `OK [<小节>] (<sub_id>) -> <路径>` | 已保存 | — |
| `SKIP [<小节>] 已存在` | 增量跳过 | — |
| `EMPTY [<小节>] (<sub_id>) 无字幕` | 接口返回空列表 | 否 |
| `-- [<小节>] 暂无语音 (未开课或未录制)` | `code=10002`，未开课/未录制 | 否 |
| `FAIL [<小节>] (<sub_id>): <原因>` | 网络或接口错误 | 是 |

汇报时必须把「无字幕/暂无语音」和「失败」分开统计，不要笼统说成下载失败。

## SRT 格式细节

- 序号为原始 `enumerate` 计数，**空文本条目被跳过但序号保留**，所以可能出现序号不连续——这是刻意保留的行为，不要"修正"。
- 时间戳毫秒位固定 `,000`（接口只给整秒）。
- 默认增量跳过「已存在且非空」的 srt；要重新生成加 `--no-skip`。

## 常见问题

| 现象 | 处理 |
|---|---|
| 大量 `暂无语音` | 选了小节里没开课/没录制的部分（如未来学期）。用 `--course-id` 前先确认课程，或看 `classroom --list-only` 的页数。 |
| `FAIL … 获取字幕失败 (code=…)` | 非 10002 的业务错误，多为会话过期。重新 `login` 后重试。 |
| 想要带时间轴的文本摘要 | 先导出 SRT，再自行读取处理；不要直接手写 requests 调字幕接口。 |