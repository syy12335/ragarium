# ragarium/utils/yaml_reader.py

import os
import shutil
import yaml
from pathlib import Path
from typing import Any, Optional


def ensure_yaml_config_file(path: Path) -> Path:
    """
    Ensure a runtime YAML config exists.

    Runtime files such as config/application.yaml are intentionally ignored by
    Git. When a fresh checkout only has config/application.yaml.example, copy
    that template on first read and leave existing user files untouched.
    """
    if path.exists():
        return path

    template = Path(f"{path}.example")
    if template.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, path)
    return path


class YamlConfigReader:
    """
    通用 YAML 配置读取器。

    路径解析顺序：
      1. 如果 yaml_path 是绝对路径：直接使用该路径
      2. 否则，如果存在环境变量 APP_CONFIG_PATH：
         - 如果指向目录：目录 + yaml_path
         - 如果指向文件：直接使用该文件
      3. 否则，从当前文件向上逐级拼接 yaml_path，找到第一个存在的文件

    约定：
      application.yaml 通常位于 project-root/config/application.yaml
    """

    def __init__(self, yaml_path: str, env_var: str = "APP_CONFIG_PATH"):
        """
        参数
        yaml_path: 配置文件路径，可以是绝对路径或相对于项目根的路径，
                   例如 "config/application.yaml"
        env_var:  可选环境变量名称，用于显式指定配置路径或根目录
        """
        self.config_path = self._resolve_config_path(yaml_path, env_var)
        self.config = self._load_yaml()

    @staticmethod
    def _resolve_config_path(yaml_path: str, env_var: str) -> Path:
        path_obj = Path(yaml_path)

        # 1. 绝对路径优先
        if path_obj.is_absolute():
            path_obj = ensure_yaml_config_file(path_obj)
            if path_obj.exists():
                return path_obj
            raise FileNotFoundError(f"配置文件不存在：{path_obj}")

        # 2. 环境变量（优先用于部署环境锁定路径）
        env_value = os.environ.get(env_var)
        if env_value:
            env_path = Path(env_value)
            # 情况 A：指向目录
            if env_path.is_dir():
                candidate = env_path / yaml_path
            else:
                # 情况 B：指向具体文件（例如 /etc/my_app/application.yaml）
                candidate = env_path

            candidate = ensure_yaml_config_file(candidate)
            if candidate.exists():
                return candidate
            raise FileNotFoundError(
                f"通过环境变量 {env_var}={env_value} 未找到配置文件：{candidate}"
            )

        # 3. 从当前文件向上逐级搜索 yaml_path
        current = Path(__file__).resolve()
        for parent in [current] + list(current.parents):
            candidate = parent / yaml_path
            candidate = ensure_yaml_config_file(candidate)
            if candidate.exists():
                return candidate

        raise FileNotFoundError(
            f"未能定位配置文件：{yaml_path}。"
            f"已尝试：绝对路径、环境变量 {env_var}、从 {__file__} 向上逐级搜索。"
        )

    def _load_yaml(self) -> dict:
        with self.config_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
            return data if data is not None else {}

    def get(self, key_path: str, default: Optional[Any] = None) -> Any:
        """
        通过点号路径读取配置项，例如：
          get("dataset.raw_path")
        """
        keys = key_path.split(".")
        value: Any = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
