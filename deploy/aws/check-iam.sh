#!/usr/bin/env bash
# Read-only IAM checks for the sympany-socmon deployment — run in AWS CloudShell (eu-central-2):
#
#     bash check-iam.sh
#
# It only calls sts get-caller-identity, iam get-* / list-* and iam simulate-principal-policy
# (an evaluation API that answers "would this be allowed?"). It creates, changes or deletes
# nothing. The signed-in identity needs iam:Get*, iam:List* and iam:SimulatePrincipalPolicy.
#
# The simulation evaluates each role's identity policies together with its permissions
# boundary, for the exact resources this deployment uses (DEPLOY.md). It cannot see
# Organizations SCPs or KMS key policies, so an "allowed" here is necessary, not sufficient.

set -uo pipefail
REGION=eu-central-2
FAILS=0
ok()   { printf '  \033[32mOK  \033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS + 1)); }
note() { printf '  \033[33mNOTE\033[0m %s\n' "$*"; }
info() { printf '       %s\n' "$*"; }

ACC=$(aws sts get-caller-identity --query Account --output text) || { echo "AWS CLI not signed in"; exit 1; }
echo "Signed in as: $(aws sts get-caller-identity --query Arn --output text)"
echo "Account:      $ACC"
[ "$ACC" = "123456789012" ] || note "expected account 123456789012"

ECS_ROLE=sympany-socmon-trust-ecs-tasks-role
CB_ROLE=sympany-socmon-trust-codebuild-role
SCHED_ROLE=sympany-socmon-trust-scheduler-role

role_arn() { aws iam get-role --role-name "$1" --query Role.Arn --output text 2>/dev/null; }

# ---------------------------------------------------------------------------------------
# 1. The three deployment roles: ARN/path, trust, boundary, attached policies
# ---------------------------------------------------------------------------------------
check_role() {  # <role name> <service that must be able to assume it>
  local name=$1 svc=$2 arn path trust pb
  echo; echo "== Role $name"
  arn=$(role_arn "$name")
  if [ -z "$arn" ]; then bad "role not found (or no iam:GetRole permission)"; return 1; fi
  info "ARN: $arn"
  path=$(aws iam get-role --role-name "$name" --query Role.Path --output text)
  # The path only matters for iam:PassRole; the PassRole simulations below decide pass/fail.
  info "path: $path  (a PassRole resource of role/sympany-socmon/* only covers path /sympany-socmon/)"
  trust=$(aws iam get-role --role-name "$name" --query 'Role.AssumeRolePolicyDocument.Statement[].Principal.Service' --output text)
  if grep -qw "$svc" <<<"$trust"; then ok "trust policy allows $svc"; else bad "trust policy allows '$trust', expected $svc"; fi
  pb=$(aws iam get-role --role-name "$name" --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text)
  if [ "$pb" != "None" ]; then ok "permissions boundary: ${pb##*/}"; else note "no permissions boundary attached"; fi
  info "managed policies: $(aws iam list-attached-role-policies --role-name "$name" --query 'AttachedPolicies[].PolicyName' --output text)"
  info "inline policies:  $(aws iam list-role-policies --role-name "$name" --query 'PolicyNames' --output text)"
}

check_role "$ECS_ROLE" ecs-tasks.amazonaws.com
check_role "$CB_ROLE" codebuild.amazonaws.com
check_role "$SCHED_ROLE" scheduler.amazonaws.com

ECS_ARN=$(role_arn "$ECS_ROLE")
CB_ARN=$(role_arn "$CB_ROLE")
SCHED_ARN=$(role_arn "$SCHED_ROLE")

# ---------------------------------------------------------------------------------------
# 2. Simulate every permission the deployment needs (identity policies + boundary)
# ---------------------------------------------------------------------------------------
REGION_CTX="ContextKeyName=aws:RequestedRegion,ContextKeyValues=$REGION,ContextKeyType=string"
sim() {  # <principal arn> <action> <resource arn> [extra --context-entries values]
  local p=$1 a=$2 r=$3 d; shift 3
  [ -n "$p" ] || return 0
  d=$(aws iam simulate-principal-policy --policy-source-arn "$p" --action-names "$a" --resource-arns "$r" \
        --context-entries "$REGION_CTX" "$@" --query 'EvaluationResults[0].EvalDecision' --output text 2>&1)
  if [ "$d" = "allowed" ]; then ok "$a  $r"; else bad "$a  $r  -> $d"; fi
}
PASS_CTX="ContextKeyName=iam:PassedToService,ContextKeyValues=ecs-tasks.amazonaws.com,ContextKeyType=string"
TD_SCAN="arn:aws:ecs:$REGION:$ACC:task-definition/sympany-socmon-scan:1"
REPO="arn:aws:ecr:$REGION:$ACC:repository/sympany-socmon"

echo; echo "== $ECS_ROLE as task EXECUTION role (start containers)"
sim "$ECS_ARN" ecr:GetAuthorizationToken "*"
sim "$ECS_ARN" ecr:BatchGetImage "$REPO"
sim "$ECS_ARN" ecr:GetDownloadUrlForLayer "$REPO"
sim "$ECS_ARN" logs:CreateLogStream "arn:aws:logs:$REGION:$ACC:log-group:/ecs/sympany-socmon-web:log-stream:web/check"
sim "$ECS_ARN" logs:PutLogEvents "arn:aws:logs:$REGION:$ACC:log-group:/ecs/sympany-socmon-scan:log-stream:scan/check"
for P in APP_USERS SESSION_SECRET APIFY_TOKEN BRIGHTDATA_API_KEY; do
  sim "$ECS_ARN" ssm:GetParameters "arn:aws:ssm:$REGION:$ACC:parameter/sympany-socmon/$P"
done
sim "$ECS_ARN" kms:Decrypt "*" "ContextKeyName=kms:ViaService,ContextKeyValues=ssm.$REGION.amazonaws.com,ContextKeyType=string"

echo; echo "== $ECS_ROLE as TASK role (what the app calls)"
for A in dynamodb:GetItem dynamodb:PutItem dynamodb:Query dynamodb:BatchWriteItem; do
  sim "$ECS_ARN" "$A" "arn:aws:dynamodb:$REGION:$ACC:table/sympany-socmon-data"
done
for A in dynamodb:PutItem dynamodb:Query; do
  sim "$ECS_ARN" "$A" "arn:aws:dynamodb:$REGION:$ACC:table/sympany-socmon-audit"
done
sim "$ECS_ARN" bedrock:InvokeModel "arn:aws:bedrock:$REGION::foundation-model/qwen.qwen3-235b-a22b-2507-v1:0"
sim "$ECS_ARN" bedrock:InvokeModel "arn:aws:bedrock:$REGION::foundation-model/qwen.qwen3-vl-235b-a22b"
sim "$ECS_ARN" transcribe:StartStreamTranscription "*"
sim "$ECS_ARN" sns:Publish "arn:aws:sns:$REGION:$ACC:sympany-socmon-alerts"
sim "$ECS_ARN" ecs:RunTask "$TD_SCAN"                      # "Run Scan" button
sim "$ECS_ARN" iam:PassRole "$ECS_ARN" "$PASS_CTX"         # ... passes the scan task's role

echo; echo "== $SCHED_ROLE (daily scan)"
sim "$SCHED_ARN" ecs:RunTask "$TD_SCAN"
sim "$SCHED_ARN" iam:PassRole "$ECS_ARN" "$PASS_CTX"

echo; echo "== $CB_ROLE (image build)"
BUCKET="sympany-socmon-releases-$ACC"
sim "$CB_ARN" s3:GetObject "arn:aws:s3:::$BUCKET/sympany-socmon-release.zip"
sim "$CB_ARN" s3:GetObjectVersion "arn:aws:s3:::$BUCKET/sympany-socmon-release.zip"
sim "$CB_ARN" s3:GetBucketLocation "arn:aws:s3:::$BUCKET"
sim "$CB_ARN" ecr:GetAuthorizationToken "*"
for A in ecr:BatchCheckLayerAvailability ecr:InitiateLayerUpload ecr:UploadLayerPart ecr:CompleteLayerUpload ecr:PutImage; do
  sim "$CB_ARN" "$A" "$REPO"
done
sim "$CB_ARN" logs:CreateLogGroup "arn:aws:logs:$REGION:$ACC:log-group:/aws/codebuild/sympany-socmon-build"
sim "$CB_ARN" logs:PutLogEvents "arn:aws:logs:$REGION:$ACC:log-group:/aws/codebuild/sympany-socmon-build:log-stream:check"

# ---------------------------------------------------------------------------------------
# 3. The PassRole statement as written, for the record
# ---------------------------------------------------------------------------------------
echo; echo "== iam:PassRole and CloudWatch Logs statements in the policies attached to $ECS_ROLE"
for PA in $(aws iam list-attached-role-policies --role-name "$ECS_ROLE" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
  case "$PA" in arn:aws:iam::aws:*) continue ;; esac
  V=$(aws iam get-policy --policy-arn "$PA" --query Policy.DefaultVersionId --output text)
  aws iam get-policy-version --policy-arn "$PA" --version-id "$V" --query PolicyVersion.Document --output json \
    | jq -c --arg p "${PA##*/}" '(.Statement | if type == "array" then .[] else . end) | select((.Action|tostring)|test("PassRole|logs:")) | {policy:$p, Sid, Action, Resource, Condition}'
done

# ---------------------------------------------------------------------------------------
# 4. Roles this deployment does not use — show what they reference
# ---------------------------------------------------------------------------------------
policy_docs() {  # all policy documents of a role (customer-managed + inline), one JSON per line
  local name=$1 PA V PN
  for PA in $(aws iam list-attached-role-policies --role-name "$name" --query 'AttachedPolicies[].PolicyArn' --output text); do
    case "$PA" in arn:aws:iam::aws:*) continue ;; esac
    V=$(aws iam get-policy --policy-arn "$PA" --query Policy.DefaultVersionId --output text)
    aws iam get-policy-version --policy-arn "$PA" --version-id "$V" --query PolicyVersion.Document --output json | jq -c .
  done
  for PN in $(aws iam list-role-policies --role-name "$name" --query PolicyNames --output text); do
    aws iam get-role-policy --role-name "$name" --policy-name "$PN" --query PolicyDocument --output json | jq -c .
  done
}
for R in sympany-spl-task-execution-role sympany-social-listening-audit-housekeeping-role CognitoIdpSNSServiceRole; do
  echo; echo "== $R (not used by this deployment)"
  if [ -z "$(role_arn "$R")" ]; then note "role not found"; continue; fi
  info "managed policies: $(aws iam list-attached-role-policies --role-name "$R" --query 'AttachedPolicies[].PolicyName' --output text)"
  DOCS=$(policy_docs "$R")
  OTHER=$(grep -oE '[0-9]{12}' <<<"$DOCS" | sort -u | grep -v "^$ACC$" | tr '\n' ' ')
  if [ -n "$OTHER" ]; then note "policies reference other AWS account(s): $OTHER"; fi
  NAMES=$(grep -oE '(table|parameter|log-group:)/?[A-Za-z0-9_./-]+' <<<"$DOCS" | sort -u | tr '\n' ' ')
  [ -n "$NAMES" ] && info "resources: $NAMES"
done

# ---------------------------------------------------------------------------------------
# 5. Bedrock models visible in Zurich (needs bedrock:ListFoundationModels; skipped otherwise)
# ---------------------------------------------------------------------------------------
echo; echo "== Bedrock models in $REGION"
aws bedrock list-foundation-models --region "$REGION" \
  --query "modelSummaries[?modelId=='qwen.qwen3-235b-a22b-2507-v1:0' || modelId=='qwen.qwen3-vl-235b-a22b'].[modelId,modelLifecycle.status]" \
  --output text 2>/dev/null || note "could not list models (no bedrock:ListFoundationModels permission)"

echo
if [ "$FAILS" -eq 0 ]; then echo "All checks passed."; else echo "$FAILS check(s) FAILED — see the FAIL lines above."; fi
