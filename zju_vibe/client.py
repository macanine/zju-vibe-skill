"""HTTP 客户端: 带重试的 session 封装 + 学在浙大/智云课堂 API."""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from urllib.parse import unquote

import requests

from .auth import UA, classroom_token

LEARNING = "https://courses.zju.edu.cn"
CLASSROOM = "https://classroom.zju.edu.cn"


def safe_name(s: str, sub: str = "-") -> str:
    return (s or "").replace("/", sub).strip()


@dataclass
class Upload:
    id: int
    reference_id: int
    file_name: str
    course_name: str
    size: int = 0


@dataclass
class Subject:
    course_id: int
    sub_id: int
    course_name: str
    sub_name: str
    lecturer_name: str = ""
    ppt_image_urls: list = field(default_factory=list)


class ApiError(Exception):
    pass


class NoVoiceData(ApiError):
    """字幕接口 code=10002: 该小节暂无语音/转写数据 (如未开课或未录制)."""


class Client:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers.setdefault("User-Agent", UA)

    # ---- low level ----
    def _req(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", 30)
        delay = 0.1
        last = None
        for _ in range(6):
            try:
                r = self.s.request(method, url, **kw)
                return r
            except requests.RequestException as e:
                last = e
                time.sleep(delay)
                delay *= 2
        raise ApiError(f"请求失败 {url}: {last}")

    def get(self, url: str, **kw) -> requests.Response:
        return self._req("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self._req("POST", url, **kw)

    # ---- 学在浙大 ----
    def get_courses(self) -> list[dict]:
        courses: list[dict] = []
        page = 1
        payload_fields = (
            "id,name,course_code,academic_year_id,semester_id,"
            "start_date,end_date,is_started,is_closed"
        )
        while True:
            payload = {
                "fields": payload_fields,
                "page": page,
                "page_size": 100,
                "conditions": {
                    "status": ["ongoing", "notStarted", "closed"],
                    "keyword": "",
                    "classify_type": "recently_started",
                    "display_studio_list": False,
                },
                "showScorePassedStatus": False,
            }
            r = self.post(f"{LEARNING}/api/my-courses", json=payload)
            try:
                j = r.json()
            except Exception as e:
                raise ApiError(f"课程列表解析失败: {e}")
            batch = j.get("courses")
            if not isinstance(batch, list):
                raise ApiError("课程列表响应异常 (courses 缺失)")
            courses.extend(batch)
            pages = j.get("pages", 1) or 1
            if page >= pages:
                break
            page += 1
        return courses

    def get_academic_years(self) -> list[dict]:
        r = self.get(f"{LEARNING}/api/my-academic-years?fields=id,name,sort,is_active")
        return r.json().get("academic_years", [])

    def get_semesters(self) -> list[dict]:
        r = self.get(f"{LEARNING}/api/my-semesters?")
        return r.json().get("semesters", [])

    def get_activities_uploads(self, course_id: int) -> list[dict]:
        r = self.get(f"{LEARNING}/api/courses/{course_id}/activities")
        j = r.json()
        out = []
        for act in j.get("activities", []) or []:
            ups = act.get("uploads")
            if isinstance(ups, list):
                out.extend(ups)
        return out

    def get_homework_uploads(self, course_id: int) -> list[dict]:
        out = []
        base = (
            f"{LEARNING}/api/courses/{course_id}/homework-activities"
            "?conditions=%7B%22itemsSortBy%22:%7B%22predicate%22:%22module%22,"
            "%22reverse%22:false%7D%7D&page={}&page_size=20&reloadPage=false"
        )
        r = self.get(base.format(1))
        j = r.json()
        for hw in j.get("homework_activities", []) or []:
            ups = hw.get("uploads")
            if isinstance(ups, list):
                out.extend(ups)
        pages = j.get("pages", 1) or 1
        for page in range(2, int(pages) + 1):
            r = self.get(base.format(page))
            j = r.json()
            for hw in j.get("homework_activities", []) or []:
                ups = hw.get("uploads")
                if isinstance(ups, list):
                    out.extend(ups)
        return out

    def collect_uploads(self, courses: list[dict], include_homework: bool = True) -> list[Upload]:
        out: list[Upload] = []
        for c in courses:
            cid = c.get("id")
            cname = safe_name(str(c.get("name", cid)))
            if cid is None:
                continue
            seen = set()
            for u in self.get_activities_uploads(cid):
                key = (u.get("id"), u.get("reference_id"))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    Upload(
                        id=int(u.get("id", 0)),
                        reference_id=int(u.get("reference_id", 0)),
                        file_name=str(u.get("name", f"{u.get('id')}")),
                        course_name=cname,
                        size=int(u.get("size") or 0),
                    )
                )
            if include_homework:
                try:
                    for u in self.get_homework_uploads(cid):
                        key = (u.get("id"), u.get("reference_id"))
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(
                            Upload(
                                id=int(u.get("id", 0)),
                                reference_id=int(u.get("reference_id", 0)),
                                file_name=str(u.get("name", f"{u.get('id')}")),
                                course_name=cname,
                                size=int(u.get("size") or 0),
                            )
                        )
                except ApiError:
                    pass
        return out

    def download_upload_stream(self, upload: Upload, dest_dir: str):
        """返回 (final_name, response). 先 reference/blob, 失败兜底 uploads/{id}/blob (Preview 版)."""
        from pathlib import Path

        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        last = None
        for _ in range(5):
            r = self.get(f"{LEARNING}/api/uploads/reference/{upload.reference_id}/blob", stream=True)
            if not r.ok:
                r = self.get(f"{LEARNING}/api/uploads/{upload.id}/blob", stream=True)
            if r.ok:
                name = upload.file_name
                url = r.url
                if "name=" in url:
                    try:
                        part = url.split("name=", 1)[1].split("&", 1)[0]
                        name = unquote(part) or name
                    except Exception:
                        pass
                return name, r
            last = r.status_code
            time.sleep(0.5)
        raise ApiError(f"下载失败 {upload.file_name} (HTTP {last})")

    # ---- 智云课堂 ----
    def _classroom_headers(self) -> dict:
        token = classroom_token(self.s)
        return {"User-Agent": UA, "Authorization": f"Bearer {token}"}

    def _parse_sub(self, course_id: int, course_name: str, sub_id: int, sub_name: str, lecturer: str) -> Subject:
        return Subject(
            course_id=int(course_id),
            sub_id=int(sub_id),
            course_name=safe_name(str(course_name), "_"),
            sub_name=safe_name(str(sub_name), "_"),
            lecturer_name=str(lecturer or ""),
        )

    def get_month_subs(self, month: str) -> list[Subject]:
        """month 格式 YYYY-MM."""
        h = self._classroom_headers()
        r = self.get(f"{CLASSROOM}/courseapi/v2/course-live/get-my-course-month?month={month}", headers=h)
        j = r.json()
        subs: list[Subject] = []
        for day in j.get("list", []) or []:
            for c in day.get("course", []) or []:
                try:
                    subs.append(
                        self._parse_sub(c["id"], c["title"], c["sub_id"], c["sub_title"], c.get("realname", ""))
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        return subs

    def get_range_subs(self, start: str, end: str) -> list[Subject]:
        """start/end 格式 YYYY-MM-DD, 逐天拉取."""
        from datetime import date

        h = self._classroom_headers()
        y1, m1, d1 = map(int, start.split("-"))
        y2, m2, d2 = map(int, end.split("-"))
        day, last = date(y1, m1, d1), date(y2, m2, d2)
        subs: list[Subject] = []
        from datetime import timedelta

        while day <= last:
            ds = day.isoformat()
            r = self.get(f"{CLASSROOM}/courseapi/v2/course-live/get-my-course-day?day={ds}", headers=h)
            try:
                j = r.json()
            except Exception:
                day += timedelta(days=1)
                continue
            lst = j.get("list")
            if isinstance(lst, dict):
                for data in lst.values():
                    for c in (data.get("course") or []):
                        try:
                            subs.append(
                                self._parse_sub(c["id"], c["title"], c["sub_id"], c["sub_title"], c.get("realname", ""))
                            )
                        except (KeyError, ValueError, TypeError):
                            continue
            day += timedelta(days=1)
        return subs

    def search_courses(self, course_name: str = "", teacher_name: str = "") -> list[dict]:
        h = self._classroom_headers()
        r = self.get(f"{CLASSROOM}/userapi/v1/infosimple", headers=h)
        j = r.json()
        account = j["params"]["account"]
        user_id = j["params"]["id"]
        courses: list[dict] = []
        page = 1
        total = None
        while True:
            rnd = random.random()
            r = self.get(
                f"{CLASSROOM}/pptnote/v1/searchlist?tenant_id=112&user_id={user_id}"
                f"&user_name={account}&page={page}&per_page=16&title={course_name}"
                f"&realname={teacher_name}&trans=&tenant_code=112&randomKey={rnd}",
                headers=h,
            )
            j = r.json()
            if j.get("code") != 0:
                raise ApiError(f"搜索失败: {j.get('msg')}")
            batch = (j.get("total") or {}).get("list", []) or []
            courses.extend(batch)
            if total is None:
                total = (j.get("total") or {}).get("total", 0) or 0
            if len(courses) >= int(total):
                break
            page += 1
        return courses

    def get_course_subs(self, course_id: int) -> list[Subject]:
        h = self._classroom_headers()
        r = self.get(f"{CLASSROOM}/userapi/v1/infosimple", headers=h)
        account = r.json()["params"]["account"]
        r = self.get(
            f"https://yjapi.cmc.zju.edu.cn/courseapi/v3/multi-search/get-course-detail"
            f"?course_id={course_id}&student={account}",
            headers=h,
        )
        data = r.json().get("data", {})
        course_name = safe_name(str(data.get("title", course_id)), "_")
        subs: list[Subject] = []
        sub_list = data.get("sub_list", {}) or {}
        for year_data in sub_list.values():
            if not isinstance(year_data, dict):
                continue
            for month_data in year_data.values():
                if not isinstance(month_data, dict):
                    continue
                for week_data in month_data.values():
                    if not isinstance(week_data, list):
                        continue
                    for s in week_data:
                        try:
                            subs.append(
                                Subject(
                                    course_id=int(course_id),
                                    sub_id=int(str(s["id"])),
                                    course_name=course_name,
                                    sub_name=safe_name(str(s.get("sub_title", s["id"])), "_"),
                                    lecturer_name=str(s.get("lecturer_name", "")),
                                )
                            )
                        except (KeyError, ValueError, TypeError):
                            continue
        return subs

    def get_ppt_urls(self, course_id: int, sub_id: int) -> list[str]:
        urls: list[str] = []
        page = 1
        total = None
        retries = 5
        while True:
            r = self.get(
                f"{CLASSROOM}/pptnote/v1/schedule/search-ppt"
                f"?course_id={course_id}&sub_id={sub_id}&page={page}&per_page=100"
            )
            j = r.json()
            lst = j.get("list", []) or []
            if total is None:
                total = j.get("total", 0) or 0
            if page > 1 and len(lst) != min(100, int(total) - len(urls)):
                # 本页数量不对, 重试本页 (不递增 page 即重发本页)
                retries -= 1
                if retries <= 0:
                    raise ApiError(f"获取 PPT 列表失败 course={course_id} sub={sub_id}")
                time.sleep(0.2)
                continue
            for item in lst:
                try:
                    content = json.loads(item.get("content", "{}"))
                    url = content.get("pptimgurl")
                    if url:
                        urls.append(url)
                except Exception:
                    continue
            if len(urls) >= int(total):
                break
            page += 1
        return urls

    # ---- 智云字幕 ----
    def get_subtitle(self, sub_id: int) -> list[dict]:
        """拉取一节课的字幕列表. 返回 [{begin_sec, end_sec, text, trans_text}].

        接口无需 Bearer token, 带登录 cookies 即可.
        """
        r = self.get(
            "https://yjapi.cmc.zju.edu.cn/courseapi/v3/web-socket/search-trans-result"
            f"?sub_id={sub_id}&format=json"
        )
        try:
            j = r.json()
        except Exception as e:
            raise ApiError(f"字幕响应解析失败: {e}")
        if j.get("code") != 0:
            if j.get("code") == 10002:
                raise NoVoiceData(f"sub_id={sub_id} 暂无语音数据 (未开课或未录制)")
            raise ApiError(f"获取字幕失败 (code={j.get('code')}): {j.get('msg')}")
        lst = j.get("list") or []
        if not lst:
            return []
        contents = (lst[0] or {}).get("all_content") or []
        out = []
        for c in contents:
            try:
                out.append(
                    {
                        "begin_sec": int(c.get("BeginSec", 0)),
                        "end_sec": int(c.get("EndSec", 0)),
                        "text": str(c.get("Text") or ""),
                        "trans_text": str(c.get("TransText") or ""),
                    }
                )
            except (ValueError, TypeError):
                continue
        return out
