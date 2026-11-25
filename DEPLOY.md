# Deploying on AWS — Sympany AWS account, eu-central-2 (Zurich)

The application ships as **one Docker image**, run as one ECS Fargate service:

| What | How it runs | Size |
|---|---|---|
| **Web app** (`sympany-socmon-web`) | ECS service, **2 tasks** (eu-central-2a + 2b), private subnets, behind WAF + ALB | 1 vCPU / 4 GB each |
| **Scans** | Inside the web tasks (`SCAN_LAUNCH=inline`): **Run Scan** in the dashboard, **once per Swiss calendar day** (`scan.manual_per_day`); no automatic daily scan. Each scan catches up on the days since the last one. A DynamoDB lock makes sure only one scan runs at a time across both tasks | — |

| Concern | AWS service | Where in the code |
|---|---|---|
| Sign-in | **Built into the app**: username + password, accounts in Parameter Store (no Cognito, no SSO) | `src/auth.py`, `tools/create_app_user.py` |
| AI: sentiment / risk | Amazon Bedrock `qwen.qwen3-235b-a22b-2507-v1:0` (In-Region) | `src/llm.py`, `src/pipeline/risk_classifier.py` |
| AI: image / video-frame text | Amazon Bedrock `qwen.qwen3-vl-235b-a22b` (Media Compliance only, hidden for now) | `src/llm.py`, `src/compliance.py` |
| Speech to text | Amazon Transcribe streaming (de-CH, fr-FR, it-IT, en-US) | `src/speech.py` |
| Data | Amazon DynamoDB `sympany-socmon-data` (TTL) + `sympany-socmon-audit` | `src/store.py` |
| Scans | In the web app: Run Scan once a day, lock | `src/scan_runner.py`, `src/scan_job.py` |
| Secrets | SSM Parameter Store `/sympany-socmon/*` (SecureString) → ECS `secrets` | `deploy/aws/task-definition-web.json` |
| Alerts | Amazon SNS `sympany-socmon-alerts` | `src/escalation.py`, `src/scan_job.py` |
| Logs | CloudWatch Logs `/ecs/sympany-socmon-web` | — |

No Groq or other non-AWS AI service is used. Media Compliance is **hidden**
(`FEATURE_MEDIA_COMPLIANCE=false`); its code is unchanged (section 12).

**Why these choices.** Names use the `sympany-socmon-*` prefix because the IAM policy Sympany gave
our roles (`sympany-socmon-permissions-boundary`) only covers that prefix. Scans run inside the
web app, so the deployment needs no EventBridge Scheduler and no change to Sympany's role
policies. The image is built by AWS CodeBuild. From what Sympany already built we **reuse** the
VPC and subnets (`sympany-slp-vpc`), the internet-facing load balancer `sympany-spl-ext-alb`, its
WAF `sympany-spl-waf` (unchanged) and its security group `sympany-slp-ext-alb-sg`; we add an HTTPS
listener and our own target group. Their `sympany-spl-ecs-cluster`, `social-listening-*` tables,
buckets, topic and `sympany-spl-task-execution-role` are not used.

---

## 0. From the Sympany cloud team (once)

Checked with the read-only scripts in `deploy/aws/` (`check-iam.sh`, `check-access.sh`,
`check-network.sh`, `check-existing.sh`, `check-reuse.sh`, `check-final.sh`). Still needed:

1. **Permissions for the deploying user**: `iam:PassRole` on `sympany-socmon-trust-ecs-tasks-role`
   (→ `ecs-tasks.amazonaws.com`) and `sympany-socmon-trust-codebuild-role` (→ `codebuild.amazonaws.com`);
   `elasticloadbalancing:CreateListener` / `ModifyListener` on `sympany-spl-ext-alb` and its listeners.
2. **Security group `sympany-socmon-web`** in `sympany-slp-vpc`: inbound TCP 8080 from
   `sg-xxxxxxxx` (`sympany-slp-ext-alb-sg`) only; outbound default.
