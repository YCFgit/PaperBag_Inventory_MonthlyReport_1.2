# 观远卡片 API 通用调用指南

## 1. 文档定位

本文档面向“通过观远 API 获取卡片数据”的通用场景，覆盖以下内容：

- API 作用与整体调用流程
- 鉴权 API 与卡片数据 API 说明
- 请求头、请求参数、请求体结构
- `curl`、Python、Java 调用示例
- 本项目中的接入方式、配置方式与排障方法

如果你只想在本项目里做单卡联调，可以直接跳到“本项目中的落地方式”和“常用调试命令”两节。

## 2. API 概览

本项目当前接入了两类观远接口：

1. 鉴权接口：获取访问 token
2. 卡片数据接口：按 `card_id` 拉取指定卡片数据

当前项目配置位于 `config/app.yaml`：

```yaml
guanyuan:
  base_url: "https://data-application-test.topsports.com.cn"
  auth_token_path: "/auth-token/oauth2/client_token"
  data_card_path_template: "/data-strategy/guanYuan/card/{card_id}/Data"
```

拼接后得到：

- token API：`GET {base_url}{auth_token_path}`
- card API：`POST {base_url}/data-strategy/guanYuan/card/{card_id}/Data`

## 3. 调用流程

一个完整的调用过程通常如下：

1. 使用 `client_id` 和 `client_secret` 请求 token。
2. 从鉴权返回中提取可用 token。
3. 在卡片接口请求头中带上 `auth-token`。
4. 在请求体中传入 `userId`、分页参数、`view`、动态参数和筛选器。
5. 解析返回结果中的行数据。

本项目对应代码如下：

- `src/clients/auth_client.py`
- `src/services/token_service.py`
- `src/clients/guanyuan_client.py`
- `src/services/card_service.py`

## 4. 鉴权 API

### 4.1 请求说明

请求方法：

```text
GET
```

请求地址：

```text
{base_url}{auth_token_path}
```

查询参数：

- `grant_type=client_credentials`
- `client_id=<你的 client id>`
- `client_secret=<你的 client secret>`

本项目里的实现见 `AuthClient.fetch_token()`。

### 4.2 token 返回兼容规则

不同环境下，token 可能出现在不同字段。本项目当前兼容以下几种常见结构：

```json
{
  "access_token": "xxx",
  "expires_in": 7200
}
```

```json
{
  "client_token": "xxx",
  "expires_in": 7200
}
```

```json
{
  "data": {
    "access_token": "xxx",
    "expires_in": 7200
  }
}
```

```json
{
  "data": {
    "client_token": "xxx",
    "expires_in": 7200
  }
}
```

本项目由 `TokenService._parse_token_payload()` 负责兼容解析。

### 4.3 鉴权 API 的 `curl` 示例

```bash
curl --get 'https://data-application-test.topsports.com.cn/auth-token/oauth2/client_token' \
  --data-urlencode 'grant_type=client_credentials' \
  --data-urlencode 'client_id=YOUR_CLIENT_ID' \
  --data-urlencode 'client_secret=YOUR_CLIENT_SECRET'
```

### 4.4 鉴权 API 的 Python 示例

```python
import requests

BASE_URL = "https://data-application-test.topsports.com.cn"
AUTH_PATH = "/auth-token/oauth2/client_token"

resp = requests.get(
    f"{BASE_URL}{AUTH_PATH}",
    params={
        "grant_type": "client_credentials",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
    },
    timeout=30,
)
resp.raise_for_status()
payload = resp.json()

token = (
    payload.get("access_token")
    or payload.get("client_token")
    or payload.get("data", {}).get("access_token")
    or payload.get("data", {}).get("client_token")
)

print(token)
```

### 4.5 鉴权 API 的 Java 示例

