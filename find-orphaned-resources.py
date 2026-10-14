import argparse
import logging
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    ProfileNotFound,
    EndpointConnectionError,
)

logger = logging.getLogger(__name__)

###
'''
# Scans AWS accounts for common sources of waste like:
 - Unattached EBS volumes (status: available)
 - Unused Elastic IPs (not associated with any instance)
 - Old EBS snapshots (> N days)
 - Idle load balancers (no healthy targets)
 - Empty target groups (ALB/NLB)
# //SHAL 2024
###
'''

# Rough on-demand pricing 
PRICE_EBS_GP3_PER_GB_MONTH = 0.07
PRICE_EBS_GP2_PER_GB_MONTH = 0.11
PRICE_EIP_PER_MONTH = 4.00
PRICE_SNAPSHOT_PER_GB_MONTH = 0.05
PRICE_ALB_PER_MONTH = 16.00
PRICE_NLB_PER_MONTH = 16.00


def setup_logging(level_name):
    """Configure root logging with a consistent format."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,
    )


def _handle_client_error(err, context):
    error_code = err.response.get('Error', {}).get('Code', 'Unknown')
    error_msg = err.response.get('Error', {}).get('Message', str(err))
    logger.error(
        "%s failed [%s]: %s", context, error_code, error_msg
    )


def find_unattached_volumes(ec2, region):
    findings = []
    logger.debug("Scanning for unattached EBS volumes in %s", region)
    try:
        paginator = ec2.get_paginator('describe_volumes')
        for page in paginator.paginate(
            Filters=[{'Name': 'status', 'Values': ['available']}]
        ):
            for vol in page['Volumes']:
                try:
                    size = vol['Size']
                    vol_type = vol['VolumeType']
                    if vol_type == 'gp2':
                        monthly = size * PRICE_EBS_GP2_PER_GB_MONTH
                    else:
                        monthly = size * PRICE_EBS_GP3_PER_GB_MONTH

                    findings.append({
                        'region': region,
                        'type': 'EBS Volume',
                        'id': vol['VolumeId'],
                        'detail': f"{size} GB {vol_type}",
                        'created': vol['CreateTime'].strftime('%Y-%m-%d'),
                        'monthly_cost': round(monthly, 2),
                    })
                except KeyError as e:
                    logger.warning(
                        "Skipping malformed volume record in %s: missing %s",
                        region, e
                    )
    except ClientError as e:
        _handle_client_error(e, f"describe_volumes in {region}")
    except EndpointConnectionError as e:
        logger.error("Error: Cannot reach EC2 endpoint in %s: %s", region, e)
    except BotoCoreError as e:
        logger.error("Error: BotoCore error listing volumes in %s: %s", region, e)
    except Exception as e:
        logger.exception("Error: Unexpected error listing volumes in %s: %s", region, e)

    logger.debug("Found %d unattached volumes in %s", len(findings), region)
    return findings


def find_unused_eips(ec2, region):
    findings = []
    logger.debug("Scanning for unused Elastic IPs in %s", region)
    try:
        response = ec2.describe_addresses()
    except ClientError as e:
        _handle_client_error(e, f"describe_addresses in {region}")
        return findings
    except EndpointConnectionError as e:
        logger.error("Error: Cannot reach EC2 endpoint in %s: %s", region, e)
        return findings
    except BotoCoreError as e:
        logger.error("Error: BotoCore error describing addresses in %s: %s", region, e)
        return findings

    for addr in response.get('Addresses', []):
        try:
            if 'AssociationId' not in addr and 'InstanceId' not in addr:
                findings.append({
                    'region': region,
                    'type': 'Elastic IP',
                    'id': addr.get('PublicIp', 'unknown'),
                    'detail': addr.get('AllocationId', ''),
                    'created': 'n/a',
                    'monthly_cost': PRICE_EIP_PER_MONTH,
                })
        except Exception as e:
            logger.warning("Skipping malformed EIP record in %s: %s", region, e)

    logger.debug("Found %d unused EIPs in %s", len(findings), region)
    return findings


def find_old_snapshots(ec2, region, max_age_days):
    findings = []
    logger.debug(
        "Scanning for EBS snapshots older than %d days in %s",
        max_age_days, region
    )
    now = datetime.now(timezone.utc)
    try:
        paginator = ec2.get_paginator('describe_snapshots')
        for page in paginator.paginate(OwnerIds=['self']):
            for snap in page.get('Snapshots', []):
                try:
                    age = (now - snap['StartTime']).days
                    if age > max_age_days:
                        size = snap.get('VolumeSize', 0)
                        monthly = size * PRICE_SNAPSHOT_PER_GB_MONTH
                        findings.append({
                            'region': region,
                            'type': 'EBS Snapshot',
                            'id': snap['SnapshotId'],
                            'detail': f"{size} GB, age {age} days",
                            'created': snap['StartTime'].strftime('%Y-%m-%d'),
                            'monthly_cost': round(monthly, 2),
                        })
                except KeyError as e:
                    logger.warning(
                        "Skipping malformed snapshot in %s: missing %s",
                        region, e
                    )
    except ClientError as e:
        _handle_client_error(e, f"describe_snapshots in {region}")
    except EndpointConnectionError as e:
        logger.error("Error: Cannot reach EC2 endpoint in %s: %s", region, e)
    except BotoCoreError as e:
        logger.error("Error: BotoCore error listing snapshots in %s: %s", region, e)
    except Exception as e:
        logger.exception("Error: Unexpected error listing snapshots in %s: %s", region, e)

    logger.debug("Found %d old snapshots in %s", len(findings), region)
    return findings


def find_idle_load_balancers(elbv2, region):
    findings = []
    logger.debug("Scanning for idle load balancers in %s", region)
    try:
        paginator = elbv2.get_paginator('describe_load_balancers')
        for page in paginator.paginate():
            for lb in page.get('LoadBalancers', []):
                lb_arn = lb.get('LoadBalancerArn')
                lb_name = lb.get('LoadBalancerName', 'unknown')
                lb_type = lb.get('Type', 'unknown')

                if not lb_arn:
                    logger.warning(
                        "Skipping LB %s in %s: missing ARN", lb_name, region
                    )
                    continue

                try:
                    tg_resp = elbv2.describe_target_groups(
                        LoadBalancerArn=lb_arn
                    )
                    target_groups = tg_resp.get('TargetGroups', [])
                except ClientError as e:
                    _handle_client_error(
                        e, f"describe_target_groups for {lb_name} in {region}"
                    )
                    continue

                if not target_groups:
                    findings.append({
                        'region': region,
                        'type': f'{lb_type.upper()} (no target groups)',
                        'id': lb_name,
                        'detail': lb.get('DNSName', ''),
                        'created': lb['CreatedTime'].strftime('%Y-%m-%d'),
                        'monthly_cost': PRICE_ALB_PER_MONTH,
                    })
                    continue

                total_healthy = 0
                for tg in target_groups:
                    tg_arn = tg.get('TargetGroupArn')
                    if not tg_arn:
                        continue
                    try:
                        health = elbv2.describe_target_health(
                            TargetGroupArn=tg_arn
                        )
                        total_healthy += sum(
                            1 for t in health.get('TargetHealthDescriptions', [])
                            if t.get('TargetHealth', {}).get('State') == 'healthy'
                        )
                    except ClientError as e:
                        _handle_client_error(
                            e, f"describe_target_health for {tg_arn} in {region}"
                        )
                        continue

                if total_healthy == 0:
                    findings.append({
                        'region': region,
                        'type': f'{lb_type.upper()} (no healthy targets)',
                        'id': lb_name,
                        'detail': lb.get('DNSName', ''),
                        'created': lb['CreatedTime'].strftime('%Y-%m-%d'),
                        'monthly_cost': PRICE_ALB_PER_MONTH,
                    })
    except ClientError as e:
        _handle_client_error(e, f"describe_load_balancers in {region}")
    except EndpointConnectionError as e:
        logger.error("Error: Cannot reach ELBv2 endpoint in %s: %s", region, e)
    except BotoCoreError as e:
        logger.error("Error: BotoCore error listing LBs in %s: %s", region, e)
    except Exception as e:
        logger.exception("Error: Unexpected error listing LBs in %s: %s", region, e)

    logger.debug("Found %d idle load balancers in %s", len(findings), region)
    return findings


def find_empty_target_groups(elbv2, region):
    findings = []
    logger.debug("Scanning for empty target groups in %s", region)
    try:
        paginator = elbv2.get_paginator('describe_target_groups')
        for page in paginator.paginate():
            for tg in page.get('TargetGroups', []):
                tg_arn = tg.get('TargetGroupArn')
                if not tg_arn:
                    logger.warning(
                        "Skipping target group %s in %s: missing ARN",
                        tg.get('TargetGroupName', 'unknown'), region
                    )
                    continue
                try:
                    health = elbv2.describe_target_health(
                        TargetGroupArn=tg_arn
                    )
                except ClientError as e:
                    _handle_client_error(
                        e, f"describe_target_health for {tg_arn} in {region}"
                    )
                    continue

                if not health.get('TargetHealthDescriptions'):
                    findings.append({
                        'region': region,
                        'type': 'Target Group (empty)',
                        'id': tg['TargetGroupName'],
                        'detail': f"{tg['Protocol']}:{tg.get('Port', 'n/a')}",
                        'created': 'n/a',
                        'monthly_cost': 0.0,
                    })
    except ClientError as e:
        _handle_client_error(e, f"describe_target_groups in {region}")
    except EndpointConnectionError as e:
        logger.error("Error: Cannot reach ELBv2 endpoint in %s: %s", region, e)
    except BotoCoreError as e:
        logger.error("Error: BotoCore error listing target groups in %s: %s", region, e)
    except Exception as e:
        logger.exception(
            "Unexpected error listing target groups in %s: %s", region, e
        )

    logger.debug("Found %d empty target groups in %s", len(findings), region)
    return findings


def print_summary(all_findings):
    """Print a grouped summary with totals."""
    if not all_findings:
        logger.info("No orphaned resources found. Nice and clean.")
        return

    logger.info("=" * 78)
    logger.info("Orphaned resource summary")
    logger.info("=" * 78)

    by_type = {}
    for f in all_findings:
        by_type.setdefault(f['type'], []).append(f)

    total_monthly = 0.0
    for rtype, items in sorted(by_type.items()):
        subtotal = sum(i['monthly_cost'] for i in items)
        total_monthly += subtotal
        logger.info(
            "%s  (%d found, ~$%.2f/mo)", rtype, len(items), subtotal
        )
        logger.info("-" * 78)
        for item in items:
            logger.info(
                "  [%s] %-40s %-35s $%.2f/mo",
                item['region'], item['id'], item['detail'],
                item['monthly_cost']
            )

    logger.info("=" * 78)
    logger.info("Estimated total monthly savings: $%.2f", total_monthly)
    logger.info("Estimated annual savings:        $%.2f", total_monthly * 12)
    logger.info("=" * 78)


def build_session(profile):
    """Create a boto3 Session, handling credential/profile errors."""
    try:
        if profile:
            logger.info("Using AWS profile: %s", profile)
            return boto3.Session(profile_name=profile)
        return boto3.Session()
    except ProfileNotFound as e:
        logger.error("Error: AWS profile not found: %s", e)
        sys.exit(2)
    except NoCredentialsError as e:
        logger.error("Error: AWS credentials not found: %s", e)
        sys.exit(2)
    except BotoCoreError as e:
        logger.error("Error: Failed to create boto3 session: %s", e)
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser(
        description="Find orphaned AWS resources and estimate monthly savings."
    )
    parser.add_argument(
        '--regions',
        nargs='+',
        required=True,
        help='List of AWS regions to scan (e.g. us-east-1 eu-west-1)'
    )
    parser.add_argument(
        '--snapshot-age',
        type=int,
        default=30,
        help='Flag EBS snapshots older than N days (default: 30)'
    )
    parser.add_argument(
        '--profile',
        default=None,
        help='AWS profile to use (optional)'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging verbosity (default: INFO)'
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    if args.snapshot_age < 0:
        logger.error("--snapshot-age must be >= 0 (got %d)", args.snapshot_age)
        sys.exit(1)

    session = build_session(args.profile)

    all_findings = []
    failed_regions = []

    for region in args.regions:
        logger.info("Scanning region: %s", region)
        try:
            ec2 = session.client('ec2', region_name=region)
            elbv2 = session.client('elbv2', region_name=region)
        except (ClientError, BotoCoreError, EndpointConnectionError) as e:
            logger.error(
                "Cannot create clients for %s, skipping region: %s", region, e
            )
            failed_regions.append(region)
            continue

        all_findings.extend(find_unattached_volumes(ec2, region))
        all_findings.extend(find_unused_eips(ec2, region))
        all_findings.extend(
            find_old_snapshots(ec2, region, args.snapshot_age)
        )
        all_findings.extend(find_idle_load_balancers(elbv2, region))
        all_findings.extend(find_empty_target_groups(elbv2, region))

    print_summary(all_findings)

    if failed_regions:
        logger.warning(
            "Some regions could not be scanned: %s",
            ", ".join(failed_regions)
        )
        sys.exit(3)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception("Unhandled exception: %s", e)
        sys.exit(1)


 # ToDo
# - 
# ########################
# - references
# https://docs.aws.amazon.com/boto3/latest/
# https://docs.python.org/3/library/logging.html
#