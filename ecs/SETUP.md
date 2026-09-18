# ECS setup (create once)

Do not change `app/` or `Dockerfile`. This replaces EKS CronJob + PVC with Fargate + EFS.

Account: `972910065688`  
Region: `ap-east-1`  
Cluster name: `portal-monitor`  
Schedule: UTC `00:00 / 06:00 / 12:00 / 18:00`

Replace `FILE_SYSTEM_ID`, `ACCESS_POINT_*`, `SUBNET_ID_*`, `TASK_SECURITY_GROUP_ID`, `EFS_SECURITY_GROUP_ID`.

## 1. ECR

```bash
aws ecr create-repository \
  --repository-name portal-monitor \
  --region ap-east-1 \
  --image-scanning-configuration scanOnPush=true
```

## 2. IAM

See [iam/README.md](../iam/README.md).

```bash
aws iam create-role \
  --role-name portal-monitor-github-ecs \
  --assume-role-policy-document file://iam/github-actions-ecs-trust.json

aws iam put-role-policy \
  --role-name portal-monitor-github-ecs \
  --policy-name portal-monitor-github-ecs \
  --policy-document file://iam/github-actions-ecs-policy.json

aws iam create-role \
  --role-name portal-monitor-ecs-execution \
  --assume-role-policy-document file://iam/ecs-task-execution-trust.json

aws iam attach-role-policy \
  --role-name portal-monitor-ecs-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy \
  --role-name portal-monitor-ecs-execution \
  --policy-name portal-monitor-secrets \
  --policy-document file://iam/ecs-task-execution-secrets-policy.json

aws iam create-role \
  --role-name portal-monitor-ecs-task \
  --assume-role-policy-document file://iam/ecs-task-execution-trust.json

# After EFS exists, edit iam/ecs-task-efs-policy.json then:
aws iam put-role-policy \
  --role-name portal-monitor-ecs-task \
  --policy-name portal-monitor-efs \
  --policy-document file://iam/ecs-task-efs-policy.json

aws iam create-role \
  --role-name portal-monitor-events-ecs \
  --assume-role-policy-document file://iam/ecs-events-trust.json

aws iam put-role-policy \
  --role-name portal-monitor-events-ecs \
  --policy-name portal-monitor-events-ecs \
  --policy-document file://iam/ecs-events-policy.json
```

GitHub repo secret: `AWS_ROLE_ARN` = `arn:aws:iam::972910065688:role/portal-monitor-github-ecs`

GitHub Actions variables (no secret):

- `ECS_SUBNETS` — comma-separated, e.g. `subnet-aaa,subnet-bbb`
- `ECS_SECURITY_GROUP` — task SG id

## 3. Logs

```bash
aws logs create-log-group --log-group-name /ecs/portal-monitor --region ap-east-1
aws logs create-log-group --log-group-name /ecs/portal-monitor-test --region ap-east-1
```

## 4. Secret

```bash
aws secretsmanager create-secret \
  --name portal-monitor/alert-webhook \
  --secret-string 'YOUR_WEBHOOK_URL' \
  --region ap-east-1
```

Put the **full secret ARN** (including the random suffix) into both task definition `valueFrom` fields.

## 5. Network

Use private subnets with NAT (or ECR / logs / EFS VPC endpoints).  
Do not reuse jumpserver EFS (`fs-06b032fde6e10caea` is in another VPC).

Create:

- Task security group: egress HTTPS (and DNS)
- EFS security group: inbound TCP 2049 from the task SG

## 6. EFS

Create a filesystem in the same VPC as the task. Then:

```bash
aws efs create-access-point \
  --file-system-id FILE_SYSTEM_ID \
  --posix-user Uid=1000,Gid=1000 \
  --root-directory "Path=/portal-monitor,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=755}" \
  --region ap-east-1

aws efs create-access-point \
  --file-system-id FILE_SYSTEM_ID \
  --posix-user Uid=1000,Gid=1000 \
  --root-directory "Path=/portal-monitor-test,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=755}" \
  --region ap-east-1
```

Fill `FILE_SYSTEM_ID` / `ACCESS_POINT_PROD` / `ACCESS_POINT_TEST` in:

- `ecs/task-definition.json`
- `ecs/task-definition-test.json`
- `iam/ecs-task-efs-policy.json`

## 7. Cluster and first task definition

```bash
aws ecs create-cluster --cluster-name portal-monitor --region ap-east-1

# After filling EFS IDs and secret ARN:
sed "s|IMAGE_PLACEHOLDER|sha-xxxxxxx|" ecs/task-definition.json \
  | aws ecs register-task-definition --cli-input-json file:///dev/stdin --region ap-east-1

sed "s|IMAGE_PLACEHOLDER|sha-xxxxxxx|" ecs/task-definition-test.json \
  | aws ecs register-task-definition --cli-input-json file:///dev/stdin --region ap-east-1
```

## 8. EventBridge (4 times per day)

```bash
aws events put-rule \
  --cli-input-json file://ecs/eventbridge-rule.json \
  --region ap-east-1
```

Fill subnets / SG in `ecs/eventbridge-target.json`, then:

```bash
aws events put-targets \
  --cli-input-json file://ecs/eventbridge-target.json \
  --region ap-east-1
```

Later releases only change the image via `.github/workflows/cd-ecs.yml`.

## 9. Cut over

After ECS is healthy, suspend or delete the EKS CronJob so the job does not run twice.
