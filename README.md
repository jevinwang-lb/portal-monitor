# Portal Safe Browsing Monitor

定时检查 Google Safe Browsing Transparency Report 中配置域名 / URL 的安全状态，并在状态发生变化时通过 Microsoft Teams Workflow Webhook 发送通知。

当前运行方式：

```text
Google Transparency Report
        ↓
Python + Playwright
        ↓
SAFE / UNSAFE / UNKNOWN / NO_DATA
        ↓
status.json 状态比较
        ↓
状态变化
        ↓
Power Automate Webhook
        ↓
Microsoft Teams
```

Production 运行在 Kubernetes CronJob 中，每 10 分钟检查一次。

---

## 1. Status

当前支持：

| Status | Description |
|---|---|
| `SAFE` | Google 明确返回安全 |
| `UNSAFE` | Google 判定网站或部分页面存在风险 |
| `UNKNOWN` | Google 无法明确判断 |
| `NO_DATA` | Google 暂无该站点数据 |
| `CHECK_ERROR` | 页面访问或检测过程异常 |

支持识别的 UNSAFE 页面结果包括：

```text
This site is unsafe
Some pages on this site are unsafe
Contains harmful content
```

已使用 Google Safe Browsing 测试 URL 验证：

```text
MALWARE
SOCIAL_ENGINEERING
UNWANTED_SOFTWARE
```

当前统一识别为：

```text
UNSAFE
```

---

## 2. Alert Logic

首次发现：

```text
FIRST CHECK
    ↓
UNSAFE
    ↓
Teams Alert
    ↓
保存 UNSAFE
```

持续异常：

```text
UNSAFE → UNSAFE
→ No status change
→ 不重复告警
```

恢复：

```text
UNSAFE → SAFE
→ Teams Alert
→ 保存 SAFE
```

持续正常：

```text
SAFE → SAFE
→ 不通知
```

`UNKNOWN / NO_DATA / CHECK_ERROR` 不覆盖之前已经存在的有效 `SAFE / UNSAFE` 状态。

---

## 3. Project Structure

```text
portal-monitor/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── cd-test.yml
│       └── cd-cronjob.yml
│
├── app/
│   └── monitor.py
│
├── k8s/
│   ├── storageclass.yaml
│   ├── pvc.yaml
│   ├── test-pvc.yaml
│   ├── configmap.yaml
│   ├── job.yaml
│   └── cronjob.yaml
│
├── Dockerfile
├── requirements.txt
├── domains.txt
└── README.md
```

Runtime 文件不要提交 Git：

```text
status.json
debug_*.txt
debug_*.png
docker-state/
.venv/
.env
```

---

## 4. Local Setup

## Create Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装：

```bash
python -m pip install -r requirements.txt
```

Local macOS 使用本机 Google Chrome。

---

## 5. Configure Domains

编辑：

```text
domains.txt
```

例如：

```text
portal.boruxa.com
bilibili.com
www.baidu.com
```

也支持具体 URL/path：

```text
testsafebrowsing.appspot.com/apiv4/ANY_PLATFORM/MALWARE/URL/
```

一行一个。

支持注释：

```text
# Production
portal.boruxa.com

# Test
testsafebrowsing.appspot.com/apiv4/ANY_PLATFORM/MALWARE/URL/
```

---

## 6. Teams Webhook

Teams / Power Automate Workflow：

```text
When a Teams webhook request is received
        ↓
Post message in a chat or channel
```

保存 Workflow 后复制 Trigger 的完整 HTTP URL。

设置：

```bash
export ALERT_WEBHOOK_URL='YOUR_WEBHOOK_URL'
```

如果复制出来的 URL 包含 `\`：

```bash
export ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL//\\/}"
```

检查 URL 结构：

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

不要输出或提交完整 Webhook URL。

---

## 7. Test Teams Webhook

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

正常：

```text
HTTP/2 202
```

Teams 应收到：

```text
Safe Browsing Alert

Domain: portal-test.example.com
Previous: SAFE
Current: UNSAFE
```

---

## 8. Local Run

如果公司 Zero Trust 导致 Python Webhook SSL verification error，本地测试可临时：

```bash
export WEBHOOK_VERIFY_TLS=false
```

运行：

```bash
python app/monitor.py
```

正常示例：

```text
Checking: portal.boruxa.com

Previous: UNSAFE
Current : UNSAFE

No status change.
```

首次发现 UNSAFE：

```text
Previous: (first check)
Current : UNSAFE

UNSAFE: portal.boruxa.com
FIRST CHECK AND UNSAFE

Webhook HTTP: 202
```

Local 状态保存在：

```text
status.json
```

---

## 9. Docker

Build：

```bash
docker buildx build \
  --platform linux/amd64 \
  -t jevinwanglb/portal-monitor:test \
  .
