"""命令行入口: login / logout / courses / learn / classroom / subtitle."""
from __future__ import annotations

import argparse
import getpass
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests

from . import __version__
from .auth import UA, LoginError, login as do_login, warmup_classroom
from .client import ApiError, NoVoiceData, Client
from .download import (
    DownloadError,
    download_learn_file,
    download_subject_ppts,
    save_subtitle_srt,
)
from .store import (
    clear_session,
    default_save_dir,
    load_session,
    save_session,
    saved_password,
    session_path,
)


def build_saved_session() -> tuple[str | None, requests.Session | None]:
    username, cookies = load_session()
    if not username or not cookies:
        return None, None
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    for c in cookies:
        try:
            s.cookies.set(
                c.get("name", ""),
                c.get("value", ""),
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
            )
        except Exception:
            continue
    return username, s


def require_client() -> tuple[str, Client]:
    username, s = build_saved_session()
    if not username or s is None:
        print("尚未登录, 请先运行: ./zju-vibe login -u <学号>", file=sys.stderr)
        raise SystemExit(2)
    return username, Client(s)


def persist_session(username: str, session: requests.Session) -> None:
    """把当前 jar 写回 session.pkl (用于懒预热后补存 classroom cookies)."""
    import pickle

    cookies = [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
        for c in session.cookies
    ]
    with open(session_path(), "wb") as f:
        pickle.dump({"username": username, "cookies": cookies}, f)


def ensure_classroom_token(username: str, client: Client) -> None:
    """老会话缺 _token 时自动走一遍 classroom 预热并回写, 无需重输密码.

    token 缺失时无需重新输入密码, 直接重走一遍 OAuth 链即可补齐.
    """
    from .auth import classroom_token

    try:
        classroom_token(client.s)
        return
    except LoginError:
        pass
    print("智云 token 缺失, 正在自动补预热...", file=sys.stderr)
    warmup_classroom(client.s)
    classroom_token(client.s)  # 仍缺则抛给上层
    persist_session(username, client.s)


def cmd_login(args) -> int:
    username = args.username or input("学号: ").strip()
    password = args.password
    if not password:
        password = saved_password(username) or getpass.getpass("密码: ")
    try:
        session = do_login(username, password)
    except (LoginError, requests.RequestException) as e:
        print(f"登录失败: {e}", file=sys.stderr)
        return 1
    save_session(username, password, session.cookies)
    print(f"登录成功: {username}")
    return 0


def cmd_logout(_args) -> int:
    clear_session()
    print("已退出登录 (本地会话已清除)")
    return 0


def filter_courses(courses, years, semesters, year=None, semester=None):
    if year:
        ids = {y["id"] for y in years if year in str(y.get("name", ""))}
        courses = [c for c in courses if c.get("academic_year_id") in ids]
    if semester:
        sem = next((s for s in semesters if semester in str(s.get("name", ""))), None)
        if sem is None:
            print(f"未找到学期 '{semester}', 可用: " + ", ".join(s.get("name", "") for s in semesters))
            return []
        courses = [
            c
            for c in courses
            if c.get("semester_id") == sem["id"]
            or (c.get("semester_id") == 0 and c.get("academic_year_id") == sem.get("academic_year_id"))
        ]
    return courses


def cmd_courses(args) -> int:
    try:
        _, client = require_client()
        courses = client.get_courses()
        years = client.get_academic_years()
        semesters = client.get_semesters()
    except (ApiError, requests.RequestException) as e:
        print(f"获取课程失败: {e}", file=sys.stderr)
        return 1
    courses = filter_courses(courses, years, semesters, args.year, args.semester)
    courses.sort(key=lambda c: c.get("id", 0))
    if args.json:
        import json

        print(json.dumps(courses, ensure_ascii=False, indent=2))
        return 0
    print(f"共 {len(courses)} 门课程:")
    for c in courses:
        print(f"  [{c.get('id')}] {c.get('name')} (学年{c.get('academic_year_id')} 学期{c.get('semester_id')})")
    return 0


def resolve_learn_courses(client, args):
    courses = client.get_courses()
    years = client.get_academic_years()
    semesters = client.get_semesters()
    if args.course:
        want = set(args.course)
        picked = [c for c in courses if c.get("id") in want]
        missing = want - {c.get("id") for c in picked}
        if missing:
            print(f"警告: 以下课程 ID 不在你的课程列表中: {sorted(missing)}", file=sys.stderr)
        return picked
    if args.all:
        return courses
    return filter_courses(courses, years, semesters, args.year, args.semester)


