#!/usr/bin/env bash
# Read-only: can the app be deployed into the resources the cloud team already created
# (sympany-spl-* / social-listening-*) without any IAM change?   ->   bash check-reuse.sh
#
# Only describe / get / list calls and iam simulate-principal-policy; nothing is changed.

set -uo pipefail
export AWS_DEFAULT_REGION=eu-central-2
REGION=eu-central-2
FAILS=0
ok()   { printf '  \033[32mOK  \033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS + 1)); }
info() { printf '       %s\n' "$*"; }

ACC=$(aws sts get-caller-identity --query Account --output text) || { echo "AWS CLI not signed in"; exit 1; }
ME=$(aws sts get-caller-identity --query Arn --output text)
case "$ME" in *:assumed-role/*) R=${ME#*:assumed-role/}; ME=$(aws iam get-role --role-name "${R%%/*}" --query Role.Arn --output text) ;; esac
ROLE=$(aws iam get-role --role-name sympany-spl-task-execution-role --query Role.Arn --output text)
ALB=$(aws elbv2 describe-load-balancers --names sympany-spl-ext-alb --query 'LoadBalancers[0].LoadBalancerArn' --output text)
L80=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB" --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text)
VPC=vpc-xxxxxxxx
CTX="ContextKeyName=aws:RequestedRegion,ContextKeyValues=$REGION,ContextKeyType=string"
arn() { printf 'arn:aws:%s:%s:%s:%s' "$1" "$REGION" "$ACC" "$2"; }
sim() {  # <principal> <action> <resource...> [-- context entries]
  local p=$1 a=$2 d; shift 2
  local res=() ctx=("$CTX")
  while [ $# -gt 0 ]; do [ "$1" = "--" ] && { shift; ctx+=("$@"); break; }; res+=("$1"); shift; done
  d=$(aws iam simulate-principal-policy --policy-source-arn "$p" --action-names "$a" --resource-arns "${res[@]}" \
        --context-entries "${ctx[@]}" --query 'EvaluationResults[0].EvalDecision' --output text 2>&1)
  if [ "$d" = "allowed" ]; then ok "$a"; else bad "$a  (${res[*]}) -> $d"; fi
}

echo "== You ($ME): deploy into the existing cluster / load balancer"
sim "$ME" iam:PassRole "$ROLE" -- "ContextKeyName=iam:PassedToService,ContextKeyValues=ecs-tasks.amazonaws.com,ContextKeyType=string"
sim "$ME" ecs:RegisterTaskDefinition "*"
sim "$ME" ecs:CreateService "$(arn ecs service/sympany-spl-ecs-cluster/sympany-socmon-web)"
sim "$ME" ecs:UpdateService "$(arn ecs service/sympany-spl-ecs-cluster/sympany-socmon-web)"
sim "$ME" elasticloadbalancing:CreateTargetGroup "$(arn elasticloadbalancing targetgroup/sympany-socmon-web/0123456789abcdef)"
sim "$ME" elasticloadbalancing:CreateListener "$ALB"
sim "$ME" elasticloadbalancing:ModifyListener "$L80"
sim "$ME" elasticloadbalancing:ModifyLoadBalancerAttributes "$ALB"
sim "$ME" ec2:CreateSecurityGroup "$(arn ec2 vpc/$VPC)" "$(arn ec2 security-group/*)"
sim "$ME" ec2:AuthorizeSecurityGroupIngress "$(arn ec2 security-group/*)"
for A in ecr:GetAuthorizationToken; do sim "$ME" "$A" "*"; done
for A in ecr:CreateRepository ecr:InitiateLayerUpload ecr:UploadLayerPart ecr:CompleteLayerUpload ecr:PutImage ecr:BatchCheckLayerAvailability; do
  sim "$ME" "$A" "$(arn ecr repository/sympany-socmon)"
done
sim "$ME" ssm:PutParameter "$(arn ssm parameter/ecsapp/APP_USERS)"
sim "$ME" logs:CreateLogGroup "$(arn logs log-group:/ecs/app)"
sim "$ME" dynamodb:UpdateTimeToLive "$(arn dynamodb table/social-listening-posts)"

echo; echo "== Their role ($ROLE): what the app would do with it"
sim "$ROLE" logs:CreateLogStream "$(arn logs log-group:/ecs/app:log-stream:web/x)"
sim "$ROLE" logs:PutLogEvents "$(arn logs log-group:/ecs/app:log-stream:web/x)"
sim "$ROLE" ssm:GetParameters "$(arn ssm parameter/ecsapp/APP_USERS)"
sim "$ROLE" ecr:BatchGetImage "$(arn ecr repository/sympany-socmon)"
for T in social-listening-posts social-listening-risk-compliance-audit; do
  for A in dynamodb:Query dynamodb:PutItem dynamodb:UpdateItem dynamodb:BatchWriteItem dynamodb:GetItem; do sim "$ROLE" "$A" "$(arn dynamodb table/$T)"; done
done
sim "$ROLE" bedrock:InvokeModel "arn:aws:bedrock:$REGION::foundation-model/qwen.qwen3-235b-a22b-2507-v1:0"
sim "$ROLE" bedrock:InvokeModel "arn:aws:bedrock:$REGION::foundation-model/qwen.qwen3-vl-235b-a22b"
for A in transcribe:StartTranscriptionJob transcribe:GetTranscriptionJob transcribe:DeleteTranscriptionJob; do sim "$ROLE" "$A" "*"; done
for A in s3:PutObject s3:GetObject s3:DeleteObject; do sim "$ROLE" "$A" "arn:aws:s3:::sympany-social-listening-media/transcribe/x.flac"; done
sim "$ROLE" sns:Publish "$(arn sns sympany-social-listening-alerts)"

echo; echo "== Facts about the existing resources"
for T in social-listening-posts social-listening-sentiment social-listening-risk-compliance-audit; do
  info "$T: $(aws dynamodb describe-table --table-name "$T" --query 'Table.[join(`,`,KeySchema[].join(`:`,[AttributeName,KeyType])),join(`,`,AttributeDefinitions[].join(`:`,[AttributeName,AttributeType])),ItemCount,TableStatus]' --output text 2>&1)"
  info "    TTL: $(aws dynamodb describe-time-to-live --table-name "$T" --query 'TimeToLiveDescription.[TimeToLiveStatus,AttributeName]' --output text 2>&1)"
done
info "media bucket encryption: $(aws s3api get-bucket-encryption --bucket sympany-social-listening-media --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.[SSEAlgorithm,KMSMasterKeyID]' --output text 2>&1)"
info "log group /ecs/app: $(aws logs describe-log-groups --log-group-name-prefix /ecs/app --query 'logGroups[].logGroupName' --output text 2>&1)"
info "parameters under /ecsapp: $(aws ssm describe-parameters --parameter-filters Key=Path,Values=/ecsapp --query 'Parameters[].Name' --output text 2>&1)"
info "cluster: $(aws ecs describe-clusters --clusters sympany-spl-ecs-cluster --query 'clusters[0].[status,join(`,`,capacityProviders),runningTasksCount]' --output text 2>&1)"
info "services in cluster: $(aws ecs list-services --cluster sympany-spl-ecs-cluster --query 'serviceArns' --output text 2>&1)"
info "ALB listeners: $(aws elbv2 describe-listeners --load-balancer-arn "$ALB" --query 'Listeners[].[Port,DefaultActions[0].Type]' --output text 2>&1 | tr '\n\t' '; ')"
info "target groups: $(aws elbv2 describe-target-groups --query 'TargetGroups[].[TargetGroupName,Port,join(`,`,LoadBalancerArns)]' --output text 2>&1 | tr '\n' ';')"

echo
if [ "$FAILS" -eq 0 ]; then echo "Reuse looks possible without any IAM change."
else echo "$FAILS check(s) failed — paste this output back so we can decide."; fi
