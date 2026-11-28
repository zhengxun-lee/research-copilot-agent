"""Local model profiles. Secrets are masked in public views; explicit local reveal is separate."""

from copy import deepcopy
import ipaddress
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import urlparse

import yaml

ROLES = ("default", "simple", "complex", "embedding")


def resolved_api_key(env_name, fallback=""):
    mode = os.environ.get(env_name + "_MODE", "legacy")
    if mode == "clear":
        return ""
    if mode == "inherit":
        return fallback
    return os.environ.get(env_name, "").strip() or fallback


def masked_key(value):
    """Replace every key character with one asterisk, without exposing a prefix."""
    if not value:
        return ""
    return "*" * len(value)


def valid_url(value, optional=False):
    if optional and not value:
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("API 地址无效")
    try:
        parsed = urlparse(value)
        _ = parsed.port  # Validate the optional port without retaining an unused value.
    except ValueError:
        raise ValueError("API 地址无效") from None
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API 地址须为不含凭据、查询参数的 HTTP(S) 地址")
    if parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname == "localhost"
        if not local:
            raise ValueError("非本机 API 地址必须使用 HTTPS")
    return value.rstrip("/")


class ModelSettings:
    def __init__(self, path, profiles=None, enabled=None):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.token = ""
        self.expires = 0
        self.revision = 0
        if profiles is None:
            import api_config as c
            from config import MODEL_ROUTER_ENABLED

            names = (
                ("default", c.MODEL_NAME, c.OPENAI_BASE_URL, c.OPENAI_API_KEY),
                (
                    "simple",
                    c.SIMPLE_MODEL_NAME,
                    c.SIMPLE_MODEL_BASE_URL,
                    c.SIMPLE_MODEL_API_KEY,
                ),
                (
                    "complex",
                    c.COMPLEX_MODEL_NAME,
                    c.COMPLEX_MODEL_BASE_URL,
                    c.COMPLEX_MODEL_API_KEY,
                ),
                (
                    "embedding",
                    c.EMBEDDING_MODEL_NAME,
                    c.EMBEDDING_BASE_URL,
                    c.EMBEDDING_API_KEY,
                ),
            )
            profiles = {
                role: dict(
                    model_name=model,
                    base_url=url,
                    api_key=key,
                    key_mode="set" if key else "clear",
                )
                for role, model, url, key in names
            }
            for role in ("simple", "complex"):
                if profiles[role]["api_key"] == c.OPENAI_API_KEY:
                    profiles[role]["key_mode"] = "inherit"
            for role, env_name in [
                ("default", "OPENAI_API_KEY_MODE"),
                ("simple", "SIMPLE_MODEL_API_KEY_MODE"),
                ("complex", "COMPLEX_MODEL_API_KEY_MODE"),
                ("embedding", "EMBEDDING_API_KEY_MODE"),
            ]:
                if os.environ.get(env_name) in ("set", "clear", "inherit"):
                    profiles[role]["key_mode"] = os.environ[env_name]
            enabled = MODEL_ROUTER_ENABLED if enabled is None else enabled
        self.profiles = deepcopy(profiles)
        self.enabled = True if enabled is None else enabled

    def snapshot(self):
        with self.lock:
            records = deepcopy(self.profiles)
            default = (
                records["default"]["api_key"]
                if records["default"]["key_mode"] == "set"
                else ""
            )
            for role, p in records.items():
                p["api_key"] = (
                    default
                    if p["key_mode"] == "inherit"
                    else (p["api_key"] if p["key_mode"] == "set" else "")
                )
                if role in ("simple", "complex") and not p["base_url"]:
                    p["base_url"] = records["default"]["base_url"]
            return records, self.enabled

    def public(self):
        with self.lock:
            records, enabled = self.snapshot()
            return {
                "profiles": {
                    role: {
                        "model_name": p["model_name"],
                        "base_url": valid_url(p["base_url"]),
                        "key_configured": bool(p["api_key"]),
                        "key_preview": masked_key(p["api_key"]),
                        "key_mode": p["key_mode"],
                    }
                    for role, p in records.items()
                },
                "router_enabled": enabled,
                "revision": self.revision,
                "can_edit": os.name == "posix",
                "storage": "local_file_permissions_0600",
                "embedding_requires_restart": True,
            }

    def unlock(self):
        if os.name != "posix":
            raise PermissionError("当前系统未实现配置文件 ACL 管理，请使用本地配置文件")
        with self.lock:
            self.token = secrets.token_urlsafe(32)
            self.expires = time.monotonic() + 600
            return {"edit_token": self.token, "expires_in": 600}

    def _check_token(self, token):
        if (
            not self.token
            or not isinstance(token, str)
            or not secrets.compare_digest(token, self.token)
            or time.monotonic() > self.expires
        ):
            raise PermissionError("操作会话已失效，请重试")

    def reveal(self, payload, token):
        """Explicit same-origin, loopback-only reveal; never used by public()."""
        with self.lock:
            self._check_token(token)
            if not isinstance(payload, dict) or set(payload) != {"role", "revision"}:
                raise ValueError("密钥请求无效")
            role = payload.get("role")
            if not isinstance(role, str) or role not in ROLES:
                raise ValueError("模型档位无效")
            if payload.get("revision") != self.revision:
                raise ValueError("配置已变更，请刷新后重试")
            records, _ = self.snapshot()
            self.token = ""
            return {"api_key": records[role]["api_key"]}

    def save(self, payload, token):
        with self.lock:
            self._check_token(token)
            if not isinstance(payload, dict) or set(payload) - {
                "profiles",
                "router_enabled",
                "revision",
            }:
                raise ValueError("模型配置字段无效")
            if payload.get("revision") != self.revision:
                raise ValueError("配置已变更，请刷新后重新编辑")
            if not isinstance(payload.get("router_enabled"), bool):
                raise ValueError("路由开关必须为布尔值")
            changes = payload.get("profiles")
            if not isinstance(changes, dict) or set(changes) != set(ROLES):
                raise ValueError("请提交完整模型配置")
            new = deepcopy(self.profiles)
            for role, change in changes.items():
                if not isinstance(change, dict) or set(change) - {
                    "model_name",
                    "base_url",
                    "key_action",
                    "api_key",
                }:
                    raise ValueError("模型配置字段无效")
                model = change.get("model_name")
                if (
                    not isinstance(model, str)
                    or not model.strip()
                    or len(model) > 200
                    or any(ord(c) < 32 for c in model)
                ):
                    raise ValueError("模型名称无效")
                new[role]["model_name"] = model.strip()
                new[role]["base_url"] = valid_url(
                    change.get("base_url"), optional=False
                )
                action = change.get("key_action", "keep")
                if action == "set":
                    key = change.get("api_key")
                    if (
                        not isinstance(key, str)
                        or not 1 <= len(key) <= 4096
                        or not key.isascii()
                        or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key)
                    ):
                        raise ValueError(
                            "API Key 须为有效 ASCII 字符，不可包含空白或中文引号"
                        )
                    new[role].update(api_key=key, key_mode="set")
                elif action in ("clear", "inherit"):
                    if action == "inherit" and role not in ("simple", "complex"):
                        raise ValueError("此配置不支持继承默认 Key")
                    new[role].update(api_key="", key_mode=action)
                elif action != "keep":
                    raise ValueError("Key 操作无效")
            if self.path.is_symlink():
                raise ValueError("拒绝写入符号链接配置文件")
            data = yaml.safe_load(self.path.read_text()) if self.path.exists() else {}
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError("本地配置文件格式无效")
            api = data.setdefault("api", {})
            for role, profile in new.items():
                target = api if role == "default" else api.setdefault(role, {})
                target.update(
                    model_name=profile["model_name"],
                    base_url=profile["base_url"],
                    api_key=profile["api_key"],
                    api_key_mode=profile["key_mode"],
                )
            data.setdefault("agent", {})["model_router_enabled"] = payload[
                "router_enabled"
            ]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".model-settings-", dir=self.path.parent)
            try:
                os.chmod(name, 0o600)
                with os.fdopen(fd, "w") as file:
                    yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            self.profiles = new
            self.enabled = payload["router_enabled"]
            self.revision += 1
            self.token = ""
            self.expires = 0
            return self.public()

    def apply(self, agent):
        profiles, enabled = self.snapshot()
        router = agent.model_router
        router.enabled = enabled
        for role in ("default", "simple", "complex"):
            p = profiles[role]
            setattr(router, role + "_model", p["model_name"])
            setattr(router, role + "_api_key", p["api_key"])
            setattr(router, role + "_base_url", p["base_url"])
            agent.trace.redact.add(p["api_key"])
        default = profiles["default"]
        agent.llm.api_key = default["api_key"]
        agent.llm.base_url = default["base_url"]
        agent.llm.model_name = default["model_name"]
