# Claimdesk on AWS (eu-central-1), serverless so an idle demo costs close to nothing.
#
#   CloudFront ─┬─ /*      → S3 (React app, private, origin access control)
#               └─ /api/*  → Lambda function URL (FastAPI via Mangum; refuses calls without CloudFront's secret header)
#   API Lambda ── S3 store (claims, documents, rollout state, reviewer feedback) ── SQS ──▶ worker Lambda (OCR + extraction)
#   worker ── Bedrock (champion: Claude via the EU inference profile)  /  Modal vLLM (challenger: fine-tuned Qwen3)
#
# First apply: `terraform apply -target=aws_ecr_repository.app`, push the image, then `terraform apply`.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "claimdesk" } }
}

data "aws_caller_identity" "me" {}

resource "random_id" "suffix" { byte_length = 3 }
resource "random_password" "origin" {
  length  = 40
  special = false
}

locals {
  name      = "claimdesk-${random_id.suffix.hex}"
  image_uri = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  env = {
    STORE_BUCKET         = aws_s3_bucket.store.bucket
    QUEUE_URL            = aws_sqs_queue.jobs.url
    ORIGIN_SECRET        = random_password.origin.result
    REVIEWS_READONLY     = "true"
    CHAMPION_BASE_URL    = "bedrock"
    CHAMPION_MODEL       = var.champion_model
    CHALLENGER_BASE_URL  = var.challenger_base_url
    CHALLENGER_KEY_PARAM = aws_ssm_parameter.challenger_key.name
    TESSERACT_CMD        = "tesseract"
  }
}

# ── storage and queue ──────────────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "store" { bucket = "${local.name}-store" }
resource "aws_s3_bucket_public_access_block" "store" {
  bucket                  = aws_s3_bucket.store.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600
}
resource "aws_sqs_queue" "jobs" {
  name                       = "${local.name}-jobs"
  visibility_timeout_seconds = 360 # > worker timeout
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 3 })
}

resource "aws_ssm_parameter" "challenger_key" {
  name  = "/${local.name}/challenger-api-key"
  type  = "SecureString"
  value = var.challenger_api_key
}

resource "aws_ecr_repository" "app" {
  name                 = "claimdesk"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({ rules = [{ rulePriority = 1, description = "keep 5 images", action = { type = "expire" },
  selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 } }] })
}

# ── functions ──────────────────────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "fn" {
  name = "${local.name}-fn"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole",
  Principal = { Service = "lambda.amazonaws.com" } }] })
}
resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.fn.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "fn" {
  role = aws_iam_role.fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.store.arn}/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.store.arn },
      { Effect = "Allow", Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.jobs.arn },
      { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = aws_ssm_parameter.challenger_key.arn },
      # Only the champion model, only through EU inference profiles (data stays in EU regions).
      { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = [
        "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.me.account_id}:inference-profile/${var.champion_model}",
        "arn:aws:bedrock:eu-*::foundation-model/${replace(var.champion_model, "eu.", "")}",
      ] },
    ]
  })
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name}-api"
  role          = aws_iam_role.fn.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  image_config { command = ["claimdesk.handlers.api"] }
  memory_size = 1024
  timeout     = 30
  environment { variables = local.env }
  tracing_config { mode = "Active" }
  lifecycle { ignore_changes = [image_uri] } # CI deploys new images; Terraform owns the rest
}
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE" # CloudFront-only via the secret header checked in the app
}

resource "aws_lambda_function" "worker" {
  function_name = "${local.name}-worker"
  role          = aws_iam_role.fn.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  image_config { command = ["claimdesk.handlers.worker"] }
  memory_size = 2048 # Tesseract is CPU-bound; Lambda CPU scales with memory
  timeout     = 300
  environment { variables = local.env }
  tracing_config { mode = "Active" }
  lifecycle { ignore_changes = [image_uri] } # CI deploys new images; Terraform owns the rest
}
resource "aws_lambda_event_source_mapping" "jobs" {
  event_source_arn        = aws_sqs_queue.jobs.arn
  function_name           = aws_lambda_function.worker.arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config { maximum_concurrency = 2 } # caps spend if someone floods the upload form
}

# ── web + CDN ──────────────────────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "web" { bucket = "${local.name}-web" }
resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${local.name}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_cache_policy" "optimized" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_origin_request_policy" "all_but_host" { name = "Managed-AllViewerExceptHostHeader" }

resource "aws_cloudfront_distribution" "cdn" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }
  origin {
    origin_id   = "api"
    domain_name = split("/", aws_lambda_function_url.api.function_url)[2]
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 30
    }
    custom_header {
      name  = "x-origin-verify"
      value = random_password.origin.result
    }
  }
  default_cache_behavior {
    target_origin_id       = "web"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
  }
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_but_host.id
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "s3:GetObject",
    Principal = { Service = "cloudfront.amazonaws.com" }, Resource = "${aws_s3_bucket.web.arn}/*",
  Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.cdn.arn } } }] })
}

# ── guard rails on spend ───────────────────────────────────────────────────────────────────────────────────

resource "aws_budgets_budget" "monthly" {
  name         = local.name
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

# ── CI: GitHub Actions deploys app code with short-lived credentials (OIDC), no stored keys ────────────────

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "deploy" {
  name = "${local.name}-deploy"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
    Principal = { Federated = aws_iam_openid_connect_provider.github.arn },
    Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" },
      StringLike = { "token.actions.githubusercontent.com:sub" = [
        "repo:${var.github_repo}:ref:refs/heads/main",
        # newer repos sign tokens with an immutable subject: owner@id/repo@id
        "repo:${split("/", var.github_repo)[0]}@*/${split("/", var.github_repo)[1]}@*:ref:refs/heads/main",
  ] } } }] })
}
resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
    "ecr:PutImage", "ecr:BatchGetImage"], Resource = aws_ecr_repository.app.arn },
    { Effect = "Allow", Action = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"], Resource = [aws_lambda_function.api.arn, aws_lambda_function.worker.arn] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"], Resource = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"] },
    { Effect = "Allow", Action = ["cloudfront:CreateInvalidation"], Resource = aws_cloudfront_distribution.cdn.arn },
  ] })
}
