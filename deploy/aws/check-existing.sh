#!/usr/bin/env bash
# Read-only: what already exists for the app in this account (eu-central-2) — certificates,
# DNS zones, load balancers, security groups and WAF — and who hosts Sympany's public DNS.
#
#     bash check-existing.sh            # checks sympany.ch
#     bash check-existing.sh other.com  # another domain
#
# Only list / describe / get calls and a public DNS lookup; nothing is created or changed.

set -uo pipefail
export AWS_DEFAULT_REGION=eu-central-2
DOMAIN=${1:-sympany.ch}
VPC=vpc-xxxxxxxx          # sympany-slp-vpc
row() { printf '  %s\n' "$*"; }

echo "== ACM certificates in eu-central-2 (an ALB can only use a certificate from its own Region)"
out=$(aws acm list-certificates --certificate-statuses ISSUED PENDING_VALIDATION \
      --query 'CertificateSummaryList[].[DomainName,Status,Type,InUse,CertificateArn]' --output text 2>&1)
[ -n "$out" ] && sed 's/^/  /' <<<"$out" || row "(none)"
for arn in $(aws acm list-certificates --query 'CertificateSummaryList[].CertificateArn' --output text 2>/dev/null); do
  row "$(aws acm describe-certificate --certificate-arn "$arn" --query 'Certificate.[DomainName,join(`, `,SubjectAlternativeNames),NotAfter]' --output text)"
done

echo; echo "== Route 53 hosted zones in this account"
out=$(aws route53 list-hosted-zones --query 'HostedZones[].[Name,Config.PrivateZone,Id]' --output text 2>&1)
[ -n "$out" ] && sed 's/^/  /' <<<"$out" || row "(none — Sympany's DNS is managed elsewhere)"

echo; echo "== Public DNS for $DOMAIN (who hosts it)"
if command -v dig >/dev/null; then
  row "name servers: $(dig +short NS "$DOMAIN" | tr '\n' ' ')"
else
  nslookup -type=NS "$DOMAIN" 2>/dev/null | grep -i 'nameserver' | sed 's/^/  /'
fi
row "(awsdns-* = Route 53, possibly in another Sympany account; anything else = external DNS provider)"

echo; echo "== Load balancers (with their HTTPS certificates)"
for lb in $(aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerArn' --output text); do
  row "$(aws elbv2 describe-load-balancers --load-balancer-arns "$lb" --query 'LoadBalancers[0].[LoadBalancerName,Scheme,VpcId,DNSName]' --output text)"
  aws elbv2 describe-listeners --load-balancer-arn "$lb" --query 'Listeners[].[Protocol,Port,Certificates[0].CertificateArn]' --output text | sed 's/^/      listener: /'
done
aws elbv2 describe-load-balancers --query 'length(LoadBalancers)' --output text | grep -qx 0 && row "(none)"

echo; echo "== Security groups in sympany-slp-vpc"
aws ec2 describe-security-groups --filters Name=vpc-id,Values=$VPC \
  --query 'SecurityGroups[].[GroupId,GroupName,length(IpPermissions)]' --output text |
  while read -r id name n; do row "$id  $name  ($n inbound rule(s))"; done

echo; echo "== WAF web ACLs (regional)"
out=$(aws wafv2 list-web-acls --scope REGIONAL --query 'WebACLs[].[Name,Id]' --output text 2>&1)
[ -n "$out" ] && sed 's/^/  /' <<<"$out" || row "(none)"

echo; echo "== Already created with the sympany / socmon names"
row "ECS clusters:    $(aws ecs list-clusters --query 'clusterArns' --output text)"
row "ECR repos:       $(aws ecr describe-repositories --query 'repositories[].repositoryName' --output text 2>/dev/null)"
row "DynamoDB tables: $(aws dynamodb list-tables --query 'TableNames' --output text)"
row "S3 buckets:      $(aws s3api list-buckets --query "Buckets[?contains(Name,'sympany')].Name" --output text 2>/dev/null)"
row "SNS topics:      $(aws sns list-topics --query 'Topics[].TopicArn' --output text | tr '\t' '\n' | grep -i sympany | tr '\n' ' ')"
