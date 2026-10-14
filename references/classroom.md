# 智云课堂：PPT 下载并转 PDF

## 四种取课方式（互斥，按优先级从上到下）

| 需求 | 参数 | 行为 |
|---|---|---|
| 整门课全量 | `--course-id <id>`（可重复） | 走 `multi-search/get-course-detail` 展开全部小节 |
| 某个月 | `--month 2024-09` | 走 `get-my-course-month` |
| 指定日期区间 | `--start 2024-09-01 --end 2024-09-07` | 逐天调 `get-my-course-day`，逐天容错 |
| 不给日期 | 无 | 默认本周一 ~ 周日，并打印所用区间 |
| 不知道课 ID | `--search-title X` 或 `--search-teacher Y` | **只搜索不下载**，打印候选 `course_id`，用完需带 `--course-id` 再跑一次 |

搜索与下载是两步：

```bash
./zju-vibe classroom --search-title 高等数学 --search-teacher 张三   # 第 1 步: 找 course_id
./zju-vibe classroom --course-id 123456 --list-only                 # 第 2 步: 预演
./zju-vibe classroom --course-id 123456                             # 第 3 步: 下载
```

只给 `--search-*` 而不给 `--course-id` 时，命令在打印候选后就返回 0，不会下载——这是预期行为，不是失败。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--start` / `--end` | 本周一/周日 | `YYYY-MM-DD` |
| `--month` | 无 | `YYYY-MM`，与 `--start/--end` 二选一 |
| `--course-id` | 无 | 整课全量，可重复 |
| `--search-title` / `--search-teacher` | 无 | 全库搜索课程名 / 教师名 |
| `--out` | `~/Downloads/zju-vibe` | 下载根目录 |
| `--list-only` | 关 | 打印小节清单后退出 |
| `--no-pdf` | 关 | 只留图片不拼 PDF |
| `--no-skip` | 关 | 不跳过已存在文件 |
| `--workers` | 8 | 并发数（同时作用于取页和下图） |

## 输出格式

预演/清单阶段每行：

```
  [<课程名>] <小节名> (course=<course_id> sub=<sub_id>, <N> 页, 老师 <讲师>)
```

`sub=<id>` 就是 `subtitle` 命令要的小节 ID，先记下来。

落盘布局：

```
<out>/<课程名>/<小节名>/<课程名>-<小节名>.pdf
<out>/<课程名>/<小节名>/ppt_images/1.jpg, 2.jpg, …
```

- PDF **每图一页，页面尺寸=图片像素尺寸**；`--no-pdf` 时只返回 `ppt_images/` 目录。
- 图片按序号命名，`ppt_images/` 里**保留原图**，PDF 由其合成，删图不会自动重建 PDF（需 `--no-skip` 重跑）。

## 分页与去重注意

- `search-ppt` 分页每页 100，若某页返回条数与预期不符会原地重试（最多 5 次），仍不符则该小节报 `获取 PPT 列表失败`。
- 页数为 0 的小节会被 `enrich_with_ppt_urls` 过滤掉，不出现在清单里，也不计为失败。

## 常见问题

| 现象 | 处理 |
|---|---|
| `智云 token 缺失` | CLI 会自动重走 OAuth 预热链补齐；仍失败则 `logout` 后重新 `login`。 |
| `跳过 <课程>-<小节>: …` | 该小节取页失败（网络或接口限流）。缩小日期范围或降 `--workers` 后重试。 |
| `无有效 PPT 图片` | 该小节没有幻灯片，或图片全被服务端拒绝。报告给用户即可。 |
| `Errno 24 Too many open files` | 极高页数拼 PDF。CLI 已逐张 load 后关闭，仍触发就分批（缩小 `--start/--end` 或按 course 分次）下载。 |
| 想要回放视频 | 不支持，版权原因。明确告知用户。 |