3. **HTTPS:** the hostname, an ACM certificate for it in eu-central-2 (or `acm:RequestCertificate`),
   and two CNAME records in Sympany's DNS (certificate validation; hostname → load balancer).
4. **Alert e-mail addresses** for the SNS topic.

After they confirm, `bash check-access.sh` should show no FAIL lines.

---

## 1. On the release machine: login account and release zip

**Client login** (in the repository, Python virtualenv active):
```bash
python -m tools.create_app_user sympany.client
```
Prints a generated **password (shown once)** and the `APP_USERS` value. Give the password to
the client over a separate secure channel; only the hash goes to AWS (section 4).

**Release zip** — the source CodeBuild builds the image from (never zip the folder by hand:
`.env` holds live keys):
```bash
python tools/make_release_zip.py          # -> ../sympany-socmon-<date>.zip
```
Upload it to CloudShell (Actions → Upload file).

## 2. AWS CloudShell — variables

Console Region **Europe (Zurich)**:
```bash
export AWS_REGION=eu-central-2 AWS_DEFAULT_REGION=eu-central-2
ACCOUNT=123456789012
# sympany-slp-vpc (check-network.sh): app subnets = private + NAT, ALB subnets = public
VPC_ID=vpc-xxxxxxxx
PRIVATE_SUBNET_1A=subnet-xxxxxxxx; PRIVATE_SUBNET_1B=subnet-xxxxxxxx   # sympany-slp-internal-app-subnet-*
PUBLIC_SUBNET_1A=subnet-xxxxxxxx;  PUBLIC_SUBNET_1B=subnet-xxxxxxxx    # sympany-slp-external-alb-subnet-*
WEB_SG=sg-xxxxxxxx                   # sympany-socmon-web, from the cloud team (section 0)
# their load balancer (reused): internet-facing, WAF sympany-spl-waf attached, SG sympany-slp-ext-alb-sg
ALB_ARN=$(aws elbv2 describe-load-balancers --names sympany-spl-ext-alb --query 'LoadBalancers[0].LoadBalancerArn' --output text)
CERT_ARN=arn:aws:acm:eu-central-2:123456789012:certificate/xxxxxxxx   # from the cloud team
ROLE_ECS=arn:aws:iam::123456789012:role/sympany-socmon-trust-ecs-tasks-role
ROLE_CODEBUILD=arn:aws:iam::123456789012:role/sympany-socmon-trust-codebuild-role

unzip -q sympany-socmon-*.zip -d sympany-socmon && cd sympany-socmon
```

## 3. Release bucket, ECR and the image build (CodeBuild)

```bash
BUCKET=sympany-socmon-releases-$ACCOUNT
aws s3api create-bucket --bucket $BUCKET --create-bucket-configuration LocationConstraint=eu-central-2
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration   BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket $BUCKET --versioning-configuration Status=Enabled
aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --lifecycle-configuration   '{"Rules":[{"ID":"keep-last-3-releases","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":1,"NewerNoncurrentVersions":2}}]}'
aws s3 cp ../sympany-socmon-*.zip s3://$BUCKET/sympany-socmon-release.zip

aws ecr create-repository --repository-name sympany-socmon --image-scanning-configuration scanOnPush=true

sed "s#<CODEBUILD_ROLE_ARN>#$ROLE_CODEBUILD#" deploy/aws/codebuild-project.json > /tmp/codebuild.json
aws codebuild create-project --cli-input-json file:///tmp/codebuild.json
BUILD_ID=$(aws codebuild start-build --project-name sympany-socmon-build --query build.id --output text)
aws codebuild batch-get-builds --ids $BUILD_ID --query 'builds[0].buildStatus'   # repeat until SUCCEEDED (~5-8 min)
```
The build pushes `sympany-socmon:<timestamp>` and `sympany-socmon:latest` to ECR. Build logs:
`/aws/codebuild/sympany-socmon-build`.

## 4. Parameter Store (secrets)