```java
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;

public class GuanYuanAuthDemo {
    public static void main(String[] args) throws Exception {
        String baseUrl = "https://data-application-test.topsports.com.cn";
        String query =
            "grant_type=client_credentials"
            + "&client_id=" + URLEncoder.encode("YOUR_CLIENT_ID", StandardCharsets.UTF_8)
            + "&client_secret=" + URLEncoder.encode("YOUR_CLIENT_SECRET", StandardCharsets.UTF_8);

        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/auth-token/oauth2/client_token?" + query))
            .GET()
            .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        System.out.println(response.body());
    }
}
```

## 5. 卡片数据 API

### 5.1 请求说明

请求方法：

```text
POST
```

请求地址：

```text
{base_url}/data-strategy/guanYuan/card/{card_id}/Data
```

请求头通常至少包含：

- `Content-Type: application/json`
- `auth-token: <token>`

### 5.2 常见请求体字段

本项目中，卡片请求体一般由以下字段组成：

- `userId`：观远用户 ID
- `limit`：单页条数
- `offset`：分页起点
- `view`：卡片视图类型，常见值为 `GRID` 或 `GRAPH`
- `refresh`：是否刷新
- `dynamicParams`：动态参数列表
- `filters`：筛选条件列表

本项目在 `GuanYuanClient.fetch_card_page()` 中会自动补：

- `userId`
- `limit`
- `offset`
- 默认 `view=GRID`

### 5.3 `dynamicParams` 常见字段说明

`dynamicParams` 常见字段如下：

- `dpId`：动态参数 ID
- `name`：动态参数名称
- `valueType`：值类型，常见为 `DATE`
- `defaultValue`：默认值，本项目通常写模板变量
- `customize`：是否允许自定义
- `multiple`：是否多选
- `optionValue`：选项值
- `inheritParent`：是否继承父级参数

如果只是做最小调用，通常只保留 `name`、`valueType`、`defaultValue` 也能表达清楚请求语义；如果要完全复刻观远前台卡片配置，则建议带全。

### 5.4 `filters` 常见字段说明

`filters` 常见字段如下：

- `name`：筛选字段名称
- `filterType`：筛选操作符，如 `EQ`、`IN`、`GE`、`LE`、`BT`
- `filterValue`：筛选值数组
- `fdId`：字段 ID
- `fdType`：字段类型
- `dsId`：数据集 ID
- `metaType`：字段元数据类型
- `filterLevel`：筛选层级

如果是通用调用，只要接口允许，通常至少需要：

- `name`
- `filterType`
- `filterValue`

如果要完全复刻某张现有卡片的行为，建议把观远前台导出的筛选元信息一并保留。

### 5.5 通用请求体示例

```json
{
  "userId": "230101973",
  "limit": 200,
  "offset": 0,
  "view": "GRAPH",
  "refresh": true,
  "dynamicParams": [
    {
      "name": "本期开始日期",
      "valueType": "DATE",
      "defaultValue": "2026-05-01"
    },
    {
      "name": "本期结束日期",
      "valueType": "DATE",
      "defaultValue": "2026-05-31"
    }
  ],
  "filters": [
    {
      "name": "日期",
      "filterType": "GE",
      "filterValue": ["2026-05-01"]
    },
    {
      "name": "日期",
      "filterType": "LE",
      "filterValue": ["2026-05-31"]
    }
  ]
}
```

### 5.6 卡片 API 的 `curl` 示例

```bash
curl 'https://data-application-test.topsports.com.cn/data-strategy/guanYuan/card/xe5da9d423db44bbe96028ad/Data' \
  -H 'Content-Type: application/json' \
  -H 'auth-token: YOUR_AUTH_TOKEN' \
  --data-raw '{
    "userId": "230101973",
    "limit": 100,
    "offset": 0,
    "view": "GRAPH",
    "refresh": true,
    "dynamicParams": [
      {
        "name": "本期开始日期",
        "valueType": "DATE",
        "defaultValue": "2026-05-01"
      },
      {
        "name": "本期结束日期",
        "valueType": "DATE",
        "defaultValue": "2026-05-31"
      }
    ],
    "filters": []
  }'
```

