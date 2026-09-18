# ECS flow (Actions)

Application code stays the same. Images go to ECR. Schedule is EventBridge, not Kubernetes CronJob.

```text
git push / git tag
    ↓
Build and Push ECR Image
    ↓
972910065688.dkr.ecr.ap-east-1.amazonaws.com/portal-monitor:sha-xxxxxxx
972910065688.dkr.ecr.ap-east-1.amazonaws.com/portal-monitor:v1.x.x
    ↓
CD ECS Test  (manual, RunTask family portal-monitor-test)
    ↓
CD ECS       (manual, register portal-monitor + EventBridge target)
    ↓
EventBridge cron(0 0,6,12,18 * * ? *) UTC
    ↓
ecs:RunTask  (Fargate, EFS /data)
```

| Workflow | When |
|---|---|
| `.github/workflows/docker-publish-ecr.yml` | push `main` / `v*` / manual |
| `.github/workflows/cd-ecs-test.yml` | manual `image_tag` |
| `.github/workflows/cd-ecs.yml` | manual `image_tag` (production) |

Existing Docker Hub + EKS workflows are unchanged until cut over.

GitHub secret: `AWS_ROLE_ARN`
