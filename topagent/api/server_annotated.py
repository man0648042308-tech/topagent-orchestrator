# ============================================================================
# server.py —— TopAgent 控制中心 HTTP 服务器（带超详细逐词讲解注释版）
# ============================================================================
# 本文件是"讲解注释版"：在原始代码每一行后/上方加入中文注释，
# 帮助初学者理解每个单词、符号、语句的作用。
# 注意：本文件与原 server.py 功能完全一致，只是多了注释，可直接运行。
# 运行方式：python server_annotated.py
# ============================================================================

from __future__ import annotations
# from          -> 关键字，表示"从某个模块里导入"
# __future__    -> Python 内置的特殊模块名，代表"未来的语言特性"。
#                  放在 import 之后，可以提前启用新版本 Python 才有的语法。
# import        -> 关键字，表示"导入"
# annotations   -> 特性名称，启用"类型注解延迟求值"：
#                  让所有类型注解（如 list[str]）以字符串形式保存、不被立即执行，
#                  从而避免"循环导入"或"注解在运行时求值"带来的错误。
# 整行作用：兼容不同 Python 版本，让类型注解写法更安全。
# 上面是可直接运行的真实语句，下面继续逐项解释。

import json
# import    -> 关键字，表示"导入"
# json      -> Python 标准库模块（JavaScript Object Notation，JSON 数据格式）。
#              提供 dumps()（把字典转成字符串）、loads()（把字符串解析成字典）。
# 整行作用：导入 JSON 模块，后面用它解析请求体、生成响应数据。

import mimetypes
# import     -> 关键字，导入
# mimetypes  -> 标准库模块，用于"根据文件扩展名猜测 MIME 类型"。
#              MIME 类型是浏览器识别文件种类的标记，例如：
#              .html  -> text/html，.png -> image/png。
# 整行作用：为静态文件（HTML/JS/CSS）自动生成正确的 Content-Type 响应头。

import time
# import -> 关键字，导入
# time   -> 标准库模块，提供时间相关函数。
#           本文件用到 time.monotonic()（单调时钟）和 time.sleep()（睡眠）。
# 整行作用：用于 SSE 事件流的"截止时间判断"和"每秒轮询间隔"。

from http import HTTPStatus
# from       -> 关键字，"从某模块中"
# http       -> Python 标准库的 HTTP 相关包
# import     -> 关键字，导入
# HTTPStatus -> http 包里的枚举类，预定义 HTTP 状态码：
#               HTTPStatus.OK=200（成功）、NOT_FOUND=404（找不到）、
#               CREATED=201（已创建）、BAD_REQUEST=400（请求错误）、
#               INTERNAL_SERVER_ERROR=500（服务器内部错误）。
# 整行作用：用语义化名称代替魔法数字，提高代码可读性。

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# from                  -> 关键字，"从某模块中"
# http.server           -> 标准库模块，Python 自带的简易 HTTP 服务器
# import                -> 关键字，导入
# BaseHTTPRequestHandler-> 基础"HTTP 请求处理器"类：
#                          它规定了收到 GET/POST 请求后调用 do_GET/do_POST 方法。
# ThreadingHTTPServer  -> 多线程 HTTP 服务器类：
#                          每个请求在独立线程中处理，可同时服务多个客户端。
# 整行作用：导入这两个核心类，本文件的 HTTP 处理类与服务器创建都基于它们。

from pathlib import Path
# from     -> 关键字，"从某模块中"
# pathlib  -> 标准库模块，面向对象的路径操作
# import   -> 关键字，导入
# Path     -> 表示"文件系统路径"的类，提供 / 拼接、resolve() 等方法。
# 整行作用：用 Path 安全地拼接、解析静态资源目录路径。

from typing import Any
# from    -> 关键字，"从某模块中"
# typing  -> 标准库模块，专门提供"类型注解"工具
# import  -> 关键字，导入
# Any     -> 特殊类型标注，表示"可以是任何类型"（不限制）。
# 整行作用：函数返回值类型不确定时用 Any 标注，兼顾灵活性与可读性。

from urllib.parse import parse_qs, urlparse
# from           -> 关键字，"从某模块中"
# urllib.parse   -> 标准库模块，负责 URL（网址）的解析处理
# import         -> 关键字，导入
# parse_qs       -> 函数：把查询字符串（?a=1&b=2）解析成字典 {'a': ['1'], 'b': ['2']}
# urlparse       -> 函数：把完整 URL 拆成 scheme、netloc、path、query 等部分
# 整行作用：解析 HTTP 请求的路径与查询参数，供路由分发使用。

from topagent import __version__
# from         -> 关键字，"从某模块中"
# topagent     -> 本项目的顶层包名
# import       -> 关键字，导入
# __version__  -> 包内定义的版本号字符串（双下划线开头表示"特殊变量"）。
# 整行作用：健康检查接口里返回当前版本号。

from topagent.bus.store import MessageBus
# from               -> 关键字，"从某模块中"
# topagent.bus.store -> 本项目"消息总线"模块的路径（topagent 包 -> bus 包 -> store 模块）
# import             -> 关键字，导入
# MessageBus         -> 消息总线类：管理代理之间传递的消息，如查询、列表、重新入队过期消息。
# 整行作用：导入消息总线，用于查询消息集合与状态统计。

from topagent.core.database import Database, db, load_json
# from                -> 关键字，"从某模块中"
# topagent.core.database -> 本项目"核心数据库"模块
# import              -> 关键字，导入
# Database            -> 数据库类：封装 SQL 查询（one 取一行、all 取多行、initialize 初始化）
# db                  -> 模块级"全局数据库实例"（单例），默认使用它操作 SQLite
# load_json           -> 函数：把数据库里存成 JSON 字符串的字段解析回 Python 对象
# 整行作用：导入数据库相关能力，ControlCenter 用它执行所有 SQL。

from topagent.core.models import ExecutionConstraints, ExecutionRequest
# from                 -> 关键字，"从某模块中"
# topagent.core.models -> 本项目"数据模型"模块
# import               -> 关键字，导入
# ExecutionConstraints -> 执行约束数据模型：超时秒数、最大轮数、是否允许付费调用、元数据
# ExecutionRequest     -> 执行请求数据模型：哪个代理、什么任务、属于哪个 run、约束条件
# 整行作用：POST /api/dispatch 时构造这两个模型对象传给调度器。

