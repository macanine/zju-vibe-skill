"""统一身份认证登录 (RSA 无填充加密) + 会话保持."""
from __future__ import annotations

import re
import sys
import time
from urllib.parse import unquote, urljoin

import requests


UA = "Mozilla/5.0 (X11; Linux x86_64; rv:88.0) Gecko/20100101 Firefox/88.0"

CLASSROOM_WARMUP_URL = (
    "https://tgmedia.cmc.zju.edu.cn/index.php?r=auth/login&auType=cmc&tenant_code=112"
    "&forward=https%3A%2F%2Fclassroom.zju.edu.cn%2F"
)


def rsa_no_padding(password: str, modulus_hex: str, exponent_hex: str) -> str:
    m = int(modulus_hex, 16)
    e = int(exponent_hex, 16)
    n = int.from_bytes(password.encode(), "big")
    c = pow(n, e, m)
    # 逐字节 {:02x} 格式化, 保留字节前导 0
    blen = (c.bit_length() + 7) // 8
    return c.to_bytes(blen, "big").hex() if blen else ""


class LoginError(Exception):
    pass


def _http(s: requests.Session, method: str, url: str, step: str,
          retries: int = 3, timeout: int = 15, **kw) -> requests.Response:
    """带重试的单次请求. timeout 是读超时; 每次重试退避, 失败抛 LoginError(带步骤名)."""
    last: Exception | None = None
    for i in range(1, retries + 1):
        try:
            return s.request(method, url, timeout=timeout, **kw)
        except requests.RequestException as e:
            last = e
            if i < retries:
                time.sleep(2 * i)
    raise LoginError(f"{step}失败(已重试{retries}次): {type(last).__name__}: {str(last)[:160]}")


def login(username: str, password: str, session: requests.Session | None = None) -> requests.Session:
    """执行浙大统一身份认证登录, 返回带 cookies 的 session.

    Raises:
        LoginError: 登录失败(页面异常 / execution 缺失 / 用户名密码错误)
    """
    s = session or requests.Session()
    s.headers.update({"User-Agent": UA})

    r = _http(s, "GET", "https://zjuam.zju.edu.cn/cas/login", "打开统一身份认证页面")
    text = r.text
    if "统一身份认证平台" not in text:
        # cookie 可能过期, 清掉重试一次
        s.cookies.clear()
        r = _http(s, "GET", "https://zjuam.zju.edu.cn/cas/login", "打开统一身份认证页面(重试)")
        text = r.text
        if "统一身份认证平台" not in text:
            raise LoginError("无法打开统一身份认证页面, 请检查网络/代理")

    m = re.search(r'<input type="hidden" name="execution" value="(.*?)" />', text)
    if not m:
        raise LoginError("未找到 execution 参数, 登录页面可能已变更")
    execution = m.group(1)

    r = _http(s, "GET", "https://zjuam.zju.edu.cn/cas/v2/getPubKey", "获取登录公钥")
    try:
        key = r.json()
        modulus, exponent = key["modulus"], key["exponent"]
    except Exception as e:
        raise LoginError(f"获取 RSA 公钥失败: {e}")
    rsapwd = rsa_no_padding(password, modulus, exponent)

    r = _http(
        s, "POST", "https://zjuam.zju.edu.cn/cas/login", "提交登录",
        data={
            "username": username,
            "password": rsapwd,
            "execution": execution,
            "_eventId": "submit",
            "authcode": "",
        },
    )
    if "统一身份认证平台" in r.text:
        raise LoginError("用户名或密码错误")

    # 预热三个业务系统, 失败不致命.
    # 注意 classroom 预热必须跟随完整 OAuth 跳转链才能拿到 _token/JWTUser,
    # 且 tgmedia 偶发 SSL EOF, 这里单独重试.
    for method, url in [
        ("GET", "https://courses.zju.edu.cn/user/courses"),
        ("GET", CLASSROOM_WARMUP_URL),
        (
            "POST",
            "https://zjuam.zju.edu.cn/cas/login?service=https://zdbk.zju.edu.cn/jwglxt/xtgl/login_ssologin.html",
        ),
    ]:
        if url == CLASSROOM_WARMUP_URL:
            warmup_classroom(s, verbose=False)
            continue
        try:
            s.request(method, url, timeout=20)
        except Exception:
            pass
    return s


def warmup_classroom(s: requests.Session, retries: int = 4, verbose: bool = True) -> bool:
    """走完 tgmedia OAuth 跳转链, 拿到 _token/JWTUser 等 classroom 相关 cookie.

    逐跳手动跟进(allow_redirects=False): 每跳独立超时, 失败快速重试,
    避免整链一个 s.get() 被 tgmedia 半死连接拖住 (timeout 是读超时而非总时限).
    返回是否拿到 _token, 从不抛异常.
    """
    for attempt in range(1, retries + 1):
        ok, hops, err = _walk_classroom_chain(s, verbose=verbose)
        if ok:
            return True
        if verbose:
            print(f"  预热第 {attempt}/{retries} 次失败: {err}, 重试...", file=sys.stderr)
    return any(c.name == "_token" for c in s.cookies)


def _walk_classroom_chain(s: requests.Session, verbose: bool = True,
                          per_hop_timeout: int = 12, max_hops: int = 12):
    """手动逐跳走完 OAuth 链. 返回 (是否拿到_token, 跳数, 错误信息)."""
    def log(msg: str):
        if verbose:
            print(msg, file=sys.stderr, flush=True)

    url = CLASSROOM_WARMUP_URL
    deadline = time.monotonic() + 90
    for hop in range(max_hops):
        if time.monotonic() > deadline:
            return False, hop, "总耗时超 90s"
        try:
            r = s.get(url, timeout=per_hop_timeout, allow_redirects=False)
        except requests.RequestException as e:
            return False, hop, f"{type(e).__name__}: {e}".splitlines()[0][:160]
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            nxt = urljoin(url, r.headers["Location"])
            host = nxt.split("/")[2] if "/" in nxt.split("://", 1)[-1] else nxt
            log(f"  [预热 {hop + 1}] {r.status_code} {host} ...")
            url = nxt
            continue
        # 终点
        if any(c.name == "_token" for c in s.cookies):
            log(f"  [预热 {hop + 1}] 完成, 已拿到 _token")
            return True, hop + 1, ""
        return False, hop + 1, f"终点 HTTP {r.status_code} 但无 _token"
    return False, max_hops, "跳转超 12 跳"


def classroom_token(session: requests.Session) -> str:
    """从 _token cookie 中解析 JWT.

    注意: _token 的 domain 是 .zju.edu.cn (顶级域共享), 值形如
    <sig>:2:<urlencoded php-serialize({i:0;s:6:"_token";i:1;s:N:"<JWT>";})>.
    requests 按请求 URL 自动附带该 cookie, 因此无需按 domain 过滤.
    """
    hit = None
    for c in session.cookies:
        if c.name == "_token":
            hit = c
            break
    if hit is None:
        raise LoginError("智云 classroom token 缺失, 请重新 login")
    m = re.search(r'\{i:\d+;s:\d+:"_token";i:\d+;s:\d+:"(.+?)";\}', unquote(hit.value))
    if not m:
        raise LoginError("智云 classroom token 格式异常, 请重新 login")
    return m.group(1)