### 5.7 卡片 API 的 Python 示例

```python
import requests

BASE_URL = "https://data-application-test.topsports.com.cn"
CARD_ID = "xe5da9d423db44bbe96028ad"
TOKEN = "YOUR_AUTH_TOKEN"

payload = {
    "userId": "230101973",
    "limit": 100,
    "offset": 0,
    "view": "GRAPH",
    "refresh": True,
    "dynamicParams": [
        {
            "name": "本期开始日期",
            "valueType": "DATE",
            "defaultValue": "2026-05-01",
        },
        {
            "name": "本期结束日期",
            "valueType": "DATE",
            "defaultValue": "2026-05-31",
        },
    ],
    "filters": [
        {"name": "日期", "filterType": "GE", "filterValue": ["2026-05-01"]},
        {"name": "日期", "filterType": "LE", "filterValue": ["2026-05-31"]},
    ],
}

resp = requests.post(
    f"{BASE_URL}/data-strategy/guanYuan/card/{CARD_ID}/Data",
    headers={
        "Content-Type": "application/json",
        "auth-token": TOKEN,
    },
    json=payload,
    timeout=60,
)
resp.raise_for_status()
result = resp.json()
print(result)
```

### 5.8 卡片 API 的 Java 示例

下面示例使用 Java 11+ 自带 `HttpClient`。

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

public class GuanYuanCardDemo {
    public static void main(String[] args) throws Exception {
        String token = "YOUR_AUTH_TOKEN";
        String body = """
            {
              "userId": "230101973",
              "limit": 100,
              "offset": 0,
              "view": "GRAPH",
              "refresh": true,
              "dynamicParams": [
                {
                  "name": "本期开始日期",
                  "valueType": "DATE",
                  "defaultValue": "2026-05-01"
                },
                {
                  "name": "本期结束日期",
                  "valueType": "DATE",
                  "defaultValue": "2026-05-31"
                }
              ],
              "filters": []
            }
            """;

        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("https://data-application-test.topsports.com.cn/data-strategy/guanYuan/card/xe5da9d423db44bbe96028ad/Data"))
            .header("Content-Type", "application/json")
            .header("auth-token", token)
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        System.out.println(response.body());
    }
}
```

### 5.9 端到端 `curl` 示例

下面示例演示“先取 token，再取卡片”的完整流程：

```bash
TOKEN=$(
  curl --silent --get 'https://data-application-test.topsports.com.cn/auth-token/oauth2/client_token' \
    --data-urlencode 'grant_type=client_credentials' \
    --data-urlencode 'client_id=YOUR_CLIENT_ID' \
    --data-urlencode 'client_secret=YOUR_CLIENT_SECRET'
)

echo "$TOKEN"
```

取到 token 后，再用它请求卡片：

```bash
curl 'https://data-application-test.topsports.com.cn/data-strategy/guanYuan/card/xe5da9d423db44bbe96028ad/Data' \
  -H 'Content-Type: application/json' \
  -H 'auth-token: YOUR_AUTH_TOKEN' \
  --data-raw '{
    "userId": "230101973",
    "limit": 100,
    "offset": 0,
    "view": "GRAPH",
    "refresh": true,
    "dynamicParams": [],
    "filters": []
  }'
