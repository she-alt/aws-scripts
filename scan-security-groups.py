import boto3
import logging
from prettytable import PrettyTable


###
'''
# Print list of all security groups and their inbound/outbound rules, for given regions
# //SHAL 2024
###
'''

# regions we want to iterate over
regions = ['eu-central-1', 'us-east-1', 'eu-north-1']


def scan_security_groups_in_region(region):
   
    rows = []
    
    try:
        # Set up default session using the specified profile
        boto3.setup_default_session(profile_name='default')
        
        # Create EC2 client for the specified region
        ec2_client = boto3.client('ec2', region_name=region)
        
        # Get all security groups for the region
        security_groups = ec2_client.describe_security_groups()

    except boto3.exceptions.Boto3Error as e:
        # Handle Boto3-related errors and log them
        logging.error(f"Error retrieving security groups in region {region}: {e}")
        return []  # Return empty list if an error occurs

    try:
        for sg in security_groups['SecurityGroups']:
            group_name = sg['GroupName']
            group_id = sg['GroupId']

            # Function to process rules (inbound or outbound)
            def process_rules(rule_type, permissions):
                for permission in permissions:
                    from_port = permission.get('FromPort', 'All')
                    to_port = permission.get('ToPort', 'All')
                    protocol = permission['IpProtocol']
                    
                    # Handle IPv4 ranges
                    for ip_range in permission.get('IpRanges', []):
                        rows.append([region, group_name, group_id, rule_type, from_port, to_port, protocol, ip_range['CidrIp'], "N/A"])
                    
                    # Handle IPv6 ranges
                    for ipv6_range in permission.get('Ipv6Ranges', []):
                        rows.append([region, group_name, group_id, rule_type, from_port, to_port, protocol, ipv6_range['CidrIpv6'], "N/A"])
                    
                    # Handle security group references (UserIdGroupPairs)
                    for sg_pair in permission.get('UserIdGroupPairs', []):
                        rows.append([region, group_name, group_id, rule_type, from_port, to_port, protocol, "N/A", sg_pair['GroupId']])

            # Process inbound and outbound rules
            process_rules("Inbound", sg['IpPermissions'])
            process_rules("Outbound", sg['IpPermissionsEgress'])
    
    except Exception as e:
        # Handle any unforeseen errors in the processing
        logging.error(f"Error: Problem processing security groups in region {region}: {e}")
        return []
    
    return rows


def main():
    
    # Initialize logging for better error reporting
    logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

    # Initialize PrettyTable with column headers
    table = PrettyTable()
    table.field_names = ["Region", "Group Name", "Group ID", "Rule Type", "From Port", "To Port", "Protocol", "CIDR/IP", "Source/Destination Group"]

    # Scan each region's security groups
    for region in regions:
        try:
            rows = scan_security_groups_in_region(region)  # Scan security groups for the region
            for row in rows:
                table.add_row(row)
            # Add marker row after each region for clarity
            table.add_row(["-", "-", "-", "-", "-", "-", "-", "-", "-"])
            
        except Exception as e:
            logging.error(f"Region {region} generated an exception: {e}")
            return

    # Print the consolidated table
    try:
        print(table)
    except Exception as e:
        logging.error(f"Error printing the table: {e}")

if __name__ == "__main__":
    main()




#
# ToDo
# - Have commandline arguments, for regions and help 
# - Refine exceptions
# ########################
# - References
# https://pypi.org/project/prettytable/
# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html
# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_security_groups.html