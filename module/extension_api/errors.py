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


class InvalidRequestError(ValueError):
    """REST 请求体不符合稳定契约。"""


class ConfigValidationError(ValueError):
    """配置路径不可写或配置值未通过上游规则。"""

    def __init__(self, path: str, message: str = "配置值无效") -> None:
        self.path = path
        super().__init__(f"{message}: {path}")


class ConfigRevisionConflictError(RuntimeError):
    """客户端基于过期配置提交写入。"""


class TaskNotFoundError(LookupError):
    """请求的调度任务不属于该实例。"""

    def __init__(self, task: str) -> None:
        self.task = task
        super().__init__(f"任务不存在: {task}")


class TaskDisabledError(RuntimeError):
    """停用任务不能被加入立即运行队列。"""

    def __init__(self, task: str) -> None:
        self.task = task
        super().__init__(f"任务已停用: {task}")


class InstanceOperationError(RuntimeError):
    """实例启动或停止没有达到预期状态。"""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__("实例操作失败")


class DataWriteError(RuntimeError):
    """上游数据写入失败，对外只保留安全描述。"""

    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__("实例数据写入失败")