```

## 6. 分页调用示例

若卡片数据量较大，通常需要循环翻页。

分页规则：

- 第一页通常 `offset=0`
- 每次翻页 `offset += limit`
- 当返回行数小于 `limit` 时停止

Python 示例：

```python
def extract_rows(payload):
    candidates = [
        payload.get("rows"),
        payload.get("data", {}).get("rows") if isinstance(payload.get("data"), dict) else None,
        payload.get("data", {}).get("rowList") if isinstance(payload.get("data"), dict) else None,
        payload.get("result", {}).get("rows") if isinstance(payload.get("result"), dict) else None,
        payload.get("data", {}).get("list") if isinstance(payload.get("data"), dict) else None,
        payload.get("list"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def fetch_all_pages(session, base_url, card_id, token, payload, limit=200, max_pages=10):
    all_rows = []
    offset = 0

    for _ in range(max_pages):
        request_body = {**payload, "limit": limit, "offset": offset}
        resp = session.post(
            f"{base_url}/data-strategy/guanYuan/card/{card_id}/Data",
            headers={"Content-Type": "application/json", "auth-token": token},
            json=request_body,
            timeout=60,
        )
        resp.raise_for_status()
        page = resp.json()
        rows = extract_rows(page)
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        offset += limit

    return all_rows
```

## 7. 筛选器写法与兼容规则

### 7.1 两种常见写法

本项目兼容两类筛选器格式。

写法一，观远原生字段：

```json
{
  "name": "日期",
  "filterType": "BT",
  "filterValue": ["2026-05-01", "2026-05-31"]
}
```

写法二，简化字段：

```json
{
  "fieldName": "日期",
  "operator": "BETWEEN",
  "values": ["2026-05-01", "2026-05-31"]
}
```

### 7.2 `BT/BETWEEN` 自动拆分

本项目中的 `normalize_filters()` 会把 `BT` 或 `BETWEEN` 自动拆成：

- `GE`
- `LE`

例如：

```json
[
  {"name": "日期", "filterType": "BT", "filterValue": ["2026-05-01", "2026-05-31"]}
]
```

会被规范化为：

```json
[
  {"name": "日期", "filterType": "GE", "filterValue": ["2026-05-01"]},
  {"name": "日期", "filterType": "LE", "filterValue": ["2026-05-31"]}
]
```

这是本项目里一个重要兼容策略。当前联调经验表明，部分卡片直接使用 `BT` 日期过滤时稳定性较差。

## 8. 响应结构与数据提取

### 8.1 常见返回形态

观远卡片返回中的“行数据”不一定只在一个固定字段下。本项目当前兼容以下位置：

- `rows`
- `data.rows`
- `data.rowList`
- `result.rows`
- `data.list`
- `list`

也就是说，以下几种结构都可能是正常的：

```json
{
  "code": 200,
  "rows": [
    {"地区": "东北", "库销比": 2.18}
  ]
}
```

```json
{
  "code": 200,
  "data": {
    "rows": [
      {"地区": "东北", "库销比": 2.18}
    ]
  }
}
```

```json
{
  "code": 200,
  "data": {
    "rowList": [
      {"地区": "东北", "库销比": 2.18}
    ]
  }
}
```

### 8.2 Python 提取示例

```python
def extract_rows(payload):
    candidates = [
        payload.get("rows"),
        payload.get("data", {}).get("rows") if isinstance(payload.get("data"), dict) else None,
        payload.get("data", {}).get("rowList") if isinstance(payload.get("data"), dict) else None,
        payload.get("result", {}).get("rows") if isinstance(payload.get("result"), dict) else None,
        payload.get("data", {}).get("list") if isinstance(payload.get("data"), dict) else None,
        payload.get("list"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []
```

## 9. 本项目中的落地方式

### 9.1 环境变量

本项目运行前至少需要配置：

- `GUANYUAN_CLIENT_ID`
- `GUANYUAN_CLIENT_SECRET`
- `GUANYUAN_USER_ID`

示例见 `.env.example`。

### 9.2 token 缓存

本项目会把 token 缓存在：

```text
data/processed/token_cache.json
```

当缓存未过期时直接复用；当卡片请求返回 `401` 时，会自动刷新一次 token 后重试。

### 9.3 卡片定义方式

所有卡片都定义在 `config/cards.yaml`。

每张卡片通常包含：

- `card_id`
- `name`
- `role`
- `section`
- `pagination`
- `request_body`
- `dynamic_params`
- `filters`
- `notes`

### 9.4 模板变量渲染

项目会在发请求前，先渲染卡片配置中的模板变量。常用变量包括：

- `{{report_month_start}}`
- `{{report_month_end}}`
- `{{previous_month_start}}`
- `{{previous_month_end}}`
- `{{previous_year_same_month_start}}`
- `{{previous_year_same_month_end}}`
- `{{fiscal_year_start}}`
- `{{rolling_30d_start}}`
- `{{rolling_30d_end}}`

对应实现：

- `src/utils/date_helper.py`
- `src/utils/template.py`

### 9.5 默认不向远端附加本地范围过滤

当前 `config/app.yaml` 中：

```yaml
scope:
  apply_remote_filters: false
```

这表示项目默认不把本地范围规则整体推给远端，而是优先在拉回原始数据后再做本地清洗。原因是部分卡片在远端附加额外 filters 后会报 `500` 或应用层异常。

## 10. 常用调试命令

### 10.1 校验配置

```bash
python -m src.main validate-config
```

### 10.2 单卡联调

```bash
python -m src.main inspect-card --month 2026-05 --card-id xe5da9d423db44bbe96028ad
```

输出：

- 原始包：`data/raw/2026-05/<run_id>/`
- 巡检报告：`data/processed/inspection/2026-05/<card_id>_raw_inspection.json`

### 10.3 批量巡检全部卡片

```bash
python -m src.main inspect-all-cards --month 2026-05
```

### 10.4 离线复盘最近原始包

```bash
python -m src.main inspect-latest-raw --month 2026-05
```

### 10.5 用归档原始包重放

```bash
python -m src.main replay-raw \
  --raw-file data/raw/2026-05/<run_id>/<file>.json \
  --month 2026-05 \
  --skip-llm \
  --skip-send
```

## 11. 输出文件说明

### 11.1 原始包归档

目录：

```text
data/raw/<report_month>/<run_id>/
```

文件名：

```text
<role>_<card_id>.json
```

每个原始包会保留：

- `card_id`
- `card_name`
- `role`
- `section`
- `resolved_request_body`
- `resolved_dynamic_params`
- `resolved_filters`
- `pages`

### 11.2 巡检结果

目录：

```text
data/processed/inspection/<report_month>/
```

巡检信息通常包含：

- `page_count`
- `row_count`
- `fields`
- 字段样例值

## 12. 常见问题

### 12.1 返回 `401`

优先检查：

- `GUANYUAN_CLIENT_ID`
- `GUANYUAN_CLIENT_SECRET`
- `GUANYUAN_USER_ID`

若仍失败，通常不是缓存问题，而是鉴权信息本身无效。

### 12.2 返回 `500`

优先排查：

- 是否追加了过多远端筛选器
- 是否仍在使用未拆分的 `BT/BETWEEN`
- 卡片本身在观远前台是否能稳定打开

### 12.3 空数据

优先检查：

- 月份是否传错
- 动态参数 ID 或名称是否失效
- 筛选器字段名是否被观远改动
- 卡片本月是否本就无数据

### 12.4 字段结构漂移

推荐先执行：

```bash
python -m src.main inspect-card --month 2026-05 --card-id <card_id>
```

然后核对：

- 原始返回 `pages`
- 巡检输出中的 `fields`
- 是否还能在 `rows / data.rows / data.rowList / list` 中找到行数据

## 13. 本项目已验证的关键约束

当前项目中已经验证过的重点结论如下：

- `qd0651b4b8bc944e88a6d1f0` 不使用原始 `BT` 日期过滤，改用 `GE 2024-03-01` 与 `LE {{report_month_end}}`
- `j21833508e589464c922d381` 必须使用 `view=GRID`
- `d01d19a06c98445008a49a3f` 使用 `{{previous_month_start}} ~ {{report_month_end}}`
- `l1d70dacd48c3422d9f7f67c` 不再追加纸袋分类过滤

详细联调结论见 `docs/integration_notes.md`。