def cmd_learn(args) -> int:
    try:
        _, client = require_client()
        picked = resolve_learn_courses(client, args)
    except (ApiError, requests.RequestException) as e:
        print(f"获取课程失败: {e}", file=sys.stderr)
        return 1
    if not picked:
        print("未选中任何课程 (用 --course ID 或 --all 或 --year/--semester 筛选)", file=sys.stderr)
        return 2
    print(f"选中 {len(picked)} 门课程, 正在拉取课件列表...")
    try:
        uploads = client.collect_uploads(picked, include_homework=not args.no_homework)
    except (ApiError, requests.RequestException) as e:
        print(f"拉取课件列表失败: {e}", file=sys.stderr)
        return 1
    if args.ext_exclude:
        excl = {e.lower().lstrip(".") for e in args.ext_exclude.split(",") if e.strip()}
        uploads = [u for u in uploads if u.file_name.rsplit(".", 1)[-1].lower() not in excl]
    uploads.sort(key=lambda u: (u.course_name, u.file_name))
    total_size = sum(u.size for u in uploads)
    print(f"共 {len(uploads)} 个文件, 合计 {total_size / 1024 / 1024:.1f} MB")
    for u in uploads:
        print(f"  [{u.course_name}] {u.file_name} ({u.size // 1024} KB, id={u.id} ref={u.reference_id})")
    if args.list_only or not uploads:
        return 0
    out = args.out or default_save_dir()
    ok = skip = fail = 0
    workers = max(1, args.workers)
    from concurrent.futures import ThreadPoolExecutor as TPE

    def one(u):
        d = str(Path(out) / u.course_name)
        return download_learn_file(
            client, u, d,
            skip_existing=not args.no_skip,
            no_preview=args.no_preview,
        )

    with TPE(max_workers=workers) as ex:
        futs = {ex.submit(one, u): u for u in uploads}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                st = fut.result()
                if st == "skip":
                    skip += 1
                else:
                    ok += 1
                    print(f"OK {u.file_name}")
            except (DownloadError, ApiError, requests.RequestException) as e:
                fail += 1
                print(f"FAIL {u.file_name}: {e}", file=sys.stderr)
    print(f"完成: 成功 {ok}, 跳过 {skip}, 失败 {fail}, 目录 {out}")
    return 1 if fail and not ok else 0


def resolve_classroom_subs(client, args):
    if args.course_id:
        subs = []
        for cid in args.course_id:
            subs.extend(client.get_course_subs(cid))
        return subs
    if args.month:
        return client.get_month_subs(args.month)
    start, end = args.start, args.end
    if not start or not end:
        today = date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        start, end = start.isoformat(), end.isoformat()
        print(f"未指定日期, 默认本周 {start} ~ {end}")
    return client.get_range_subs(start, end)


def enrich_with_ppt_urls(client, subs, workers=8):
    enriched = []

    def one(s):
        try:
            urls = client.get_ppt_urls(s.course_id, s.sub_id)
        except Exception:
            time_sleep(1)
            urls = client.get_ppt_urls(s.course_id, s.sub_id)
        s.ppt_image_urls = urls
        return s

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, s): s for s in subs}
        for fut in as_completed(futs):
            try:
                s = fut.result()
                if s.ppt_image_urls:
                    enriched.append(s)
            except Exception as e:
                s = futs[fut]
                print(f"跳过 {s.course_name}-{s.sub_name}: {e}", file=sys.stderr)
    enriched.sort(key=lambda s: (s.course_name, s.sub_id))
    return enriched


def time_sleep(s):
    import time

    time.sleep(s)


def cmd_classroom(args) -> int:
    try:
        username, client = require_client()
        ensure_classroom_token(username, client)
        if args.search_title or args.search_teacher:
            if not args.course_id:
                courses = client.search_courses(args.search_title or "", args.search_teacher or "")
                print(f"搜索到 {len(courses)} 门课程:")
                for c in courses:
                    print(f"  course_id={c.get('course_id')} {c.get('title')} {c.get('realname')} {c.get('term_name', '')}")
                print("用 --course-id <id> 拉取该课程全部 PPT")
                return 0
        subs = resolve_classroom_subs(client, args)
    except (ApiError, requests.RequestException, LoginError) as e:
        print(f"获取智云课程失败: {e}", file=sys.stderr)
        return 1
    print(f"共 {len(subs)} 节课, 正在获取 PPT 页数...")
    try:
        subs = enrich_with_ppt_urls(client, subs, workers=args.workers)
    except (ApiError, requests.RequestException) as e:
        print(f"获取 PPT 列表失败: {e}", file=sys.stderr)
        return 1
    total_pages = sum(len(s.ppt_image_urls) for s in subs)
    print(f"有 PPT 的共 {len(subs)} 节, {total_pages} 页")
    for s in subs:
        print(f"  [{s.course_name}] {s.sub_name} (course={s.course_id} sub={s.sub_id}, {len(s.ppt_image_urls)} 页, 老师 {s.lecturer_name})")
    if args.list_only or not subs:
        return 0
    out = args.out or default_save_dir()
    ok = fail = 0
    for s in subs:
        try:
            p = download_subject_ppts(
                client, s, out,
                to_pdf=not args.no_pdf,
                workers=args.workers,
                skip_existing=not args.no_skip,
            )
            ok += 1
            print(f"OK {s.sub_name} -> {p}")
        except (DownloadError, ApiError, requests.RequestException) as e:
            fail += 1
            print(f"FAIL {s.sub_name}: {e}", file=sys.stderr)
    print(f"完成: 成功 {ok}, 失败 {fail}, 目录 {out}")
    return 1 if fail and not ok else 0


