# Daily editorials snapshot run.
# Runs at 00:00 every night: one `uv run main.py` invocation.

locals {
  editorials_job_name        = "daily-editorials-playlist-snapshot"
  editorials_job_description  = "Daily editorial-playlist snapshot at 00:00"
  editorials_schedule         = "cron(0 0 * * ? *)"
}

resource "aws_scheduler_schedule" "daily_editorials_pipeline" {
  name                         = local.editorials_job_name
  description                  = local.editorials_job_description
  group_name                   = aws_scheduler_schedule_group.ep_jobs.name
  schedule_expression          = local.editorials_schedule
  schedule_expression_timezone = var.timezone
  # DEV: schedule is created but paused during code review. Set back to
  # "ENABLED" and re-apply once the code is approved to start the daily runs.
  state                        = "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.ep.arn
    role_arn = aws_iam_role.eventbridge_scheduler_role.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.ep.arn
      launch_type         = "FARGATE"
      propagate_tags      = "TASK_DEFINITION"

      network_configuration {
        subnets          = data.aws_subnets.public.ids
        security_groups  = [aws_security_group.ecs_tasks.id]
        assign_public_ip = true
      }
    }

    input = jsonencode({
      containerOverrides = [
        {
          name    = var.container_name
          command = ["uv", "run", "main.py"]
        }
      ]
    })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

output "daily_editorials_pipeline_schedule_arn" {
  description = "ARN of the daily editorials schedule"
  value       = aws_scheduler_schedule.daily_editorials_pipeline.arn
}

output "daily_editorials_pipeline_next_execution" {
  description = "Next execution time for the daily editorials schedule"
  value       = "Daily at 00:00 ${var.timezone}"
}
