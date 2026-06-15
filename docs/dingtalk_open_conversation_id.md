# 获取 `openConversationId` 操作说明

## 1. 目标

要把 PDF 月报作为群文件直接发到钉钉群，当前主链路只缺：

- `openConversationId`

## 2. 最快做法

优先推荐用钉钉 H5 JSAPI 选群后直接读取返回值。

仓库里已经放好了一个最小页面模板：

- [dingtalk_choose_conversation.html](/Users/ycf/Documents/OpenClaw/PaperBag_Inventory_MonthlyReport_1.2/docs/dingtalk_choose_conversation.html)

现在建议配合仓库里的本地签名服务一起使用。整体流程是三步：

1. 后端调用钉钉 OAPI 获取 `jsapi_ticket`
2. 页面完成 `dd.config` 鉴权
3. 调用 `biz.chat.chooseConversationByCorpId` 让你手动选群

选群成功后，页面会直接回显：

- `title`
- `chatId`
- `openConversationId`

现在不需要你再手工把 `openConversationId` 发给我了。页面选群成功后，项目会自动把绑定结果保存到本地，后续月报任务直接读取这个绑定并发送 PDF。

## 3. 使用前提

这个页面不是本地双击就能用，必须满足下面条件：

1. 你的钉钉应用已经开通 **网页应用/H5 微应用** 能力。
2. 页面被部署在应用配置允许访问的 HTTPS 域名下。
3. 页面运行在钉钉客户端里打开。
4. 你准备好 `dd.config` 所需参数，或者能访问签名接口：
   - `corpId`
   - `agentId`
   - `timeStamp`
   - `nonceStr`
   - `signature`

## 4. 你现在已知的参数

你已经提供过：

- `AgentId = 4668444612`

这可以直接填到模板页面里。

## 5. 还需要准备的参数

### 5.1 `corpId`

通常从钉钉工作台进入 H5 应用时，可以从页面 URL 上的 `corpId` 参数里拿到。

### 5.2 `signature`

这是 `dd.config` 的签名结果，不能前端直接算，通常由服务端返回。

仓库里已经补了一个最小本地命令：

```bash
python -m src.main serve-dingtalk-jsapi --host 127.0.0.1 --port 8000
```

运行前在 `.env` 里补齐：

```dotenv
DINGTALK_APP_KEY=你的应用 AppKey
DINGTALK_APP_SECRET=你的应用 AppSecret
DINGTALK_AGENT_ID=4668444612
```

它会提供一个简单接口：

```text
GET /api/dingtalk/jsapi-config?url=<当前页面URL>&corpId=<企业corpId>
```

返回：

```json
{
  "corpId": "dingxxxx",
  "agentId": "4668444612",
  "timeStamp": 1718188800,
  "nonceStr": "random-string",
  "signature": "calculated-signature"
}
```

## 6. 最小操作步骤

1. 在本地启动签名服务：

   ```bash
   python -m src.main serve-dingtalk-jsapi --host 127.0.0.1 --port 8000
   ```

2. 把 [dingtalk_choose_conversation.html](/Users/ycf/Documents/OpenClaw/PaperBag_Inventory_MonthlyReport_1.2/docs/dingtalk_choose_conversation.html) 部署到你的 H5 应用域名下，或者直接让当前服务提供这个页面。
3. 在钉钉客户端中打开页面。
4. 页面 URL 里如果已经带了 `corpId`，页面会自动填充；没有的话手工填入。
5. 在页面里填写签名接口地址，例如：

   ```text
   http://127.0.0.1:8000/api/dingtalk/jsapi-config
   ```

6. 点“自动获取签名参数”。
7. 点“初始化 JSAPI”。
8. 初始化成功后，点“选择钉钉群并获取 openConversationId”。
9. 在弹出的群列表中选目标群。
10. 页面会自动把绑定结果写入 `data/processed/dingtalk_binding.json`，并同时保存 `chatId`、`unionId`、`userId`、`operatorName` 等后续发送需要的绑定信息。

## 7. `corpId` 和 `signature` 分别怎么拿

### 7.1 `corpId`

推荐顺序：

1. 最优先让页面自动读取钉钉容器里的 `dd.corpId`
2. 如果 URL 查询参数里已经带了 `corpId`，页面也会自动填充
3. 如果前两者都拿不到，再手工填入企业对应的 `corpId`

### 7.2 `signature`

不要手工算，也不要在前端算。直接通过上面的 `/api/dingtalk/jsapi-config` 接口获取。

## 8. 如果你不想写页面

还有一个更快的替代方案：

1. 用钉钉开放平台的 **JSAPI Explorer**
2. 直接调 `biz.chat.chooseConversationByCorpId`
3. 在调试结果里读出 `openConversationId`

这种方式更省事，但可重复性不如仓库里的模板页。

## 9. 你拿到 `openConversationId` 之后

绑定完成后，项目后续会自动做下面这件事：

1. 用企业内部应用 `appKey/appSecret` 获取 `accessToken`
2. 自动创建或复用群文件空间与文件夹
3. 上传生成好的 PDF 到钉钉文件空间
4. 调用 `convFile` 文件发送接口，把 PDF 作为群文件发到目标群
5. 定时任务后续直接复用这个绑定
