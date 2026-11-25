#!/usr/bin/env bash
# Read-only checks behind the go-live e-mail (AWS CloudShell):   bash check-final.sh
# Only describe / get / list calls and public DNS lookups. Nothing is created or changed.
# A section that prints "AccessDenied" simply means this user may not read it.

set -uo pipefail
export AWS_DEFAULT_REGION=eu-central-2
ALB_NAME=sympany-spl-ext-alb
WAF_NAME=sympany-spl-waf
WAF_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   # sympany-spl-waf id (set before running)
HOST=socmon.sympany.ch
APEX=sympany.ch
h() { echo; echo "== $*"; }
run() { "$@" 2>&1 | sed 's/^/  /'; }

h "1. Service control policies on this account (usually only readable from the management account)"
run aws organizations list-policies-for-target --target-id 123456789012 --filter SERVICE_CONTROL_POLICY \
  --query 'Policies[].[Name,Id]' --output text

h "2. WAF $WAF_NAME — rules, action, and limits"
run aws wafv2 get-web-acl --scope REGIONAL --name "$WAF_NAME" --id "$WAF_ID" --query \
  'WebACL.{Default:DefaultAction, Rules:Rules[].{Priority:Priority,Name:Name,Action:Action,Override:OverrideAction,RateLimit:Statement.RateBasedStatement.Limit,ManagedGroup:Statement.ManagedRuleGroupStatement.Name,SizeLimit:Statement.SizeConstraintStatement.Size}}' --output json
echo "  attached to:"
run aws wafv2 list-resources-for-web-acl --web-acl-arn \
  "$(aws wafv2 get-web-acl --scope REGIONAL --name "$WAF_NAME" --id "$WAF_ID" --query WebACL.ARN --output text 2>/dev/null)" \
  --resource-type APPLICATION_LOAD_BALANCER --output text

h "3. GuardDuty in eu-central-2"
DET=$(aws guardduty list-detectors --query 'DetectorIds[0]' --output text 2>&1)
echo "  detector: $DET"
if [ -n "$DET" ] && [ "$DET" != "None" ] && ! grep -qi 'error\|denied' <<<"$DET"; then
  run aws guardduty get-detector --detector-id "$DET" \
    --query '{Status:Status, Features:Features[].{Name:Name,Status:Status,Extra:AdditionalConfiguration[].[Name,Status]}}' --output json
fi

h "4. Load balancer $ALB_NAME — settings"
ALB=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].LoadBalancerArn' --output text)
run aws elbv2 describe-load-balancers --load-balancer-arns "$ALB" \
  --query 'LoadBalancers[0].[Scheme,State.Code,DNSName,join(`,`,AvailabilityZones[].ZoneName),join(`,`,SecurityGroups)]' --output text
run aws elbv2 describe-load-balancer-attributes --load-balancer-arn "$ALB" --query \
  "Attributes[?contains(['idle_timeout.timeout_seconds','routing.http.drop_invalid_header_fields.enabled','deletion_protection.enabled','access_logs.s3.enabled','routing.http.desync_mitigation_mode'], Key)].[Key,Value]" --output text

h "5. Its listeners and the existing target group"
run aws elbv2 describe-listeners --load-balancer-arn "$ALB" \
  --query 'Listeners[].[Port,Protocol,DefaultActions[0].Type,DefaultActions[0].TargetGroupArn]' --output text
for TG in $(aws elbv2 describe-target-groups --load-balancer-arn "$ALB" --query 'TargetGroups[].TargetGroupArn' --output text); do
  echo "  $(aws elbv2 describe-target-groups --target-group-arns "$TG" --query 'TargetGroups[0].[TargetGroupName,Protocol,Port,TargetType,HealthCheckPath]' --output text)"
  echo "    registered targets: $(aws elbv2 describe-target-health --target-group-arn "$TG" --query 'length(TargetHealthDescriptions)' --output text)"
done

h "6. Outbound path of the app subnets (app subnet -> NAT -> internet gateway)"
for SN in subnet-xxxxxxxx subnet-xxxxxxxx; do
  NAT=$(aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=$SN \
        --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'].NatGatewayId | [0]" --output text)
  echo "  $SN -> $NAT"
done
run aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=vpc-xxxxxxxx \
  --query 'NatGateways[].[NatGatewayId,State,SubnetId,ConnectivityType,NatGatewayAddresses[0].PublicIp]' --output text
for NS in $(aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=vpc-xxxxxxxx --query 'NatGateways[].SubnetId' --output text); do
  echo "  NAT subnet $NS default route -> $(aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=$NS \
        --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'] | [0].[GatewayId,TransitGatewayId,VpcEndpointId]" --output text)"
done
echo "  (igw-* = straight to the internet; vpce-* = a firewall in between; one NAT = both AZs depend on it)"

h "7. Public DNS: CAA on $APEX and whether $HOST is already taken"
doh() { curl -s "https://dns.google/resolve?name=$1&type=$2" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print([a['data'] for a in d.get('Answer',[])] or 'none')"; }
echo "  CAA $APEX: $(doh "$APEX" CAA)     (none = any CA allowed, incl. Amazon)"
echo "  $HOST: $(doh "$HOST" CNAME) / A: $(doh "$HOST" A)     (none = free to use)"

h "8. KMS key from the spl policy (customer-managed keys cost about \$1/month)"
run aws kms describe-key --key-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  --query 'KeyMetadata.[KeyManager,KeyState,Description]' --output text

h "9. Security services already on (for the e-mail's GuardDuty / SIEM notes)"
echo "  Security Hub: $(aws securityhub describe-hub --query HubArn --output text 2>&1 | head -1)"
echo "  Inspector (ECR/ECS scanning): $(aws inspector2 batch-get-account-status --query 'accounts[0].resourceState.[ecr.status,lambda.status]' --output text 2>&1 | head -1)"
echo "  CloudTrail trails: $(aws cloudtrail describe-trails --query 'trailList[].[Name,IsOrganizationTrail]' --output text 2>&1 | tr '\n\t' '; ')"