from topagent.memory.store import MemoryStore
# from                -> 关键字，"从某模块中"
# topagent.memory.store -> 本项目"记忆存储"模块
# import              -> 关键字，导入
# MemoryStore         -> 记忆存储类：候选记忆入库、提升为正式记忆、归档记忆。
# 整行作用：为 /api/memory 相关接口提供数据能力。

from topagent.registry.builder import build_all
# from                 -> 关键字，"从某模块中"
# topagent.registry.builder -> 本项目"注册表构建"模块
# import               -> 关键字，导入
# build_all            -> 函数：扫描数据库里的代理/技能/能力，构建"注册表摘要"。
# 整行作用：启动时生成注册表摘要，供健康检查接口展示。

from topagent.runtime.dispatcher import Dispatcher
# from                    -> 关键字，"从某模块中"
# topagent.runtime.dispatcher -> 本项目"任务调度器"模块
# import                  -> 关键字，导入
# Dispatcher              -> 调度器类：把任务分派给合适的代理去执行/验证。
# 整行作用：支持 POST /api/dispatch 与 /api/verify 两个接口。

from topagent.runtime.orchestrator import RuntimeOrchestrator
# from                      -> 关键字，"从某模块中"
# topagent.runtime.orchestrator -> 本项目"运行时编排器"模块
# import                    -> 关键字，导入
# RuntimeOrchestrator       -> 编排器类：创建执行 run、按步骤推进 run 的执行。
# 整行作用：支持 POST /api/runs 与 /api/runs/{id}/steps 两个接口。


# ----------------------------------------------------------------------------
# 常量区
# ----------------------------------------------------------------------------
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
# DASHBOARD_DIR -> 常量（全大写），表示"前端仪表盘静态文件所在目录"。
# =             -> 赋值运算符：把右侧的结果保存到左侧变量中。
# Path(...)     -> 调用 Path 类的构造函数，把参数包成一个路径对象。
# __file__      -> 特殊变量：当前这个 .py 文件所在的完整路径字符串。
# .resolve()    -> 方法：把相对路径解析为"绝对路径"（去掉 .. 和 .）。
# .parent       -> 属性：当前路径的"上级目录"（本文件在 .../api/ 下，parent 就是 .../）。
# .parent       -> 再取一次上级目录（从 api/ 再往上一级，得到项目根目录）。
# /             -> pathlib 特有的"路径拼接运算符"，把左右两段路径拼成一个新路径。
# "dashboard"   -> 字符串字面量，目标子目录的名字。
# 整行作用：算出项目根目录下的 dashboard 文件夹路径，用于托管前端静态资源。


# ----------------------------------------------------------------------------
# 工具函数：解码数据库行里的 JSON 字段
# ----------------------------------------------------------------------------
def _decode_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # def                    -> 关键字，定义函数
    # _decode_rows           -> 函数名。下划线开头表示"模块内部私有函数"；
    #                          decode=解码，rows=行。整体含义：解码多行数据。
    # (rows: list[dict[str, Any]])
    #   rows                 -> 参数名，接收要处理的数据行列表
    #   : list[dict[str, Any]] -> 类型注解：rows 是"列表"，每个元素是"字典"，键是 str，值是任意类型
    # -> list[dict[str, Any]] -> 返回值类型注解：处理后仍返回同样结构的列表
    # :                       -> 冒号：函数体即将开始
    for row in rows:
        # for          -> 关键字，循环遍历
        # row          -> 循环变量：每次取出列表里的"一行"（一个字典）
        # in           -> 关键字，"在...之中"
        # rows         -> 要遍历的列表
        # :            -> 冒号：循环体开始（以下缩进部分每轮都执行）
        for key in list(row):
            # for     -> 关键字，循环遍历
            # key     -> 循环变量：当前正在处理的"键名"
            # in      -> 关键字，"在...之中"
            # list(row) -> 把字典 row 的键转换成列表。
            #            为什么要 list()：循环中会 pop 键，为避免"遍历时改字典"报错，
            #            先复制一份键列表再遍历。
            # :       -> 冒号：内层循环体开始
            if key.endswith("_json"):
                # if            -> 关键字：条件判断
                # key           -> 当前键名（字符串）
                # .endswith("_json") -> 字符串方法：判断这个键名是否以 "_json" 结尾。
                #                     约定：数据库里 JSON 字段的列名带 _json 后缀。
                # :              -> 冒号：条件成立时执行下面的缩进代码
                row[key[:-5]] = load_json(row.pop(key), None)
                # row                -> 当前这一行（字典）
                # [key[:-5]]         -> 用"切片"取键名去掉后缀的部分。
                #                     例：key="payload_json"，key[:-5] 去掉最后5个字符"json"前缀
                #                     实际上是去掉 "_json" 这5个字符，得到 "payload"。
                # =                  -> 赋值：把解析结果写回该行，用新的键名。
                # load_json(...)     -> 函数调用：把字符串形式的 JSON 解析成 Python 对象。
                # row.pop(key)       -> 字典方法 pop：取出并"删除"原键对应的值。
                #                     先把值取出来，原键就被移除，避免留下重复列。
                # , None             -> load_json 的第二个参数：解析失败时返回的默认值 None。
        # 内层 for 结束后，外层的下一轮继续处理下一行
    return rows
    # return -> 关键字：函数结束，把结果返回给调用者
    # rows   -> 被原地修改过的数据行列表（原始对象被改了，但仍是同一个列表对象）
# 整行作用（整个函数）：把所有键名以 _json 结尾的字段，解析成真正的 Python 对象，
# 并把键名去掉后缀（如 payload_json -> payload）。


