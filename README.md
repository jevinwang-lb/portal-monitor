# Portal Safe Browsing Monitor

- [Portal Safe Browsing Monitor](#portal-safe-browsing-monitor)
  - [Status](#status)
  - [1. Local 首次运行](#1-local-首次运行)
    - [1.1 创建 Python 环境](#11-创建-python-环境)
    - [1.2 配置监控域名](#12-配置监控域名)
    - [1.3 配置 Teams Webhook](#13-配置-teams-webhook)
    - [1.4 Curl 测试 Teams Webhook](#14-curl-测试-teams-webhook)
    - [1.5 本地运行 Monitor](#15-本地运行-monitor)
  - [2. Docker](#2-docker)
    - [2.1 Build](#21-build)
    - [2.2 Local Docker Test](#22-local-docker-test)
    - [2.3 Push](#23-push)
  - [3. Kubernetes 首次部署](#3-kubernetes-首次部署)
    - [3.1 Namespace](#31-namespace)
    - [3.2 EBS CSI / StorageClass](#32-ebs-csi--storageclass)
    - [3.3 PVC](#33-pvc)
    - [3.4 Domains ConfigMap](#34-domains-configmap)
    - [3.5 Teams Secret](#35-teams-secret)
    - [3.6 首次 Job 测试](#36-首次-job-测试)
    - [3.7 验证 EBS 状态持久化](#37-验证-ebs-状态持久化)
    - [3.8 CronJob](#38-cronjob)
  - [Project Structure](#project-structure)
  - [State Storage](#state-storage)

---
定时检查 Google Safe Browsing Transparency Report 中配置域名的安全状态，并在状态发生变化时通过 Microsoft Teams Webhook 通知。

## Status

| Status        | Description             |
| ------------- | ----------------------- |
| `SAFE`        | Google 明确返回安全     |
| `UNSAFE`      | Google 将网站标记为危险 |
| `UNKNOWN`     | Google 无法明确判断     |
| `NO_DATA`     | Google 暂无该站点数据   |
| `CHECK_ERROR` | 检测过程发生异常        |

通知逻辑：

```text
首次发现 UNSAFE
→ Teams 告警

UNSAFE → UNSAFE
→ 不重复告警

UNSAFE → SAFE
→ Teams 恢复通知

SAFE → SAFE
→ 不通知
```

---

## 1. Local 首次运行

### 1.1 创建 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

Local macOS 使用本机安装的 Google Chrome，不需要额外安装 Playwright Chromium。

---

### 1.2 配置监控域名

编辑：

```text
domains.txt
```

一行一个域名：

```text
portal.boruxa.com
bilibili.com
www.baidu.com
```

支持注释：

```text
# Portal
portal.boruxa.com

# Other
example.com
```

---

### 1.3 配置 Teams Webhook

在 Teams / Power Automate 创建：

```text
When a Teams webhook request is received
        ↓
Post message in a chat or channel
```

Trigger 设置：

```text
Who can trigger the flow?
Anyone
```

保存 Workflow 后，从 Trigger 中复制完整的 **HTTP URL**。

本地设置：

```bash
export ALERT_WEBHOOK_URL='YOUR_WEBHOOK_URL'
```

如果复制出来的 URL 包含多余的 `\`：

```bash
export ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL//\\/}"
```

确认 URL 结构：

```bash
python3 - <<'PY'
import os
from urllib.parse import urlparse, parse_qs

u = os.environ["ALERT_WEBHOOK_URL"]
p = urlparse(u)

print("host:", p.hostname)
print("query keys:", list(parse_qs(p.query).keys()))
PY
```

正常应类似：

```text
host: xxxxx.environment.api.powerplatform.com
query keys: ['api-version', 'sp', 'sv', 'sig']
```

不要直接打印或提交完整 Webhook URL。

---

### 1.4 Curl 测试 Teams Webhook

发送测试告警：

```bash
curl -i -X POST "$ALERT_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "status_changed",
    "domain": "portal-test.example.com",
    "previous": "SAFE",
    "current": "UNSAFE",
    "time": "2026-08-21T09:00:00+08:00"
  }'
```

正常应返回：

```text
HTTP/2 202
```

并在 Teams Channel 收到类似：

```text
🚨 Safe Browsing Alert

Domain: portal-test.example.com
Previous: SAFE
Current: UNSAFE
Time: 2026-08-21T09:00:00+08:00
```

---

### 1.5 本地运行 Monitor

如果公司 Zero Trust 导致 Python 调用 Webhook 出现 SSL Certificate Error，本地测试可以临时设置：

```bash
export WEBHOOK_VERIFY_TLS=false
```

然后运行：

```bash
python app/monitor.py
```

首次发现 `UNSAFE` 时应看到：

```text
Current : UNSAFE

🚨 UNSAFE: portal.boruxa.com
🚨 FIRST CHECK AND UNSAFE

Notification events: 1
Webhook HTTP: 202
```

状态保存在：

```text
status.json
```

如果再次运行且状态没有变化：

```text
Previous: UNSAFE
Current : UNSAFE

No status change.
No notification events.
```

---

## 2. Docker

### 2.1 Build

```bash
docker buildx build \
  --platform linux/amd64 \
  -t jevinwanglb/repo:portal-monitor-v1 \
  .
```

### 2.2 Local Docker Test

```bash
mkdir -p docker-state
```

运行：

```bash
docker run --rm \
  --platform linux/amd64 \
  --ipc=host \
  -v "$(pwd)/docker-state:/data" \
  jevinwanglb/repo:portal-monitor-v1
```

状态文件会保存在：

```text
docker-state/status.json
```

### 2.3 Push

```bash
docker login
```

```bash
docker push jevinwanglb/repo:portal-monitor-v1
```

K8s 使用：

```text
jevinwanglb/repo:portal-monitor-v1
```

---

## 3. Kubernetes 首次部署

推荐结构：

```text
Namespace: portal-monitor

ConfigMap
└── domains.txt

PVC / EBS gp3
└── status.json

Secret
└── Teams Webhook URL

CronJob
└── monitor.py
```

---

### 3.1 Namespace

创建：

```bash
kubectl create namespace portal-monitor
```

设置为当前默认 Namespace：

```bash
kubectl config set-context \
  --current \
  --namespace=portal-monitor
```

确认：

```bash
kubectl config view --minify \
  -o jsonpath='{..namespace}'; echo
```

应返回：

```text
portal-monitor
```

---

### 3.2 EBS CSI / StorageClass

确认 EBS CSI Driver：

```bash
kubectl get pods -n kube-system | grep ebs
```

应看到类似：

```text
ebs-csi-controller   Running
ebs-csi-node         Running
```

创建 gp3 StorageClass：

```bash
kubectl apply -f k8s/storageclass.yaml
```

确认：

```bash
kubectl get storageclass
```

应包含：

```text
gp3   ebs.csi.aws.com
```

---

### 3.3 PVC

创建：

```bash
kubectl apply -f k8s/pvc.yaml
```

查看：

```bash
kubectl get pvc
```

首次可能显示：

```text
portal-monitor-state   Pending
```

如果 StorageClass 使用：

```text
WaitForFirstConsumer
```

这是正常的。

等 Job Pod 使用 PVC 后，EBS 才会创建并变为：

```text
portal-monitor-state   Bound
```

---

### 3.4 Domains ConfigMap

创建：

```bash
kubectl apply -f k8s/configmap.yaml
```

确认：

```bash
kubectl get configmap portal-monitor-config
```

K8s 中实际监控的域名由 ConfigMap 提供。

修改域名时只需要更新：

```text
k8s/configmap.yaml
```

然后：

```bash
kubectl apply -f k8s/configmap.yaml
```

不需要重新 Build Docker Image。

---

### 3.5 Teams Secret

本地先配置完整 Webhook URL：

```bash
export ALERT_WEBHOOK_URL='YOUR_WEBHOOK_URL'
```

如有多余 `\`：

```bash
export ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL//\\/}"
```

创建 Secret：

```bash
kubectl create secret generic portal-monitor-alert \
  --from-literal=webhook-url="$ALERT_WEBHOOK_URL"
```

确认：

```bash
kubectl get secret portal-monitor-alert
```

应看到：

```text
portal-monitor-alert   Opaque   1
```

不要把 Webhook URL 写入 Git、Dockerfile 或 Kubernetes YAML。

---

### 3.6 首次 Job 测试

先使用 Job 验证，不要直接部署 CronJob：

```bash
kubectl apply -f k8s/job.yaml
```

查看 Pod：

```bash
kubectl get pods -w
```

查看日志：

```bash
kubectl logs job/portal-monitor-test -f
```

首次发现 UNSAFE 应类似：

```text
Previous: (first check)
Current : UNSAFE

🚨 UNSAFE: portal.boruxa.com
🚨 FIRST CHECK AND UNSAFE

Notification events: 1
Webhook HTTP: 202
```

同时确认 PVC：

```bash
kubectl get pvc
```

应变为：

```text
portal-monitor-state   Bound
```

---

### 3.7 验证 EBS 状态持久化

不要删除 PVC。

删除测试 Job：

```bash
kubectl delete job portal-monitor-test
```

重新执行：

```bash
kubectl apply -f k8s/job.yaml
```

查看日志：

```bash
kubectl logs job/portal-monitor-test -f
```

如果网站状态没有变化，应看到：

```text
Previous: UNSAFE
Current : UNSAFE

No status change.
No notification events.
```

说明：

```text
Pod 1
 ↓
EBS / status.json
 ↓
Pod 结束

Pod 2
 ↓
重新挂载 EBS
 ↓
读取之前状态
 ↓
不重复 Teams 告警
```

---

### 3.8 CronJob

Job 测试通过后部署：

```bash
kubectl apply -f k8s/cronjob.yaml
```

查看：

```bash
kubectl get cronjob
```

查看执行产生的 Job：

```bash
kubectl get jobs
```

查看最新 Pod：

```bash
kubectl get pods
```

CronJob 建议：

```yaml
schedule: "*/5 * * * *"
concurrencyPolicy: Forbid
```

即：

```text
每 5 分钟检查一次
+
禁止多个 Monitor Job 同时执行
```

---

## Project Structure

```text
portal-monitor/
├── .gitignore
├── .dockerignore
├── Dockerfile
├── README.md
├── requirements.txt
├── domains.txt
│
├── app/
│   └── monitor.py
│
└── k8s/
    ├── storageclass.yaml
    ├── pvc.yaml
    ├── configmap.yaml
    ├── job.yaml
    └── cronjob.yaml
```

Runtime 文件不要提交 Git：

```text
status.json
debug_*.txt
debug_*.png
docker-state/
```

Teams Webhook URL 也不要提交 Git。

---

## State Storage

`status.json` 只保存每个域名最后一次有效状态，不保存历史。

例如：

```json
{
  "portal.boruxa.com": "UNSAFE"
}
```

因此文件不会随着 CronJob 运行次数持续增长。

状态变化：

```text
First Check → UNSAFE
→ Teams Alert
→ Save UNSAFE

UNSAFE → UNSAFE
→ No Alert

UNSAFE → SAFE
→ Teams Recovery
→ Save SAFE

SAFE → SAFE
→ No Alert
```