```

Push：

```bash
docker login -u jevinwanglb
```

然后：

```bash
docker push jevinwanglb/portal-monitor:test
```

正式 CI 使用：

```text
jevinwanglb/portal-monitor
```

---

## 10. Docker Image Version

开发提交使用 Git SHA：

```text
jevinwanglb/portal-monitor:sha-96b8ec3
```

正式 Release：

```text
jevinwanglb/portal-monitor:v1.0.0
jevinwanglb/portal-monitor:v1.0.1
```

推荐流程：

```text
main push
   ↓
CI
   ↓
sha-xxxxxxx
   ↓
Test Job
   ↓
验证
   ↓
Git Tag v1.x.x
   ↓
Production CronJob
```

---

## 11. Kubernetes Architecture

Namespace：

```text
portal-monitor
```

结构：

```text
portal-monitor
│
├── ConfigMap
│   └── portal-monitor-config
│       └── domains.txt
│
├── Secret
│   └── portal-monitor-alert
│       └── Teams Webhook
│
├── Test PVC
│   └── portal-monitor-state-test
│
├── Production PVC
│   └── portal-monitor-state
│
├── Test Job
│   └── portal-monitor-test
│
└── Production CronJob
    └── portal-monitor
```

Test 与 Production 使用不同 PVC，避免测试修改 Production 状态。

---

## 12. Namespace

首次创建：

```bash
kubectl create namespace portal-monitor
```

设置当前 context：

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

## 13. EBS CSI / StorageClass

确认 EBS CSI：

```bash
kubectl get pods -n kube-system | grep ebs
```

应看到：

```text
ebs-csi-controller
ebs-csi-node
```

确认 StorageClass：

```bash
kubectl get storageclass
```

Production 使用：

```text
gp3
```

Provisioner：

```text
ebs.csi.aws.com
```

---

## 14. Production PVC

```bash
kubectl apply -f k8s/pvc.yaml
```

PVC：

```text
portal-monitor-state
```

挂载：

```text
/data
```

状态文件：

```text
/data/status.json
```

---

## 15. Test PVC

```bash
kubectl apply -f k8s/test-pvc.yaml
```

PVC：

```text
portal-monitor-state-test
```

Test Job 使用该 PVC，不修改 Production `status.json`。

查看：

```bash
kubectl get pvc
```

可能先显示：

```text
Pending
```

如果 StorageClass 是：

```text
WaitForFirstConsumer
```

属于正常现象。

Pod 创建后 EBS 会动态创建并变成：

```text
Bound
```

---

## 16. ConfigMap

域名配置：

```bash
kubectl apply -f k8s/configmap.yaml
```

查看：

```bash
kubectl get configmap portal-monitor-config
```

修改域名只需要更新：

```text
k8s/configmap.yaml
```

然后：

```bash
kubectl apply -f k8s/configmap.yaml
```

不需要重新 Build Docker Image。

---

## 17. Teams Secret

本地：

```bash
export ALERT_WEBHOOK_URL='YOUR_WEBHOOK_URL'
```

创建：

```bash
kubectl create secret generic portal-monitor-alert \
  --from-literal=webhook-url="$ALERT_WEBHOOK_URL"
```

确认：

```bash
kubectl get secret portal-monitor-alert
```

不要把 Webhook URL 提交到 Git。

---

## 18. Test Job

Test 环境使用：

```text
Image: sha-xxxxxxx
PVC: portal-monitor-state-test
Workload: Job
```

查看：

```bash
kubectl get jobs
```

日志：

```bash
kubectl logs job/portal-monitor-test -f
```

Test Job 完成后：

```text
STATUS: Complete
```

不会持续占用 CPU / Memory。

---

## 19. Production CronJob

Production：

```text
Image: v1.x.x
PVC: portal-monitor-state
Schedule: every 10 minutes
```

查看：

```bash
kubectl get cronjob portal-monitor
```

当前 Schedule：

```text
*/10 * * * *
```

即：

```text
00
10
20
30
40
50
```

分钟执行。

CronJob 使用：

```yaml
concurrencyPolicy: Forbid
```

避免 CronJob 自身产生多个并发 Job。

---

## 20. Manual Trigger CronJob

无需等待 10 分钟：

```bash
kubectl create job \
  --from=cronjob/portal-monitor \
  portal-monitor-manual-test
```

查看：

```bash
kubectl logs \
  job/portal-monitor-manual-test \
  -f
```

完成后删除：

```bash
kubectl delete job portal-monitor-manual-test
```

注意：

`concurrencyPolicy: Forbid` 只限制 CronJob 自动创建的 Job，不限制手工创建的 Job。

---

## 21. Suspend Production CronJob

测试期间如果不希望 Production 自动运行：

```bash
kubectl patch cronjob portal-monitor \
  -p '{"spec":{"suspend":true}}'
```

恢复：

```bash
kubectl patch cronjob portal-monitor \
  -p '{"spec":{"suspend":false}}'
```

确认：

```bash
kubectl get cronjob portal-monitor
```

---

## 22. CI/CD

## CI

GitHub Actions：

```text
main push
   ↓
Build Docker
   ↓
Push Docker Hub
   ↓