# ----------------------------------------------------------------------------
# 核心业务类：ControlCenter（控制中心）
# ----------------------------------------------------------------------------
class ControlCenter:
    # class          -> 关键字：定义一个类
    # ControlCenter  -> 类名（帕斯卡命名法：每个单词首字母大写）。
    #                  含义：控制中心——集中管理查询、统计、分发等全部业务逻辑。
    # :               -> 冒号：类体开始
    def __init__(self, database: Database | None = None):
        # def       -> 关键字：定义方法
        # __init__  -> 特殊方法名："构造函数"。用类创建对象时自动被调用，用来初始化对象。
        # self      -> 参数：指向"当前正在创建的实例对象"本身。
        #             Python 规定实例方法的第一个参数必须是 self。
        # database  -> 参数：可选的外部数据库对象。
        # : Database | None -> 类型注解：database 可以是 Database 类型，或者是 None。
        #                     | 表示"或者"（Python 3.10+ 的联合类型写法）。
        # = None    -> 默认值：如果不传这个参数，它就是 None。
        # :         -> 冒号：方法体开始
        self.db = database or db
        # self.db   -> 在实例上创建属性 db（self 指向实例，句点表示"的"）
        # =         -> 赋值
        # database or db -> 逻辑或表达式：
        #                如果 database 不是空值（传入了数据库）就用它；
        #                否则（None）用模块级全局数据库实例 db。
        # 作用：默认使用全局数据库，也允许外部注入测试数据库。
        self.db.initialize()
        # self.db     -> 数据库实例
        # .initialize() -> 调用初始化方法：建表、准备数据等（幂等，可重复调用）。
        # 作用：确保数据库结构就绪。
        self.registry_summary = build_all(self.db)
        # self.registry_summary -> 实例属性：注册表摘要
        # =                      -> 赋值
        # build_all(self.db)     -> 调用函数，扫描数据库生成代理/技能/能力摘要。
        # 作用：启动时构建一次，供 health 接口返回。
        self.bus = MessageBus(self.db)
        # self.bus -> 实例属性：消息总线
        # =        -> 赋值
        # MessageBus(self.db) -> 用数据库构造消息总线对象。
        self.memory = MemoryStore(self.db)
        # self.memory -> 实例属性：记忆存储
        # =           -> 赋值
        # MemoryStore(self.db) -> 用数据库构造记忆存储对象。
        self.dispatcher = Dispatcher(database=self.db)
        # self.dispatcher -> 实例属性：任务调度器
        # =               -> 赋值
        # Dispatcher(database=self.db) -> 构造调度器，用"关键字参数"传入数据库。
        #                                 命名参数让调用含义更清晰。
        self.orchestrator = RuntimeOrchestrator(
            # self.orchestrator -> 实例属性：运行时编排器
            # =                 -> 赋值
            # RuntimeOrchestrator(  -> 构造编排器，参数跨行书写
            database=self.db, dispatcher=self.dispatcher
            # database=self.db       -> 关键字参数：给它数据库实例
            # , dispatcher=...       -> 逗号分隔第二个参数：给它调度器实例
            # )                      -> 右括号：结束函数调用
        )

    def health(self) -> dict[str, Any]:
        # def     -> 关键字：定义方法
        # health  -> 方法名：健康检查，返回系统当前状态。
        # self    -> 指向实例
        # -> dict[str, Any] -> 返回值类型注解：返回"字典"，键是 str，值是任意类型。
        dead = self.db.one(
            # dead   -> 局部变量：统计出的"死信消息"数量
            # =      -> 赋值
            # self.db.one(  -> 调用数据库 one 方法：执行 SQL 并返回"第一行"（一个字典）
            "SELECT COUNT(*) AS count FROM messages WHERE status='dead_letter'"
            # 这是 SQL 查询语句：
            # SELECT COUNT(*) AS count -> 统计行数，并命名为 count 列
            # FROM messages            -> 从 messages 表查
            # WHERE status='dead_letter' -> 只统计状态为 dead_letter（死信）的行
        )["count"]
        # )       -> 结束 one 调用
        # ["count"] -> 从返回的行字典里取出 "count" 键对应的数值
        running = self.db.one(
            # running -> 局部变量：正在运行中的执行数量
            # self.db.one(...) -> 查询第一行
            "SELECT COUNT(*) AS count FROM executions WHERE status='running'"
            # 统计 executions 表里 status='running'（运行中）的行数
        )["count"]
        return {
            # return -> 关键字：返回一个字典给调用者
            # { ... } -> 字典字面量：键值对用冒号分隔、项之间用逗号分隔
            "ok": True,
            # "ok"  -> 键：是否正常
            # :     -> 分隔键和值
            # True  -> 布尔值：表示一切正常
            "version": __version__,
            # "version" -> 键：版本号
            # __version__ -> 从 topagent 包导入的版本常量
            "database": str(self.db.path),
            # "database" -> 键：数据库文件位置
            # str(...)   -> 把 Path 对象转成字符串
            # self.db.path -> 数据库实例的 path 属性（SQLite 文件路径）
            "registry": self.registry_summary,
            # "registry" -> 键：注册表摘要
            # self.registry_summary -> 构造对象时构建好的摘要
            "signals": {"dead_letters": dead, "running_executions": running},
            # "signals" -> 键：关键信号统计（嵌套字典）
            # {"dead_letters": dead, "running_executions": running}
            #            -> 死信数量 + 运行中数量
        }
        # 作用：GET /api/health 的响应内容。

    def metrics(self) -> dict[str, Any]:
        # def      -> 关键字：定义方法
        # metrics  -> 方法名：指标统计（执行、消息、记忆、代理等数量）。
        # -> dict[str, Any] -> 返回字典
        execution_rows = self.db.all(
            # execution_rows -> 局部变量：按状态分组的执行统计数据
            # =              -> 赋值
            # self.db.all(...) -> 调用数据库 all 方法：执行 SQL 并返回"所有行"（列表）
            "SELECT status, COUNT(*) AS count FROM executions GROUP BY status"
            # SQL：SELECT status, COUNT(*) ... GROUP BY status
            # -> 按 status 分组，统计每种状态各有多少条。
        )
        return {
            # 返回一个综合指标字典
            "executions": {row["status"]: row["count"] for row in execution_rows},
            # "executions" -> 键：执行分布
            # {row["status"]: row["count"] for row in execution_rows}
            #    -> 字典推导式：对每一行，用 status 作键、count 作值，
            #       生成形如 {'running': 3, 'completed': 10} 的字典。
            "messages": self.bus.stats(),
            # "messages" -> 键：消息统计
            # self.bus.stats() -> 调用消息总线的 stats() 方法得到统计字典
            "memory": {
                row["status"]: row["count"]
                for row in self.db.all(
                    "SELECT status, COUNT(*) AS count FROM memories GROUP BY status"
                )
                # 嵌套的字典推导式：从 memories 表按状态分组统计。
            },
            "agents": self.db.one("SELECT COUNT(*) AS count FROM agents")["count"],
            # "agents" -> 键：代理总数
            # self.db.one(...)["count"] -> 查询 agents 表总行数并取 count
            "skills": self.db.one("SELECT COUNT(*) AS count FROM skills")["count"],
            # "skills" -> 键：技能总数（同上思路）
            "capabilities": self.db.one("SELECT COUNT(*) AS count FROM capabilities")["count"],
            # "capabilities" -> 键：能力总数（同上思路）
        }
        # 作用：GET /api/metrics 的响应内容。

    def get_collection(self, name: str, query: dict[str, list[str]]) -> Any:
        # def            -> 关键字：定义方法
        # get_collection -> 方法名：获取一个"集合"（一系列记录）。
        # self           -> 指向实例
        # name           -> 参数：集合名称，如 "runs"、"agents"
        # query          -> 参数：URL 查询参数，字典的值是列表（parse_qs 的格式）
        # -> Any         -> 返回值类型不限
        limit = min(int(query.get("limit", [100])[0]), 500)
        # limit   -> 局部变量：本次查询要返回的最大行数
        # =       -> 赋值
        # query.get("limit", [100]) -> 从 query 里取 "limit" 参数；
        #                             如果不存在，返回默认值 [100]（parse_qs 的格式是列表）
        # [0]     -> 取列表的第一个元素（parse_qs 会把 limit=50 变成 ["50"]）
        # int(...) -> 把字符串 "50" 转成整数 50
        # min(..., 500) -> 取两者较小值，防止客户端要求太大，上限封顶 500。
        if name == "health":
            # if        -> 条件判断
            # name == "health" -> 判断集合名是否为 health（== 是比较运算符，返回布尔值）
            # :         -> 冒号：条件成立执行下面
            return self.health()
            # return          -> 直接返回
            # self.health()   -> 调用本类的 health() 方法
        if name == "metrics":
            # 集合名是 metrics 时：
            return self.metrics()
            # 调用 metrics() 方法并返回
        if name == "runs":
            # 集合名是 runs（执行运行记录）时：
            return _decode_rows(self.db.all(
                # _decode_rows(...) -> 先查数据，再调用解码函数解析 _json 字段
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
                # SELECT *      -> 查询所有列
                # FROM runs     -> 从 runs 表
                # ORDER BY created_at DESC -> 按创建时间倒序（最新在前）
                # LIMIT ?       -> 最多返回 ? 条；? 是占位符，防 SQL 注入
                # , (limit,)    -> 逗号：第二个参数是元组，把 limit 的值填进占位符
                #                 (limit,) 带尾逗号表示"单元素元组"，这是参数必须的格式
            ))
        if name == "executions":
            # 集合名是 executions（执行记录）时：
            return _decode_rows(self.db.all(
                "SELECT * FROM executions ORDER BY created_at DESC LIMIT ?", (limit,)
                # 从 executions 表查询，逻辑同上
            ))
        if name == "events":
            # 集合名是 events（执行事件）时：
            return _decode_rows(self.db.all(
                "SELECT * FROM execution_events ORDER BY occurred_at DESC LIMIT ?", (limit,)
                # 从 execution_events 表查询，按发生时间倒序
            ))
        if name == "messages":
            # 集合名是 messages（消息）时：
            return self.bus.list(
                # 调用消息总线的 list() 方法查询消息
                recipient_agent_id=query.get("recipient", [None])[0],
                # recipient_agent_id= -> 关键字参数：接收方代理 ID
                # query.get("recipient", [None])[0] -> 取 recipient 参数，默认 [None] 再取首个
                status=query.get("status", [None])[0], limit=limit,
                # status=   -> 关键字参数：按状态过滤（默认 None 表示不过滤）
                # limit=limit -> 关键字参数：行数上限
            )
        if name == "memory":
            # 集合名是 memory（记忆）时：
            return self.memory.list(status=query.get("status", [None])[0], limit=limit)
            # 调用记忆存储的 list() 方法，按状态过滤、限制条数
        if name == "agents":
            # 集合名是 agents（代理）时：
            return _decode_rows(self.db.all("SELECT * FROM agents ORDER BY agent_id"))
            # 查询全部代理，按 agent_id 排序（未限制条数）
        if name == "skills":
            # 集合名是 skills（技能）时：
            return _decode_rows(self.db.all("SELECT * FROM skills ORDER BY skill_id"))
            # 查询全部技能，按 skill_id 排序
        if name == "capabilities":
            # 集合名是 capabilities（能力）时：
            return _decode_rows(self.db.all(
                """SELECT c.*,
                   (SELECT COUNT(*) FROM capability_evidence e
                    WHERE e.capability_id=c.capability_id) AS evidence_count,
                   (SELECT MAX(recorded_at) FROM capability_evidence e
                    WHERE e.capability_id=c.capability_id) AS latest_evidence_at
                FROM capabilities c ORDER BY capability_id"""
                # 三引号字符串：SQL 可以跨多行书写
                # SELECT c.*            -> 取 capabilities 表的别名 c 的所有列
                # 第一个子查询：计算每条能力有多少条"能力证据"，命名为 evidence_count
                # 第二个子查询：取该能力最近一条证据的时间，命名为 latest_evidence_at
                # FROM capabilities c   -> 主表并起别名 c
                # ORDER BY capability_id -> 按能力 ID 排序
            ))
        if name == "audit":
            # 集合名是 audit（审计记录）时：
            return _decode_rows(self.db.all(
                "SELECT * FROM audit_records ORDER BY occurred_at DESC LIMIT ?", (limit,)
                # 查询审计记录，按发生时间倒序，限制条数
            ))
        if name == "presence":
            # 集合名是 presence（代理在线状态）时：
            return _decode_rows(self.db.all(
                "SELECT * FROM agent_presence ORDER BY last_heartbeat_at DESC"
                # 查询代理在线表，按最近心跳时间倒序
            ))
        raise KeyError(name)
        # raise        -> 关键字：主动抛出异常
        # KeyError(name) -> 抛出一个"键不存在"异常，内容是集合名。
        # 作用：集合名不匹配任何分支时，让上层 catch 到并返回 404。

    def get_item(self, collection: str, item_id: str) -> Any:
        # def         -> 关键字：定义方法
        # get_item    -> 方法名：获取"单个"记录。
        # collection  -> 参数：集合名
        # item_id     -> 参数：记录的主键值
        # -> Any      -> 返回值不限
        table_key = {
            # table_key -> 局部变量：字典，建立"集合名 -> (表名, 主键列名)"的映射
            "runs": ("runs", "run_id"),
            # "runs" -> 集合名；("runs", "run_id") -> 元组：表名、主键列名
            "executions": ("executions", "execution_id"),
            "messages": ("messages", "message_id"),
            "memory": ("memories", "memory_id"),
            # 注意：memory 集合对应的表名是 memories
        }.get(collection)
        # .get(collection) -> 从字典中查 collection；不存在则返回 None
        if not table_key:
            # not table_key -> 如果 table_key 是 None（集合名不被支持）
            raise KeyError(collection)
            # 抛出异常，由上层转换为 404
        table, key = table_key
        # table, key = table_key -> 元组解包：把元组拆成两个变量
        #                          table 是表名，key 是主键列名
        row = self.db.one(f"SELECT * FROM {table} WHERE {key}=?", (item_id,))
        # row     -> 查询结果行
        # f"..."  -> f-string：花括号里的表达式会被求值并插入字符串
        # {table} -> 插入表名；{key} -> 插入主键列名
        # WHERE {key}=? -> 条件：主键等于 ?（占位符）
        # (item_id,)    -> 参数元组：把 item_id 填进占位符
        if not row:
            # 如果没查到（row 为 None）
            raise KeyError(item_id)
            # 抛出异常，由上层转换为 404
        return _decode_rows([row])[0]
        # _decode_rows([row]) -> 把单行包成列表再解码（复用解码函数）
        # [0]                 -> 取解码后的第一项（还原成单行）

    def post(self, path: list[str], body: dict[str, Any]) -> Any:
        # def   -> 关键字：定义方法
        # post  -> 方法名：处理所有 POST 写操作。
        # path  -> 参数：URL 路径按 "/" 分割后的列表，如 ["runs", "abc", "steps", "1"]
        # body  -> 参数：请求体解析后的字典
        # -> Any -> 返回值不限
        if path == ["runs"]:
            # path == ["runs"] -> 判断路径是否正好是 /api/runs（创建 run）
            run_id = self.orchestrator.create_run(
                # run_id -> 保存创建好的 run 的 ID
                # self.orchestrator.create_run(...) -> 调用编排器的创建方法
                str(body["requirement"]), metadata=body.get("metadata")
                # str(body["requirement"]) -> 必填字段 requirement（需求描述），转成字符串
                # , metadata=body.get("metadata") -> 可选字段 metadata；body.get 取不到时是 None
            )
            return {"ok": True, "run_id": run_id}
            # 返回成功标志和新 run 的 ID
        if len(path) == 4 and path[0] == "runs" and path[2] == "steps":
            # len(path) == 4          -> 路径有 4 段，如 ["runs","<run_id>","steps","<step_id>"]
            # and path[0] == "runs"   -> 第一段是 runs（and：全部条件都要满足）
            # and path[2] == "steps"  -> 第三段是 steps
            # 作用：匹配"推进某个 run 的某个步骤"的请求。
            result = self.orchestrator.run_step(
                # result -> 保存执行结果对象
                path[1], path[3],
                # path[1] -> run_id；path[3] -> step_id（位置参数）
                allow_paid_calls=bool(body.get("allow_paid_calls", True)),
                # allow_paid_calls= -> 关键字参数：是否允许付费调用
                # bool(...) -> 转成布尔值；缺省时按质量优先策略允许付费/订阅额度调用
                shared_inputs=body.get("inputs"),
                # shared_inputs= -> 关键字参数：共享输入数据（可为 None）
            )
            return result.__dict__
            # result.__dict__ -> 把对象的所有属性转成字典返回（序列化技巧）
        if path == ["dispatch"]:
            # 路径是 /api/dispatch（分派任务）
            constraints = ExecutionConstraints(
                # constraints -> 构造"执行约束"对象
                timeout_seconds=int(body.get("timeout_seconds", 300)),
                # timeout_seconds= -> 超时秒数；int() 转整数；默认 300 秒
                max_turns=int(body.get("max_turns", 10)),
                # max_turns= -> 最大轮数；默认 10
                allow_paid_calls=bool(body.get("allow_paid_calls", True)),
                # allow_paid_calls= -> 是否允许付费调用；默认 True，可显式关闭
                metadata=body.get("metadata") or {},
                # metadata= -> 元数据；如果没传或为空，用 {}（空字典）
            )
            result = self.dispatcher.dispatch(
                # 调用调度器的 dispatch 方法分派任务
                ExecutionRequest(
                    # ExecutionRequest(...) -> 构造"执行请求"对象
                    agent_id=str(body["agent_id"]), task=str(body["task"]),
                    # agent_id= -> 目标代理 ID（必填，转字符串）
                    # task=     -> 任务描述（必填，转字符串）；逗号分隔参数
                    run_id=body.get("run_id"), constraints=constraints,
                    # run_id=       -> 可选的 run 关联；constraints= -> 传入约束对象
                )
            )
            return result.to_dict()
            # result.to_dict() -> 把调度结果对象转成字典返回
        if path == ["verify"]:
            # 路径是 /api/verify（验证某个执行）
            constraints = ExecutionConstraints(
                # 同样构造约束对象（参数与 dispatch 分支一致）
                timeout_seconds=int(body.get("timeout_seconds", 300)),
                max_turns=int(body.get("max_turns", 10)),
                allow_paid_calls=bool(body.get("allow_paid_calls", True)),
                metadata=body.get("metadata") or {},
            )
            return self.dispatcher.verify(
                # 调用调度器的 verify 方法进行验证
                verifier_agent_id=str(body["verifier_agent_id"]),
                # verifier_agent_id= -> 验证者代理 ID（必填）
                subject_execution_id=str(body["subject_execution_id"]),
                # subject_execution_id= -> 被验证的执行 ID（必填）
                task=str(body["task"]),
                # task= -> 验证任务描述
                constraints=constraints,
                # constraints= -> 约束对象
            ).to_dict()
            # .to_dict() -> 把结果转成字典返回
        if path == ["memory", "candidates"]:
            # 路径是 /api/memory/candidates（新增候选记忆）
            return self.memory.add_candidate(**body).__dict__
            # self.memory.add_candidate(**body)
            #   **body -> 解包运算符：把字典的键值对展开成关键字参数传给函数。
            #   .__dict__ -> 把返回对象转成字典
        if len(path) == 3 and path[0] == "memory" and path[2] == "promote":
            # 匹配 /api/memory/{id}/promote（提升记忆为正式记忆）
            return self.memory.promote(
                # 调用记忆存储的 promote 方法
                path[1], verified_by=str(body["verified_by"]),
                # path[1] -> 记忆 ID；verified_by= -> 验证人（必填）
                supersede_existing=bool(body.get("supersede_existing", False)),
                # supersede_existing= -> 是否替换已有同主题记忆，默认 False
            ).__dict__
            # .__dict__ -> 转成字典返回
        if len(path) == 3 and path[0] == "memory" and path[2] == "archive":
            # 匹配 /api/memory/{id}/archive（归档记忆）
            return self.memory.archive(
                # 调用记忆存储的 archive 方法
                path[1], actor=str(body["actor"]), reason=str(body["reason"])
                # path[1] -> 记忆 ID；actor= -> 操作人；reason= -> 归档原因
            ).__dict__
            # .__dict__ -> 转成字典返回
        if path == ["messages", "requeue-expired"]:
            # 匹配 /api/messages/requeue-expired（把过期消息重新入队）
            return {"ok": True, "requeued": self.bus.requeue_expired()}
            # {"ok": True, ...} -> 返回成功标志
            # self.bus.requeue_expired() -> 返回重新入队的消息数量
        raise KeyError("/".join(path))
        # raise -> 抛出异常
        # "/".join(path) -> 把路径列表用 "/" 拼回字符串，作为错误信息
        # 作用：没有匹配到任何已支持的路由时，让上层返回 404。