```bash
aws ssm put-parameter --name /sympany-socmon/APP_USERS --type SecureString \
  --value 'sympany.client:pbkdf2_sha256$600000$...$...'          # the APP_USERS value from section 1
aws ssm put-parameter --name /sympany-socmon/SESSION_SECRET --type SecureString \
  --value "$(openssl rand -base64 48 | tr -d '\n')"
# Provider keys — type them yourself; never put them in files, chat or e-mail.
# Use PLACEHOLDER if a key is not available yet: that provider's channels are then skipped.
aws ssm put-parameter --name /sympany-socmon/APIFY_TOKEN        --type SecureString --value '<apify token>'
aws ssm put-parameter --name /sympany-socmon/BRIGHTDATA_API_KEY --type SecureString --value '<bright data key>'
```

## 5. DynamoDB, SNS, logs

```bash
for T in sympany-socmon-data sympany-socmon-audit; do
  aws dynamodb create-table --table-name $T \
    --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST --sse-specification Enabled=true,SSEType=KMS \
    --deletion-protection-enabled
  aws dynamodb wait table-exists --table-name $T
  aws dynamodb update-continuous-backups --table-name $T \
    --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
done
# collected posts and cases expire after 730 days (POST_RETENTION_DAYS); the audit table never expires
aws dynamodb update-time-to-live --table-name sympany-socmon-data \
  --time-to-live-specification Enabled=true,AttributeName=expires_at

TOPIC=$(aws sns create-topic --name sympany-socmon-alerts --query TopicArn --output text)
aws sns subscribe --topic-arn $TOPIC --protocol email --notification-endpoint risk-team@sympany.ch
# repeat per recipient; each confirms from the e-mail AWS sends

aws logs create-log-group --log-group-name /ecs/sympany-socmon-web
aws logs put-retention-policy --log-group-name /ecs/sympany-socmon-web --retention-in-days 365
```

## 6. Amazon Bedrock model check

```bash
aws bedrock-runtime converse --model-id qwen.qwen3-235b-a22b-2507-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Reply with OK"}]}]' --query 'output.message.content[0].text'
```

## 7. Load balancer (reuse `sympany-spl-ext-alb`; its WAF stays as it is)

