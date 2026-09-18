# IAM roles for ECS CD

Create these roles in account `972910065688` (`ap-east-1`). Full order: [ecs/SETUP.md](../ecs/SETUP.md).

GitHub OIDC provider already exists:

`arn:aws:iam::972910065688:oidc-provider/token.actions.githubusercontent.com`

| File | Role |
|---|---|
| `github-actions-ecs-trust.json` + `github-actions-ecs-policy.json` | `portal-monitor-github-ecs` |
| `ecs-task-execution-trust.json` + `AmazonECSTaskExecutionRolePolicy` + `ecs-task-execution-secrets-policy.json` | `portal-monitor-ecs-execution` |
| `ecs-task-execution-trust.json` + `ecs-task-efs-policy.json` | `portal-monitor-ecs-task` |
| `ecs-events-trust.json` + `ecs-events-policy.json` | `portal-monitor-events-ecs` |

Replace `FILE_SYSTEM_ID` / `ACCESS_POINT_*` in `ecs-task-efs-policy.json` after EFS exists.

If this repo is not `jevinwang-lb/portal-monitor`, edit the `sub` in `github-actions-ecs-trust.json`.
