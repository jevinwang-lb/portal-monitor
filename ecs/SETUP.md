# Portal Monitor — ECS Fargate 完整创建流程

创建 + 发版总览见 **[FLOW.md](FLOW.md)**。本文是创建资源的 CLI。

状态文件在 **EFS `/data/status.json`**。GitHub Action（`.github/workflows/cd-ecs.yml`）只更新镜像，**不创建**下面这些资源。按顺序在本机执行（已配置 `aws` CLI，区域默认 `ap-east-1`）。

先填变量：

```bash
export AWS_REGION=ap-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export GITHUB_ORG=YOUR_GITHUB_ORG
export CLUSTER=portal-monitor
export VPC_ID=vpc-xxxxxxxx
export SUBNET_A=subnet-xxxxxxxx
export SUBNET_B=subnet-yyyyyyyy
export IMAGE=lifebytehub/portal-monitor:v1.0.0
```

JSON 里的 `YOUR_ACCOUNT_ID` / `YOUR_GITHUB_ORG` / `YOUR_CLUSTER` 用编辑器替换后再 create-role。

---

## 0. 安全组（任务出网 + EFS NFS）

```bash
ECS_SG=$(aws ec2 create-security-group \
  --group-name portal-monitor-ecs-task \
  --description "portal-monitor Fargate task" \
  --vpc-id "$VPC_ID" \
  --query GroupId --output text)

EFS_SG=$(aws ec2 create-security-group \
  --group-name portal-monitor-efs \
  --description "portal-monitor EFS" \
  --vpc-id "$VPC_ID" \
  --query GroupId --output text)

echo "ECS_SG=$ECS_SG"
echo "EFS_SG=$EFS_SG"

# 任务：HTTPS 出网（拉镜像、Google、Webhook）
aws ec2 authorize-security-group-egress \
  --group-id "$ECS_SG" \
  --ip-permissions 'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]'

# 任务 → EFS
aws ec2 authorize-security-group-egress \
  --group-id "$ECS_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=2049,ToPort=2049,UserIdGroupPairs=[{GroupId=$EFS_SG}]"

# EFS ← 任务
aws ec2 authorize-security-group-ingress \
  --group-id "$EFS_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=2049,ToPort=2049,UserIdGroupPairs=[{GroupId=$ECS_SG}]"
```

默认安全组往往已有全部 egress；若 create 时报 egress 已存在，忽略即可。`AssignPublicIp=ENABLED` 时任务要放在 **public subnet**（有 IGW 路由），否则拉不了 Docker Hub。

---

## 1. EFS（状态盘）

```bash
EFS_ID=$(aws efs create-file-system \
  --encrypted \
  --performance-mode generalPurpose \
  --throughput-mode bursting \
  --tags Key=Name,Value=portal-monitor-state \
  --query FileSystemId --output text)

echo "EFS_ID=$EFS_ID"

aws efs create-mount-target \
  --file-system-id "$EFS_ID" \
  --subnet-id "$SUBNET_A" \
  --security-groups "$EFS_SG"

aws efs create-mount-target \
  --file-system-id "$EFS_ID" \
  --subnet-id "$SUBNET_B" \
  --security-groups "$EFS_SG"

# Playwright 镜像用户一般为 uid 1000
AP_ID=$(aws efs create-access-point \
  --file-system-id "$EFS_ID" \
  --posix-user Uid=1000,Gid=1000 \
  --root-directory "Path=/portal-monitor,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=0755}" \
  --tags Key=Name,Value=portal-monitor-data \
  --query AccessPointId --output text)

echo "AP_ID=$AP_ID"
```

容器里看到的就是 `/data` → 这里的 `/portal-monitor`（`status.json`、debug 文件）。

测试环境另建 Access Point：`Path=/portal-monitor-test`。

---

## 2. Secrets Manager

Webhook（纯字符串，不要提交 Git）：

```bash
aws secretsmanager create-secret \
  --name portal-monitor/alert-webhook-url \
  --secret-string "$ALERT_WEBHOOK_URL"
```

Docker Hub（Fargate 拉私有镜像；JSON 格式）：

```bash
aws secretsmanager create-secret \
  --name portal-monitor/dockerhub \
  --secret-string "{\"username\":\"$DOCKERHUB_LIFEBYTE_DEPLOYER_USERNAME\",\"password\":\"$DOCKERHUB_LIFEBYTE_DEPLOYER_TOKEN\"}"
```

记下两个 secret 的完整 ARN（带随机后缀），填进 `ecs/task-definition.json` 的 `valueFrom` / `credentialsParameter`。

---

## 3. IAM

详见各 JSON。顺序：OIDC → GitHub 部署 Role → 执行 Role → Task Role → EventBridge Role。