```bash
TG_ARN=$(aws elbv2 create-target-group --name sympany-socmon-web --protocol HTTP --port 8080 --vpc-id $VPC_ID   --target-type ip --health-check-path /api/health --healthy-threshold-count 2 --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 modify-target-group-attributes --target-group-arn $TG_ARN --attributes Key=deregistration_delay.timeout_seconds,Value=30

# HTTPS 443 -> our target group (TLS 1.2/1.3)
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTPS --port 443 --certificates CertificateArn=$CERT_ARN   --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 --default-actions Type=forward,TargetGroupArn=$TG_ARN

# HTTP 80: today it forwards to sympany-slp-ext-alb-tg (no targets) -> redirect to HTTPS instead
L80=$(aws elbv2 describe-listeners --load-balancer-arn $ALB_ARN --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text)
aws elbv2 modify-listener --listener-arn $L80   --default-actions 'Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'
```
DNS (Sympany's DNS provider): `socmon.sympany.ch` CNAME → `sympany-spl-ext-alb-xxxxxxxxxx.eu-central-2.elb.amazonaws.com`.

Notes on the reused load balancer and WAF (checked with `check-final.sh`):
- Security group `sympany-slp-ext-alb-sg`: 80 and 443 from anywhere. To limit access to Sympany's
  network later, only its inbound rules change.
- WAF `sympany-spl-waf`: default Allow; blocks the AWS managed Common, KnownBadInputs, PHP, SQLi,
  Linux and AdminProtection rule sets, a few sanctioned countries (CU, IR, KP, RU, SY, VE) and
  its (empty) IP block lists; rate (1000) and body-size rules only count. Fine for the app as it
  is; the app itself locks an account after 5 failed sign-ins in 15 minutes.
- Idle timeout 60 s — enough while Media Compliance is hidden (scans run in the background).

## 8. ECS cluster and web service

```bash
aws ecs create-cluster --cluster-name sympany-socmon --settings name=containerInsights,value=enabled

sed -e "s#<ECS_TASKS_ROLE_ARN>#$ROLE_ECS#g" deploy/aws/task-definition-web.json > /tmp/web.json
WEB_TD_ARN=$(aws ecs register-task-definition --cli-input-json file:///tmp/web.json --query taskDefinition.taskDefinitionArn --output text)

aws ecs create-service --cluster sympany-socmon --service-name sympany-socmon-web --task-definition sympany-socmon-web \
  --desired-count 2 --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_1A,$PRIVATE_SUBNET_1B],securityGroups=[$WEB_SG],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=web,containerPort=8080" \
  --health-check-grace-period-seconds 60 \
  --deployment-configuration "minimumHealthyPercent=100,maximumPercent=200,deploymentCircuitBreaker={enable=true,rollback=true}" \
  --enable-execute-command
aws ecs wait services-stable --cluster sympany-socmon --services sympany-socmon-web
```
If tasks stop immediately, check the stopped reason (`aws ecs describe-tasks`) — usually a
missing `/sympany-socmon/*` parameter or a log permission.

## 9. Import the data collected so far (one time)

```bash
aws ecs run-task --cluster sympany-socmon --task-definition $WEB_TD_ARN --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_1A,$PRIVATE_SUBNET_1B],securityGroups=[$WEB_SG],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"web","command":["python","-m","tools.seed_dynamodb"]}]}'
```
Copies `data/` from the image into DynamoDB (safe to re-run). Progress is in `/ecs/sympany-socmon-web`.

## 10. Scans and alarms

Scans need no AWS setup. There is no automatic daily scan (`SCAN_DAILY_AT` is not set):
someone clicks **Run Scan**, at most once per Swiss calendar day (`scan.manual_per_day`).
Alarm on failed scans and unhealthy tasks:
```bash
aws logs put-metric-filter --log-group-name /ecs/sympany-socmon-web --filter-name sympany-socmon-scan-failed \
  --filter-pattern '"SCAN_JOB_FAILED"' \
  --metric-transformations metricName=ScanJobFailed,metricNamespace=Sympany/SocMon,metricValue=1,defaultValue=0
aws cloudwatch put-metric-alarm --alarm-name sympany-socmon-scan-failed --namespace Sympany/SocMon --metric-name ScanJobFailed \
  --statistic Sum --period 300 --evaluation-periods 1 --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching --alarm-actions $TOPIC
aws cloudwatch put-metric-alarm --alarm-name sympany-socmon-unhealthy-targets --namespace AWS/ApplicationELB \
  --metric-name UnHealthyHostCount --dimensions Name=TargetGroup,Value=${TG_ARN##*:} Name=LoadBalancer,Value=${ALB_ARN#*loadbalancer/} \
  --statistic Maximum --period 60 --evaluation-periods 3 --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions $TOPIC
```

**How scans and the dashboard fit together.** A scan runs when a user clicks **Run Scan**:
the full scan (Sympany posts, followers, competitors, reply times), once per Swiss calendar day
(a scan that fails does not count). Only one scan runs at a time (a DynamoDB lock shared by
both web tasks). Each scan collects posts, skips those already seen, analyses the new ones and adds them to DynamoDB,
so the dashboard always shows everything collected so far (the last scanned data when
nothing new was found). The dashboard shows *Last scan <date/time>* and reloads by itself
when a newer scan has finished.

- **Engagement refresh:** posts a provider returns again get their likes / comments / views
  updated (no new AI call).
- **Failed analysis:** shown as **Failed** (not "no risk"), kept out of the charts, and
  analysed again at the start of each following scan — up to 10 attempts.
- **Catch-up:** each channel fetches the posts published since its last complete scan: the
  provider limit is multiplied by the days since then (`catchup:` in config.yaml), and a full
  page with no post seen before is fetched again with twice the limit. Posts that may still
  be missing are noted in the logs (`Coverage …`).
- **Summary e-mail:** after every successful scan (`escalation.run_summary: always`). Failed
  scans and HIGH-risk alerts are always sent.

## 11. Verify and hand over

1. `curl -s https://<hostname>/api/health` returns `{"status":"ok",…}`.
2. Open `https://<hostname>` → sign in as `sympany.client`. The sidebar shows Analytics, Reports
   and Campaign (no Media Compliance).
3. Click **Run Scan**; the dashboard updates when it finishes (logs in `/ecs/sympany-socmon-web`).
4. Send the client the URL, the username and (separately) the password.

---

## 12. Day-2 operations

**Provider API keys arrive / change**
```bash
aws ssm put-parameter --name /sympany-socmon/APIFY_TOKEN        --type SecureString --overwrite --value '<apify token>'
aws ssm put-parameter --name /sympany-socmon/BRIGHTDATA_API_KEY --type SecureString --overwrite --value '<bright data key>'
aws ecs update-service --cluster sympany-socmon --service sympany-socmon-web --force-new-deployment
```
Locally, put them in your own `.env` (`APIFY_TOKEN=…`, `BRIGHTDATA_API_KEY=…`), which is never
zipped or built into the image.

**Add a user / reset a password**: `python -m tools.create_app_user <name> --existing "<current APP_USERS>"`,
put the new value in `/sympany-socmon/APP_USERS` (`--overwrite`), then force a new deployment as
above. Rotating `SESSION_SECRET` signs everybody out.

**Release a new version**
```bash
python tools/make_release_zip.py                                  # on the release machine; upload to CloudShell
aws s3 cp sympany-socmon-*.zip s3://sympany-socmon-releases-123456789012/sympany-socmon-release.zip
aws codebuild start-build --project-name sympany-socmon-build        # wait for SUCCEEDED
aws ecs update-service --cluster sympany-socmon --service sympany-socmon-web --force-new-deployment
```
Release when no scan is running. A scan cut off by a release has to be clicked again (it
does not use up the day, and its lock expires after 3 hours at most).

**Turn Media Compliance back on (later)**: set `FEATURE_MEDIA_COMPLIANCE=true` in
`deploy/aws/task-definition-web.json`, register it and redeploy. Before that, ask Sympany to (1) set
the rule `SizeRestrictions_BODY` of `AWS-AWSManagedRulesCommonRuleSet` in `sympany-spl-waf` to
*Count* (uploads are larger than 8 KB) and (2) raise the idle timeout of `sympany-spl-ext-alb` to
300 s (video checks take minutes); and have Sympany's compliance team review the rule
set in `config/rules/sympany-ch-v1.json` (FINMA / Swiss insurance advertising rules).

**Optional: scans as a separate ECS task** (bigger scans, isolated from the web tasks). Needs
Sympany to fix the `PassTaskRoles` resource in their policy (it targets the path `/sympany-socmon/`,
which the roles do not have — use the exact role ARN). Then register
`deploy/aws/task-definition-scan.json`, set `SCAN_LAUNCH=ecs` plus `ECS_CLUSTER`,
`SCAN_TASK_DEFINITION`, `SCAN_CONTAINER_NAME`, `SCAN_SUBNETS`, `SCAN_SECURITY_GROUPS` on the web
task, and create an EventBridge schedule from `deploy/aws/scheduler-target.json` instead of
`SCAN_DAILY_AT`.

**Emergency shell into a web task** (ECS Exec, audited in CloudTrail):
```bash
aws ecs execute-command --cluster sympany-socmon --task <task-id> --container web --interactive --command "/bin/sh"
```

---

## 13. Local development

`.env` (copy `.env.example`) switches the same code to local mode — files under `data/`, no
sign-in, scans in-process. AI still runs on Amazon Bedrock, so use AWS credentials that can
call the two models in eu-central-2.
```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn src.api:app --reload --port 8000
cd frontend && npm install && npm run dev
```
To try the sign-in screen locally set `AUTH_MODE=password`, `APP_USERS` and `SESSION_SECRET` in `.env`.
