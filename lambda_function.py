import sys

# making sure dependencies are found
sys.path.append("/opt/python")

import boto3
import pymupdf
import tempfile
import io
import json
import logging
from PIL import Image, ImageDraw
from pprint import pprint


def get_rows_columns_map(table_result, blocks_map):
    rows = {}
    scores = []
    for relationship in table_result["Relationships"]:
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                cell = blocks_map[child_id]
                if cell["BlockType"] == "CELL":
                    row_index = cell["RowIndex"]
                    col_index = cell["ColumnIndex"]
                    if row_index not in rows:
                        # create new row
                        rows[row_index] = {}

                    # get confidence score
                    scores.append(str(cell["Confidence"]))

                    # get the text value
                    rows[row_index][col_index] = get_text(cell, blocks_map)
    return rows, scores


def get_text(result, blocks_map):
    text = ""
    if "Relationships" in result:
        for relationship in result["Relationships"]:
            if relationship["Type"] == "CHILD":
                for child_id in relationship["Ids"]:
                    word = blocks_map[child_id]
                    if word["BlockType"] == "WORD":
                        if (
                            "," in word["Text"]
                            and word["Text"].replace(",", "").isnumeric()
                        ):
                            text += '"' + word["Text"] + '"' + " "
                        else:
                            text += word["Text"] + " "
                    if word["BlockType"] == "SELECTION_ELEMENT":
                        if word["SelectionStatus"] == "SELECTED":
                            text += "X "
    return text


def generate_table_csv(table_result, blocks_map, table_index):
    rows, scores = get_rows_columns_map(table_result, blocks_map)

    table_id = "Table_" + str(table_index)

    # get cells.
    csv = "Table: {0}\n\n".format(table_id)

    for row_index, cols in rows.items():
        for col_index, text in cols.items():
            col_indices = len(cols.items())
            csv += "{}".format(text) + ","
        csv += "\n"

    csv += "\n\n Confidence Scores % (Table Cell) \n"
    cols_count = 0
    for score in scores:
        cols_count += 1
        csv += score + ","
        if cols_count == col_indices:
            csv += "\n"
            cols_count = 0

    csv += "\n\n\n"
    return csv