def cmd_subtitle(args) -> int:
    """字幕: 单节预览/保存, 或按 course 整课批量下载."""
    try:
        username, client = require_client()
        ensure_classroom_token(username, client)
    except (ApiError, requests.RequestException, LoginError) as e:
        print(f"获取字幕失败: {e}", file=sys.stderr)
        return 1
    if args.course_id:
        return cmd_subtitle_batch(client, args)
    if args.sub_id is None:
        print("请指定 sub_id 或 --course-id", file=sys.stderr)
        return 2
    try:
        contents = client.get_subtitle(args.sub_id)
    except (ApiError, requests.RequestException, LoginError) as e:
        print(f"获取字幕失败: {e}", file=sys.stderr)
        return 1
    if not contents:
        print(f"sub_id={args.sub_id} 无字幕内容")
        return 0
    dur = max((c.get("end_sec", 0) for c in contents), default=0)
    print(f"共 {len(contents)} 条字幕, 时长约 {dur // 60} 分 {dur % 60} 秒")
    for c in contents[:args.preview]:
        print(f"  [{c['begin_sec']:>6d}s -> {c['end_sec']:>6d}s] {c['text'][:80]}")
    if args.preview_only:
        return 0
    # --out 语义: 以 .srt 结尾视为文件路径, 否则视为目录(自动拼文件名)
    out_arg = args.out or default_save_dir()
    out = Path(out_arg)
    if out.suffix.lower() != ".srt":
        out = out / f"sub_{args.sub_id}.{args.lang}.srt"
    save_subtitle_srt(contents, out, lang=args.lang)
    print(f"已保存: {out} ({out.stat().st_size // 1024} KB)")
    return 0


