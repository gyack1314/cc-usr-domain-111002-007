# 多工作空间门户的浏览器上下文隔离采集本地门户

本项目是可在本地运行的合成业务门户，提供真实浏览器页面、交互状态及样本资料，不包含业务采集端。资料、用户与工作空间都是虚构内容。

## 环境

Python 3.12、Playwright 1.56.0 与 Chromium。`portal/` 是标准库 HTTP 服务，`web/` 是浏览器页面及 JavaScript 交互，`tests/` 检查门户自身行为。Python 用于服务与浏览器控制，JavaScript 只在浏览器内运行，不需要 Node.js 服务。

安装依赖及浏览器：

```sh
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
python -m portal --port 8090
```

在浏览器打开本机8090端口即可操作。门户的正常交互在页面完成，`web/data.json` 保存合成来源材料。状态随页面或浏览器上下文生命周期保存；需要持久状态的功能使用当前 origin 的 localStorage。重新开始可创建新的浏览器上下文。

运维入口 GET `/__state` 查看来源动作记录，POST `/__control` 用 JSON 设置 phase、version、confirmed。它们只用于本地来源调度，接入程序的正常操作不能借用运维入口取得业务数据或完成授权。GET `/api/runtime` 和 POST `/api/action` 是门户页面内部协议。

## 采集组件

`collector/` 是业务采集端，按计划逐空间采集，只使用门户公开页面，不接触运维入口：

- 计划（`config/plan.json`）明确给出用户配置、允许的空间编号与资料类别，每个空间的结果独立存放在 `outputs/<空间>/`。
- 每个空间使用独立 BrowserContext，登录材料只来自运行配置或本空间自己的状态文件（`state/<空间>/`，路径与空间不符即拒绝加载），不向别的空间复制 cookie 或存储状态。
- 切换空间只通过门户公开的选择界面，不修改 localStorage；空间标识必须在导航、列表、详情三处一致且属于计划允许集合才接收资料，新标签子页同样核对，地址栏参数不作为身份依据。
- 业务主键 = 空间 + record-id；发现空间不一致即保留证据到 `outputs/<空间>/quarantine/` 并停止该空间链，其他空间继续，异常资料不进入正式结果。
- `max_contexts` 限制上下文并发数；上下文只属于本空间，关闭前先把在途新标签处理完，不会归到下一个空间。日志不保存会话秘密。

```sh
python -m portal --port 8090          # 先启动门户
python -m collector --plan config/plan.json
python -m collector.demo              # 端到端演示：双上下文存储隔离 + 错误详情/旧列表隔离
```

## 验证与容器

```sh
python -m unittest discover -s tests -v
python -m compileall -q portal tests collector
docker build -t workspace-isolation-portal .
docker run --rm --network none --shm-size=1g workspace-isolation-portal
```

Dockerfile 固定浏览器基础镜像的完整摘要，依赖版本在 requirements.txt 固定。首次构建需要下载依赖；镜像完成后，上述检查禁用外网，浏览器与门户在同一容器内通信。默认运行来源检查，不运行资料采集。

如需在宿主浏览器操作容器内门户：

```sh
docker run --rm -p 127.0.0.1:8090:8090 workspace-isolation-portal python -m portal --host 0.0.0.0 --port 8090
```

页面的 DOM 状态、公开身份属性与中文加载提示可用于等待完成，避免使用固定秒数等待。来源动作记录可核对页面操作；不要在日志记录会话秘密或不需要的私密字段。

来源场景、属性及控制方式详见 `source-contract.json`。
