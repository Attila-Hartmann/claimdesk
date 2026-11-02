output "url" { value = "https://${aws_cloudfront_distribution.cdn.domain_name}" }
output "ecr_repository" { value = aws_ecr_repository.app.repository_url }
output "web_bucket" { value = aws_s3_bucket.web.bucket }
output "distribution_id" { value = aws_cloudfront_distribution.cdn.id }
output "functions" { value = [aws_lambda_function.api.function_name, aws_lambda_function.worker.function_name] }
output "deploy_role_arn" { value = aws_iam_role.deploy.arn }
