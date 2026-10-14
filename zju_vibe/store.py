"""本地会话 / 配置存取. 只存 cookies, 不存明文密码."""
from __future__ import annotations

import json
import pickle
from pathlib import Path


def base_dir() -> Path:
    p = Path.home() / ".zju-vibe"
    p.mkdir(parents=True, exist_ok=True)
    return p


def session_path() -> Path:
    return base_dir() / "session.pkl"


def config_path() -> Path:
    return base_dir() / "config.json"


def save_session(username: str, password: str, jar) -> None:
    cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
        }
        for c in jar
    ]
    with open(session_path(), "wb") as f:
        pickle.dump({"username": username, "cookies": cookies}, f)
    # 密码只尝试写入系统 keyring, 失败则忽略(下次手动输入)
    try:
        import keyring  # type: ignore

        keyring.set_password("zju-vibe", username, password)
    except Exception:
        pass


def load_session():
    """返回 (username, cookies_list) 或 (None, None)."""
    p = session_path()
    if not p.exists():
        return None, None
    try:
        with open(p, "rb") as f:
            data = pickle.load(f)
        return data.get("username"), data.get("cookies", [])
    except Exception:
        return None, None


def saved_password(username: str) -> str | None:
    try:
        import keyring  # type: ignore

        return keyring.get_password("zju-vibe", username)
    except Exception:
        return None


def clear_session() -> None:
    try:
        session_path().unlink()
    except FileNotFoundError:
        pass


def load_config() -> dict:
    p = config_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def default_save_dir() -> str:
    cfg = load_config()
    if cfg.get("save_dir"):
        return cfg["save_dir"]
    return str(Path.home() / "Downloads" / "zju-vibe")