```bash
# 3.1 账号里若还没有 GitHub OIDC
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com

# 3.2 GitHub Actions 部署
# 先改 iam/github-actions-ecs-trust.json 和 iam/github-actions-ecs-policy.json
aws iam create-role \
  --role-name portal-monitor-github-ecs \
  --assume-role-policy-document file://iam/github-actions-ecs-trust.json

aws iam put-role-policy \
  --role-name portal-monitor-github-ecs \
  --policy-name portal-monitor-github-ecs \
  --policy-document file://iam/github-actions-ecs-policy.json

# 3.3 执行角色（拉镜像、读 secret、写日志）
aws iam create-role \
  --role-name portal-monitor-ecs-execution \
  --assume-role-policy-document file://iam/ecs-task-execution-trust.json

aws iam attach-role-policy \
  --role-name portal-monitor-ecs-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy \
  --role-name portal-monitor-ecs-execution \
  --policy-name portal-monitor-ecs-execution-secrets \
  --policy-document file://iam/ecs-task-execution-secrets-policy.json

# 3.4 任务角色（容器进程；EFS 用 access point + 安全组即可，可不加 IAM auth）
aws iam create-role \
  --role-name portal-monitor-ecs-task \
  --assume-role-policy-document file://iam/ecs-task-execution-trust.json

# 3.5 EventBridge → RunTask
aws iam create-role \
  --role-name portal-monitor-events-ecs \
  --assume-role-policy-document file://iam/ecs-events-trust.json

aws iam put-role-policy \
  --role-name portal-monitor-events-ecs \
  --policy-name portal-monitor-events-ecs \
  --policy-document file://iam/ecs-events-policy.json
```

GitHub 仓库 Secret：

```text
AWS_ROLE_ARN=arn:aws:iam::<ACCOUNT>:role/portal-monitor-github-ecs
```

---

## 4. CloudWatch Logs + ECS cluster

```bash
aws logs create-log-group --log-group-name /ecs/portal-monitor

aws ecs create-cluster --cluster-name "$CLUSTER"
```

---

## 5. 第一条 Task definition

编辑 `ecs/task-definition.json`：

- `YOUR_ACCOUNT_ID`
- `fs-YOUR_EFS_ID` / `fsap-YOUR_ACCESS_POINT_ID`
- secret ARN
- `REPLACE_IMAGE_TAG`

若镜像是 **ECR 且公有拉策略或 execution role 能拉**，删掉 `repositoryCredentials` 整段。

```bash
aws ecs register-task-definition \
  --cli-input-json file://ecs/task-definition.json
```

---

## 6. 先手动跑一次（确认盘和告警）

```bash
aws ecs run-task \
  --cluster "$CLUSTER" \
  --launch-type FARGATE \
  --platform-version LATEST \
  --task-definition portal-monitor \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$ECS_SG],assignPublicIp=ENABLED}"
```

```bash
aws ecs list-tasks --cluster "$CLUSTER"
aws logs tail /ecs/portal-monitor --follow
```

日志里应有 `State saved: /data/status.json`。

---

## 7. EventBridge 每 10 分钟

```bash
aws events put-rule \
  --name portal-monitor-schedule \
  --schedule-expression "rate(10 minutes)" \
  --state DISABLED
```

先 `DISABLED`，等切流再打开。

编辑 `ecs/eventbridge-target.json`（cluster、subnet、`sg-YOUR_ECS_TASK_SG`、account）。

```bash
aws events put-targets \
  --rule portal-monitor-schedule \
  --targets file://ecs/eventbridge-target.json
```

`ecs-events-policy.json` 里的 `YOUR_CLUSTER` 必须和这里的 cluster 名一致。

---

## 8. 从 EKS 切过来

```bash
kubectl patch cronjob portal-monitor -n portal-monitor \
  --type merge -p '{"spec":{"suspend":true}}'

aws events enable-rule --name portal-monitor-schedule
```

不要两边同时跑，否则两份状态、可能重复告警。

---

## 9. 以后发版

GitHub Actions → **CD - Deploy ECS** → 填 `image_tag`。  
它会：新 task revision（只换镜像）→ EventBridge 指向新 revision。

---

## 资源一览

| 资源 | 名称 | 作用 |
|---|---|---|
| EFS | `portal-monitor-state` | `/data/status.json` |
| Access Point | `/portal-monitor` | 状态目录 |
| Secret | `portal-monitor/alert-webhook-url` | Teams |
| Secret | `portal-monitor/dockerhub` | 拉私有镜像 |
| Cluster | `portal-monitor` | Fargate |
| Task family | `portal-monitor` | 容器定义 |
| Rule | `portal-monitor-schedule` | 每 10 分钟 |
| Role | `portal-monitor-github-ecs` | CD |
| Role | `portal-monitor-ecs-execution` | 拉镜像 |
| Role | `portal-monitor-ecs-task` | 跑进程 |
| Role | `portal-monitor-events-ecs` | 调度 RunTask |
