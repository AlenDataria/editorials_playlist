output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.ep.repository_url
}

output "ecr_image_uri_latest" {
  description = "Image URI using latest tag"
  value       = "${aws_ecr_repository.ep.repository_url}:latest"
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.ep.name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.ep.arn
}

output "ecs_task_definition_arn" {
  description = "ARN of the ECS task definition"
  value       = aws_ecs_task_definition.ep.arn
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS task role"
  value       = aws_iam_role.ecs_task_role.arn
}

output "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution role"
  value       = aws_iam_role.ecs_task_execution_role.arn
}

output "ecs_security_group_id" {
  description = "ID of the ECS tasks security group"
  value       = aws_security_group.ecs_tasks.id
}

output "cloudwatch_log_group" {
  description = "Name of the CloudWatch log group for ECS tasks"
  value       = aws_cloudwatch_log_group.ecs_tasks.name
}

output "schedule_group_name" {
  description = "Name of the EventBridge Scheduler group"
  value       = aws_scheduler_schedule_group.ep_jobs.name
}

output "github_actions_role_arn" {
  description = "ARN of the IAM role assumed by the GitHub Actions ECR deploy workflow (set as AWS_DEPLOY_ROLE_ARN repository variable on GitHub)"
  value       = aws_iam_role.github_actions_ecr_push.arn
}
