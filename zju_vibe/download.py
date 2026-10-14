"""文件下载: 学在浙大课件 + 智云 PPT 图片下载 + 图片转 PDF + 字幕存 SRT."""
from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image


class DownloadError(Exception):
    pass


def need_skip(path: Path, expect_size: int | None) -> bool:
    if not path.exists():
        return False
    if not expect_size:
        return False
    try:
        return path.stat().st_size == int(expect_size)
    except OSError:
        return False


def stream_to_file(resp: requests.Response, dest: Path, desc: str = "") -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = int(resp.headers.get("Content-Length") or 0)
    try:
        from tqdm import tqdm

        bar = tqdm(total=total or None, unit="B", unit_scale=True, desc=desc[:40], leave=False)
    except ImportError:
        bar = None
    size = 0
    try:
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                size += len(chunk)
                if bar:
                    bar.update(len(chunk))
    finally:
        if bar:
            bar.close()
    return size


def download_learn_file(client, upload, dest_dir: str, skip_existing: bool = True,
                        no_preview: bool = False) -> str:
    """下载单个学在浙大课件, 返回 'ok' | 'skip'."""
    from .client import LEARNING

    dest_dir_p = Path(dest_dir)
    target = dest_dir_p / upload.file_name
    if skip_existing and upload.size and need_skip(target, upload.size):
        return "skip"

    # reference/blob 优先, 失败兜底 uploads/{id}/blob (Preview 版)
    urls = [f"{LEARNING}/api/uploads/reference/{upload.reference_id}/blob"]
    if not no_preview:
        urls.append(f"{LEARNING}/api/uploads/{upload.id}/blob")
    resp = None
    for u in urls:
        for _ in range(3):
            try:
                r = client.get(u, stream=True)
                if r.ok:
                    resp = r
                    break
            except Exception:
                time.sleep(0.5)
        if resp is not None:
            break
    if resp is None:
        raise DownloadError(f"下载失败: {upload.file_name}")
    name = upload.file_name
    try:
        from urllib.parse import unquote

        if "name=" in resp.url:
            part = resp.url.split("name=", 1)[1].split("&", 1)[0]
            name = unquote(part) or name
    except Exception:
        pass
    target = dest_dir_p / name
    if skip_existing:
        try:
            expect = int(resp.headers.get("Content-Length") or upload.size or 0)
        except Exception:
            expect = 0
        if expect and need_skip(target, expect):
            return "skip"
    stream_to_file(resp, target, desc=name)
    return "ok"


def download_ppt_image(client, url: str, dest: Path, retries: int = 5) -> None:
    """下载单张 PPT 图片, 校验非空且为合法图片."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    delay = 0.1
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            r = client.get(url, stream=True)
            data = r.content
            if not data:
                raise DownloadError("空响应")
            Image.open(io.BytesIO(data)).verify()
            dest.write_bytes(data)
            if dest.stat().st_size == 0:
                raise DownloadError("空文件")
            return
        except Exception as e:
            last_err = e
            time.sleep(delay)
            delay *= 2
    try:
        if dest.exists():
            dest.unlink()
    except OSError:
        pass
    raise DownloadError(f"PPT 图片下载失败 {url}: {last_err}")


def download_subject_ppts(client, subject, base_dir: str, to_pdf: bool = True,
                          workers: int = 8, skip_existing: bool = True) -> str:
    """下载一节智云课堂的全部 PPT 图片, 可选拼 PDF. 返回 PDF 路径或图片目录."""
    sub_dir = Path(base_dir) / subject.course_name / subject.sub_name
    img_dir = sub_dir / "ppt_images"
    img_dir.mkdir(parents=True, exist_ok=True)

    urls = subject.ppt_image_urls
    paths: list[Path] = []
    for i, url in enumerate(urls, start=1):
        ext = (url.split("?")[0].rsplit(".", 1)[-1] or "jpg").lower()
        if len(ext) > 5 or "/" in ext:
            ext = "jpg"
        paths.append(img_dir / f"{i}.{ext}")

    todo = [(u, p) for u, p in zip(urls, paths)
            if not (skip_existing and p.exists() and p.stat().st_size > 0)]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(download_ppt_image, client, u, p): (u, p) for u, p in todo}
            for fut in as_completed(futs):
                u, p = futs[fut]
                try:
                    fut.result()
                except Exception as e:
                    raise DownloadError(f"{subject.sub_name}: {e}")
                time.sleep(0.02)

    ordered = [p for p in paths if p.exists() and p.stat().st_size > 0]
    if not ordered:
        raise DownloadError(f"{subject.sub_name}: 无有效 PPT 图片")
    if not to_pdf:
        return str(img_dir)
    pdf_path = sub_dir / f"{subject.course_name}-{subject.sub_name}.pdf"
    if skip_existing and pdf_path.exists() and pdf_path.stat().st_size > 0:
        return str(pdf_path)
    images_to_pdf([str(p) for p in ordered], str(pdf_path))
    return str(pdf_path)


def images_to_pdf(image_paths: list[str], pdf_path: str) -> None:
    """每张图片一页, 页面尺寸=图片像素尺寸.

    注意: 必须逐张 open → load 进内存 → 立即关闭, 不能一次性全 open.
    PIL 的 Image.open 是懒加载, 会一直占着文件句柄, 几百页 PPT 会直接
    触发 Errno 24 Too many open files (macOS 默认 fd 上限 256).
    """
    fixed = []
    for p in image_paths:
        with Image.open(p) as im:
            im.load()
            if im.mode in ("RGBA", "LA", "PA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                fixed.append(bg)
            elif im.mode != "RGB":
                fixed.append(im.convert("RGB"))
            else:
                fixed.append(im.copy())
    if not fixed:
        raise DownloadError("无有效图片, 无法生成 PDF")
    first, rest = fixed[0], fixed[1:]
    Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
    first.save(pdf_path, "PDF", save_all=True, append_images=rest)


def srt_timestamp(seconds: int) -> str:
    """秒 → SRT 时间戳."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},000"


def save_subtitle_srt(contents: list[dict], dest: Path, lang: str = "zh") -> Path:
    """字幕列表存为 SRT 文件.

    lang: 'zh' 中文 / 'en' 英文(TransText) / 'mixed' 中英双语(中文在上英文在下).
    空文本条目跳过, 但序号保持原始 enumerate 计数.
    返回写出的文件路径.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, c in enumerate(contents):
        zh = (c.get("text") or "").strip()
        en = (c.get("trans_text") or "").strip()
        if lang == "en":
            body = en
        elif lang == "mixed":
            if en and zh:
                body = f"{zh}\n{en}"
            else:
                body = zh or en
        else:
            body = zh
        if not body.strip():
            continue
        lines.append(f"{index + 1}\n")
        lines.append(f"{srt_timestamp(c.get('begin_sec', 0))} --> {srt_timestamp(c.get('end_sec', 0))}\n")
        lines.append(f"{body}\n\n")
    dest.write_text("".join(lines), encoding="utf-8")
    return dest
