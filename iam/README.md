# IAM roles for ECS CD (create manually)

完整创建顺序（安全组、EFS、Secret、Cluster、Task、EventBridge、切流）见 **[ecs/SETUP.md](../ecs/SETUP.md)**。

Based on:

- [Configuring OpenID Connect in Amazon Web Services](https://docs.github.com/en/actions/how-tos/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [Create an OpenID Connect identity provider in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
- [AmazonECSTaskExecutionRolePolicy](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonECSTaskExecutionRolePolicy.html)

| 文件 | Role |
|---|---|
| `github-actions-ecs-trust.json` + `github-actions-ecs-policy.json` | `portal-monitor-github-ecs` |
| `ecs-task-execution-trust.json` + AWS managed `AmazonECSTaskExecutionRolePolicy` + `ecs-task-execution-secrets-policy.json` | `portal-monitor-ecs-execution` |
| `ecs-task-execution-trust.json` | `portal-monitor-ecs-task` |
| `ecs-events-trust.json` + `ecs-events-policy.json` | `portal-monitor-events-ecs` |