sha-xxxxxxx
```

例如：

```text
jevinwanglb/portal-monitor:sha-c0691a8
```

Git Tag：

```bash
git tag v1.0.1
git push origin v1.0.1
```

生成：

```text
jevinwanglb/portal-monitor:v1.0.1
```

---

## Test CD

Test CD：

```text
CI success
    ↓
CD Test
    ↓
Deploy sha-xxxxxxx
    ↓
portal-monitor-test
    ↓
portal-monitor-state-test
    ↓
Completed
```

Test Job 自动使用最新 SHA Image。

---

## Production CD

Production：

```text
Test Passed
    ↓
Release v1.x.x
    ↓
CD Production
    ↓
Update CronJob
    ↓
Production PVC
```

查看 Production 当前 Image：

```bash
kubectl get cronjob portal-monitor \
  -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'; echo
```

例如：

```text
jevinwanglb/portal-monitor:v1.0.0
```

---

## 23. Debug PVC

Job / CronJob Pod 完成后：

```text
STATUS = Succeeded / Completed
```

不能再：

```bash
kubectl exec
```

例如会出现：

```text
cannot exec into a container in a completed pod
```

此时可以创建临时 Debug Pod 挂载 PVC。

---

## Debug Production PVC

```bash
kubectl run pvc-debug \
  -n portal-monitor \
  --image=busybox \
  --restart=Never \
  --overrides='
{
  "spec": {
    "containers": [{
      "name": "pvc-debug",
      "image": "busybox",
      "command": ["sh", "-c", "sleep 3600"],
      "volumeMounts": [{
        "name": "state",
        "mountPath": "/data"
      }]
    }],
    "volumes": [{
      "name": "state",
      "persistentVolumeClaim": {
        "claimName": "portal-monitor-state"
      }
    }]
  }
}'
```

确认：

```bash
kubectl get pod pvc-debug
```

进入：

```bash
kubectl exec -it pvc-debug -- sh
```

查看：

```sh
ls -lah /data
```

查看状态：

```sh
cat /data/status.json
```

可能还会看到：

```text
debug_bilibili.com.txt
debug_bilibili.com.png
debug_www.baidu.com.txt
debug_www.baidu.com.png
```

退出：

```sh
exit
```

删除 Debug Pod：

```bash
kubectl delete pod pvc-debug
```

---

## Debug Test PVC

如果需要查看 Test 状态，只需要把：

```text
portal-monitor-state
```

换成：

```text
portal-monitor-state-test
```

即：

```json
"persistentVolumeClaim": {
  "claimName": "portal-monitor-state-test"
}
```

然后：

```bash
kubectl exec -it pvc-debug -- sh
```

查看：

```sh
cat /data/status.json
```

---

## 24. Debug Files

当 Google 页面无法得到明确状态时，Monitor 会保存 Debug 信息：

```text
/data/debug_<domain>.txt
/data/debug_<domain>.png
```

例如：

```text
/data/debug_bilibili.com.txt
/data/debug_bilibili.com.png
```

用于确认 Google Transparency Report 实际返回的页面内容。

这些文件只用于排查，不应提交 Git。

---

## 25. Useful Commands

查看 Pod：

```bash
kubectl get pods
```

只看 Running：

```bash
kubectl get pods \
  --field-selector=status.phase=Running
```

查看 Job：

```bash
kubectl get jobs
```

查看 CronJob：

```bash
kubectl get cronjob
```

查看 PVC：

```bash
kubectl get pvc
```

查看 PV：

```bash
kubectl get pv
```

查看 Production Image：

```bash
kubectl get cronjob portal-monitor \
  -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'; echo
```

查看 Test Job Image：

```bash
kubectl get job portal-monitor-test \
  -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```

查看日志：

```bash
kubectl logs job/portal-monitor-test
```

查看 CronJob 最近产生的 Jobs：

```bash
kubectl get jobs \
  --sort-by=.metadata.creationTimestamp
```

---

## 26. Google Web Risk

最初方案也考虑直接使用 Google Web Risk API。

Web Risk 可以直接进行 URL threat checking，但依赖：

```text
Google Cloud Project
Google Cloud API
Credential / IAM
```

当前环境没有对应 Google Cloud 配置，因此目前 POC 使用公开的：

```text
Google Safe Browsing Transparency Report
```

配合：

```text
Python + Playwright + Chromium
```

进行检测。

后续如果具备 Google Cloud 条件，可再评估切换至 Web Risk API。

---

## 27. Current Deployment Model

最终流程：

```text
Developer
   │
   └── git push main
          ↓
         CI
          ↓
Docker Hub :sha-xxxxxxx
          ↓
     Automatic Test CD
          ↓
       Test Job
          ↓
 Test PVC / status.json
          ↓
       Validation
          ↓
      Git Tag v1.x.x
          ↓
 Docker Hub :v1.x.x
          ↓
    Production CD
          ↓
 Production CronJob
          ↓
 Every 10 Minutes
          ↓
 Google Transparency Report
          ↓
      Status Change
          ↓
      Teams Alert
```
