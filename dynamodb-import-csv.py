import boto3
import pandas as pd
import time
from botocore.exceptions import NoCredentialsError, PartialCredentialsError


###
'''
# Imports a csv file into a dynamodb table. 
# //SHAL 2024
###
'''


def load_csv_to_dynamodb(table_name: str, csv_file_path: str):
    try:
        # Initialize a session using Amazon DynamoDB
        session = boto3.Session()
        dynamodb = session.resource('dynamodb', region_name='eu-central-1')
        table = dynamodb.Table(table_name)

        # Read the CSV file into a DataFrame
        data = pd.read_csv(csv_file_path)      
        
        total_consumed_capacity = 0
        with table.batch_writer() as batch:
            for index, row in data.iterrows():
                # Convert row to dictionary and write to DynamoDB
                batch.put_item(Item=row.to_dict())

                # Track consumed capacity
                response = table.put_item(
                    Item=row.to_dict(),
                    ReturnConsumedCapacity='TOTAL'
                )
                total_consumed_capacity += response['ConsumedCapacity']['CapacityUnits']
                time.sleep(1) # better to wait a bit here :)

        print(f"Successfully loaded data from {csv_file_path} to {table_name} table.")
        print(f"Total consumed capacity: {total_consumed_capacity} capacity units.")

    except FileNotFoundError:
        print(f"Error: The file {csv_file_path} does not exist.")
    except NoCredentialsError:
        print("Error: AWS credentials not found.")
    except PartialCredentialsError:
        print("Error: Incomplete AWS credentials found.")
    except Exception as e:
        print(f"An error occurred: {e}")

# Usage example
if __name__ == "__main__":
    table_name = '<table-name>'
    csv_file_path = '<data-to-import.csv>'
    load_csv_to_dynamodb(table_name, csv_file_path)
