"""本地秘钥：机器码绑定 + 公钥验签，无需远程服务器。"""

from omni_bot_sdk.licensing.machine import get_machine_code
from omni_bot_sdk.licensing.verify import LicenseError, verify_license

__all__ = [
    "get_machine_code",
    "verify_license",
    "LicenseError",
]
