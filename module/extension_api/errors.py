"""API 扩展服务层异常。"""


class InstanceNotFoundError(LookupError):
    """请求的 AzurPilot 实例不存在。"""

    def __init__(self, instance: str) -> None:
        self.instance = instance
        super().__init__(f"AzurPilot 实例不存在: {instance}")


class InvalidLanguageError(ValueError):
    """请求的配置语言不受支持。"""

    def __init__(self, language: str) -> None:
        self.language = language
        super().__init__("不支持的配置语言")


class InvalidQueryError(ValueError):
    """REST 查询参数不符合稳定契约。"""

    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        super().__init__(f"查询参数无效: {parameter}")


class DataReadError(RuntimeError):
    """上游数据读取失败，对外只保留安全描述。"""

    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__("实例数据读取失败")
