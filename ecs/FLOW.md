# 创建 + 发布（ECS Fargate）

状态：`EFS → /data/status.json`  
镜像：`lifebytehub/portal-monitor:<tag>`  
调度：EventBridge `rate(10 minutes)` → ECS `RunTask`

CLI 细节（安全组、EFS、IAM、register-task-definition）见 [SETUP.md](SETUP.md)。  
本文是 **先创建一次、再怎么发版**。

---

## A. 创建（只做一次）

```text
填变量（账号 / VPC / subnet / 镜像 tag）
        ↓
0  安全组（任务 443、EFS 2049）
1  EFS + Access Point /portal-monitor
2  Secrets Manager（webhook、Docker Hub）
3  IAM
     OIDC token.actions.githubusercontent.com
     portal-monitor-github-ecs      GitHub CD
     portal-monitor-ecs-execution   拉镜像 + 读 secret
     portal-monitor-ecs-task        跑容器
     portal-monitor-events-ecs      EventBridge RunTask
4  CloudWatch /ecs/portal-monitor + ECS cluster
5  编辑 ecs/task-definition.json → register-task-definition
6  aws ecs run-task 手工跑通（看日志 State saved）
7  EventBridge 规则 portal-monitor-schedule（先 DISABLED）
8  kubectl patch cronjob … suspend:true
   aws events enable-rule
9  GitHub Secret AWS_ROLE_ARN
```

完成标志：

- `run-task` 日志有 `State saved: /data/status.json`
- `aws events describe-rule --name portal-monitor-schedule` 为 `ENABLED`（切流后）
- EKS CronJob `SUSPEND=True`

---

## B. 发布

分 **打镜像** 和 **让 ECS 用这张镜像**。不会自动连在一起，避免 SHA 直接上生产。

### B1. 开发镜像（每次 push main，且改了 app / Dockerfile 等）

工作流：`docker-publish.yml`

```text
git push origin main
        ↓
CI：Build and Push Docker Image
        ↓
lifebytehub/portal-monitor:sha-<7位>
```

这张图 **不要** 直接给 EventBridge。可选：本机或 `aws ecs run-task` 换测试 Access Point 验证。

### B2. 生产镜像（打 tag）

在 **已经验证过的那个 commit** 上打 tag（不要再多推几笔再标）：

```bash
git log -1 --oneline
git tag v1.0.1
git push origin v1.0.1
```

```text
tag v1.0.1
        ↓
CI 再构建一次
        ↓
lifebytehub/portal-monitor:v1.0.1
```

Docker Hub 上确认 tag 存在、且 deployer 能 pull。

### B3. 发布到 ECS（换线上任务定义）

工作流：`cd-ecs.yml`（手动）

1. GitHub → Actions → **CD - Deploy ECS** → Run workflow  
2. `image_tag` 填 `v1.0.1`（不要填 `sha-…` 除非你明确要测 SHA）  
3. 等待成功  

它会：

```text
describe 现有 family portal-monitor
        ↓
只改 container image
        ↓
register-task-definition → 新 revision
        ↓
EventBridge 目标改成新 TaskDefinitionArn
```

下次调度（最多 10 分钟）用新镜像。不立刻跑一次。要马上跑：

```bash
aws ecs run-task \
  --cluster portal-monitor \
  --launch-type FARGATE \
  --task-definition portal-monitor \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-A,subnet-B],securityGroups=[sg-ECS],assignPublicIp=ENABLED}"
```

### B4. 发布后检查

```bash
# 当前 family 最新镜像
aws ecs describe-task-definition \
  --task-definition portal-monitor \
  --query 'taskDefinition.{rev:revision,image:containerDefinitions[0].image}'

# EventBridge 是不是指到同一份
aws events list-targets-by-rule \
  --rule portal-monitor-schedule \
  --query 'Targets[0].EcsParameters.TaskDefinitionArn'

# 最近一次任务
aws ecs list-tasks --cluster portal-monitor --desired-status STOPPED
aws logs tail /ecs/portal-monitor --since 30m
```

日志里应看到 `State saved: /data/status.json`。状态在 EFS，发版 **不会清空** `status.json`。

### B5. 回滚

再跑一次 **CD - Deploy ECS**，`image_tag` 填上一个好的版本（例如 `v1.0.0`）。  
或控制台把 EventBridge 目标改回旧 `portal-monitor:revision`。

---

## 日常发版（最短）

```bash
# 1. 代码合进 main，等 SHA 构建成功（可选自测）
# 2. 打生产 tag
git tag v1.0.2
git push origin v1.0.2
# 3. 等 Docker Hub 出现 v1.0.2
# 4. Actions → CD - Deploy ECS → image_tag=v1.0.2
# 5. 看 /ecs/portal-monitor 日志
```

---

## 改域名

`domains.txt` 在镜像里。改完必须走 B1/B2 出新镜像，再 B3。  
只改 k8s ConfigMap **不会**作用到 ECS。

Webhook：改 Secrets Manager `portal-monitor/alert-webhook-url`，下一轮任务生效，不用发版。

---

## 和 EKS 发布的关系

| | EKS（旧） | ECS（新） |
|---|---|---|
| 构建 | `docker-publish.yml` 相同 | 相同 |
| 测试 | `cd-test-job.yml` + Test Job | 可选 `run-task` + 测试 Access Point |
| 生产 | `cd-cronjob.yml` + CronJob | **`cd-ecs.yml` + EventBridge** |

切到 ECS 后不要再跑 `cd-cronjob.yml`，除非 CronJob 已 suspend 且你清楚不会双跑。