def cmd_subtitle_batch(client: Client, args) -> int:
    """按 course_id 批量下载整课所有小节的 SRT, 文件名自带日期(sub_name)."""
    subs = []
    for cid in args.course_id:
        try:
            subs.extend(client.get_course_subs(cid))
        except (ApiError, requests.RequestException, LoginError) as e:
            print(f"获取课程 {cid} 小节列表失败: {e}", file=sys.stderr)
    if not subs:
        print("未找到任何小节", file=sys.stderr)
        return 1
    subs.sort(key=lambda s: (s.course_name, s.sub_name))
    print(f"共 {len(subs)} 节, 正在批量拉取字幕...")
    out_base = Path(args.out or default_save_dir())
    skip_existing = not args.no_skip
    ok = empty = fail = skip = 0

    def one(sub):
        dest = out_base / sub.course_name / f"{sub.sub_name}.{args.lang}.srt"
        if skip_existing and dest.exists() and dest.stat().st_size > 0:
            return sub, "skip", None
        try:
            contents = client.get_subtitle(sub.sub_id)
        except NoVoiceData:
            return sub, "novoice", None
        except Exception as e:
            return sub, "fail", str(e)
        if not contents:
            return sub, "empty", None
        save_subtitle_srt(contents, dest, lang=args.lang)
        return sub, "ok", dest

    workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, s): s for s in subs}
        for fut in as_completed(futs):
            sub, st, info = fut.result()
            if st == "ok":
                ok += 1
                print(f"OK [{sub.sub_name}] ({sub.sub_id}) -> {info}")
            elif st == "skip":
                skip += 1
                print(f"SKIP [{sub.sub_name}] 已存在")
            elif st == "empty":
                empty += 1
                print(f"EMPTY [{sub.sub_name}] ({sub.sub_id}) 无字幕")
            elif st == "novoice":
                empty += 1
                print(f"-- [{sub.sub_name}] 暂无语音 (未开课或未录制)")
            else:
                fail += 1
                print(f"FAIL [{sub.sub_name}] ({sub.sub_id}): {info}", file=sys.stderr)
    print(f"完成: 成功 {ok}, 跳过 {skip}, 无字幕 {empty}, 失败 {fail}, 目录 {out_base}")
    return 1 if fail and not ok else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zju-vibe", description="浙大课程资料抓取: 学在浙大课件 / 智云课堂 PPT / 字幕 SRT")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="统一身份认证登录")
    pl.add_argument("-u", "--username", help="学号")
    pl.add_argument("-p", "--password", help="密码 (缺省则交互输入)")
    pl.set_defaults(func=cmd_login)

    po = sub.add_parser("logout", help="清除本地会话")
    po.set_defaults(func=cmd_logout)

    pc = sub.add_parser("courses", help="列出学在浙大课程")
    pc.add_argument("--year", help="按学年名过滤 (如 2024-2025)")
    pc.add_argument("--semester", help="按学期名过滤 (如 秋冬)")
    pc.add_argument("--json", action="store_true", help="输出 JSON")
    pc.set_defaults(func=cmd_courses)

    pl2 = sub.add_parser("learn", help="功能1: 学在浙大课件批量下载")
    pl2.add_argument("--course", type=int, action="append", default=[], help="课程 ID, 可重复指定")
    pl2.add_argument("--all", action="store_true", help="下载全部课程")
    pl2.add_argument("--year", help="按学年名过滤")
    pl2.add_argument("--semester", help="按学期名过滤")
    pl2.add_argument("--out", help="下载目录 (默认 ~/Downloads/zju-vibe)")
    pl2.add_argument("--list-only", action="store_true", help="只列出不下载")
    pl2.add_argument("--no-homework", action="store_true", help="不含作业附件 (默认含作业)")
    pl2.add_argument("--no-skip", action="store_true", help="不跳过已存在同大小文件")
    pl2.add_argument("--no-preview", action="store_true", help="禁用 Preview 兜底 (仅下载开放下载的文件)")
    pl2.add_argument("--ext-exclude", help="排除扩展名, 逗号分隔 (如 mp4,zip)")
    pl2.add_argument("--workers", type=int, default=4, help="并发下载数 (默认 4)")
    pl2.set_defaults(func=cmd_learn)

    pr = sub.add_parser("classroom", help="功能2: 智云课堂 PPT 下载并转 PDF")
    pr.add_argument("--start", help="开始日期 YYYY-MM-DD (默认本周一)")
    pr.add_argument("--end", help="结束日期 YYYY-MM-DD (默认本周日)")
    pr.add_argument("--month", help="按月拉取 YYYY-MM (与 --start/--end 二选一)")
    pr.add_argument("--course-id", type=int, action="append", default=[], help="整课全量拉取, 可重复指定")
    pr.add_argument("--search-title", help="搜索全部课程: 课程名关键字")
    pr.add_argument("--search-teacher", help="搜索全部课程: 教师名关键字")
    pr.add_argument("--out", help="下载目录 (默认 ~/Downloads/zju-vibe)")
    pr.add_argument("--list-only", action="store_true", help="只列出不下载")
    pr.add_argument("--no-pdf", action="store_true", help="只保留图片, 不拼 PDF")
    pr.add_argument("--no-skip", action="store_true", help="不跳过已存在文件")
    pr.add_argument("--workers", type=int, default=8, help="并发数 (默认 8)")
    pr.set_defaults(func=cmd_classroom)

    ps = sub.add_parser("subtitle", help="智云课堂字幕: 拉取并转 SRT")
    ps.add_argument("sub_id", type=int, nargs="?", default=None, help="小节 ID (如 1979437, 与 --course-id 二选一)")
    ps.add_argument("--course-id", type=int, action="append", default=[],
                    help="整课批量下载该课程全部小节的 SRT (文件名自带日期), 可重复指定")
    ps.add_argument("--lang", choices=["zh", "en", "mixed"], default="zh",
                    help="字幕语言: zh 中文 / en 英文 / mixed 中英双语 (默认 zh)")
    ps.add_argument("--out", help="单节: 输出的 srt 路径; 批量: 输出目录 (默认下载目录)")
    ps.add_argument("--preview", type=int, default=5, help="单节预览前 N 条 (默认 5)")
    ps.add_argument("--preview-only", action="store_true", help="单节只预览不保存文件")
    ps.add_argument("--no-skip", action="store_true", help="批量: 不跳过已存在文件")
    ps.add_argument("--workers", type=int, default=4, help="批量并发数 (默认 4)")
    ps.set_defaults(func=cmd_subtitle)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
