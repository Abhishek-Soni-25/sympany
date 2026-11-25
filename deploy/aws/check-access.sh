#!/usr/bin/env bash
# Read-only check: can the signed-in CloudShell user run every step of DEPLOY.md?
#
#     bash check-access.sh
#
# Uses only sts get-caller-identity and iam simulate-principal-policy (an evaluation API that
# answers "would this be allowed?") against the exact sympany-socmon resources the runbook
# creates. It creates, changes or deletes nothing. Organizations SCPs are not fully visible
# to the simulator, so "allowed" here is necessary, not sufficient.

set -uo pipefail
REGION=eu-central-2
FAILS=0
ok()  { printf '  \033[32mOK  \033[0m %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS + 1)); }

ACC=$(aws sts get-caller-identity --query Account --output text) || { echo "AWS CLI not signed in"; exit 1; }
ME=$(aws sts get-caller-identity --query Arn --output text)
echo "Checking: $ME"
case "$ME" in
  *:assumed-role/*)  # simulate the role behind an assumed-role session
    R=${ME#*:assumed-role/}; R=${R%%/*}
    ME=$(aws iam get-role --role-name "$R" --query Role.Arn --output text) ;;
esac

REGION_CTX="ContextKeyName=aws:RequestedRegion,ContextKeyValues=$REGION,ContextKeyType=string"
sim() {  # <step> <action> <resource> [extra context]
  local step=$1 a=$2 r=$3 d; shift 3
  d=$(aws iam simulate-principal-policy --policy-source-arn "$ME" --action-names "$a" --resource-arns "$r" \
        --context-entries "$REGION_CTX" "$@" --query 'EvaluationResults[0].EvalDecision' --output text 2>&1)
  if [ "$d" = "allowed" ]; then ok "$step  $a"; else bad "$step  $a  ($r) -> $d"; fi
}
A="arn:aws:%s:$REGION:$ACC:%s"
arn() { printf "$A" "$1" "$2"; }
PASS_CTX="ContextKeyName=iam:PassedToService,ContextKeyValues=ecs-tasks.amazonaws.com,ContextKeyType=string"

echo; echo "== Section 3: release bucket, ECR, CodeBuild"
B="arn:aws:s3:::sympany-socmon-releases-$ACC"
for X in s3:CreateBucket s3:PutBucketPublicAccessBlock s3:PutBucketVersioning s3:PutLifecycleConfiguration; do sim 3 "$X" "$B"; done
sim 3 s3:PutObject "$B/sympany-socmon-release.zip"
sim 3 ecr:CreateRepository "$(arn ecr repository/sympany-socmon)"
for X in codebuild:CreateProject codebuild:StartBuild codebuild:BatchGetBuilds; do sim 3 "$X" "$(arn codebuild project/sympany-socmon-build)"; done
sim 3 iam:PassRole "arn:aws:iam::$ACC:role/sympany-socmon-trust-codebuild-role"   "ContextKeyName=iam:PassedToService,ContextKeyValues=codebuild.amazonaws.com,ContextKeyType=string"

echo; echo "== Section 4: Parameter Store"
sim 4 ssm:PutParameter "$(arn ssm parameter/sympany-socmon/APP_USERS)"

echo; echo "== Section 5: DynamoDB, SNS, logs"
for X in dynamodb:CreateTable dynamodb:DescribeTable dynamodb:UpdateTimeToLive dynamodb:UpdateContinuousBackups; do
  sim 5 "$X" "$(arn dynamodb table/sympany-socmon-data)"
done
sim 5 sns:CreateTopic "$(arn sns sympany-socmon-alerts)"
sim 5 sns:Subscribe "$(arn sns sympany-socmon-alerts)"
sim 5 logs:CreateLogGroup "$(arn logs log-group:/ecs/sympany-socmon-web)"
sim 5 logs:PutRetentionPolicy "$(arn logs log-group:/ecs/sympany-socmon-web)"

echo; echo "== Section 6: Bedrock test call"
sim 6 bedrock:InvokeModel "arn:aws:bedrock:$REGION::foundation-model/qwen.qwen3-235b-a22b-2507-v1:0"

echo; echo "== Section 7: reuse load balancer sympany-spl-ext-alb (security group + certificate come from the cloud team)"
ALB=$(aws elbv2 describe-load-balancers --names sympany-spl-ext-alb --query 'LoadBalancers[0].LoadBalancerArn' --output text)
L80=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB" --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text)
for X in elasticloadbalancing:CreateTargetGroup elasticloadbalancing:ModifyTargetGroupAttributes; do
  sim 7 "$X" "$(arn elasticloadbalancing targetgroup/sympany-socmon-web/0123456789abcdef)"
done
sim 7 elasticloadbalancing:CreateListener "$ALB"
sim 7 elasticloadbalancing:ModifyListener "$L80"

echo; echo "== Sections 8-9: ECS cluster, task definition, web service, one-off import task"
sim 8 ecs:CreateCluster "$(arn ecs cluster/sympany-socmon)"
sim 8 ecs:RegisterTaskDefinition "*"
sim 8 ecs:CreateService "$(arn ecs service/sympany-socmon/sympany-socmon-web)"
sim 8 ecs:UpdateService "$(arn ecs service/sympany-socmon/sympany-socmon-web)"
sim 9 ecs:RunTask "$(arn ecs task-definition/sympany-socmon-web:1)"
sim 8 iam:PassRole "arn:aws:iam::$ACC:role/sympany-socmon-trust-ecs-tasks-role" "$PASS_CTX"

echo; echo "== Section 10: alarms"
sim 10 logs:PutMetricFilter "$(arn logs log-group:/ecs/sympany-socmon-web)"
sim 10 cloudwatch:PutMetricAlarm "$(arn cloudwatch alarm:sympany-socmon-scan-failed)"

echo
if [ "$FAILS" -eq 0 ]; then echo "You can run every step of DEPLOY.md yourself."
else echo "$FAILS step(s) need extra permissions — ask the cloud team for the FAIL lines above."; fi
