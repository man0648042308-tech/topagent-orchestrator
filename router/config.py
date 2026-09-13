"""
配置加载 — 钥匙管理员
====================
总机比喻里, 这里是"钥匙管理员":
  · 读 config.yaml (电话簿: 各平台地址/超时/路由矩阵)
  · 找 API Key (钥匙): 环境变量 → Windows DPAPI 本地密钥库

依赖: PyYAML (唯一第三方依赖)。若未安装, 会提示 pip install pyyaml。
"""
import sys
from pathlib import Path

# 路径常量:
#   BASE_DIR  = router/ 目录 (config.yaml 所在)
#   ROOT_DIR  = 项目根目录 (topagent/ 与 runtime/ 所在)
BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent
CONFIG_FILE = BASE_DIR / "config.yaml"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from topagent.secrets.vault import SecretResolver

# PyYAML 可选导入: 没装也能导入本模块, 只在真正加载配置时报错
try:
    import yaml
except ImportError:
    yaml = None


def _load_config() -> dict:
    """读取 config.yaml (路由矩阵 + 平台定义)"""
    if yaml is None:
        raise RuntimeError("缺少 PyYAML, 请先执行: pip install pyyaml")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# 启动即加载一次, 全局可直接用 (改动 config.yaml 需重启进程)
CONFIG = _load_config()
PLATFORMS: dict = CONFIG["platforms"]      # 平台定义: 地址/密钥环境变量/超时/类型
ROUTING: dict = CONFIG["routing"]          # 路由矩阵: 任务类型 → 首选 + 故障链
DEFAULT_TASK_TYPE: str = CONFIG.get("default_task_type", "general")


def get_api_key(env_name: str) -> str | None:
    """获取某平台的 API Key

    查找顺序:
      1. 环境变量 (如 DASHSCOPE_API_KEY) — 优先
      2. runtime/secrets.enc — Windows 当前用户 DPAPI 解密
    返回 None 表示没找到 Key。
    """
    return SecretResolver().get(env_name)


def key_status() -> dict:
    """返回各平台 Key 是否就绪 (供 --test 诊断)"""
    return {
        name: bool(get_api_key(pf["api_key_env"]))
        for name, pf in PLATFORMS.items()
    }
