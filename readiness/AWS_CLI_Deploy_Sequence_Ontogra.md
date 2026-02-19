# AWS CLI Deploy Sequence (Ontogra API)

Use this as a direct command-run order for first deploy of `api.ontogra.com`.

## 0) Set variables once
```powershell
$AWS_REGION="us-east-1"
$AWS_ACCOUNT_ID="<account-id>"
$APP_NAME="ontogra-api"
$CLUSTER_NAME="ontogra-cluster"
$SERVICE_NAME="ontogra-api-svc"
$ECR_REPO="ontogra-api"
$VPC_ID="<vpc-id>"
$SUBNET1="<subnet-id-a>"
$SUBNET2="<subnet-id-b>"
$ALB_SG="<sg-alb>"
$ECS_SG="<sg-ecs>"
$ROUTE53_ZONE_ID="<route53-zone-id>"
$CERT_ARN="<acm-cert-arn-for-api.ontogra.com>"
```

## 1) Create ECR repository
```powershell
aws ecr create-repository --repository-name $ECR_REPO --region $AWS_REGION
```

## 2) Build and push image
```powershell
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker build -t "$ECR_REPO:latest" C:\Citeline
docker tag "$ECR_REPO:latest" "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest"
```

## 3) Create ALB + target group
```powershell
$ALB_ARN=$(aws elbv2 create-load-balancer --name ontogra-api-alb --subnets $SUBNET1 $SUBNET2 --security-groups $ALB_SG --type application --scheme internet-facing --query "LoadBalancers[0].LoadBalancerArn" --output text --region $AWS_REGION)
$TG_ARN=$(aws elbv2 create-target-group --name ontogra-api-tg --protocol HTTP --port 8000 --target-type ip --vpc-id $VPC_ID --health-check-path /health --query "TargetGroups[0].TargetGroupArn" --output text --region $AWS_REGION)
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTPS --port 443 --certificates CertificateArn=$CERT_ARN --default-actions Type=forward,TargetGroupArn=$TG_ARN --region $AWS_REGION
```

## 4) Create ECS cluster
```powershell
aws ecs create-cluster --cluster-name $CLUSTER_NAME --region $AWS_REGION
```

## 5) Register task definition
Create `taskdef.json` with:
- image: `$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest`
- port mapping: `8000`
- log driver: `awslogs`
- env vars: `DATABASE_URL`, `CORS_ALLOW_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `ALLOWED_HOSTS`, `HIPAA_ENFORCEMENT=true`, `API_INTERNAL_AUTH_MODE=jwt`, `API_INTERNAL_JWT_SECRET`, `HIPAA_AUDIT_LOGGING=true`.

```powershell
aws ecs register-task-definition --cli-input-json file://taskdef.json --region $AWS_REGION
```

## 6) Create ECS service (Fargate)
```powershell
aws ecs create-service `
  --cluster $CLUSTER_NAME `
  --service-name $SERVICE_NAME `
  --task-definition $APP_NAME `
  --desired-count 2 `
  --launch-type FARGATE `
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET1,$SUBNET2],securityGroups=[$ECS_SG],assignPublicIp=DISABLED}" `
  --load-balancers "targetGroupArn=$TG_ARN,containerName=$APP_NAME,containerPort=8000" `
  --region $AWS_REGION
```

## 7) Route53 record for api subdomain
1. Get ALB DNS name:
```powershell
$ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns $ALB_ARN --query "LoadBalancers[0].DNSName" --output text --region $AWS_REGION)
```
2. Create alias `A` record `api.ontogra.com` -> ALB in hosted zone.

## 8) Update frontend env
Set in your frontend host:
- `NEXT_PUBLIC_API_URL=https://api.ontogra.com`
- `NEXTAUTH_URL=https://app.ontogra.com`
- `AUTH_SECRET=<strong-secret>`
- `API_INTERNAL_AUTH_MODE=jwt`
- `API_INTERNAL_JWT_SECRET=<same as backend>`
- `NEXT_PUBLIC_HIPAA_ENFORCEMENT=true`
- `AUTH_ALLOW_DEMO_USERS=false`
- `NEXT_PUBLIC_AUTH_ALLOW_DEMO_USERS=false`

## 9) Smoke test
```powershell
curl https://api.ontogra.com/health
```
Expected: JSON with `status=ok`.
