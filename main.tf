resource "aws_s3_bucket" "test_bucket" {
  bucket = "test-bucket-rcanillas-28012025"
}
resource "aws_lambda_permission" "allow_bucket" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.test_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.test_bucket.arn
}

resource "aws_s3_bucket_notification" "bucket_notification" {
  bucket = aws_s3_bucket.test_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.test_lambda.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    filter_suffix       = ".pdf"
  }
  depends_on = [aws_lambda_permission.allow_bucket]
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_policy_attachment" "lambda_basic_execution" {
  name       = "basic-execution-lambda-attachment"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  roles      = [aws_iam_role.iam_for_lambda.name]
}

resource "aws_iam_policy_attachment" "lambda_textract_access" {
  name       = "textract-lambda-attachment"
  policy_arn = "arn:aws:iam::aws:policy/AmazonTextractFullAccess"
  roles      = [aws_iam_role.iam_for_lambda.name]
}

resource "aws_iam_policy" "s3_policy" {
  name        = "s3-policy"
  description = "s3 policy for bucket"


  policy = <<EOF
   {
"Version": "2012-10-17",
"Statement": [
    {
        "Effect": "Allow",
        "Action": [
            "logs:*"
        ],
        "Resource": "arn:aws:logs:*:*:*"
    },
    {
        "Effect": "Allow",
        "Action": [
            "s3:*"
        ],
        "Resource": "${aws_s3_bucket.test_bucket.arn}}"
    }
]

} 
    EOF
}

resource "aws_iam_policy_attachment" "lambda_s3_access" {
  name       = "s3-lambda-attachment"
  policy_arn = aws_iam_policy.s3_policy.arn
  roles      = [aws_iam_role.iam_for_lambda.name]
}

resource "aws_iam_role" "iam_for_lambda" {
  name               = "iam_for_lambda"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

data "archive_file" "lambda" {
  type        = "zip"
  source_file = "main.py"
  output_path = "lambda_function_payload.zip"
}

resource "aws_lambda_function" "test_lambda" {
  filename      = "lambda_function_payload.zip"
  function_name = "lambda_function_test"
  role          = aws_iam_role.iam_for_lambda.arn
  handler       = "main.lambda_handler"

  source_code_hash = data.archive_file.lambda.output_base64sha256

  runtime = "python3.12"

}

