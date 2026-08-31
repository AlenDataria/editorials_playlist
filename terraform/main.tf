# ECR repository for the editorials-playlist runtime image
resource "aws_ecr_repository" "ep" {
  name                 = "${var.project_name}-app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.project_name}-ecr"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

# IAM role for EventBridge Scheduler
resource "aws_iam_role" "eventbridge_scheduler_role" {
  name = "${var.project_name}-eventbridge-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name      = "${var.project_name}-eventbridge-scheduler-role"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

# IAM policy allowing Scheduler to run ECS tasks
resource "aws_iam_role_policy" "eventbridge_scheduler_policy" {
  name = "${var.project_name}-eventbridge-scheduler-policy"
  role = aws_iam_role.eventbridge_scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:RunTask"
        ]
        Resource = [
          aws_ecs_task_definition.ep.arn,
          "${replace(aws_ecs_task_definition.ep.arn, "/:\\d+$/", ":*")}"
        ]
        Condition = {
          ArnLike = {
            "ecs:cluster" = aws_ecs_cluster.ep.arn
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:TagResource"
        ]
        Resource = "${replace(aws_ecs_cluster.ep.arn, ":cluster/", ":task/")}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.ecs_task_execution_role.arn,
          aws_iam_role.ecs_task_role.arn
        ]
        Condition = {
          StringLike = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      }
    ]
  })
}

# EventBridge Scheduler group
resource "aws_scheduler_schedule_group" "ep_jobs" {
  name = "${var.project_name}-jobs"
}
