#!/usr/bin/env bash
# Read-only network check for the sympany-socmon deployment (AWS CloudShell, eu-central-2):
#
#     bash check-network.sh
#
# Lists the VPCs and subnets, says which subnets can reach the internet and how (internet
# gateway = public, NAT / transit gateway = private with outbound access, none = isolated),
# and lists VPC endpoints. Only ec2 describe-* calls; nothing is created or changed.
#
# It cannot see firewall / proxy allow-lists in Sympany's shared egress (e.g. behind a transit
# gateway in another account). For a live test see the end of this script's output.

set -uo pipefail
export AWS_DEFAULT_REGION=eu-central-2

echo "== VPCs"
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,Tags[?Key==`Name`]|[0].Value]' --output text |
  while read -r id cidr name; do printf '  %-24s %-18s %s\n' "$id" "$cidr" "${name:-}"; done

echo; echo "== Subnets and their default route (0.0.0.0/0)"
printf '  %-26s %-12s %-16s %-24s %-22s %s\n' SUBNET AZ CIDR VPC TYPE NAME
for row in $(aws ec2 describe-subnets --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,VpcId]' --output text | tr '\t' ','); do
  IFS=, read -r sn az cidr vpc <<<"$row"
  name=$(aws ec2 describe-subnets --subnet-ids "$sn" --query 'Subnets[0].Tags[?Key==`Name`]|[0].Value' --output text)
  rt=$(aws ec2 describe-route-tables --filters Name=association.subnet-id,Values="$sn" --query 'RouteTables[0].RouteTableId' --output text)
  if [ "$rt" = "None" ] || [ -z "$rt" ]; then   # no explicit association: the VPC's main table
    rt=$(aws ec2 describe-route-tables --filters Name=vpc-id,Values="$vpc" Name=association.main,Values=true --query 'RouteTables[0].RouteTableId' --output text)
  fi
  tgt=$(aws ec2 describe-route-tables --route-table-ids "$rt" \
        --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'] | [0].[GatewayId,NatGatewayId,TransitGatewayId,NetworkInterfaceId,VpcPeeringConnectionId]" --output text)
  case "$tgt" in
    *igw-*) type="public (internet gw)" ;;
    *nat-*) type="private + NAT" ;;
    *tgw-*) type="private + transit gw" ;;
    *eni-*) type="private + appliance" ;;
    *pcx-*) type="private + peering" ;;
    *)      type="isolated (no route)" ;;
  esac
  printf '  %-26s %-12s %-16s %-24s %-22s %s\n' "$sn" "$az" "$cidr" "$vpc" "$type" "${name/None/}"
done
cat <<'TXT'

  Needed: 2 "private + NAT" or "private + transit gw" subnets (eu-central-2a, 2b) for the ECS
  tasks, and 2 "public (internet gw)" subnets (2a, 2b) for an internet-facing load balancer.
TXT

echo; echo "== VPC endpoints (traffic to these AWS services stays inside AWS)"
aws ec2 describe-vpc-endpoints --query 'VpcEndpoints[].[VpcId,VpcEndpointType,ServiceName,State]' --output text |
  while read -r vpc type svc state; do printf '  %-24s %-10s %-50s %s\n' "$vpc" "$type" "$svc" "$state"; done
cat <<'TXT'
  Useful (optional): Gateway s3 + dynamodb. Without a NAT route, the tasks would also need
  Interface endpoints for ecr.api, ecr.dkr, logs, ssm, sns, bedrock-runtime, transcribestreaming
  — and Apify / Bright Data / YouTube would still be unreachable.

== Network ACLs that block outbound HTTPS (443)
TXT
aws ec2 describe-network-acls --query 'NetworkAcls[].[NetworkAclId,VpcId]' --output text | while read -r acl vpc; do
  deny=$(aws ec2 describe-network-acls --network-acl-ids "$acl" \
    --query "NetworkAcls[0].Entries[?Egress==\`true\` && RuleAction=='deny' && RuleNumber<\`32767\`].[RuleNumber,CidrBlock,PortRange.From,PortRange.To]" --output text)
  if [ -n "$deny" ]; then printf '  %s (%s) has outbound deny rules:\n%s\n' "$acl" "$vpc" "$(sed 's/^/      /' <<<"$deny")"; fi
done
echo "  (no output above = no custom outbound deny rules)"

cat <<'TXT'

== Live test (optional — shows what the private subnet can really reach)
  CloudShell normally runs outside your VPC, so a curl from it proves nothing about the VPC.
  To test from inside: CloudShell -> Actions -> Create VPC environment -> pick the VPC, one of
  the private subnets and a security group that allows outbound 443. In that environment run:

    for u in https://api.apify.com https://api.brightdata.com https://www.youtube.com \
             https://bedrock-runtime.eu-central-2.amazonaws.com https://transcribestreaming.eu-central-2.amazonaws.com \
             https://api.ecr.eu-central-2.amazonaws.com https://ssm.eu-central-2.amazonaws.com; do
      printf '%-58s ' "$u"; curl -s -o /dev/null -m 10 -w '%{http_code}\n' "$u" || echo BLOCKED
    done

  Any HTTP code (200, 403, 404 ...) = reachable; 000 / BLOCKED = blocked by routing or firewall.
  Delete the VPC environment afterwards (it only adds a temporary network interface).
TXT