def lambda_handler(event, context):
    print(json.dumps(event))
    textract_client = boto3.client("textract")
    s3_client = boto3.client("s3")
    # Get the PDF object from S3
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = event["Records"][0]["s3"]["object"]["key"]
    filename = key.split("/")[1].split(".")[0]
    obj = s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )
    pdf_content = obj["Body"].read()

    # Open the PDF document using PyMuPDF
    pdf_doc = pymupdf.open(stream=pdf_content)

    # Convert each page of the PDF to a JPG image
    total_text = []
    for i in range(len(pdf_doc)):
        page = pdf_doc[i]
        pixmap = page.get_pixmap(dpi=300)
        image = pixmap.pil_image()
        img = pixmap.tobytes()
        document = f"processed/{filename}/{filename}-page-{i + 1}.jpg"

        # Upload the JPG image to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=document,
            Body=img,
        )

        # Detect text in the document
        # Process using S3 object
        detection_response = textract_client.detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": document}}
        )

        # Get the text blocks
        blocks = detection_response["Blocks"]
        width, height = image.size
        page_text = []
        for block in blocks:
            draw = ImageDraw.Draw(image)
            # Draw WORD - Green -  start of word, red - end of word
            if block["BlockType"] == "WORD":
                draw.line(
                    [
                        (
                            width * block["Geometry"]["Polygon"][0]["X"],
                            height * block["Geometry"]["Polygon"][0]["Y"],
                        ),
                        (
                            width * block["Geometry"]["Polygon"][3]["X"],
                            height * block["Geometry"]["Polygon"][3]["Y"],
                        ),
                    ],
                    fill="green",
                    width=2,
                )

                draw.line(
                    [
                        (
                            width * block["Geometry"]["Polygon"][1]["X"],
                            height * block["Geometry"]["Polygon"][1]["Y"],
                        ),
                        (
                            width * block["Geometry"]["Polygon"][2]["X"],
                            height * block["Geometry"]["Polygon"][2]["Y"],
                        ),
                    ],
                    fill="red",
                    width=2,
                )

            # Draw box around entire LINE
            if block["BlockType"] == "LINE":
                page_text.append(block["Text"])
                points = []

                for polygon in block["Geometry"]["Polygon"]:
                    points.append((width * polygon["X"], height * polygon["Y"]))

                draw.polygon((points), outline="black")

        annotated_document = f"processed/{filename}/{filename}-page-{i + 1}_annoted.jpg"
        annotated_text = "\n".join(page_text)
        total_text.append(annotated_text)

        in_mem_file = io.BytesIO()
        image.save(in_mem_file, format="jpeg")
        in_mem_file.seek(0)

        s3_client.put_object(
            Bucket=bucket,
            Key=annotated_document,
            Body=in_mem_file,
        )
        # print(len(blocks))
    document_text = "\n\n".join(total_text)
    raw_text_document = f"processed/{filename}/{filename}_raw_text.txt"
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
        temp_file.write(document_text)
        temp_file_path = temp_file.name
        s3_client.upload_file(temp_file_path, bucket, raw_text_document)

    # Get the tables
    table_response = textract_client.analyze_document(
        Document={"S3Object": {"Bucket": bucket, "Name": document}},
        FeatureTypes=["TABLES"],
    )
    table_blocks = table_response["Blocks"]
    # pprint(blocks)

    blocks_map = {}
    table_blocks = []
    for block in blocks:
        blocks_map[block["Id"]] = block
        if block["BlockType"] == "TABLE":
            table_blocks.append(block)

    if len(table_blocks) <= 0:
        logging.warn("No table found.")
    else:
        logging.info("processing table.")
        for index, table in enumerate(table_blocks):
            csv += generate_table_csv(table, blocks_map, index + 1)
            csv += "\n\n"

        table_document = f"processed/{filename}/{filename}_table_extract.csv"
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write(csv)
            temp_file_path = temp_file.name
            s3_client.upload_file(temp_file_path, bucket, table_document)


if __name__ == "__main__":
    lambda_handler(
        {
            "Records": [
                {
                    "eventVersion": "2.1",
                    "eventSource": "aws:s3",
                    "awsRegion": "eu-west-3",
                    "eventTime": "2025-01-28T14:49:02.006Z",
                    "eventName": "ObjectCreated:Put",
                    "userIdentity": {"principalId": "AWS:AIDATMDN2HSWFD755GY2M"},
                    "requestParameters": {"sourceIPAddress": "77.132.39.200"},
                    "responseElements": {
                        "x-amz-request-id": "PXJTCZ9ZV3P9KE9T",
                        "x-amz-id-2": "wNWF9KIyGm8zii9flh88RniSwqcCJ20bbjfpkUowd3d9+WcYKYkhvXCxobb5lgYGmEQf4dno6ANsYOkS9Qkp/3noo0KR1CL9ekkJtkQ5kRM=",
                    },
                    "s3": {
                        "s3SchemaVersion": "1.0",
                        "configurationId": "tf-s3-lambda-20250128142629188800000001",
                        "bucket": {
                            "name": "test-bucket-rcanillas-28012025",
                            "ownerIdentity": {"principalId": "A3FVN5NA18LZ3D"},
                            "arn": "arn:aws:s3:::test-bucket-rcanillas-28012025",
                        },
                        "object": {
                            "key": "raw/table_exemple.pdf",
                            "size": 357927,
                            "eTag": "5294a0e02abed3df1294758f16a5fb5f",
                            "sequencer": "006798EE5DE7E79F7F",
                        },
                    },
                }
            ]
        },
        {},
    )
