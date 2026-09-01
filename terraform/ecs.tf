locals {
  resolved_docker_image = var.docker_image != "" ? var.docker_image : "${aws_ecr_repository.ep.repository_url}:latest"

  # Non-secret env for the open-stint state file on S3. Added only when a bucket
  # is configured; otherwise the app falls back to a local file.
  state_env = var.state_s3_bucket != "" ? [
    { name = "S3_BUCKET_NAME", value = var.state_s3_bucket },
    { name = "AWS_REGION", value = var.aws_region },
  ] : []

  container_env = concat(var.container_environment_vars, local.state_env)
}

resource "aws_ecs_cluster" "ep" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name      = "${var.project_name}-cluster"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

resource "aws_cloudwatch_log_group" "ecs_tasks" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 7

  tags = {
    Name      = "${var.project_name}-logs"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.project_name}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name      = "${var.project_name}-ecs-task-execution-role"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_task_execution_ecr_policy" {
  name = "${var.project_name}-ecr-access"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets_policy" {
  count = var.secrets_manager_arn != "" ? 1 : 0
  name  = "${var.project_name}-secrets-access"
  role  = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = var.secrets_manager_arn
      }
    ]
  })
}

resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name      = "${var.project_name}-ecs-task-role"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

resource "aws_iam_role_policy" "ecs_task_role_policy" {
  name = "${var.project_name}-task-permissions"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect = "Allow"
          Action = [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ]
          Resource = "${aws_cloudwatch_log_group.ecs_tasks.arn}:*"
        }
      ],
      var.state_s3_bucket != "" ? [
        {
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject"]
          Resource = "arn:aws:s3:::${var.state_s3_bucket}/editorial_playlist_state/*"
        }
      ] : []
    )
  })
}

resource "aws_ecs_task_definition" "ep" {
  family                   = "${var.project_name}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = var.container_name
      image     = local.resolved_docker_image
      essential = true

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_tasks.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      environment = local.container_env

      secrets = var.secrets_manager_arn != "" && length(var.secrets_manager_keys) > 0 ? [
        for key in var.secrets_manager_keys : {
          name      = key
          valueFrom = "${var.secrets_manager_arn}:${key}::"
        }
      ] : []

      cpu    = var.ecs_task_cpu
      memory = var.ecs_task_memory
    }
  ])

  tags = {
    Name      = "${var.project_name}-task-definition"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-ecs-tasks-sg"
  description = "Security group for ${var.project_name} ECS tasks"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name      = "${var.project_name}-ecs-tasks-sg"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}
