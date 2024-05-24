import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError, EndpointConnectionError
from prettytable import PrettyTable

###
'''
# Print list of all ec2 instances, their IPs and state for given regions
# //SHAL 2024
###
'''

# regions we want to iterate over
regions = ['eu-west-1', 'eu-central-1', 'eu-north-1']

def get_all_ec2_instances(regions):
    ec2_instances = []
    # Set up default session with specified profile
    boto3.setup_default_session(profile_name='default')  
    
    # Loop through all the given regions
    for region in regions:
        try:
            # Create EC2 client for the region and describe instances in the region
            ec2_client = boto3.client('ec2', region_name=region)  
            response = ec2_client.describe_instances()
            
            # Extract reservation information
            instances = response['Reservations']  
            
            # Loop through each reservation to get instance details
            for reservation in instances:
                for instance in reservation['Instances']:
                    instance_id = instance['InstanceId']  
                    state = instance['State']['Name']  # 
                    private_ip = instance.get('PrivateIpAddress', 'N/A')  
                    public_ip = instance.get('PublicIpAddress', 'N/A')  
                    
                    # Append instance details to the list
                    ec2_instances.append({
                        'Region': region,
                        'InstanceId': instance_id,
                        'State': state,
                        'PrivateIp': private_ip,
                        'PublicIp': public_ip
                    })
                    
        except NoCredentialsError:
            print(f"Error: Credentials not available for region: {region}")
        except PartialCredentialsError:
            print(f"Error: Incomplete credentials provided for region: {region}")
        except EndpointConnectionError:
            print(f"Error: Could not connect to the endpoint URL for region: {region}")
        except ClientError as e:
            print(f"Error: Client error in region {region}: {e}")
        except Exception as e:
            print(f"Error: An unexpected error occurred in region {region}: {e}")
            
    return ec2_instances


def print_ec2_table(ec2_instances):

    # if there are no EC2 instances to display
    if not ec2_instances:
        print("** No EC2 instances to display ** ")
        return

    try:
        # Initialize the table with column headers
        table = PrettyTable(['Instance ID', 'State', 'Private IP', 'Public IP', 'Region'])  

        # Add each instance's details as a row in the table
        for instance in ec2_instances:
            table.add_row([instance['InstanceId'], instance['State'], instance['PrivateIp'], instance['PublicIp'], instance['Region']])

        # Print the table
        print(table)
        
    except Exception as e:
        # Handle any unexpected errors that might occur during the table printing process
        print(f"Error: An unexpected error occurred while printing the table: {e}")


if __name__ == '__main__':    
    all_ec2_instances = get_all_ec2_instances(regions)
    print_ec2_table(all_ec2_instances)
    
    
#
# ToDo
# - Have commandline arguments, for regions and help 
# ########################
# - References
# https://pypi.org/project/prettytable/
# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html
#