# ----------------------------------------------------------------------------
# HTTP 请求处理类：ControlCenterHandler
# ----------------------------------------------------------------------------
class ControlCenterHandler(BaseHTTPRequestHandler):
    # class                    -> 关键字：定义类
    # ControlCenterHandler     -> 类名：处理控制中心的 HTTP 请求
    # (BaseHTTPRequestHandler) -> 括号：继承自标准库的"基础请求处理器"类，
    #                            继承意味着自动获得底层网络收发能力。
    # :                        -> 冒号：类体开始
    server_version = "TopAgentControlCenter/3.0"
    # server_version -> 类属性：服务器版本标识，会出现在 HTTP 响应头 Server 里。
    # =              -> 赋值
    # "TopAgentControlCenter/3.0" -> 字符串字面量
    center: ControlCenter
    # center        -> 类属性（类型注解形式声明）：指向控制中心实例
    # : ControlCenter -> 类型注解：说明这个属性保存的是 ControlCenter 对象。
    # 作用：类属性而不是实例属性，因为实例由标准库自动创建，不方便传参；
    #       用类属性让所有请求实例共享同一个 center。

    def do_GET(self) -> None:
        # def    -> 关键字：定义方法
        # do_GET -> 方法名：标准库规定"收到 GET 请求时调用"的方法
        # self   -> 指向当前请求实例
        # -> None -> 无返回值
        parsed = urlparse(self.path)
        # parsed -> 局部变量：解析结果对象
        # urlparse(self.path) -> 解析请求 URL。
        # self.path -> 请求的完整路径字符串，如 /api/runs?limit=10
        parts = [part for part in parsed.path.split("/") if part]
        # parts  -> 局部变量：路径段列表
        # [part for part in parsed.path.split("/") if part]
        #        -> 列表推导式：
        #          1. parsed.path.split("/") 把路径按 "/" 拆成列表
        #          2. for part in ... 遍历每个片段
        #          3. if part 过滤掉空字符串（开头/结尾/连续的斜杠会产生空串）
        #          例："/api/runs" -> ["api", "runs"]
        try:
            # try -> 关键字：开始"尝试执行"代码块，配合 except 捕获异常
            if parsed.path == "/api/events/stream":
                # 判断是否是 SSE 事件流接口
                self._sse(parse_qs(parsed.query))
                # 调用私有方法 _sse，参数是解析后的查询参数字典
                return
                # return -> 提前结束方法
            if parts and parts[0] == "api":
                # parts       -> 路径段非空（列表非空即为真）
                # parts[0] == "api" -> 第一段是 "api"，说明是 API 请求
                if len(parts) == 2:
                    # 路径段只有 2 段，如 /api/health，表示"集合"请求
                    payload = self.center.get_collection(parts[1], parse_qs(parsed.query))
                    # payload -> 数据结果
                    # self.center.get_collection(...) -> 调用集合查询
                    # parts[1] -> 集合名
                    # parse_qs(parsed.query) -> 查询参数（转成字典传给方法）
                elif len(parts) == 3:
                    # elif -> 否则如果路径段有 3 段，如 /api/executions/xxx，表示"单个项"
                    payload = self.center.get_item(parts[1], parts[2])
                    # 调用单记录查询：parts[1] 集合名，parts[2] 记录 ID
                else:
                    # 其他长度的路径一律不支持
                    raise KeyError(parsed.path)
                    # raise -> 主动抛出异常，走下面的 except 分支
                self._json(payload)
                # 把查询结果以 JSON 形式写回客户端
                return
                # 结束方法
            self._static(parsed.path)
            # 不是 API 请求，就当作静态文件请求处理（HTML/JS/CSS）
        except KeyError as exc:
            # except  -> 关键字：捕获指定类型的异常
            # KeyError -> 上面 raise 的异常类型
            # as exc   -> 把异常对象赋给变量 exc，方便取错误信息
            self._json({"ok": False, "error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
            # 返回 404 响应：not found: 集合名
        except Exception as exc:
            # 捕获所有其他异常（兜底）
            self._json(
                # 返回 500 错误响应
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                # f-string：type(exc).__name__ 得到异常类型名（如 ValueError）
                HTTPStatus.INTERNAL_SERVER_ERROR,
                # 状态码 500
            )

    def do_POST(self) -> None:
        # do_POST -> 标准库规定"收到 POST 请求时调用"的方法
        parsed = urlparse(self.path)
        # 解析请求路径（与 do_GET 相同逻辑）
        parts = [part for part in parsed.path.split("/") if part]
        # 拆解路径段
        try:
            if not parts or parts[0] != "api":
                # not parts -> 没有路径段；parts[0] != "api" -> 不是 API 路径
                raise KeyError(parsed.path)
                # 都不是，抛异常 -> 404
            length = int(self.headers.get("Content-Length", "0"))
            # length -> 请求体长度
            # self.headers.get("Content-Length", "0") -> 从请求头取长度，默认 "0"
            # int(...) -> 转成整数
            body = json.loads(self.rfile.read(length) or b"{}")
            # body -> 解析后的请求体字典
            # self.rfile.read(length) -> 从输入流读取 length 字节的请求体
            # or b"{}" -> 如果读取到空字节（没传 body），用 b"{}" 代替
            # json.loads(...) -> 把 JSON 字符串解析成 Python 字典
            self._json(self.center.post(parts[1:], body), HTTPStatus.CREATED)
            # self.center.post(parts[1:], body) -> 调用业务处理；
            #                                      parts[1:] 去掉开头的 "api" 段
            # self._json(数据, HTTPStatus.CREATED) -> 以 201 Created 状态返回 JSON
        except KeyError as exc:
            # 捕获 KeyError -> 404
            self._json({"ok": False, "error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            # 捕获"请求体解析失败"相关的三类异常：
            # ValueError（转整数失败）、TypeError（类型错误）、JSONDecodeError（JSON 格式错误）
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            # 返回 400 请求错误
        except Exception as exc:
            # 兜底捕获 -> 500
            self._json(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _static(self, request_path: str) -> None:
        # _static -> 私有方法：服务静态文件。
        # request_path -> 请求的路径字符串
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        # relative -> 相对路径
        # "index.html" if ... else ... -> 三元表达式（条件判断的简写形式）
        # request_path in {"", "/"}   -> 如果路径是空或 "/"，就返回首页 index.html
        # request_path.lstrip("/")    -> 否则去掉开头多余的 "/"
        target = (DASHBOARD_DIR / relative).resolve()
        # target -> 最终要读取的文件完整路径
        # DASHBOARD_DIR / relative -> 拼接目录和相对路径
        # .resolve() -> 解析成绝对路径（消除 .. 等）
        if DASHBOARD_DIR.resolve() not in target.parents and target != DASHBOARD_DIR.resolve():
            # 安全检查（防目录穿越）：
            # DASHBOARD_DIR.resolve() not in target.parents -> 目标文件的上级目录里没有 dashboard 目录
            # and target != DASHBOARD_DIR.resolve() -> 且目标不是 dashboard 目录本身
            raise KeyError(request_path)
            # 说明文件在 dashboard 之外，拒绝访问 -> 404
        if not target.is_file():
            # is_file() -> 判断该路径是不是一个存在的普通文件
            raise KeyError(request_path)
            # 文件不存在 -> 404
        data = target.read_bytes()
        # data -> 文件的原始字节内容
        # target.read_bytes() -> 以二进制方式读取整个文件
        self.send_response(HTTPStatus.OK)
        # send_response -> 标准库方法：发送状态行（HTTP/1.1 200 OK）
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        # send_header("Content-Type", ...) -> 发送"内容类型"响应头
        # mimetypes.guess_type(target.name)[0] -> 按扩展名猜 MIME 类型；
        # or "application/octet-stream" -> 猜不到就用通用二进制类型兜底
        self.send_header("Content-Length", str(len(data)))
        # 发送长度响应头：str(len(data)) 把字节数转成字符串
        self.send_header("Cache-Control", "no-store")
        # 发送缓存控制响应头：no-store 表示不缓存，保证每次都是最新
        self.end_headers()
        # end_headers -> 标准库方法：结束响应头发送，之后可以写正文
        self.wfile.write(data)
        # self.wfile -> 输出流对象
        # .write(data) -> 把文件内容写入响应

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        # _json  -> 私有方法：统一发送 JSON 响应。
        # payload -> 要发送的数据（字典等）
        # status  -> 响应状态码，默认 HTTPStatus.OK（200）
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        # data   -> 编码后的字节
        # json.dumps(payload, ...) -> 把 Python 对象序列化成 JSON 字符串
        # ensure_ascii=False -> 不把中文转成 \uXXXX，直接输出中文
        # default=str -> 遇到无法序列化的对象（如 Path）时，用 str() 转字符串
        # .encode("utf-8") -> 把字符串编码成 UTF-8 字节
        self.send_response(status)
        # 发送状态行
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 声明内容是 JSON，字符集 UTF-8
        self.send_header("Content-Length", str(len(data)))
        # 发送长度
        self.send_header("Cache-Control", "no-store")
        # 禁止缓存
        self.end_headers()
        # 结束响应头
        self.wfile.write(data)
        # 写入 JSON 数据

    def _sse(self, query: dict[str, list[str]]) -> None:
        # _sse  -> 私有方法：Server-Sent Events（服务器推送事件流）。
        #         连接建立后，服务器不断向浏览器推送事件。
        # query -> 查询参数字典
        after = query.get("after", [""])[0]
        # after -> 游标：只推送"发生时间晚于 after"的事件；默认空串（推全部）
        self.send_response(HTTPStatus.OK)
        # 发送 200 状态
        self.send_header("Content-Type", "text/event-stream")
        # 声明内容类型为事件流
        self.send_header("Cache-Control", "no-cache")
        # 不缓存（事件流不能被缓存）
        self.send_header("Connection", "keep-alive")
        # 保持连接不断开（长连接）
        self.end_headers()
        # 结束响应头
        deadline = time.monotonic() + 25
        # deadline -> 本次连接的截止时间
        # time.monotonic() -> 单调时钟（只增不减，适合计时）；+25 表示 25 秒后结束
        while time.monotonic() < deadline:
            # while -> 关键字：循环，只要条件为真就继续
            # time.monotonic() < deadline -> 当前时间还没到截止时间就继续
            if after:
                # after 非空：说明有游标，查询该时间之后的事件
                rows = self.center.db.all(
                    """SELECT * FROM execution_events WHERE occurred_at>?
                    ORDER BY occurred_at, event_id LIMIT 100""", (after,)
                    # 查询 occurred_at > after 的事件
                    # ORDER BY occurred_at, event_id -> 按发生时间、事件 ID 排序
                    # LIMIT 100 -> 每次最多取 100 条，防止刷屏
                    # (after,)  -> 把游标值填入占位符
                )
            else:
                # after 为空：首轮没有游标，不推历史数据
                rows = []
                # rows -> 空列表
            if rows:
                # rows 非空：有新事件要推送
                for row in _decode_rows(rows):
                    # 遍历解码后的每一行事件
                    after = row["occurred_at"]
                    # 更新游标：下次只推比这次更晚的事件
                    packet = json.dumps(row, ensure_ascii=False).replace("\n", "\\n")
                    # packet -> 单条事件的字符串
                    # json.dumps(row, ensure_ascii=False) -> 序列化为 JSON
                    # .replace("\n", "\\n") -> 把换行符替换为字面量 \n，避免破坏 SSE 协议
                    self.wfile.write(f"id: {after}\nevent: trace\ndata: {packet}\n\n".encode("utf-8"))
                    # 按 SSE 协议格式写事件：
                    # id: 游标     -> 事件编号
                    # event: trace -> 事件类型
                    # data: JSON   -> 事件内容
                    # 空行 \n\n    -> SSE 协议规定事件以空行结束
                self.wfile.flush()
                # flush() -> 立即把缓冲区数据发送出去（不等待攒满）
            else:
                # 没有新事件：
                self.wfile.write(b": heartbeat\n\n")
                # 写心跳注释行（SSE 以冒号开头的是注释），保活连接
                self.wfile.flush()
                # 立即发送
            time.sleep(1)
            # time.sleep(1) -> 暂停 1 秒，再进入下一轮循环（每秒轮询一次）
        # while 结束后函数自然结束（连接断开）

    def log_message(self, format: str, *args: Any) -> None:
        # log_message -> 标准库请求处理器在记录日志时会调用它。
        # 这里把它重写为"什么都不做"，避免把每个请求打到控制台刷屏。
        # format -> 日志格式字符串；*args -> 可变参数（任意多个参数打包成元组）
        return
        # return -> 空返回，函数什么都不做


# ----------------------------------------------------------------------------
# 工厂函数：创建 HTTP 服务器
# ----------------------------------------------------------------------------
def create_server(
    host: str = "127.0.0.1", port: int = 8765, *, database: Database | None = None
) -> ThreadingHTTPServer:
    # def             -> 关键字：定义函数
    # create_server   -> 函数名：创建并返回一个 HTTP 服务器。
    # host            -> 参数：监听地址，默认 127.0.0.1（仅本机）
    # : str           -> 类型注解：字符串
    # = "127.0.0.1"   -> 默认值：本机回环地址
    # port            -> 参数：监听端口，默认 8765
    # : int           -> 类型注解：整数
    # = 8765          -> 默认值
    # , *             -> 星号：它之后的所有参数只能"按名字"传入（关键字参数），
    #                    不能按位置传，用于强制明确语义。
    # database        -> 参数：可选的数据库对象（必须用 database=xxx 的形式传）
    # : Database | None -> 类型：数据库或空
    # = None          -> 默认空
    # -> ThreadingHTTPServer -> 返回值类型注解：返回多线程服务器对象
    center = ControlCenter(database)
    # center -> 创建控制中心实例
    # ControlCenter(database) -> 传入数据库（可能是 None，则使用全局 db）

    class BoundHandler(ControlCenterHandler):
        # class          -> 关键字：在函数内部定义"局部类"
        # BoundHandler   -> 局部类名：把处理类与 center 实例"绑定"在一起
        # (ControlCenterHandler) -> 继承自处理类
        pass
        # pass -> 空语句：占位，类体里什么都不加

    BoundHandler.center = center
    # 给局部类设置类属性 center，指向刚创建的控制中心。
    # 这样服务器创建的每个请求实例都能通过 self.center 访问到它。

    return ThreadingHTTPServer((host, port), BoundHandler)
    # return                   -> 返回服务器对象
    # ThreadingHTTPServer((host, port), BoundHandler)
    #                         -> 标准库构造函数：
    #                            第一个参数是 (主机, 端口) 元组，
    #                            第二个参数是请求处理类（收到请求就实例化它）。


# ----------------------------------------------------------------------------
# 入口：命令行启动
# ----------------------------------------------------------------------------
def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    # main -> 主函数：程序入口。
    # host/port -> 监听地址和端口，带默认值。
    server = create_server(host, port)
    # server -> 服务器对象
    # create_server(host, port) -> 调用工厂函数创建服务器
    print(f"TopAgent Control Center: http://{host}:{server.server_port}")
    # print -> 内置函数：在控制台输出一行提示
    # f"..." -> f-string：{} 内表达式会被求值
    # {host} -> 输出主机；{server.server_port} -> 服务器实际端口
    try:
        # try -> 尝试执行
        server.serve_forever()
        # serve_forever() -> 标准库方法：永久运行服务器，不断处理请求（阻塞）
    except KeyboardInterrupt:
        # 捕获键盘中断（用户按 Ctrl+C 时抛出）
        pass
        # pass -> 什么都不做，只是不报错
    finally:
        # finally -> 无论是否发生异常都会执行
        server.server_close()
        # server_close() -> 关闭服务器，释放端口等资源


# ----------------------------------------------------------------------------
# 标准入口判断
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    # if            -> 关键字：条件判断
    # __name__      -> 特殊变量：当前模块的名字。
    #                 直接运行本文件时它是 "__main__"；
    #                 被 import 时它是模块名（如 "server_annotated"）。
    # ==            -> 比较运算符：判断是否相等
    # "__main__"    -> 字符串字面量，表示"作为主程序直接运行"
    # :              -> 冒号：条件成立执行下面
    main()
    # main() -> 调用主函数，启动服务器
# 作用：只有直接运行本文件才启动服务器；
#       被别人 import 时不会自动启动，避免副作用。
