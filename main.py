from sodapy import Socrata
import requests
from requests.auth import HTTPBasicAuth
import json
import argparse
import sys
import os
import time


DATASET_ID = os.environ["DATASET_ID"]
APP_TOKEN = os.environ["APP_TOKEN"]
ES_HOST = os.environ["ES_HOST"]
ES_USERNAME = os.environ["ES_USERNAME"]
ES_PASSWORD = os.environ["ES_PASSWORD"]
INDEX_NAME = os.environ["INDEX_NAME"]


parser = argparse.ArgumentParser(description='Fire Incident Dispatch Data')

parser.add_argument('--page_size', type=int, help='how many rows to get per page', required=True)

parser.add_argument('--num_pages', type=int, help='how many pages to get in total')

args = parser.parse_args()

def get_data_from_api(start):
    is_success = False
    next_batch = None

    while is_success == False:
        try:
            next_batch = client.get(DATASET_ID, where='starfire_incident_id IS NOT NULL OR incident_datetime IS NOT NULL', limit=args.page_size, offset=start)
            is_success = True
        except Exception as e:
            print(f'Failed getting data from the API: {e}')
            time.sleep(3)

    return next_batch

def nicefy(rows):
    es_rows = []
    for row in rows:
        try:
            es_row = {}
            es_row["starfire_incident_id"] = row["starfire_incident_id"]
            es_row["incident_datetime"] = row["incident_datetime"]
            es_row["incident_borough"] = row["incident_borough"]
            es_row["zipcode"] = float(row["zipcode"])
            es_row["incident_classification"] = row["incident_classification"]
            es_row["incident_classification_group"] = row["incident_classification_group"]
            es_row["incident_response_seconds_qy"] = float(row["incident_response_seconds_qy"])
            es_row["incident_travel_tm_seconds_qy"] = float(row["incident_travel_tm_seconds_qy"])
            es_row["engines_assigned_quantity"] = float(row["engines_assigned_quantity"])
        except Exception as e:
            print (f"Error!: {e}, skipping row: {row}")
            continue

        es_rows.append(es_row)

    return es_rows

def send_to_elastic_search(es_rows):
    bulk_upload_data = ""

    for line in es_rows:
        action = '{"index": {"_index": "' + INDEX_NAME + '","_type": "_doc", "_id": "' + line["starfire_incident_id"] + '"}}'
        data = json.dumps(line)
        bulk_upload_data += f"{action}\n"
        bulk_upload_data += f"{data}\n"

    try:
        resp = requests.post(f"{ES_HOST}/_bulk", data=bulk_upload_data,auth=HTTPBasicAuth(ES_USERNAME, ES_PASSWORD), headers = {"Content-Type": "application/x-ndjson"})
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to insert in ES: {e}")

if __name__ == '__main__':
    try:
        resp = requests.put(f"{ES_HOST}/{INDEX_NAME}", auth=HTTPBasicAuth(ES_USERNAME, ES_PASSWORD),
            json={
                "settings": {
                    "number_of_shards": 3,
                    "number_of_replicas": 1
                },
                "mappings": {
                    "properties": {
                        "starfire_incident_id": {"type": "keyword"},
                        "incident_datetime": {"type": "date"},
                        "incident_borough": {"type": "keyword"},
                        "zipcode": {"type": "float"},
                        "incident_classification": {"type": "keyword"},
                        "incident_classification_group": {"type": "keyword"},
                        "incident_response_seconds_qy": {"type": "float"},
                        "incident_travel_tm_seconds_qy": {"type": "float"},
                        "engines_assigned_quantity": {"type": "float"}
                    }
                },
            }
        )
        resp.raise_for_status()
        #print(resp.json())
    except Exception as e:
        print("Index already exists! Skipping")
    client = Socrata("data.cityofnewyork.us", APP_TOKEN, timeout=10000)

    start = 0

    while True:
        next_batch = get_data_from_api(start)
        nicefied_batch = nicefy(next_batch)
        send_to_elastic_search(nicefied_batch)
        start += args.page_size
        print(f'Total count processed so far: {start}')
        if (args.page_size > len(next_batch) or args.num_pages == start / args.page_size):
            if (args.num_pages==None):
                print("Total number of items: ", client.get(DATASET_ID, select='COUNT(*)'))
            break
