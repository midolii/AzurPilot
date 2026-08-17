"""API 扩展服务层异常。"""


class InstanceNotFoundError(LookupError):
    """请求的 AzurPilot 实例不存在。"""

    def __init__(self, instance: str) -> None:
        self.instance = instance
        super().__init__(f"AzurPilot 实例不存在: {instance}")
